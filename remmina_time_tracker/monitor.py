"""Process and network monitor for detecting Remmina RDP/SSH connections.

Modern Remmina (1.4+) uses libfreerdp internally rather than spawning
separate xfreerdp processes. We detect active RDP/SSH sessions by
monitoring TCP connections from the Remmina process to ports 3389 (RDP)
and 22 (SSH), plus scanning for standalone xfreerdp/ssh processes as fallback.
"""

import logging
import re
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)

# Ports that indicate active remote sessions
RDP_PORT = 3389
SSH_PORT = 22
MONITORED_PORTS = {RDP_PORT: "RDP", SSH_PORT: "SSH"}

# Fallback: standalone process names (older Remmina or manual xfreerdp usage)
RDP_PROCESS_NAMES = {"xfreerdp", "xfreerdp3", "wlfreerdp"}
SSH_PROCESS_NAMES = {"ssh"}
ALL_MONITORED = RDP_PROCESS_NAMES | SSH_PROCESS_NAMES


@dataclass
class ActiveSession:
    """Tracks an active RDP/SSH session."""
    pid: str
    server: str
    folder: str
    protocol: str
    start_time: datetime
    process_name: str


def _find_remmina_pids():
    """Find all running Remmina process PIDs."""
    if psutil is None:
        return []

    pids = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info["name"]
            if name and "remmina" in name.lower():
                pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def _scan_network_connections(remmina_pids):
    """Detect active RDP/SSH sessions from Remmina's network connections.

    Checks for established TCP connections from Remmina to ports 3389 (RDP)
    or 22 (SSH).

    Returns:
        Dict[str, dict]: Map of "pid:remote_ip:remote_port" -> session info.
    """
    connections = {}

    if not remmina_pids:
        return connections

    for proc_pid in remmina_pids:
        try:
            proc = psutil.Process(proc_pid)
            for conn in proc.connections(kind="tcp"):
                if conn.status != "ESTABLISHED":
                    continue
                if not conn.raddr:
                    continue

                remote_ip = conn.raddr.ip
                remote_port = conn.raddr.port

                if remote_port not in MONITORED_PORTS:
                    continue

                protocol = MONITORED_PORTS[remote_port]
                server = f"{remote_ip}:{remote_port}"

                # Unique key: remmina_pid + remote address
                session_key = f"{proc_pid}:{server}"

                connections[session_key] = {
                    "server": server,
                    "process_name": "remmina",
                    "protocol": protocol,
                    "remmina_pid": proc_pid,
                    "cmdline": [],
                }

                logger.debug(
                    "Found %s connection: %s (Remmina PID %d)",
                    protocol, server, proc_pid,
                )

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.debug("Cannot read connections for PID %d: %s", proc_pid, e)
            continue

    return connections


def _scan_standalone_processes():
    """Fallback: scan for standalone xfreerdp/ssh processes.

    Some setups or older Remmina versions spawn separate processes.

    Returns:
        Dict[str, dict]: Map of "pid:server" -> session info.
    """
    connections = {}

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pname = proc.info["name"]
            if not pname:
                continue

            pname_lower = pname.lower()
            matched_name = None
            for monitored in ALL_MONITORED:
                if pname_lower == monitored or pname_lower.startswith(monitored):
                    matched_name = monitored
                    break

            if not matched_name:
                continue

            # For SSH, only track if it's a child of Remmina
            if matched_name in SSH_PROCESS_NAMES and not _is_remmina_child(proc):
                continue

            cmdline = proc.info.get("cmdline", [])
            server = _extract_server_from_cmdline(cmdline, matched_name)

            if not server:
                continue

            protocol = "RDP" if matched_name in RDP_PROCESS_NAMES else "SSH"
            session_key = f"{proc.pid}:{server}"

            connections[session_key] = {
                "server": server,
                "process_name": matched_name,
                "protocol": protocol,
                "remmina_pid": None,
                "cmdline": cmdline,
            }

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return connections


def scan_active_connections():
    """Scan for active RDP/SSH connections from Remmina.

    Uses two detection methods:
    1. Network-based: Check Remmina's TCP connections to ports 3389/22
    2. Process-based: Look for standalone xfreerdp/ssh processes (fallback)

    Returns:
        Dict[str, dict]: Map of session_key -> session info dict.
    """
    if psutil is None:
        logger.error("psutil not installed - cannot monitor")
        return {}

    connections = {}

    # Primary: network-based detection (Remmina with built-in libfreerdp)
    remmina_pids = _find_remmina_pids()
    if remmina_pids:
        logger.debug("Found Remmina PIDs: %s", remmina_pids)
        connections.update(_scan_network_connections(remmina_pids))

    # Fallback: standalone process detection
    standalone = _scan_standalone_processes()
    connections.update(standalone)

    if connections:
        logger.debug("Active connections: %d", len(connections))
    return connections


def kill_session(session_key, sessions_info=None, signal_num=15):
    """Terminate a session.

    For network-detected sessions (Remmina internal), we close Remmina.
    For standalone processes, we send SIGTERM to the process.

    Args:
        session_key: The session key string ("pid:server").
        sessions_info: Optional dict with session info (for remmina_pid).
        signal_num: Signal number (default: 15 = SIGTERM).

    Returns:
        True if signal was sent successfully.
    """
    if psutil is None:
        return False

    # Try to extract PID from session key
    try:
        pid_str = session_key.split(":")[0]
        pid = int(pid_str)
    except (ValueError, IndexError):
        logger.warning("Cannot parse PID from session key: %s", session_key)
        return False

    try:
        proc = psutil.Process(pid)
        proc.send_signal(signal_num)
        logger.info("Sent signal %d to PID %d (%s)", signal_num, pid, proc.name())
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        logger.warning("Failed to kill PID %d: %s", pid, e)
        return False


def _is_remmina_child(proc):
    """Check if a process is a child of Remmina."""
    try:
        parent = proc.parent()
        while parent:
            if parent.name() and "remmina" in parent.name().lower():
                return True
            parent = parent.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def _extract_server_from_cmdline(cmdline, process_name):
    """Extract server address from process command line arguments."""
    if not cmdline:
        return None

    args = cmdline if isinstance(cmdline, list) else cmdline.split()

    if process_name in RDP_PROCESS_NAMES:
        for arg in args:
            if arg.startswith("/v:"):
                return arg[3:]
            if arg.startswith("--server-hostname"):
                idx = args.index(arg)
                if idx + 1 < len(args):
                    return args[idx + 1]
        for arg in args[1:]:
            if re.match(r"^[\w.\-]+:\d+$", arg):
                return arg
        return None

    if process_name in SSH_PROCESS_NAMES:
        skip_next = False
        candidates = []
        for arg in args[1:]:
            if skip_next:
                skip_next = False
                continue
            if arg.startswith("-"):
                if arg in ("-p", "-l", "-i", "-o", "-F", "-L", "-R", "-D",
                           "-W", "-J", "-c", "-m", "-b", "-E", "-S"):
                    skip_next = True
                continue
            candidates.append(arg)

        if candidates:
            host = candidates[0]
            if "@" in host:
                host = host.split("@", 1)[1]
            return host
        return None

    return None

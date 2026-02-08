"""Main daemon for Remmina Time Tracker.

Monitors RDP/SSH connections, tracks idle time, logs to CSV,
and auto-disconnects after idle threshold.
"""

import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger("remmina_time_tracker")

# Configuration defaults
SCAN_INTERVAL_MS = 5000       # Process scan interval: 5 seconds
IDLE_CHECK_INTERVAL_MS = 30000  # Idle check interval: 30 seconds
IDLE_THRESHOLD_MS = 600000    # 10 minutes in milliseconds
CSV_PATH = os.path.expanduser("~/Documents/remmina_time_tracking.csv")

# Import local modules
from remmina_time_tracker.csv_logger import CSVLogger
from remmina_time_tracker.config_parser import parse_remmina_files, find_profile_by_server
from remmina_time_tracker.monitor import scan_active_connections, kill_session, ActiveSession
from remmina_time_tracker.idle_detector import IdleDetector
from remmina_time_tracker.sleep_handler import SleepHandler
from remmina_time_tracker.window_tracker import WindowTracker


class TimeTrackerDaemon:
    """Main daemon that orchestrates all tracking components."""

    def __init__(self, csv_path=None, idle_threshold_ms=None, enable_idle=True):
        self.csv_logger = CSVLogger(csv_path or CSV_PATH)
        self.idle_detector = IdleDetector() if enable_idle else None
        self.window_tracker = WindowTracker() if enable_idle else None
        self.idle_threshold_ms = idle_threshold_ms or IDLE_THRESHOLD_MS
        self.enable_idle = enable_idle

        # Track active sessions: session_key -> ActiveSession
        self._active_sessions: Dict[str, ActiveSession] = {}

        # Cache Remmina profiles (refreshed periodically)
        self._profiles = []
        self._profiles_last_refresh = None

        # Sleep/wake state
        self._sleep_timestamp: Optional[datetime] = None
        self._pre_sleep_idle_ms: int = 0
        self._is_sleeping = False

        # Track when Remmina lost focus (for session-specific idle tracking)
        self._remmina_unfocused_since: Optional[datetime] = None

        # GLib main loop
        self._loop = None
        self._sleep_handler = SleepHandler(
            on_sleep=self._on_sleep,
            on_wake=self._on_wake,
        )

    def start(self):
        """Start the daemon with GLib main loop."""
        try:
            from gi.repository import GLib
        except ImportError:
            logger.error("PyGObject not installed. Install: sudo apt install python3-gi")
            sys.exit(1)

        logger.info("=" * 60)
        logger.info("Remmina Time Tracker starting")
        logger.info("CSV log: %s", self.csv_logger.csv_path)
        logger.info("Idle detection: %s", "enabled" if self.enable_idle else "disabled")
        if self.enable_idle:
            logger.info("Idle threshold: %d minutes", self.idle_threshold_ms // 60000)
            logger.info("Idle check interval: %d seconds", IDLE_CHECK_INTERVAL_MS // 1000)
            if self.idle_detector and not self.idle_detector.is_available():
                logger.warning("Idle detection NOT available - install xprintidle")
        logger.info("Process scan interval: %d seconds", SCAN_INTERVAL_MS // 1000)
        logger.info("=" * 60)

        # Set up periodic callbacks
        GLib.timeout_add(SCAN_INTERVAL_MS, self._scan_tick)
        if self.enable_idle:
            GLib.timeout_add(IDLE_CHECK_INTERVAL_MS, self._idle_tick)

        # Refresh profiles every 60 seconds
        GLib.timeout_add(60000, self._refresh_profiles)

        # Start sleep/wake monitoring
        self._sleep_handler.start()

        # Refresh profiles on start
        self._refresh_profiles()

        # Do initial scan
        self._scan_tick()

        # Run GLib main loop
        self._loop = GLib.MainLoop()

        # Handle SIGTERM/SIGINT gracefully
        def shutdown(signum, frame):
            logger.info("Received signal %d, shutting down...", signum)
            self._cleanup_on_exit()
            if self._loop:
                self._loop.quit()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        try:
            logger.info("Daemon running. Press Ctrl+C to stop.")
            self._loop.run()
        except KeyboardInterrupt:
            self._cleanup_on_exit()
        finally:
            self._sleep_handler.stop()
            logger.info("Daemon stopped.")

    def _refresh_profiles(self):
        """Refresh cached Remmina profiles from disk."""
        try:
            self._profiles = parse_remmina_files()
            self._profiles_last_refresh = datetime.now()
        except Exception as e:
            logger.warning("Failed to refresh profiles: %s", e)
        return True  # Keep the timeout active

    def _scan_tick(self):
        """Periodic scan for new/ended connections."""
        if self._is_sleeping:
            return True

        try:
            current = scan_active_connections()
            current_pids = set(current.keys())
            tracked_pids = set(self._active_sessions.keys())

            # Detect new connections
            new_pids = current_pids - tracked_pids
            for pid in new_pids:
                info = current[pid]
                self._handle_connect(pid, info)

            # Detect ended connections
            ended_pids = tracked_pids - current_pids
            for pid in ended_pids:
                self._handle_disconnect(pid)

        except Exception as e:
            logger.error("Scan error: %s", e)

        return True  # Keep the timeout active

    def _idle_tick(self):
        """Periodic idle check - auto-disconnect if idle too long.

        Checks both system idle time AND Remmina window focus.
        If Remmina is not focused, count that as "session idle" time.
        """
        if self._is_sleeping:
            return True
        if not self.idle_detector or not self.idle_detector.is_available():
            return True
        if not self._active_sessions:
            self._remmina_unfocused_since = None  # Reset if no sessions
            return True

        try:
            now = datetime.now()

            # Check if Remmina window is focused
            remmina_focused = True
            if self.window_tracker:
                remmina_focused = self.window_tracker.is_remmina_focused()

            # Track when Remmina loses/regains focus
            if not remmina_focused:
                if self._remmina_unfocused_since is None:
                    self._remmina_unfocused_since = now
                    logger.debug("Remmina lost focus, starting unfocused timer")
            else:
                if self._remmina_unfocused_since is not None:
                    logger.debug("Remmina regained focus, resetting unfocused timer")
                self._remmina_unfocused_since = None

            # Determine effective idle time
            idle_ms = 0
            disconnect_reason = ""

            if not remmina_focused and self._remmina_unfocused_since:
                # Remmina is not focused - count unfocused duration as idle time
                unfocused_duration = now - self._remmina_unfocused_since
                idle_ms = unfocused_duration.total_seconds() * 1000
                disconnect_reason = f"Remmina unfocused for {idle_ms / 60000:.1f} min"
                logger.debug("Remmina unfocused idle: %.1f seconds", idle_ms / 1000)
            else:
                # Remmina is focused - use system-wide idle time
                idle_ms = self.idle_detector.get_idle_ms()
                disconnect_reason = f"System idle for {idle_ms / 60000:.1f} min"
                logger.debug("System idle (Remmina focused): %.1f seconds", idle_ms / 1000)

            if idle_ms >= self.idle_threshold_ms:
                # Calculate when idle threshold was first crossed
                last_activity = now - timedelta(milliseconds=idle_ms)
                end_time = last_activity + timedelta(milliseconds=self.idle_threshold_ms)

                logger.info(
                    "Idle threshold reached: %s. Auto-disconnecting all sessions.",
                    disconnect_reason,
                )

                # Disconnect all active sessions
                pids_to_disconnect = list(self._active_sessions.keys())
                for session_key in pids_to_disconnect:
                    session = self._active_sessions[session_key]
                    self.csv_logger.log_event(
                        "end", session.server, session.folder, timestamp=end_time
                    )
                    kill_session(session_key, self._active_sessions)
                    logger.info(
                        "Auto-disconnected: %s (%s) at %s",
                        session.server, session.folder,
                        end_time.strftime("%H:%M:%S"),
                    )
                    del self._active_sessions[session_key]

                # Reset unfocused timer
                self._remmina_unfocused_since = None

        except Exception as e:
            logger.error("Idle check error: %s", e)

        return True  # Keep the timeout active

    def _handle_connect(self, session_key, info):
        """Handle a new connection detected."""
        server = info["server"]
        protocol = info["protocol"]

        # Look up folder from Remmina profiles
        profile = find_profile_by_server(server, self._profiles)
        folder = profile.group if profile else ""

        session = ActiveSession(
            pid=session_key,
            server=server,
            folder=folder,
            protocol=protocol,
            start_time=datetime.now(),
            process_name=info["process_name"],
        )

        self._active_sessions[session_key] = session
        self.csv_logger.log_event("start", server, folder)

        logger.info(
            "Connection started: %s | folder=%s | protocol=%s",
            server, folder, protocol,
        )

    def _handle_disconnect(self, session_key):
        """Handle a connection that ended."""
        session = self._active_sessions.pop(session_key, None)
        if session:
            self.csv_logger.log_event("end", session.server, session.folder)
            logger.info(
                "Connection ended: %s | folder=%s",
                session.server, session.folder,
            )

    def _on_sleep(self, timestamp):
        """Called when system is going to sleep."""
        self._sleep_timestamp = timestamp
        self._is_sleeping = True

        if self.idle_detector and self.idle_detector.is_available():
            self._pre_sleep_idle_ms = self.idle_detector.get_idle_ms()
        else:
            self._pre_sleep_idle_ms = 0

        logger.info(
            "Sleep detected. Pre-sleep idle: %.1f seconds. Active sessions: %d",
            self._pre_sleep_idle_ms / 1000,
            len(self._active_sessions),
        )

    def _on_wake(self, timestamp):
        """Called when system wakes up."""
        self._is_sleeping = False
        sleep_duration_ms = 0

        if self._sleep_timestamp:
            sleep_duration = timestamp - self._sleep_timestamp
            sleep_duration_ms = sleep_duration.total_seconds() * 1000

        logger.info(
            "Wake detected. Slept for %.1f minutes. Checking idle state...",
            sleep_duration_ms / 60000,
        )

        if not self._active_sessions:
            logger.info("No active sessions during sleep, nothing to do.")
            self._sleep_timestamp = None
            return

        # Check if we need to auto-disconnect
        # Total idle = pre-sleep idle + sleep duration
        total_idle_ms = self._pre_sleep_idle_ms + sleep_duration_ms

        if self._pre_sleep_idle_ms >= self.idle_threshold_ms:
            # Already past threshold before sleep - end at sleep timestamp
            logger.info("Was already idle before sleep. Disconnecting at sleep time.")
            last_activity = self._sleep_timestamp - timedelta(
                milliseconds=self._pre_sleep_idle_ms
            )
            end_time = last_activity + timedelta(milliseconds=self.idle_threshold_ms)
            self._disconnect_all_sessions(end_time)

        elif total_idle_ms >= self.idle_threshold_ms:
            # Crossed threshold during sleep
            last_activity = self._sleep_timestamp - timedelta(
                milliseconds=self._pre_sleep_idle_ms
            )
            end_time = last_activity + timedelta(milliseconds=self.idle_threshold_ms)
            logger.info(
                "Idle threshold crossed during sleep. Disconnecting at %s",
                end_time.strftime("%H:%M:%S"),
            )
            self._disconnect_all_sessions(end_time)

        else:
            # Still under threshold - continue monitoring
            logger.info(
                "Total idle (%.1f min) under threshold. Resuming monitoring.",
                total_idle_ms / 60000,
            )

        self._sleep_timestamp = None

    def _disconnect_all_sessions(self, end_time):
        """Disconnect all active sessions and log end time."""
        pids_to_disconnect = list(self._active_sessions.keys())
        for session_key in pids_to_disconnect:
            session = self._active_sessions[session_key]
            self.csv_logger.log_event(
                "end", session.server, session.folder, timestamp=end_time
            )
            kill_session(session_key, self._active_sessions)
            logger.info(
                "Auto-disconnected (sleep): %s (%s)",
                session.server, session.folder,
            )
            del self._active_sessions[session_key]

    def _cleanup_on_exit(self):
        """Log end for any remaining active sessions on daemon shutdown."""
        for pid, session in list(self._active_sessions.items()):
            self.csv_logger.log_event("end", session.server, session.folder)
            logger.info("Logged end on shutdown: %s (%s)", session.server, session.folder)
        self._active_sessions.clear()


def main():
    """Entry point for the daemon."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Remmina Time Tracker - CSV session logging with idle auto-disconnect"
    )
    parser.add_argument(
        "--csv-path",
        default=CSV_PATH,
        help=f"Path to CSV log file (default: {CSV_PATH})",
    )
    parser.add_argument(
        "--idle-threshold",
        type=int,
        default=10,
        help="Idle threshold in minutes before auto-disconnect (default: 10)",
    )
    parser.add_argument(
        "--no-idle",
        action="store_true",
        help="Disable idle detection and auto-disconnect (tracking only)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Log to file instead of stderr",
    )

    args = parser.parse_args()

    # Set up logging
    log_handlers = []
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(formatter)
        log_handlers.append(file_handler)
    else:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        log_handlers.append(console_handler)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        handlers=log_handlers,
    )

    daemon = TimeTrackerDaemon(
        csv_path=args.csv_path,
        idle_threshold_ms=args.idle_threshold * 60000,
        enable_idle=not args.no_idle,
    )
    daemon.start()


if __name__ == "__main__":
    main()

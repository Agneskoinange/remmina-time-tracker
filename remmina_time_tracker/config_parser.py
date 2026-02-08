"""Parser for Remmina .remmina connection profile files."""

import configparser
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

REMMINA_DATA_DIR = os.path.expanduser("~/.local/share/remmina")


class RemminaProfile:
    """Represents a parsed Remmina connection profile."""

    def __init__(self, server, group, name, protocol, filepath):
        self.server = server
        self.group = group or ""
        self.name = name or ""
        self.protocol = protocol or ""
        self.filepath = filepath

    def __repr__(self):
        return f"RemminaProfile(server={self.server!r}, group={self.group!r}, name={self.name!r})"


def parse_remmina_files(data_dir=None):
    """Parse all .remmina files and return a list of RemminaProfile objects."""
    data_dir = data_dir or REMMINA_DATA_DIR
    profiles = []
    remmina_dir = Path(data_dir)

    if not remmina_dir.exists():
        logger.warning("Remmina data directory not found: %s", data_dir)
        return profiles

    for remmina_file in remmina_dir.glob("*.remmina"):
        try:
            config = configparser.ConfigParser()
            config.read(str(remmina_file))

            if not config.has_section("remmina"):
                continue

            server = config.get("remmina", "server", fallback="")
            group = config.get("remmina", "group", fallback="")
            name = config.get("remmina", "name", fallback="")
            protocol = config.get("remmina", "protocol", fallback="")

            if server:
                profiles.append(RemminaProfile(
                    server=server,
                    group=group,
                    name=name,
                    protocol=protocol,
                    filepath=str(remmina_file),
                ))
        except Exception as e:
            logger.warning("Failed to parse %s: %s", remmina_file, e)

    logger.debug("Parsed %d Remmina profiles", len(profiles))
    return profiles


def find_profile_by_server(server_addr, profiles=None):
    """Find a Remmina profile matching the given server address.

    Handles various formats:
    - Exact match: "192.168.1.100:3389" == "192.168.1.100:3389"
    - Host-only match: "192.168.1.100" matches "192.168.1.100:3389"
    - Hostname match: "myserver.local" matches "myserver.local:3389"
    """
    if profiles is None:
        profiles = parse_remmina_files()

    # Localhost aliases
    LOCALHOST_ALIASES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

    # Normalize: strip default ports and resolve localhost variants
    def normalize(addr):
        addr = addr.strip()
        if addr.endswith(":3389") or addr.endswith(":22"):
            addr = addr.rsplit(":", 1)[0]
        if addr in LOCALHOST_ALIASES:
            addr = "localhost"
        return addr

    target = normalize(server_addr)

    for profile in profiles:
        if normalize(profile.server) == target:
            return profile

    # Fallback: partial match (server contains target or vice versa)
    for profile in profiles:
        pserver = normalize(profile.server)
        if target in pserver or pserver in target:
            return profile

    return None

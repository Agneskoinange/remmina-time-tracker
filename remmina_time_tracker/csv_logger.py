"""CSV logger for Remmina session events."""

import csv
import os
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

DEFAULT_CSV_PATH = os.path.expanduser("~/Documents/remmina_time_tracking.csv")
CSV_HEADER = ["timestamp", "event", "server", "folder"]


class CSVLogger:
    """Thread-safe CSV logger for session start/end events."""

    def __init__(self, csv_path=None):
        self.csv_path = csv_path or DEFAULT_CSV_PATH
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self):
        """Create the CSV file with header if it doesn't exist."""
        try:
            path = Path(self.csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.stat().st_size == 0:
                with open(self.csv_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(CSV_HEADER)
                logger.info("Created CSV file: %s", self.csv_path)
        except (PermissionError, OSError) as e:
            logger.error("Cannot create CSV file at %s: %s", self.csv_path, e)
            raise

    def log_event(self, event_type, server, folder, timestamp=None):
        """Log a session event to CSV.

        Args:
            event_type: "start" or "end"
            server: Server hostname/IP (e.g., "192.168.1.100:3389")
            folder: Remmina folder/group name (e.g., "ClientXYZ")
            timestamp: Optional datetime; defaults to now.
        """
        if timestamp is None:
            timestamp = datetime.now()
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")

        try:
            with self._lock:
                with open(self.csv_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([ts_str, event_type, server, folder])
            logger.info("CSV: %s | %s | %s | %s", ts_str, event_type, server, folder)
        except (IOError, PermissionError, OSError) as e:
            logger.error("Failed to write CSV: %s", e)

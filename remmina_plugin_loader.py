"""Optional Remmina plugin loader.

If installed in Remmina's plugin directory and remmina-plugin-python is available,
this file auto-starts the time tracker daemon when Remmina launches.

Install location: /usr/lib/x86_64-linux-gnu/remmina/plugins/remmina_plugin_loader.py
"""

import logging
import os
import subprocess
import sys

logger = logging.getLogger("remmina_time_tracker.plugin_loader")

try:
    import remmina

    class RemminaTimeTrackerEntry:
        """Remmina entry plugin that ensures the time tracker daemon is running."""

        def __init__(self):
            self.name = "TimeTracker"
            self.type = "entry"
            self.description = "Time Tracker - Session logging (MRU Consulting)"
            self.version = "1.0"

        def entry_func(self):
            """Called when the menu entry is clicked - show status."""
            csv_path = os.path.expanduser("~/.local/share/remmina/time_tracking.csv")
            if os.path.exists(csv_path):
                remmina.debug(f"Time Tracker CSV: {csv_path}")
            else:
                remmina.debug("Time Tracker: No sessions logged yet.")

    # Register the entry plugin
    entry = RemminaTimeTrackerEntry()
    remmina.register_plugin(entry)

    # Ensure the systemd service is running
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "remmina-time-tracker.service"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip() != "active":
            subprocess.Popen(
                ["systemctl", "--user", "start", "remmina-time-tracker.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            remmina.debug("Time Tracker: Started background service")
        else:
            remmina.debug("Time Tracker: Background service already running")
    except Exception as e:
        remmina.debug(f"Time Tracker: Could not check/start service: {e}")

except ImportError:
    # Not running inside Remmina - this file is standalone
    pass

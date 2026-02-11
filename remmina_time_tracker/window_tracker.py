"""Tracks whether Remmina window is focused."""

import subprocess
import logging

import psutil

logger = logging.getLogger(__name__)


class WindowTracker:
    """Detects if Remmina window is currently focused."""

    def __init__(self):
        self.display_server = self._detect_display_server()
        logger.info("Window tracker initialized for %s", self.display_server)

    def _detect_display_server(self):
        """Detect X11 vs Wayland."""
        import os
        if os.environ.get("WAYLAND_DISPLAY"):
            return "wayland"
        elif os.environ.get("DISPLAY"):
            return "x11"
        else:
            return "unknown"

    def is_remmina_focused(self):
        """Check if any Remmina window is currently focused.

        Returns:
            bool: True if Remmina window has focus, False otherwise.
        """
        if self.display_server == "x11":
            return self._is_focused_x11()
        elif self.display_server == "wayland":
            return self._is_focused_wayland()
        else:
            logger.warning("Cannot detect window focus on unknown display server")
            return True  # Assume focused to avoid false positives

    def _get_active_window_id(self):
        """Get the active window ID using xdotool or xprop."""
        # Try xdotool first
        try:
            result = subprocess.run(
                ["/usr/bin/xdotool", "getactivewindow"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback to xprop
        try:
            result = subprocess.run(
                ["/usr/bin/xprop", "-root", "_NET_ACTIVE_WINDOW"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0 and "0x" in result.stdout:
                return result.stdout.split()[-1]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return None

    def _is_focused_x11(self):
        """Check focus on X11 using WM_CLASS and window PID.

        Uses multiple detection methods for reliability across distros:
        1. WM_CLASS check (works on most systems)
        2. Window PID check (fallback - checks if active window belongs to Remmina)
        """
        window_id = self._get_active_window_id()
        if not window_id:
            logger.warning("Could not get active window ID (xdotool/xprop not available)")
            return True  # Can't detect, assume focused

        # Method 1: Check WM_CLASS
        try:
            class_result = subprocess.run(
                ["/usr/bin/xprop", "-id", window_id, "WM_CLASS"],
                capture_output=True, text=True, timeout=1
            )
            if class_result.returncode == 0:
                wm_class = class_result.stdout.lower()
                is_remmina = "remmina" in wm_class
                logger.debug("Active window WM_CLASS: %s (remmina=%s)",
                             class_result.stdout.strip(), is_remmina)
                if is_remmina:
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Method 2: Check if active window's PID is a Remmina process
        try:
            pid_result = subprocess.run(
                ["/usr/bin/xdotool", "getactivewindow", "getwindowpid"],
                capture_output=True, text=True, timeout=1
            )
            if pid_result.returncode == 0:
                window_pid = int(pid_result.stdout.strip())
                if window_pid > 0:
                    proc = psutil.Process(window_pid)
                    proc_name = proc.name().lower()
                    is_remmina = "remmina" in proc_name
                    logger.debug("Active window PID %d, process: %s (remmina=%s)",
                                 window_pid, proc_name, is_remmina)
                    if is_remmina:
                        return True
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError,
                psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return False

    def _is_focused_wayland(self):
        """Check focus on Wayland (limited support).

        Wayland doesn't expose active window info for security reasons.
        We can try GNOME-specific methods but this is inherently limited.
        """
        try:
            # Try GNOME Shell D-Bus (only works on GNOME)
            import dbus
            bus = dbus.SessionBus()
            shell = bus.get_object(
                "org.gnome.Shell",
                "/org/gnome/Shell"
            )
            interface = dbus.Interface(shell, "org.gnome.Shell")
            # This may not work on all GNOME versions
            # Most Wayland compositors don't expose this for security
            logger.debug("Wayland window tracking not fully supported")
        except Exception:
            pass

        # On Wayland, we can't reliably detect focused window
        # Return True to use system-wide idle (original behavior)
        logger.debug("Using system-wide idle on Wayland (window focus not available)")
        return True

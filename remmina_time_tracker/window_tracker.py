"""Tracks whether Remmina window is focused."""

import subprocess
import logging

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

    def _is_focused_x11(self):
        """Check focus on X11 using WM_CLASS (not window title).

        Window titles can contain project folder names (e.g. VS Code shows
        "Remmina-Plugin" in its title), causing false positives. WM_CLASS
        is set by the application itself and is reliable.
        """
        # Method 1: xdotool to get window ID, then xprop for WM_CLASS
        try:
            result = subprocess.run(
                ["/usr/bin/xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                window_id = result.stdout.strip()
                class_result = subprocess.run(
                    ["/usr/bin/xprop", "-id", window_id, "WM_CLASS"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                if class_result.returncode == 0:
                    wm_class = class_result.stdout.lower()
                    return "remmina" in wm_class
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Method 2: xprop only (fallback if xdotool is missing)
        try:
            result = subprocess.run(
                ["/usr/bin/xprop", "-root", "_NET_ACTIVE_WINDOW"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0 and "0x" in result.stdout:
                window_id = result.stdout.split()[-1]
                class_result = subprocess.run(
                    ["/usr/bin/xprop", "-id", window_id, "WM_CLASS"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                if class_result.returncode == 0:
                    wm_class = class_result.stdout.lower()
                    return "remmina" in wm_class
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        logger.warning("Could not detect focused window on X11 (xdotool/xprop not available)")
        return True  # Assume focused to avoid false positives

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

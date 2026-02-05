"""System-wide idle detection for Linux (X11 and Wayland)."""

import logging
import os
import subprocess
import ctypes
import ctypes.util

logger = logging.getLogger(__name__)


class IdleDetector:
    """Detects system-wide idle time across X11 and Wayland sessions."""

    def __init__(self):
        self._method = None
        self._xlib = None
        self._xss = None
        self._detect_method()

    def _detect_method(self):
        """Auto-detect the best idle detection method for this system."""
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

        if session_type == "wayland":
            if self._test_mutter_idle():
                self._method = "mutter"
                logger.info("Idle detection: GNOME Mutter IdleMonitor (Wayland)")
                return
            if self._test_wprintidle():
                self._method = "wprintidle"
                logger.info("Idle detection: wprintidle (Wayland)")
                return

        # X11 or fallback
        if self._test_xprintidle():
            self._method = "xprintidle"
            logger.info("Idle detection: xprintidle (X11)")
            return

        if self._test_xss_ctypes():
            self._method = "xss"
            logger.info("Idle detection: libXss ctypes (X11)")
            return

        # Try xprintidle even on Wayland (XWayland might work)
        if session_type == "wayland" and self._test_xprintidle():
            self._method = "xprintidle"
            logger.info("Idle detection: xprintidle via XWayland")
            return

        logger.warning("No idle detection method available! "
                        "Install xprintidle: sudo apt install xprintidle")
        self._method = None

    def _test_xprintidle(self):
        """Test if xprintidle is available."""
        try:
            result = subprocess.run(
                ["xprintidle"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_wprintidle(self):
        """Test if wprintidle is available."""
        try:
            result = subprocess.run(
                ["wprintidle"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_mutter_idle(self):
        """Test if GNOME Mutter IdleMonitor D-Bus interface is available."""
        try:
            import dbus
            bus = dbus.SessionBus()
            obj = bus.get_object(
                "org.gnome.Mutter.IdleMonitor",
                "/org/gnome/Mutter/IdleMonitor/Core",
            )
            iface = dbus.Interface(obj, "org.gnome.Mutter.IdleMonitor")
            iface.GetIdletime()
            return True
        except Exception:
            return False

    def _test_xss_ctypes(self):
        """Test if libXss is available via ctypes."""
        try:
            xlib_path = ctypes.util.find_library("X11")
            xss_path = ctypes.util.find_library("Xss")
            if not xlib_path or not xss_path:
                return False
            xlib = ctypes.cdll.LoadLibrary(xlib_path)
            display = xlib.XOpenDisplay(None)
            if display:
                xlib.XCloseDisplay(display)
                return True
            return False
        except Exception:
            return False

    def get_idle_ms(self):
        """Get system-wide idle time in milliseconds.

        Returns:
            int: Idle time in milliseconds, or 0 if detection fails.
        """
        if self._method == "xprintidle":
            return self._get_xprintidle()
        elif self._method == "wprintidle":
            return self._get_wprintidle()
        elif self._method == "mutter":
            return self._get_mutter_idle()
        elif self._method == "xss":
            return self._get_xss_idle()
        return 0

    def is_available(self):
        """Check if idle detection is functional."""
        return self._method is not None

    def _get_xprintidle(self):
        try:
            result = subprocess.run(
                ["xprintidle"], capture_output=True, text=True, timeout=5
            )
            return int(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            return 0

    def _get_wprintidle(self):
        try:
            result = subprocess.run(
                ["wprintidle"], capture_output=True, text=True, timeout=5
            )
            return int(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError):
            return 0

    def _get_mutter_idle(self):
        try:
            import dbus
            bus = dbus.SessionBus()
            obj = bus.get_object(
                "org.gnome.Mutter.IdleMonitor",
                "/org/gnome/Mutter/IdleMonitor/Core",
            )
            iface = dbus.Interface(obj, "org.gnome.Mutter.IdleMonitor")
            return int(iface.GetIdletime())
        except Exception:
            return 0

    def _get_xss_idle(self):
        """Get idle time via libXss ctypes."""

        class XScreenSaverInfo(ctypes.Structure):
            _fields_ = [
                ("window", ctypes.c_ulong),
                ("state", ctypes.c_int),
                ("kind", ctypes.c_int),
                ("til_or_since", ctypes.c_ulong),
                ("idle", ctypes.c_ulong),
                ("eventMask", ctypes.c_ulong),
            ]

        try:
            xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
            xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xss"))

            display = xlib.XOpenDisplay(None)
            if not display:
                return 0

            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
            info = xss.XScreenSaverAllocInfo()
            root_window = xlib.XDefaultRootWindow(display)
            xss.XScreenSaverQueryInfo(display, root_window, info)
            idle_ms = info.contents.idle
            xlib.XCloseDisplay(display)
            return idle_ms
        except Exception:
            return 0

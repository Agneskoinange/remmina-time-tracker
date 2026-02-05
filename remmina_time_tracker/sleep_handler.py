"""Sleep/wake detection via systemd-logind D-Bus signals."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SleepHandler:
    """Monitors system sleep/wake events via D-Bus.

    Uses org.freedesktop.login1.Manager.PrepareForSleep signal.
    """

    def __init__(self, on_sleep=None, on_wake=None):
        """Initialize sleep handler.

        Args:
            on_sleep: Callback(timestamp) called when system is going to sleep.
            on_wake: Callback(timestamp) called when system wakes up.
        """
        self._on_sleep = on_sleep
        self._on_wake = on_wake
        self._subscription_id = None
        self._bus = None

    def start(self):
        """Start listening for sleep/wake signals on the system D-Bus."""
        try:
            from gi.repository import Gio

            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self._subscription_id = self._bus.signal_subscribe(
                "org.freedesktop.login1",
                "org.freedesktop.login1.Manager",
                "PrepareForSleep",
                "/org/freedesktop/login1",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_signal,
                None,
            )
            logger.info("Sleep/wake detection active (systemd-logind D-Bus)")
            return True
        except Exception as e:
            logger.warning("Could not subscribe to sleep/wake signals: %s", e)
            logger.warning("Install PyGObject: sudo apt install python3-gi")
            return False

    def stop(self):
        """Stop listening for sleep/wake signals."""
        if self._bus and self._subscription_id is not None:
            self._bus.signal_unsubscribe(self._subscription_id)
            self._subscription_id = None
            logger.info("Sleep/wake detection stopped")

    def _on_signal(self, conn, sender, obj, interface, signal, parameters, data):
        """Handle PrepareForSleep D-Bus signal."""
        going_to_sleep = parameters[0]
        now = datetime.now()

        if going_to_sleep:
            logger.info("System going to sleep at %s", now)
            if self._on_sleep:
                self._on_sleep(now)
        else:
            logger.info("System woke up at %s", now)
            if self._on_wake:
                self._on_wake(now)

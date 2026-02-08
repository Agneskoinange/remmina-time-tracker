# Remmina Time Tracker

**Developed for [MRU Consulting](https://mruconsulting.com)**

A lightweight session tracking plugin for [Remmina](https://remmina.org) that logs RDP/SSH connection times to CSV and auto-disconnects after system-wide inactivity.

## Features

- **CSV Session Logging** — Logs `start` and `end` events with timestamps, server name, and Remmina folder/group name
- **Smart Idle Detection** — Tracks Remmina window focus; if you switch away from Remmina (e.g., to do emails), the idle timer starts for your RDP sessions
- **Auto-Disconnect** — Kills RDP/SSH sessions after 10 minutes of inactivity (configurable)
- **Sleep/Wake Handling** — Detects system sleep via systemd-logind D-Bus; disconnects if idle threshold was crossed during sleep
- **Multi-Connection Support** — Tracks multiple simultaneous RDP/SSH sessions independently
- **Cross-Desktop** — Works on X11 (via `xprintidle`) and GNOME Wayland (via Mutter IdleMonitor)
- **Runs as systemd User Service** — Auto-starts on login, survives Remmina restarts

## How It Works

The tracker runs as a background daemon that:

1. **Scans for `xfreerdp`/`ssh` processes** spawned by Remmina every 5 seconds
2. **Reads `.remmina` profile files** to map server addresses to folder/group names
3. **Tracks Remmina window focus** — If Remmina loses focus (you switch to email, browser, etc.), starts counting "unfocused time" as idle for your RDP sessions
4. **Checks system idle time** when Remmina is focused, using `xprintidle` (X11) or GNOME Mutter D-Bus (Wayland)
5. **Auto-disconnects** by sending SIGTERM to the process if idle exceeds the threshold
6. **Listens for sleep/wake** via `org.freedesktop.login1.Manager.PrepareForSleep` D-Bus signal

## CSV Output Format

Logs are written to `~/Documents/remmina_time_tracking.csv`:

```csv
timestamp,event,server,folder
2026-02-04 14:30:00,start,192.168.1.100:3389,ClientXYZ
2026-02-04 15:45:12,end,192.168.1.100:3389,ClientXYZ
2026-02-04 16:00:00,start,10.0.0.50:3389,ClientABC
2026-02-04 16:10:00,end,10.0.0.50:3389,ClientABC
```

## Installation

### Quick Install (Ubuntu / Pop!_OS / Debian)

```bash
git clone https://github.com/Agneskoinange/remmina-time-tracker.git
cd remmina-time-tracker
chmod +x install.sh
./install.sh
```

The installer will:
- Check and install required dependencies (`psutil`, `PyGObject`, `xprintidle`)
- Install the tracker to `~/.local/lib/remmina-time-tracker/`
- Create a launcher at `~/.local/bin/remmina-time-tracker`
- **Set up a systemd user service that auto-starts on every login** — the tracker will run automatically in the background whenever you log in to your desktop

### Manual Install

```bash
# Install dependencies
sudo apt install python3-psutil python3-gi xprintidle

# Copy files
mkdir -p ~/.local/lib/remmina-time-tracker
cp -r remmina_time_tracker ~/.local/lib/remmina-time-tracker/

# Create launcher
mkdir -p ~/.local/bin
cat > ~/.local/bin/remmina-time-tracker << 'EOF'
#!/bin/bash
INSTALL_DIR="$HOME/.local/lib/remmina-time-tracker"
export PYTHONPATH="$INSTALL_DIR:$PYTHONPATH"
exec python3 -m remmina_time_tracker.daemon "$@"
EOF
chmod +x ~/.local/bin/remmina-time-tracker

# Install and start the service
cp remmina-time-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now remmina-time-tracker.service
```

> **Note:** The tracker is configured to start automatically on login via systemd. You don't need to manually start it after installation — just log out and log back in, or run `systemctl --user start remmina-time-tracker` to start it immediately.

## Usage

### Service Management

```bash
# Start the tracker
systemctl --user start remmina-time-tracker

# Stop the tracker
systemctl --user stop remmina-time-tracker

# Check status
systemctl --user status remmina-time-tracker

# View live logs
journalctl --user -u remmina-time-tracker -f

# View the CSV log
cat ~/Documents/remmina_time_tracking.csv
```

### Command-Line Options

```bash
# Run with tracking only (no idle detection / auto-disconnect)
remmina-time-tracker --no-idle

# Custom idle threshold (15 minutes instead of default 10)
remmina-time-tracker --idle-threshold 15

# Custom CSV path
remmina-time-tracker --csv-path /path/to/custom.csv

# Debug logging
remmina-time-tracker --log-level DEBUG

# Log to file
remmina-time-tracker --log-file ~/.local/share/remmina/tracker.log
```

## Dependencies

| Package | Purpose | Install Command |
|---------|---------|-----------------|
| `python3-psutil` | Process monitoring | `sudo apt install python3-psutil` |
| `python3-gi` | D-Bus/GLib integration | `sudo apt install python3-gi` |
| `xprintidle` | System-wide idle time (X11) | `sudo apt install xprintidle` |
| `xdotool` | Window focus detection (X11) | `sudo apt install xdotool` |

### Wayland Support

- **GNOME (Pop!_OS, Ubuntu)**: Uses `org.gnome.Mutter.IdleMonitor` D-Bus — no extra packages needed
- **Other Wayland compositors**: Install `wprintidle` from your package manager or [build from source](https://codeberg.org/andyscott/wprintidle)
- **XWayland fallback**: `xprintidle` may work via XWayland on some setups

## Troubleshooting

### "psutil not found"
```bash
sudo apt install python3-psutil
# or: pip3 install psutil
```

### "PyGObject not found"
```bash
sudo apt install python3-gi gir1.2-glib-2.0
```

### "Idle detection NOT available"
```bash
# X11:
sudo apt install xprintidle

# Wayland (GNOME): Should work automatically via Mutter D-Bus
# Wayland (other): Install wprintidle
```

### "No sessions being detected"
- Ensure Remmina is running and connected to an RDP server
- Check that `xfreerdp` or `xfreerdp3` processes are visible: `ps aux | grep freerdp`
- Run in debug mode: `remmina-time-tracker --log-level DEBUG`

### "Folder name is empty in CSV"
- Ensure your Remmina connections are organized in groups/folders
- The tracker reads `.remmina` files from `~/.local/share/remmina/`
- Check that the `group` field is set in your `.remmina` profile files

## Uninstalling

```bash
chmod +x uninstall.sh
./uninstall.sh
```

This removes the service, launcher, and installed files. The CSV log at `~/Documents/remmina_time_tracking.csv` is preserved.

## Architecture

```
remmina_time_tracker/
├── __init__.py          # Package init
├── daemon.py            # Main daemon: GLib event loop, orchestration
├── monitor.py           # Process scanning: detects xfreerdp/ssh processes
├── config_parser.py     # Parses ~/.local/share/remmina/*.remmina files
├── csv_logger.py        # Thread-safe CSV writer with error handling
├── idle_detector.py     # System-wide idle detection (X11/Wayland)
├── window_tracker.py    # Remmina window focus detection (X11/Wayland)
└── sleep_handler.py     # Sleep/wake D-Bus signal handler
```

## License

MIT License - See [LICENSE](LICENSE) file.

Copyright (c) 2026 MRU Consulting

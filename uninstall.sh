#!/bin/bash
# Remmina Time Tracker - Uninstallation Script
set -e

INSTALL_DIR="$HOME/.local/lib/remmina-time-tracker"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "============================================"
echo "  Remmina Time Tracker - Uninstaller"
echo "============================================"
echo ""

# Stop and disable service
if systemctl --user is-active remmina-time-tracker.service &>/dev/null; then
    systemctl --user stop remmina-time-tracker.service
    echo "[OK] Service stopped"
fi

if systemctl --user is-enabled remmina-time-tracker.service &>/dev/null; then
    systemctl --user disable remmina-time-tracker.service
    echo "[OK] Service disabled"
fi

# Remove service file
rm -f "$SERVICE_DIR/remmina-time-tracker.service"
systemctl --user daemon-reload
echo "[OK] Service file removed"

# Remove launcher
rm -f "$BIN_DIR/remmina-time-tracker"
echo "[OK] Launcher removed"

# Remove installation
rm -rf "$INSTALL_DIR"
echo "[OK] Installation directory removed"

# Remove Remmina plugin loader (if installed)
for dir in \
    "/usr/lib/x86_64-linux-gnu/remmina/plugins" \
    "/usr/lib/remmina/plugins" \
    "/usr/lib64/remmina/plugins" \
    "$HOME/.local/lib/remmina/plugins"; do
    if [ -f "$dir/remmina_plugin_loader.py" ]; then
        if [ -w "$dir" ]; then
            rm -f "$dir/remmina_plugin_loader.py"
            echo "[OK] Remmina plugin loader removed from $dir"
        else
            echo "[INFO] Run: sudo rm $dir/remmina_plugin_loader.py"
        fi
    fi
done

echo ""
echo "Uninstallation complete."
echo ""
echo "NOTE: CSV log file preserved at ~/.local/share/remmina/time_tracking.csv"
echo "      Delete manually if no longer needed."
echo ""

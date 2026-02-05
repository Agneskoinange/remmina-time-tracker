#!/bin/bash
# Remmina Time Tracker - Installation Script
# Works on Ubuntu, Pop!_OS, Debian, and other systemd-based Linux distros
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/lib/remmina-time-tracker"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"
REMMINA_PLUGIN_DIR=""

echo "============================================"
echo "  Remmina Time Tracker - Installer"
echo "  By MRU Consulting"
echo "============================================"
echo ""

# Check Python version
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 is required but not found."
    echo "Install: sudo apt install python3"
    exit 1
fi

PYTHON_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "[OK] Python $PYTHON_VERSION found"

# Check and install dependencies
echo ""
echo "Checking dependencies..."

install_apt_packages() {
    local packages=()

    # Check psutil
    if ! $PYTHON -c "import psutil" 2>/dev/null; then
        echo "[!] psutil not found"
        packages+=("python3-psutil")
    else
        echo "[OK] psutil"
    fi

    # Check PyGObject (gi)
    if ! $PYTHON -c "from gi.repository import GLib" 2>/dev/null; then
        echo "[!] PyGObject (GLib) not found"
        packages+=("python3-gi" "gir1.2-glib-2.0")
    else
        echo "[OK] PyGObject"
    fi

    # Check xprintidle
    if ! command -v xprintidle &>/dev/null; then
        echo "[!] xprintidle not found (needed for idle detection)"
        packages+=("xprintidle")
    else
        echo "[OK] xprintidle"
    fi

    if [ ${#packages[@]} -gt 0 ]; then
        echo ""
        echo "Installing missing packages: ${packages[*]}"
        echo "Running: sudo apt install -y ${packages[*]}"
        sudo apt install -y "${packages[@]}"
    fi
}

install_apt_packages

echo ""
echo "Installing Remmina Time Tracker..."

# Create install directory
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$SERVICE_DIR"

# Copy Python package
cp -r "$SCRIPT_DIR/remmina_time_tracker" "$INSTALL_DIR/"

# Create launcher script
cat > "$BIN_DIR/remmina-time-tracker" << 'LAUNCHER'
#!/bin/bash
# Remmina Time Tracker launcher
INSTALL_DIR="$HOME/.local/lib/remmina-time-tracker"
export PYTHONPATH="$INSTALL_DIR:$PYTHONPATH"

# Pass through XDG_SESSION_TYPE for idle detection
exec python3 -m remmina_time_tracker.daemon "$@"
LAUNCHER
chmod +x "$BIN_DIR/remmina-time-tracker"

# Create __main__.py for python -m execution
cat > "$INSTALL_DIR/remmina_time_tracker/__main__.py" << 'MAIN'
from remmina_time_tracker.daemon import main
main()
MAIN

echo "[OK] Installed to $INSTALL_DIR"
echo "[OK] Launcher at $BIN_DIR/remmina-time-tracker"

# Install systemd service
cp "$SCRIPT_DIR/remmina-time-tracker.service" "$SERVICE_DIR/"
systemctl --user daemon-reload
systemctl --user enable remmina-time-tracker.service

echo "[OK] systemd user service installed and enabled"

# Try to install Remmina plugin wrapper (optional)
for dir in \
    "/usr/lib/x86_64-linux-gnu/remmina/plugins" \
    "/usr/lib/remmina/plugins" \
    "/usr/lib64/remmina/plugins" \
    "$HOME/.local/lib/remmina/plugins"; do
    if [ -d "$dir" ]; then
        REMMINA_PLUGIN_DIR="$dir"
        break
    fi
done

if [ -n "$REMMINA_PLUGIN_DIR" ] && [ -f "$SCRIPT_DIR/remmina_plugin_loader.py" ]; then
    # Plugin dir found, but we need write access
    if [ -w "$REMMINA_PLUGIN_DIR" ]; then
        cp "$SCRIPT_DIR/remmina_plugin_loader.py" "$REMMINA_PLUGIN_DIR/"
        echo "[OK] Remmina plugin loader installed to $REMMINA_PLUGIN_DIR"
    else
        echo "[INFO] Remmina plugin dir found at $REMMINA_PLUGIN_DIR (needs sudo to install plugin loader)"
        echo "       Optional: sudo cp $SCRIPT_DIR/remmina_plugin_loader.py $REMMINA_PLUGIN_DIR/"
    fi
else
    echo "[INFO] Remmina plugin directory not found. Using systemd service only."
fi

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "Start now:     systemctl --user start remmina-time-tracker"
echo "Check status:  systemctl --user status remmina-time-tracker"
echo "View logs:     journalctl --user -u remmina-time-tracker -f"
echo "View CSV:      cat ~/.local/share/remmina/time_tracking.csv"
echo ""
echo "The service will auto-start on login."
echo ""
echo "Manual usage:  remmina-time-tracker --help"
echo "  Track only (no idle disconnect): remmina-time-tracker --no-idle"
echo "  Custom idle threshold:           remmina-time-tracker --idle-threshold 15"
echo ""

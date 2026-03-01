#!/usr/bin/env bash
# install.sh — set up weather-bar and enable autostart on GNOME login

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/weather_bar.py"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP="$AUTOSTART_DIR/weather-bar.desktop"

echo "=== weather-bar installer ==="

# Make the app executable
chmod +x "$APP"

# Check dependencies
if ! python3 -c "import gi" 2>/dev/null; then
    echo "Installing python3-gi…"
    sudo apt-get install -y python3-gi gir1.2-gtk-3.0
fi

# Autostart entry
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP" << EOF
[Desktop Entry]
Type=Application
Name=Weather Bar
Comment=Slim weather overlay for GNOME desktop
Exec=python3 $APP
Icon=weather-few-clouds
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

echo ""
echo "Done!"
echo ""
echo "  Run now:       python3 $APP"
echo "  Set your city: python3 $APP --city 'Madrid'"
echo "  Autostart:     enabled (starts on next login)"
echo ""
echo "Left-click the bar to refresh, right-click for options."

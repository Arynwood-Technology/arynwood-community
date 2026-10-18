#!/usr/bin/env bash
# Adds Arynwood Grove to the application menu and the desktop.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
mkdir -p "$APPS" "$ICONS"
chmod +x "$ROOT/desktop/arynwood-community"
cp "$ROOT/desktop/arynwood-community.png" "$ICONS/arynwood-community.png"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/arynwood-community.svg"

entry() {
cat <<ENTRY
[Desktop Entry]
Version=1.5
Type=Application
Name=Arynwood Grove
GenericName=Community
Comment=Messages, plans, household tasks, lists and notes for your people
Exec="$ROOT/desktop/arynwood-community"
Icon=arynwood-community
Terminal=false
Categories=Network;Chat;InstantMessaging;
Keywords=community;chat;calendar;tasks;notes;mail;irc;
StartupNotify=true
StartupWMClass=ArynwoodCommunity
Actions=stop;

[Desktop Action stop]
Name=Stop Arynwood Grove
Exec="$ROOT/desktop/arynwood-community" --stop
ENTRY
}

entry >"$APPS/arynwood-community.desktop"
chmod 644 "$APPS/arynwood-community.desktop"
if [[ -d "$DESKTOP_DIR" ]]; then
  entry >"$DESKTOP_DIR/arynwood-community.desktop"
  chmod 755 "$DESKTOP_DIR/arynwood-community.desktop"
  gio set "$DESKTOP_DIR/arynwood-community.desktop" metadata::trusted true 2>/dev/null || true
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
echo "Installed. Find Arynwood Grove in your app menu${DESKTOP_DIR:+ and on the desktop}."

#!/usr/bin/env bash
# Desktop integration for ScriptForge.
#
# Installs an app-menu entry and a desktop shortcut that launch the Qt window.
# The entry is Terminal=false on purpose: the reported failure mode was the
# window dying because a .desktop launch has no controlling terminal, so the
# launcher must not imply one and the app must not want one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="scriptforge"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
DESKTOP_DIR="$HOME/Desktop"

GREEN=$'\033[32m'; CYAN=$'\033[36m'; DIM=$'\033[2m'; OFF=$'\033[0m'
ok()  { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
info() { printf '  %s·%s %s\n' "$DIM" "$OFF" "$1"; }
say() { printf '%s==>%s %s\n' "$CYAN" "$OFF" "$1"; }

[ -t 1 ] || { GREEN=""; CYAN=""; DIM=""; OFF=""; }

say "Installing ScriptForge desktop integration"

ROOT="$(cd "$HERE/../.." && pwd)"
EXEC_CANDIDATE="$ROOT/.venv/bin/scriptforge"

if [ ! -x "$EXEC_CANDIDATE" ]; then
  EXEC_CANDIDATE="$(command -v scriptforge || true)"
fi
if [ -z "$EXEC_CANDIDATE" ] || [ ! -x "$EXEC_CANDIDATE" ]; then
  printf '  %s✗%s scriptforge executable not found. Run ./install.sh first.\n' "$GREEN" "$OFF" >&2
  exit 1
fi
EXEC_PATH="$(cd "$(dirname "$EXEC_CANDIDATE")" && pwd)/$(basename "$EXEC_CANDIDATE")"

mkdir -p "$APPS_DIR" "$DESKTOP_DIR"

# --- icons -----------------------------------------------------------------
count=0
for svg in "$HERE/../icon/scriptforge.svg"; do
  [ -f "$svg" ] || continue
  for size in 16 24 32 48 64 128 256 512; do
    png="$HERE/../icon/scriptforge-$size.png"
    [ -f "$png" ] || continue
    dest="$ICON_DIR/${size}x${size}/apps/$APP_NAME.png"
    mkdir -p "$(dirname "$dest")"
    cp -f "$png" "$dest"
    count=$((count + 1))
  done
done
mkdir -p "$ICON_DIR/scalable/apps"
cp -f "$HERE/../icon/scriptforge.svg" "$ICON_DIR/scalable/apps/$APP_NAME.svg" 2>/dev/null || true
ok "installed $count icon files into $ICON_DIR"

# --- launchers -------------------------------------------------------------
render() {
  local template="$1" out="$2"
  sed "s|@EXEC@|$EXEC_PATH|g" "$template" > "$out"
  chmod +x "$out"
}

render "$HERE/scriptforge.desktop.in" "$APPS_DIR/$APP_NAME.desktop"
ok "app-menu entry: $APPS_DIR/$APP_NAME.desktop"

render "$HERE/scriptforge-tui.desktop.in" "$APPS_DIR/$APP_NAME-tui.desktop"
ok "app-menu entry: $APPS_DIR/$APP_NAME-tui.desktop"

if [ -d "$DESKTOP_DIR" ]; then
  cp -f "$APPS_DIR/$APP_NAME.desktop" "$DESKTOP_DIR/$APP_NAME.desktop"
  chmod +x "$DESKTOP_DIR/$APP_NAME.desktop"
  # GNOME shows an untrusted launcher as a text file until this metadata is set.
  if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/$APP_NAME.desktop" metadata::trusted true 2>/dev/null || true
  fi
  ok "desktop shortcut: $DESKTOP_DIR/$APP_NAME.desktop"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" 2>/dev/null && info "desktop database updated"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$ICON_DIR" >/dev/null 2>&1 && info "icon cache refreshed"
fi

printf '\n%sDesktop integration ready.%s\n\n' "$GREEN" "$OFF"
printf '  App menu : ScriptForge (window)  ·  ScriptForge (terminal)\n'
printf '  Desktop  : %s/%s.desktop\n' "$DESKTOP_DIR" "$APP_NAME"
printf '  Launch   : %s gui\n\n' "$EXEC_PATH"
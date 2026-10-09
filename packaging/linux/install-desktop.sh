#!/usr/bin/env bash
# Install the ScriptForge icon + .desktop entry (app menu and Desktop).
# by AIHAM AM
#
#   ./packaging/linux/install-desktop.sh [--uninstall]
#
# Safe to re-run. Never touches your scripts.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
ICONS="$ROOT/packaging/icon"
TEMPLATE="$ROOT/packaging/linux/scriptforge.desktop.in"

APP_NAME="scriptforge"
EXEC_PATH="${SCRIPTFORGE_EXEC:-$ROOT/.venv/bin/scriptforge}"

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"

GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
ok()  { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
info(){ printf '  %s·%s %s\n' "$DIM" "$OFF" "$1"; }
die() { printf '  %s✗%s %s\n' "$RED" "$OFF" "$1" >&2; exit 1; }

installed_files=(
  "$APPS_DIR/$APP_NAME.desktop"
  "$APPS_DIR/$APP_NAME-gui.desktop"
  "$DESKTOP_DIR/$APP_NAME.desktop"
  "$DESKTOP_DIR/$APP_NAME-GUI.desktop"
)

uninstall() {
  echo "==> Removing ScriptForge desktop integration"
  rm -f "${installed_files[@]}"
  for size in 16 24 32 48 64 128 256 512; do
    rm -f "$ICON_BASE/${size}x${size}/apps/$APP_NAME.png"
  done
  rm -f "$ICON_BASE/scalable/apps/$APP_NAME.svg"
  command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
  ok "removed (your scripts in ~/bin were never touched)"
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

echo "==> Installing ScriptForge desktop integration"

# --------------------------------------------------------------- preflight
[ -f "$TEMPLATE" ]  || die "missing template: $TEMPLATE"
[ -d "$ICONS" ]     || die "missing icon directory: $ICONS"
if [ ! -x "$EXEC_PATH" ]; then
  if [ -x "$ROOT/.venv/bin/scriptforge" ]; then
    EXEC_PATH="$ROOT/.venv/bin/scriptforge"
  else
    die "scriptforge executable not found at $EXEC_PATH
     Run ./install.sh first, or set SCRIPTFORGE_EXEC=/path/to/scriptforge"
  fi
fi

mkdir -p "$APPS_DIR" "$DESKTOP_DIR"

# --------------------------------------------------------------- icons
installed=0
for size in 16 24 32 48 64 128 256 512; do
  src="$ICONS/$APP_NAME-$size.png"
  if [ -f "$src" ]; then
    dest="$ICON_BASE/${size}x${size}/apps"
    mkdir -p "$dest"
    cp -f "$src" "$dest/$APP_NAME.png"
    installed=$((installed + 1))
  fi
done

scalable="$ICON_BASE/scalable/apps"
mkdir -p "$scalable"
cp -f "$ICONS/$APP_NAME.svg" "$scalable/$APP_NAME.svg" 2>/dev/null && installed=$((installed + 1))
cp -f "$ICONS/$APP_NAME.svg" "$APPS_DIR/$APP_NAME.svg" 2>/dev/null || true
ok "installed $installed icon files into $ICON_BASE"

# --------------------------------------------------------------- desktop entry
generated="$APPS_DIR/$APP_NAME.desktop"
sed "s|@EXEC@|$EXEC_PATH|g" "$TEMPLATE" > "$generated"
chmod +x "$generated"
ok "app-menu entry: $generated"

# the browser GUI gets its own entry (no terminal window)
GUI_TEMPLATE="$HERE/scriptforge-gui.desktop.in"
if [ -f "$GUI_TEMPLATE" ]; then
  gui_entry="$APPS_DIR/$APP_NAME-gui.desktop"
  sed "s|@EXEC@|$EXEC_PATH|g" "$GUI_TEMPLATE" > "$gui_entry"
  chmod +x "$gui_entry"
  ok "app-menu entry: $gui_entry"
  if [ -d "$DESKTOP_DIR" ]; then
    cp -f "$gui_entry" "$DESKTOP_DIR/$APP_NAME-GUI.desktop"
    chmod +x "$DESKTOP_DIR/$APP_NAME-GUI.desktop"
    if command -v gio >/dev/null 2>&1; then
      gio set "$DESKTOP_DIR/$APP_NAME-GUI.desktop" metadata::trusted true 2>/dev/null || true
    fi
    ok "desktop shortcut: $DESKTOP_DIR/$APP_NAME-GUI.desktop"
  fi
fi

# --------------------------------------------------------------- Desktop shortcut
if [ -d "$DESKTOP_DIR" ]; then
  cp -f "$generated" "$DESKTOP_DIR/$APP_NAME.desktop"
  chmod +x "$DESKTOP_DIR/$APP_NAME.desktop"
  # GNOME needs an explicit "trusted" flag before it will launch the launcher.
  if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/$APP_NAME.desktop" metadata::trusted true 2>/dev/null || true
  fi
  ok "desktop shortcut: $DESKTOP_DIR/$APP_NAME.desktop"
fi

# --------------------------------------------------------------- caches
if command -v update-desktop-database >/dev/null; then
  update-desktop-database "$APPS_DIR" 2>/dev/null && info "desktop database updated" || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
  gtk-update-icon-cache -f -t "$ICON_BASE" >/dev/null 2>&1 && info "icon cache refreshed" || true
fi
xdg-mime default "$APP_NAME.desktop" x-scheme-handler/scriptforge 2>/dev/null || true

cat <<DONE

$(printf '%s' "$GREEN")Desktop integration ready.$(printf '%s' "$OFF")

  App menu : ScriptForge (terminal)  and  ScriptForge GUI (browser)
  Desktop  : $DESKTOP_DIR/$APP_NAME.desktop
  Command  : $EXEC_PATH

  Remove it again:
    ./packaging/linux/install-desktop.sh --uninstall

DONE
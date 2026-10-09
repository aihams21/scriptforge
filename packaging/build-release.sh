#!/usr/bin/env bash
# Build the two download bundles and the ~/Downloads/ScriptForge folder.
#
#   ./packaging/build-release.sh
#
# Produces:
#   ~/Downloads/ScriptForge/               unpacked, browsable
#   ~/Downloads/ScriptForge-linux.tar.gz   direct download
#   ~/Downloads/ScriptForge-windows.zip    direct download
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DL="${SCRIPTFORGE_OUT:-$HOME/Downloads}"
NAME="ScriptForge"

GREEN=$'\033[32m'; CYAN=$'\033[36m'; DIM=$'\033[2m'; OFF=$'\033[0m'
[ -t 1 ] || { GREEN=""; CYAN=""; DIM=""; OFF=""; }
say() { printf '%s==>%s %s\n' "$CYAN" "$OFF" "$1"; }
ok()  { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# ------------------------------------------------------------------ staging
stage() {
  local dest="$1"
  mkdir -p "$dest"
  cp -r "$SRC/scriptforge" "$dest/scriptforge"
  cp -r "$SRC/packaging"    "$dest/packaging"
  cp -r "$SRC/tests"        "$dest/tests"
  cp "$SRC/install.sh" "$SRC/install.ps1" "$SRC/pyproject.toml" \
     "$SRC/README.md" "$SRC/LICENSE" "$SRC/.gitignore" "$dest/"
  cp -r "$SRC/docs"         "$dest/docs"
  find "$dest" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  find "$dest" -name '*.pyc' -delete 2>/dev/null || true
  rm -rf "$dest/scriptforge.egg-info"
  chmod +x "$dest/install.sh" "$dest/packaging/linux/install-desktop.sh" 2>/dev/null || true
}

say "staging trees"
LINUX_TREE="$STAGE/${NAME}-linux"
WIN_TREE="$STAGE/${NAME}-windows"
stage "$LINUX_TREE"
ok "linux tree"

# The Windows zip carries no .desktop entries, no bash installers and no
# pytest fixtures: shipping them invites someone to run the wrong one.
rm -rf "$LINUX_TREE/.venv"
mkdir -p "$WIN_TREE/scriptforge" "$WIN_TREE/packaging/icon"
cp -r "$SRC/scriptforge/." "$WIN_TREE/scriptforge/"
cp "$SRC/packaging/icon/scriptforge.ico" "$SRC/packaging/icon/scriptforge.svg" "$WIN_TREE/packaging/icon/"
mkdir -p "$WIN_TREE/packaging/windows"
cp "$SRC/packaging/windows/scriptforge.bat" "$WIN_TREE/packaging/windows/"
cp "$SRC/install.ps1" "$SRC/pyproject.toml" "$SRC/README.md" "$SRC/LICENSE" "$WIN_TREE/"
mkdir -p "$WIN_TREE/docs"
cp "$SRC/docs/banner.svg" "$SRC/docs/banner.png" "$SRC/docs/demo.gif" "$WIN_TREE/docs/"
find "$WIN_TREE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
ok "windows tree"

# ------------------------------------------------------------------ verify
say "verifying"
"$SRC/.venv/bin/python" - "$LINUX_TREE" "$WIN_TREE" <<'PYCHECK'
import ast, pathlib, sys
for root in sys.argv[1:]:
    files = sorted(pathlib.Path(root).rglob("*.py"))
    for f in files:
        ast.parse(f.read_text(), filename=str(f))
    print(f"  {root}: {len(files)} python files parse")
PYCHECK
ok "python parses"
bash -n "$LINUX_TREE/install.sh" && echo "  install.sh syntax ok"
bash -n "$LINUX_TREE/packaging/linux/install-desktop.sh" && echo "  install-desktop.sh syntax ok"
"$SRC/.venv/bin/python" -c "
d=open('$LINUX_TREE/packaging/icon/scriptforge.ico','rb').read()
assert d[:4]==b'\x00\x00\x01\x00','ICO header bad'
print('  scriptforge.ico header ok')
"
ok "assets verified"

# ------------------------------------------------------------------ publish
say "publishing to $DL"
rm -rf "$DL/$NAME" "$DL/${NAME}-linux.tar.gz" "$DL/${NAME}-windows.zip"

cp -r "$LINUX_TREE" "$DL/$NAME"
ok "folder:  $DL/$NAME"

tar -czf "$DL/${NAME}-linux.tar.gz" -C "$STAGE" "$NAME-linux"
ok "archive: $(basename "$DL/${NAME}-linux.tar.gz")  $(du -h "$DL/${NAME}-linux.tar.gz" | cut -f1)"

( cd "$STAGE" && zip -qr "$DL/${NAME}-windows.zip" "$NAME-windows" )
ok "archive: $(basename "$DL/${NAME}-windows.zip")  $(du -h "$DL/${NAME}-windows.zip" | cut -f1)"

printf '\n%sDone.%s\n\n' "$GREEN" "$OFF"
printf '  folder    %s/%s\n' "$DL" "$NAME"
printf '  linux     %s/%s-linux.tar.gz\n' "$DL" "$NAME"
printf '  windows   %s/%s-windows.zip\n' "$DL" "$NAME"
printf '  files     %s\n\n' "$(find "$DL/$NAME" -type f | wc -l)"
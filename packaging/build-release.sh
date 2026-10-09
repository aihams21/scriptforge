#!/usr/bin/env bash
# Build the release folder: ~/Downloads/scriptforge-app/
# Contains everything needed to install and run ScriptForge on Linux or Windows.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$HOME/Downloads/scriptforge-app}"

GREEN=$'\033[32m'; DIM=$'\033[2m'; CYAN=$'\033[36m'; OFF=$'\033[0m'
say() { printf '%s==>%s %s\n' "$CYAN" "$OFF" "$1"; }
ok()  { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }

say "Building the release in $OUT"

rm -rf "$OUT"
mkdir -p "$OUT"

# --- source ---------------------------------------------------------------
cp -r "$SRC/scriptforge" "$OUT/scriptforge"   # $OUT is fresh, so no nesting
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$OUT/scriptforge.egg-info"
ok "application source"

# --- tests ---------------------------------------------------------------
mkdir -p "$OUT/tests"
cp "$SRC/tests"/*.py "$OUT/tests/"
ok "tests"

# --- packaging + installers ---------------------------------------------
mkdir -p "$OUT/packaging/icon" "$OUT/packaging/linux" "$OUT/packaging/windows"
cp "$SRC/packaging/icon"/*.svg "$SRC/packaging/icon"/*.png "$SRC/packaging/icon"/*.ico \
   "$SRC/packaging/icon/make_ico.py" "$OUT/packaging/icon/"
cp "$SRC/packaging/linux"/* "$OUT/packaging/linux/"
cp "$SRC/packaging/windows"/* "$OUT/packaging/windows/"
ok "icons, desktop entries and Windows assets"

cp "$SRC/install.sh" "$SRC/install.ps1" "$SRC/scriptforge.bat" \
   "$SRC/pyproject.toml" "$SRC/README.md" "$SRC/LICENSE" "$SRC/.gitignore" "$OUT/"
chmod +x "$OUT/install.sh" "$OUT/packaging/linux/install-desktop.sh"
ok "installers and metadata"

# --- quick reference ------------------------------------------------------
cat > "$OUT/QUICK-START.md" <<'EOF'
# Quick start

## Kali Linux / any Linux

```bash
chmod +x install.sh
./install.sh --desktop     # installs, self-tests, adds the icon
scriptforge gui            # mouse-driven, opens in your browser
scriptforge                # terminal interface
```

## Windows 10 / 11

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Creates **ScriptForge** (terminal) and **ScriptForge GUI** (browser) on the
Start menu and the Desktop.

## What it does

Pick any `.sh` / `.py` / `.ps1` / `.bat` script. ScriptForge reads its hidden
interface and builds a screen for it. Scripts with no interface are
re-programmed into interactive wrappers — your originals are never modified.
EOF
ok "QUICK-START.md"

# --- self check -----------------------------------------------------------
say "Verifying the build"
cd "$OUT"
python3 -c "
import ast, pathlib, sys
files = list(pathlib.Path('scriptforge').rglob('*.py')) + list(pathlib.Path('tests').rglob('*.py'))
for f in files:
    ast.parse(f.read_text())
print(f'  {len(files)} python files parse cleanly')
"
bash -n install.sh && echo "  install.sh syntax OK"
bash -n packaging/linux/install-desktop.sh && echo "  install-desktop.sh syntax OK"
python3 -c "
import zipfile
zipfile.ZipFile('packaging/icon/scriptforge.ico').testzip() if False else None
d = open('packaging/icon/scriptforge.ico','rb').read()
assert d[:4] == b'\x00\x00\x01\x00', 'ICO header bad'
print('  scriptforge.ico header OK')
"
ok "build verified"

printf '\n%sRelease ready:%s  %s\n\n' "$GREEN" "$OFF" "$OUT"
find "$OUT" -maxdepth 1 -mindepth 1 -printf '  %f\n' | sort
printf '  %s files total\n' "$(find "$OUT" -type f | wc -l)"

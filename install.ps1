<#
.SYNOPSIS
    ScriptForge installer for Windows 10/11.

.DESCRIPTION
    Creates an isolated virtual environment, installs the package, adds a
    desktop shortcut and a Start-menu entry for the window, and runs a
    self-test. Safe to re-run: it only installs what is missing.

.EXAMPLE
    iex ((New-Object System.Net.WebClient).DownloadString('https://raw.githubusercontent.com/aihams21/scriptforge/main/install.ps1'))

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Prefix "$env:LOCALAPPDATA\ScriptForge"
#>
[CmdletBinding()]
param(
    [string]$Prefix = "$env:LOCALAPPDATA\ScriptForge",
    [string]$Version = "v0.1.0",
    [string]$LocalSource = "",
    [switch]$SkipDesktop,
    [switch]$NoWindow
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Repo = "https://github.com/aihams21/scriptforge"

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Write-Note($m) { Write-Host "  [!] $m"  -ForegroundColor Yellow }
function Die($m) { Write-Host "  [x] $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "ScriptForge" -ForegroundColor White -NoNewline
Write-Host "  any script becomes a usable app" -ForegroundColor DarkGray
Write-Host ""

# ---------------------------------------------------------------- interpreter
$py = $null
foreach ($cand in @("py", "python3", "python")) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) {
        $candPath = (Get-Command $cand).Source
        # The `py` launcher is the only reliable way to hit 64-bit Python on
        # Windows; a bare `python` may be the 32-bit Store stub that cannot
        # load PySide6's wheels.
        if ($cand -eq "py") { $py = $cand } else { $py = $cand }
        break
    }
}
if (-not $py) { Die "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and tick 'Add to PATH'." }

$verOut = & $py -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
if (-not $verOut) { Die "Python is present but not runnable: $py" }
Write-Ok "python $verOut  ($py)"

# -------------------------------------------------------------------- fetch
Write-Step "download"
$tmp = Join-Path $env:TEMP ("sf-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

if ($LocalSource -and (Test-Path $LocalSource)) {
    $src = (Resolve-Path $LocalSource).Path
    Write-Ok "using local source: $src"
} else {
    $url = "$Repo/archive/refs/tags/$Version.tar.gz"
    $tgz = Join-Path $tmp "sf.tar.gz"
    try {
        Write-Ok "fetching $Version"
        (New-Object System.Net.WebClient).DownloadFile($url, $tgz)
    } catch {
        $url = "$Repo/archive/refs/heads/main.tar.gz"
        Write-Note "tag fetch failed, trying main"
        (New-Object System.Net.WebClient).DownloadFile($url, $tgz)
    }
    & tar -xzf $tgz -C $tmp
    if ($LASTEXITCODE -ne 0) { Die "could not unpack the archive" }
    $src = (Get-ChildItem -Path $tmp -Directory | Where-Object { $_.Name -like "scriptforge-*" } | Select-Object -First 1).FullName
    if (-not $src) { Die "unexpected archive layout" }
}

# -------------------------------------------------------------------- layout
Write-Step "layout"
New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
foreach ($item in @("scriptforge", "packaging")) {
    $dest = Join-Path $Prefix $item
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse -Force (Join-Path $src $item) $dest
}
foreach ($f in @("pyproject.toml", "LICENSE", "README.md")) {
    $p = Join-Path $src $f
    if (Test-Path $p) { Copy-Item -Force $p (Join-Path $Prefix $f) }
}
Get-ChildItem -Path $Prefix -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Ok "installed to $Prefix"

# --------------------------------------------------------------------- venv
Write-Step "python environment"
$Venv = Join-Path $Prefix "venv"
$Vpy  = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Vpy)) {
    & $py -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Die "could not create a virtual environment" }
}
Write-Ok "venv ready"

& $Vpy -m pip install --quiet --upgrade pip setuptools wheel 2>$null
& $Vpy -m pip install --quiet -e $Prefix
if ($LASTEXITCODE -ne 0) { Die "pip install failed" }
& $Vpy -m pip install --quiet PySide6
if ($LASTEXITCODE -ne 0) { Write-Note "PySide6 could not be installed; the terminal UI still works" }
Write-Ok "packages installed"

# ----------------------------------------------------------------- shortcuts
if (-not $SkipDesktop) {
    Write-Step "shortcuts"
    $Target = Join-Path $Venv "Scripts\scriptforge.exe"
    if (-not (Test-Path $Target)) {
        $script = Join-Path $Venv "Scripts\scriptforge-script.py"
        if (Test-Path $script) {
            $bat = Join-Path $Prefix "ScriptForge.bat"
            "@echo off`r`n`"$Vpy`" `"$script`" %*`r`n" | Set-Content -Path $bat -Encoding ASCII
            $Target = $bat
        }
    }

    $shell = New-Object -ComObject WScript.Shell
    $Icon = Join-Path $Prefix "packaging\icon\scriptforge.ico"

    $StartM = [Environment]::GetFolderPath("StartMenu")
    $Desk   = [Environment]::GetFolderPath("Desktop")

    foreach ($dir in @($StartM, $Desk)) {
        if (-not (Test-Path $dir)) { continue }
        foreach ($entry in @(
            @{ Name = "ScriptForge";     Args = "";     Style = 1 },
            @{ Name = "ScriptForge TUI"; Args = " tui";  Style = 1 }
        )) {
            $lnk = Join-Path $dir ($entry.Name + ".lnk")
            $sc = $shell.CreateShortcut($lnk)
            $sc.TargetPath = $Target
            $sc.Arguments = $entry.Args
            $sc.WorkingDirectory = $Prefix
            $sc.Description = "Turn any bash, python or PowerShell script into a usable app"
            if (Test-Path $Icon) { $sc.IconLocation = "$Icon,0" }
            $sc.WindowStyle = $entry.Style
            $sc.Save()
            Write-Ok "shortcut -> $lnk"
        }
    }
}

# ----------------------------------------------------------------- self test
Write-Step "self-test"
$check = @'
import sys, pathlib
root = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root))
from scriptforge.core.parser.classify import analyze
from scriptforge.core.rewriter import rewrite
probe = root / "_selftest.ps1"
probe.write_text('$h = Read-Host "host"\nWrite-Host "ok $h"\n')
ir = analyze(probe)
assert ir.prompt_sites, "parser recovered no prompts"
before = probe.read_bytes()
res = rewrite(ir)
assert res.ok, res.message
assert probe.read_bytes() == before, "rewrite touched the original"
probe.unlink()
try:
    import PySide6; gui = "ok"
except Exception:
    gui = "absent"
print("  parser  ok  %d prompt(s) recovered" % len(ir.prompt_sites))
print("  rewriter ok  source untouched")
print("  gui     %s" % gui)
'@
$checkFile = Join-Path $tmp "check.py"
$check | Set-Content -Path $checkFile -Encoding UTF8
& $Vpy $checkFile $Prefix
if ($LASTEXITCODE -ne 0) { Die "self-test failed" }
Write-Ok "self-test passed"

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "ScriptForge is ready." -ForegroundColor Green
Write-Host ""
Write-Host "  window    Start menu -> ScriptForge"
Write-Host "  terminal  $Prefix\venv\Scripts\scriptforge.exe tui"
Write-Host ""

if (-not $NoWindow) {
    Start-Process (Join-Path $Prefix "venv\Scripts\scriptforge.exe")
}
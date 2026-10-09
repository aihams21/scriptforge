@echo off
REM scriptforge launcher for Windows - by AIHAM AM
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\scriptforge.exe" (
  "%HERE%.venv\Scripts\scriptforge.exe" %*
) else if exist "%HERE%.venv\Scripts\scriptforge-scriptforge.exe" (
  "%HERE%.venv\Scripts\scriptforge-scriptforge.exe" %*
) else (
  echo scriptforge is not installed yet.
  echo Run:  powershell -ExecutionPolicy Bypass -File "%HERE%install.ps1"
  exit /b 1
)
endlocal

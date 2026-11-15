@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create .venv and install requirements-build.lock first.
    exit /b 1
)
.venv\Scripts\python.exe -m pytest tests -q
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe release_package.py
if errorlevel 1 exit /b 1
echo Versioned ZIP and SHA256SUMS.txt are in dist\releases.

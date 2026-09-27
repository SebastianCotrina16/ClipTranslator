@echo off
setlocal
cd /d "%~dp0"

set "UV_PYTHON_INSTALL_DIR=%~dp0python"
set "UV_PYTHON_PREFERENCE=only-managed"

set "EXTRA=cpu"
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "EXTRA=cuda"

echo Installing ClipTranslator components (%EXTRA%) > "%~dp0install.log"
"%~dp0uv.exe" sync --frozen --no-dev --extra %EXTRA% >> "%~dp0install.log" 2>&1
exit /b %ERRORLEVEL%

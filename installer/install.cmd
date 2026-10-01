@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
set "UV_PYTHON_DOWNLOADS=never"

set "EXTRA=cpu"
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "EXTRA=cuda"

echo Installing ClipTranslator components (%EXTRA%) > "%~dp0install.log"
"%~dp0uv.exe" sync --frozen --no-dev --extra %EXTRA% --python "%PYTHON%" >> "%~dp0install.log" 2>&1
if not errorlevel 1 exit /b 0

echo Retrying with a clean environment >> "%~dp0install.log"
if exist "%~dp0.venv" rmdir /s /q "%~dp0.venv"
"%~dp0uv.exe" sync --frozen --no-dev --extra %EXTRA% --python "%PYTHON%" >> "%~dp0install.log" 2>&1
exit /b %ERRORLEVEL%

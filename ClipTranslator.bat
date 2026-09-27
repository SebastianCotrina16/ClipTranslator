@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    if not exist "%USERPROFILE%\.local\bin\uv.exe" (
        echo Instalando uv...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    )
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

set "EXTRA=cpu"
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "EXTRA=cuda"

echo Preparando dependencias (%EXTRA%)...
uv sync --extra %EXTRA% --quiet
if errorlevel 1 goto :error

if /i "%~1"=="--setup" goto :setup
if not exist "%APPDATA%\ClipTranslator\config.toml" goto :setup
goto :run

:setup
uv run --no-sync python -m app.presentation.wizard
if errorlevel 1 goto :error
if /i "%~1"=="--setup" goto :end

:run
if "%~1"=="" (
    echo.
    echo Arrastra un video sobre ClipTranslator.bat para subtitularlo.
    echo Opciones: uv run python -m app.presentation.cli --help
    goto :end
)
uv run --no-sync python -m app.presentation.cli %*
if errorlevel 1 goto :error
goto :end

:error
echo.
echo Algo salió mal. Revisa el mensaje de arriba.

:end
echo.
pause

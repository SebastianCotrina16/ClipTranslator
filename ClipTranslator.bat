@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    if not exist "%USERPROFILE%\.local\bin\uv.exe" (
        echo Installing uv...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    )
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

set "EXTRA=cpu"
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "EXTRA=cuda"

echo Installing ClipTranslator (%EXTRA%). The first time this can take a few minutes...
uv sync --extra %EXTRA%
if errorlevel 1 goto :error

set "CLIPTRANSLATOR_APP=%~dp0.venv\Scripts\cliptranslator-app.exe"
set "CLIPTRANSLATOR_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$shell = New-Object -ComObject WScript.Shell; foreach ($folder in @([Environment]::GetFolderPath('Desktop'), $env:CLIPTRANSLATOR_DIR)) { $link = $shell.CreateShortcut((Join-Path $folder 'ClipTranslator.lnk')); $link.TargetPath = $env:CLIPTRANSLATOR_APP; $link.WorkingDirectory = $env:CLIPTRANSLATOR_DIR; $link.Save() }"

echo.
echo Done. From now on, open ClipTranslator from the shortcut on your desktop.
start "" "%CLIPTRANSLATOR_APP%" %*
exit /b 0

:error
echo.
echo Something went wrong. Check the message above.
pause

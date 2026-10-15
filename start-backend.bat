@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run: python -m venv .venv
    pause
    exit /b 1
)

if not exist "app\.env" (
    echo [ERROR] app\.env not found.
    pause
    exit /b 1
)

for %%F in (
    "%LOCALAPPDATA%\Microsoft\WinGet\Links"
    "%ProgramData%\chocolatey\bin"
    "C:\ffmpeg\bin"
    "C:\Program Files\ffmpeg\bin"
) do (
    if exist "%%~F\ffmpeg.exe" (
        set "PATH=%%~F;%PATH%"
        echo [ffmpeg] found at %%~F
    )
)

echo.
echo Backend: http://localhost:8000
echo To stop: close this window. (Do NOT press Ctrl+C to copy text!)
echo.


cd app

:run
rem --- PO Token server (port 4416) ---------------------------------------
rem YouTube needs a PO Token or every video/subtitle URL returns 403.
rem The 'script' fallback needs ~18s on a cold start but the plugin times it
rem out at 15s, which kills the whole job - so keep this HTTP server running.
rem Install/build steps: see SETUP.md 'PO Token'.
set "POT_MAIN=%USERPROFILE%\bgutil-ytdlp-pot-provider\server\build\main.js"
if exist "%POT_MAIN%" (
    curl -s -m 2 http://127.0.0.1:4416/ping >nul 2>&1
    if errorlevel 1 (
        echo [pot] starting PO Token server on 127.0.0.1:4416
        start "bgutil POT server" /min cmd /c node "%POT_MAIN%"
    ) else (
        echo [pot] PO Token server already running
    )
) else (
    echo [WARN] PO Token server not installed - downloads may fail with 403.
    echo        See SETUP.md section 'PO Token'.
)

..\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
echo.
echo [WARN] Backend stopped unexpectedly. Auto-restart in 5 seconds...
echo        (Close this window to stop for real)
timeout /t 5 /nobreak >nul
goto run

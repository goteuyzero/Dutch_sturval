@echo off
cd /d %~dp0
set PIP_DISABLE_PIP_VERSION_CHECK=1
set PIP_NO_WARN_SCRIPT_LOCATION=1

echo ========================================
echo Dutch Sturval - server start
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating local Python environment .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create .venv.
        echo Make sure Python is installed and added to PATH.
        pause
        exit /b 1
    )
)

if exist ".venv\.deps_installed" (
    echo Dependencies already installed. Skipping install.
) else (
    ".venv\Scripts\python.exe" -c "import fastapi, starlette, uvicorn" >nul 2>nul
    if errorlevel 1 (
        echo Installing dependencies. This is needed only on the first launch in this folder.
        echo This can take a few minutes.
        ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
        if errorlevel 1 (
            echo.
            echo Could not install dependencies.
            pause
            exit /b 1
        )
    ) else (
        echo Dependencies found. Skipping install.
    )
    type nul > ".venv\.deps_installed"
)

echo.
echo Server is starting.
echo Open in browser: http://localhost:8000
echo To stop the server, press Ctrl+C in this window.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

pause

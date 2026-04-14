@echo off
setlocal enableextensions enabledelayedexpansion

echo ============================================
echo  Brand Scraper - First Time Setup
echo ============================================
echo.
echo This will install dependencies. It takes about
echo 5-10 minutes the first time. Please do not close
echo this window.
echo.
pause

REM --- Locate repo root (this script lives in windows\) ---
set "ROOT=%~dp0.."
pushd "%ROOT%" || (echo Failed to cd to repo root & exit /b 1)

REM --- Check winget is available ---
where winget >nul 2>nul
if errorlevel 1 (
    echo ERROR: winget is not available on this machine.
    echo Please update Windows or install "App Installer" from the Microsoft Store,
    echo then run this script again.
    pause
    exit /b 1
)

REM --- Install uv if missing ---
where uv >nul 2>nul
if errorlevel 1 (
    echo Installing uv...
    winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo ERROR: Failed to install uv.
        pause
        exit /b 1
    )
) else (
    echo uv already installed.
)

REM --- Install Node.js LTS if missing ---
where node >nul 2>nul
if errorlevel 1 (
    echo Installing Node.js LTS...
    winget install --id=OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo ERROR: Failed to install Node.js.
        pause
        exit /b 1
    )
) else (
    echo Node.js already installed.
)

REM --- Refresh PATH for this session (winget updates machine PATH but not current shell) ---
call :refresh_path

REM --- Sync backend ---
echo.
echo Syncing backend dependencies (uv sync)...
pushd backend
call uv sync
if errorlevel 1 (echo ERROR: uv sync failed & popd & popd & pause & exit /b 1)

echo Installing Chromium for patchright (this downloads ~150MB)...
call uv run patchright install chromium
if errorlevel 1 (echo ERROR: patchright install failed & popd & popd & pause & exit /b 1)
popd

REM --- Install and build frontend ---
echo.
echo Installing frontend dependencies (npm install)...
pushd frontend
call npm install
if errorlevel 1 (echo ERROR: npm install failed & popd & popd & pause & exit /b 1)

echo Building frontend (npm run build)...
call npm run build
if errorlevel 1 (echo ERROR: npm run build failed & popd & popd & pause & exit /b 1)
popd

REM --- Mark setup complete ---
echo done > "%~dp0.setup_complete"

popd
echo.
echo ============================================
echo  Setup complete! You can now double-click
echo  run.bat to start the app.
echo ============================================
echo.
pause
exit /b 0

:refresh_path
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| findstr /i "Path"') do set "MACHINE_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul ^| findstr /i "Path"') do set "USER_PATH=%%B"
set "PATH=%MACHINE_PATH%;%USER_PATH%"
goto :eof

@echo off
setlocal enableextensions

set "ROOT=%~dp0.."
pushd "%ROOT%" || (echo Failed to cd to repo root & exit /b 1)

REM --- Run setup if not yet done ---
if not exist "%~dp0.setup_complete" (
    echo First-time setup required. Running setup.bat...
    call "%~dp0setup.bat"
    if errorlevel 1 (echo Setup failed. Aborting. & popd & pause & exit /b 1)
)

REM --- Ensure ports 8000 and 3000 are free ---
call :check_port 8000 Backend
if errorlevel 1 (popd & pause & exit /b 1)
call :check_port 3000 Frontend
if errorlevel 1 (popd & pause & exit /b 1)

REM --- Launch backend in its own window ---
start "Brand Scraper Backend" cmd /k "cd /d %ROOT%\backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000"

REM --- Launch frontend in its own window ---
start "Brand Scraper Frontend" cmd /k "cd /d %ROOT%\frontend && npm run start"

REM --- Wait for frontend to be ready (up to 120s) ---
echo Waiting for app to start...
set /a tries=0
:wait_loop
set /a tries+=1
if %tries% gtr 120 (
    echo App did not start within 120 seconds. Check the two windows that opened for errors.
    popd
    pause
    exit /b 1
)
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri http://localhost:3000 -TimeoutSec 1) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

REM --- Open browser ---
start "" http://localhost:3000

popd
echo.
echo Brand Scraper is running. Close the two other windows
echo (Backend, Frontend) to stop it, or run stop.bat.
echo.
exit /b 0

:check_port
netstat -ano | findstr /r /c:":%~1 .*LISTENING" >nul
if errorlevel 1 goto :port_free
echo ERROR: Port %~1 is already in use. %~2 cannot start.
echo Close the app using that port, or run stop.bat, then try again.
echo.
echo If you don't know what is using it, try restarting your PC.
exit /b 1
:port_free
exit /b 0

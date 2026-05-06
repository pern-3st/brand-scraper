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

REM --- Detect a broken venv (e.g. user moved the folder after setup) and rebuild ---
REM    The trampolines in backend\.venv\Scripts\*.exe hardcode absolute paths
REM    on non-relocatable venvs, producing "uv trampoline failed to canonicalize
REM    script path" once the folder is moved. Older installs predate the
REM    --relocatable change in setup.bat, so we self-heal here.
if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" -c "" >nul 2>nul
    if errorlevel 1 (
        echo Detected broken Python environment ^(folder likely moved^). Rebuilding backend\.venv ...
        rmdir /s /q "backend\.venv"
        pushd backend
        call uv venv --relocatable
        if errorlevel 1 (echo ERROR: uv venv failed & popd & popd & pause & exit /b 1)
        call uv sync
        if errorlevel 1 (echo ERROR: uv sync failed & popd & popd & pause & exit /b 1)
        popd
    )
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

REM --- Wait for backend AND frontend to be ready (up to 120s each) ---
REM    Backend must be polled too — otherwise the browser opens on a frontend
REM    that immediately fetches /api/brands and gets ERR_CONNECTION_REFUSED.
echo Waiting for backend to start...
call :wait_for_url "http://127.0.0.1:8000/api/brands" Backend
if errorlevel 1 (popd & pause & exit /b 1)

echo Waiting for frontend to start...
call :wait_for_url "http://127.0.0.1:3000" Frontend
if errorlevel 1 (popd & pause & exit /b 1)

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

:wait_for_url
REM %~1 = url to poll, %~2 = label for the timeout message
set /a _tries=0
:wait_for_url_loop
set /a _tries+=1
if %_tries% gtr 120 (
    echo %~2 did not respond within 120 seconds. Check the two windows that opened for errors.
    exit /b 1
)
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri '%~1' -TimeoutSec 1) ^| Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_for_url_loop
)
exit /b 0

@echo off
setlocal

echo Stopping Brand Scraper...

REM Close the named windows spawned by run.bat
taskkill /FI "WINDOWTITLE eq Brand Scraper Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq Brand Scraper Frontend*" /T /F >nul 2>nul

REM Belt-and-suspenders: kill anything still bound to our ports
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do taskkill /PID %%P /F >nul 2>nul
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":3000 .*LISTENING"') do taskkill /PID %%P /F >nul 2>nul

echo Done.
timeout /t 2 /nobreak >nul
exit /b 0

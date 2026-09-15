@echo off
rem Nomad Studio launcher for the Windows portable build (docs/APP_UPDATES.md §7.4).
rem Lives at the root of the NomadStudio folder, next to app\. Starts the bundled
rem Python; the app itself opens the browser once it answers (NOMAD_OPEN_BROWSER).
setlocal
cd /d "%~dp0"
set "APPDIR=%~dp0app"

if not exist "%APPDIR%\python\python.exe" (
  echo Nomad Studio: app\python\python.exe not found.
  echo Unzip the whole package and run NomadStudio.bat from the NomadStudio folder.
  pause
  exit /b 1
)

if "%PORT%"=="" set "PORT=5123"

rem Already running? Just open it. 127.0.0.1, not localhost: localhost can
rem resolve to IPv6 first on Windows while the server listens on IPv4.
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:%PORT%/api/health' -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
  start "" "http://localhost:%PORT%"
  exit /b 0
)

rem Bundled libraries (app\lib) are registered by python\Lib\site-packages\nomad-lib.pth.
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
rem The update script sets it to 0: the tab that asked for the update reloads itself.
if not defined NOMAD_OPEN_BROWSER set "NOMAD_OPEN_BROWSER=1"

title Nomad Studio
echo Nomad Studio is starting on http://localhost:%PORT%
echo The browser opens by itself when it is ready.
echo Close this window to stop Nomad Studio.
echo.
"%APPDIR%\python\python.exe" "%APPDIR%\app.py"

rem Exit code 3: Nomad Studio closed itself to install an update
rem (app\launcher\apply_update.ps1 starts the new version in a new window).
if %errorlevel%==3 exit

echo.
echo Nomad Studio has stopped.
pause

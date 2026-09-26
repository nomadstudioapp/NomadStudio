@echo off
rem Nomad Studio launcher for the Windows portable build (docs/APP_UPDATES.md §7.4).
rem Lives at the root of the NomadStudio folder, next to app\. Starts the bundled
rem Python in a minimized window and shows the start screen (app\launcher\
rem start.html) in the browser, which hands over to the app once it answers.
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

rem Run on in a minimized window: it stays in the taskbar (close it to stop
rem Nomad Studio, open it to read an error), and the start screen is what the
rem user looks at. The copy started here skips this and goes on below.
if not defined NOMAD_LAUNCHER_MIN (
  set "NOMAD_LAUNCHER_MIN=1"
  start "Nomad Studio" /min cmd /c "%~f0"
  exit /b 0
)

rem Bundled libraries (app\lib) are registered by python\Lib\site-packages\nomad-lib.pth.
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

rem The start screen, unless the update script started us (it sets
rem NOMAD_OPEN_BROWSER=0: the tab that asked for the update reloads itself).
rem start-config.js tells the page which port to wait for. Without the page
rem (an older app\ folder), the app opens the browser itself as before.
if not defined NOMAD_OPEN_BROWSER (
  if exist "%APPDIR%\launcher\start.html" (
    > "%APPDIR%\launcher\start-config.js" echo window.NOMAD_PORT = %PORT%;
    start "" "%APPDIR%\launcher\start.html"
    set "NOMAD_OPEN_BROWSER=0"
  ) else (
    set "NOMAD_OPEN_BROWSER=1"
  )
)

title Nomad Studio
echo Nomad Studio is starting on http://localhost:%PORT%
echo The browser shows the start screen and opens the app when it is ready.
echo Close this window to stop Nomad Studio.
echo.
"%APPDIR%\python\python.exe" "%APPDIR%\app.py"

rem Exit code 3: Nomad Studio closed itself to install an update
rem (app\launcher\apply_update.ps1 starts the new version in a new window).
if %errorlevel%==3 exit

echo.
echo Nomad Studio has stopped.
pause

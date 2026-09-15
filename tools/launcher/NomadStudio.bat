@echo off
rem Nomad Studio launcher for the Windows portable build (docs/APP_UPDATES.md §7.4).
rem Lives at the root of the NomadStudio folder, next to app\. Starts the bundled
rem Python with the bundled libraries and opens the browser once the app answers.
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
set "URL=http://localhost:%PORT%"

rem Already running? Just open it.
powershell -NoProfile -Command "try { Invoke-RestMethod '%URL%/api/health' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
  start "" "%URL%"
  exit /b 0
)

set "PYTHONPATH=%APPDIR%\lib"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE="

rem Open the browser in the background as soon as /api/health answers (max 60 s).
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for ($i=0; $i -lt 120; $i++) { try { Invoke-RestMethod '%URL%/api/health' -TimeoutSec 2 | Out-Null; Start-Process '%URL%'; break } catch { Start-Sleep -Milliseconds 500 } }"

title Nomad Studio
echo Nomad Studio is starting on %URL%
echo Close this window to stop Nomad Studio.
echo.
"%APPDIR%\python\python.exe" "%APPDIR%\app.py"

echo.
echo Nomad Studio has stopped.
pause

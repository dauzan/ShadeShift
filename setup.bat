@echo off
rem ShadeShift one-time setup on a fresh Windows laptop (needs internet once; everything after this runs offline).
rem Creates a virtual environment in this folder, installs the pinned packages, then checks the laptop.
rem Usage: double-click setup.bat   (optional: setup.bat <venv folder>, default .venv)
setlocal
cd /d "%~dp0"
set "VENV=%~1"
if "%VENV%"=="" set "VENV=.venv"
rem Keep pip's download cache in this project folder (team rule: downloads and installs stay on drive D).
set "PIP_CACHE_DIR=%CD%\.cache\pip"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo preferably to a folder on drive D, then run setup.bat again.
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 ( echo ShadeShift needs Python 3.11 or newer ^(3.12 tested^). & pause & exit /b 1 )

if not exist "%VENV%\Scripts\python.exe" (
  echo Creating the virtual environment in %VENV% ...
  %PY% -m venv "%VENV%" || ( pause & exit /b 1 )
)
echo Installing packages ^(about 600 MB, a few minutes the first time^) ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-dev.txt
if errorlevel 1 ( echo Package installation failed: check the internet connection and run setup.bat again. & pause & exit /b 1 )

"%VENV%\Scripts\python.exe" run.py check
if errorlevel 1 ( echo Setup finished with problems ^(see above^). & pause & exit /b 1 )
echo.
echo Setup complete. Start the demo with start_demo.bat ^(no hardware^) or start_live.bat ^(ESP32 on USB^).
if "%~1"=="" pause
endlocal

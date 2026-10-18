@echo off
rem ShadeShift without hardware: local server + emulated ESP32 (replays real lab curves, labeled DEMO) + dashboard.
rem Extra options are passed on, e.g.  start_demo.bat --scenario   (plays the default shading scenario)
rem Stop with Ctrl+C in this window: the gateway opens all relays first, then everything shuts down.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Run setup.bat first. & pause & exit /b 1 )
".venv\Scripts\python.exe" run.py demo %*
pause

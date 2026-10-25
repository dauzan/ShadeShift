@echo off
rem ShadeShift with the ESP32 on USB: local server + edge gateway (port auto-detected) + standby demo device + dashboard.
rem If the ESP32 is not found automatically, pass its port:  start_live.bat --port COM5   (list ports: .venv\Scripts\python run.py ports)
rem Stop with Ctrl+C in this window: the gateway opens all relays first, then everything shuts down.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" ( echo Run setup.bat first. & pause & exit /b 1 )
".venv\Scripts\python.exe" run.py live %*
pause
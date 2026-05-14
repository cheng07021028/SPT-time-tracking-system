@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo SPT Time Tracking V1.10 Persistence Setup
echo ============================================
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python tools\apply_v1_10_persistence_setup.py
echo.
pause

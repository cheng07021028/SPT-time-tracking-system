@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo SPT Time Tracking - Backup to GitHub
echo ============================================
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python tools\backup_to_github.py
echo.
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
python tools\apply_v1_23_data_guard.py
pause

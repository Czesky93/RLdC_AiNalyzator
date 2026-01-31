@echo off
REM Automated setup script for RLdC AI Analyzer Telegram Bot
REM This script automates the complete setup process

echo ╔══════════════════════════════════════════════════════════════════╗
echo ║  RLdC AI Analyzer - Automated Setup                             ║
echo ╚══════════════════════════════════════════════════════════════════╝
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed!
    echo Please install Python 3.8 or higher and try again.
    pause
    exit /b 1
)

REM Run the Python setup script
python setup.py

pause

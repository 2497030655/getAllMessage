@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 兼容 Python 3.9 / 3.12：优先用现有 venv，坏了再按本机可用版本重建
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        venv\Scripts\python.exe bootstrap.py
        if errorlevel 1 pause
        exit /b %ERRORLEVEL%
    )
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 bootstrap.py
    if errorlevel 1 pause
    exit /b %ERRORLEVEL%
)

python bootstrap.py
if errorlevel 1 pause
exit /b %ERRORLEVEL%

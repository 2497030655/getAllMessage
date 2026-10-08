@echo off
cd /d "%~dp0.."
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" -m xhs_im_service
) else (
  python -m xhs_im_service
)
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"

set CLOUD_HOST=0.0.0.0
set CLOUD_PORT=8787
set CLOUD_PARSE_WORKERS=4
set CLOUD_API_TOKEN=

if exist "cloud.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("cloud.env") do (
    if /I "%%A"=="CLOUD_HOST" set CLOUD_HOST=%%B
    if /I "%%A"=="CLOUD_PORT" set CLOUD_PORT=%%B
    if /I "%%A"=="CLOUD_PARSE_WORKERS" set CLOUD_PARSE_WORKERS=%%B
    if /I "%%A"=="CLOUD_API_TOKEN" set CLOUD_API_TOKEN=%%B
  )
)

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -m pip install -q -r cloud\requirements.txt
    venv\Scripts\python.exe -m cloud.main
    if errorlevel 1 pause
    exit /b %ERRORLEVEL%
)

echo 请先运行 start.bat 创建虚拟环境
pause
exit /b 1

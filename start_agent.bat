@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 默认关闭上云；仅当 cloud.env 配置了地址才连接
set CLOUD_WS_URL=
set CLOUD_API_TOKEN=
set AGENT_MODE=1

if exist "cloud.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("cloud.env") do (
    if /I "%%A"=="CLOUD_WS_URL" set CLOUD_WS_URL=%%B
    if /I "%%A"=="CLOUD_API_TOKEN" set CLOUD_API_TOKEN=%%B
  )
)

call start.bat

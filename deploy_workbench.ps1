# Deploy getAllMessage cloud via Alibaba Workbench CLI
# Prerequisites: run `workbench config` once with AccessKey

param(
    [string]$InstanceId = $env:ALIYUN_INSTANCE_ID,
    [string]$Region = $(if ($env:ALIYUN_REGION) { $env:ALIYUN_REGION } else { "cn-beijing" }),
    [string]$RemoteDir = "/opt/getAllMessage"
)

$ErrorActionPreference = "Stop"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$wbCfg = @(
    "$env:USERPROFILE\.workbench\config.json",
    "$env:USERPROFILE\.config\workbench\config.json"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $wbCfg) {
    Write-Host "Workbench 未配置凭证。请先在本机终端执行:"
    Write-Host "  workbench config"
    Write-Host "填入 AccessKey，再重新运行: .\deploy_workbench.ps1"
    exit 1
}

if (-not $InstanceId) {
    throw "请设置参数 -InstanceId 或环境变量 ALIYUN_INSTANCE_ID"
}

Write-Host "==> 实例: $InstanceId  区域: $Region"

# Probe region if beijing fails later
function Invoke-WB {
    param([string[]]$Args)
    & workbench @Args
    if ($LASTEXITCODE -ne 0) { throw "workbench failed: $($Args -join ' ')" }
}

$tar = Join-Path $env:TEMP "getAllMessage-cloud.tgz"
if (Test-Path $tar) { Remove-Item $tar -Force }

Write-Host "==> 打包..."
# Windows tar
tar --exclude=venv --exclude=__pycache__ --exclude=*.log --exclude=edge_profile --exclude=accounts -czf $tar .

Write-Host "==> 上传..."
Invoke-WB @("upload", $tar, "/tmp/getAllMessage-cloud.tgz", "-i", $InstanceId, "-r", $Region, "-f")

Write-Host "==> 远程安装..."
$cmd = @"
set -e
mkdir -p $RemoteDir
tar -xzf /tmp/getAllMessage-cloud.tgz -C $RemoteDir
cd $RemoteDir
chmod +x cloud/deploy/install.sh
bash cloud/deploy/install.sh
# 尝试挂上 nginx /im/ 片段（若不存在）
if [ -f /etc/nginx/nginx.conf ] && ! grep -q 'location /im/' /etc/nginx/nginx.conf /etc/nginx/conf.d/*.conf 2>/dev/null; then
  echo '=== 请手动把 cloud/deploy/nginx-im.conf 并入你的域名 server 块 ==='
fi
curl -sS http://127.0.0.1:8787/health || true
echo
"@
Invoke-WB @("exec", "-i", $InstanceId, "-r", $Region, "-c", $cmd, "--timeout", "180")

Write-Host "==> 完成。请用你自己的域名/IP 做健康检查（见 cloud.env）"

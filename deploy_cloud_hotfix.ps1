# 仅热更新云端 main.py
# 需要环境变量：ALIYUN_HOST / ALIYUN_INSTANCE_ID / ALIYUN_REGION（或参数传入）
# 勿在脚本中写死服务器 IP / 实例 ID

param(
    [string]$InstanceId = $env:ALIYUN_INSTANCE_ID,
    [string]$Region = $(if ($env:ALIYUN_REGION) { $env:ALIYUN_REGION } else { "cn-beijing" })
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

$main = Join-Path $Root "cloud\main.py"
if (-not (Test-Path $main)) { throw "missing $main" }

if (-not $InstanceId -and -not $env:ALIYUN_HOST) {
    throw "请设置 ALIYUN_INSTANCE_ID（Workbench）或 ALIYUN_HOST（SSH），勿使用仓库内硬编码地址"
}

if ($InstanceId -and (Test-Path "$env:USERPROFILE\.workbench\config.json")) {
    Write-Host "via workbench..."
    workbench upload $main /opt/getAllMessage/cloud/main.py -i $InstanceId -r $Region -f
    workbench exec -i $InstanceId -r $Region "systemctl restart getallmessage; sleep 1; curl -sS http://127.0.0.1:8787/health"
    exit 0
}

$host_ = $env:ALIYUN_HOST
if (-not $host_) { throw "缺少 ALIYUN_HOST" }
$Key = if ($env:ALIYUN_SSH_KEY) { $env:ALIYUN_SSH_KEY } else { "$env:USERPROFILE\.ssh\id_rsa" }
Write-Host "via scp..."
scp -i $Key -o StrictHostKeyChecking=accept-new $main "root@${host_}:/opt/getAllMessage/cloud/main.py"
ssh -i $Key "root@${host_}" "systemctl restart getallmessage; sleep 1; curl -sS http://127.0.0.1:8787/health"

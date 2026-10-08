# 上传项目到阿里云 ECS 并执行 install.sh
# 用法: .\deploy_to_aliyun.ps1
# 前提: 已在阿里云控制台把本机公钥加入 ECS（见 cloud/deploy/README.md）

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Host_ = $env:ALIYUN_HOST
if (-not $Host_) { throw "请先设置环境变量 ALIYUN_HOST（服务器 IP），勿在脚本中写死地址" }
$User = if ($env:ALIYUN_SSH_USER) { $env:ALIYUN_SSH_USER } else { "root" }
$Remote = "/opt/getAllMessage"
$Key = if ($env:ALIYUN_SSH_KEY) { $env:ALIYUN_SSH_KEY } else { "$env:USERPROFILE\.ssh\id_rsa" }

Write-Host "目标: ${User}@${Host_}:${Remote}"

# 排除 venv、日志等大目录
$tar = Join-Path $env:TEMP "getAllMessage-deploy.tgz"
if (Test-Path $tar) { Remove-Item $tar -Force }

Push-Location $Root
tar --exclude=venv --exclude=edge_profile --exclude=accounts --exclude=*.log --exclude=__pycache__ -czf $tar .
Pop-Location

scp -i $Key -o StrictHostKeyChecking=accept-new $tar "${User}@${Host_}:/tmp/getAllMessage-deploy.tgz"
ssh -i $Key -o StrictHostKeyChecking=accept-new "${User}@${Host_}" @"
set -e
mkdir -p $Remote
tar -xzf /tmp/getAllMessage-deploy.tgz -C $Remote
chmod +x $Remote/cloud/deploy/install.sh
bash $Remote/cloud/deploy/install.sh
"@

Write-Host "部署完成。健康检查: curl http://${Host_}:8787/health"

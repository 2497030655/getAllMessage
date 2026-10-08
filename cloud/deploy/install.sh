#!/usr/bin/env bash
# 在阿里云 ECS 上安装 getAllMessage 云端服务
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/getAllMessage}"
PY="${PY:-python3}"

echo "==> 安装目录: $APP_DIR"
mkdir -p "$APP_DIR"

if ! command -v "$PY" >/dev/null 2>&1; then
  if command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y python3 python3-venv python3-pip
  else
    echo "请先安装 python3"; exit 1
  fi
fi

cd "$APP_DIR"

if [ ! -d venv ]; then
  "$PY" -m venv venv
fi

./venv/bin/pip install -U pip
./venv/bin/pip install -r cloud/requirements.txt

if [ ! -f cloud.env ]; then
  cp cloud.env.example cloud.env
  echo "已生成 cloud.env，请编辑 CLOUD_API_TOKEN 后: systemctl restart getallmessage"
fi

install -m 644 cloud/deploy/getallmessage.service /etc/systemd/system/getallmessage.service
systemctl daemon-reload
systemctl enable getallmessage
systemctl restart getallmessage

echo "==> 服务状态:"
systemctl status getallmessage --no-pager || true
echo "==> 健康检查:"
sleep 1
curl -sS "http://127.0.0.1:${CLOUD_PORT:-8787}/health" || true
echo
echo "完成。请在阿里云安全组放行 TCP ${CLOUD_PORT:-8787}"

# Workbench 远程部署说明

## 1. 配置 AccessKey（本机交互，只需一次）

```powershell
workbench config
```

按提示填入阿里云 AccessKey ID / Secret，区域选 ECS 所在区（常见 `cn-hangzhou` / `cn-beijing`）。

## 2. 查实例

```powershell
workbench list ecs -r cn-hangzhou
# 或
workbench list ecs -r cn-beijing
```

记下 `InstanceId`（形如 `i-bp1xxxxx`）。

## 3. 上传并安装云端

在项目根目录：

```powershell
$IID = "i-你的实例ID"
$REG = "cn-hangzhou"   # 改成实际区域

# 打包（排除 venv）
tar --exclude=venv --exclude=__pycache__ --exclude=*.log -czf $env:TEMP\gam-cloud.tgz .

workbench upload $env:TEMP\gam-cloud.tgz /tmp/gam-cloud.tgz -i $IID -r $REG -f
workbench exec -i $IID -r $REG -c "mkdir -p /opt/getAllMessage && tar -xzf /tmp/gam-cloud.tgz -C /opt/getAllMessage && chmod +x /opt/getAllMessage/cloud/deploy/install.sh && bash /opt/getAllMessage/cloud/deploy/install.sh"
```

## 4. 挂 Nginx 域名反代

```powershell
workbench exec -i $IID -r $REG -c "grep -q 'location /im/' /etc/nginx/nginx.conf || echo '请把 cloud/deploy/nginx-im.conf 片段并入你的域名 server 块后 nginx -t && nginx -s reload'"
```

或手动：把 `cloud/deploy/nginx-im.conf` 内容并入你的域名 server，然后：

```bash
nginx -t && nginx -s reload
```

## 5. 验证

本机（把域名换成你自己的）：

```powershell
curl.exe http://你的域名/im/health
```

PC Agent：先在 `cloud.env` 填写 `CLOUD_WS_URL` / `CLOUD_API_TOKEN`，再：

```bat
start_agent.bat
```

默认仓库配置为**关闭上云**（`CLOUD_WS_URL` 为空）。启用示例：`ws://你的域名/im/ws/agent`；有 HTTPS 后用 `wss://`。

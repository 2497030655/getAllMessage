from pathlib import Path

p = Path("/etc/nginx/nginx.conf")
text = p.read_text(encoding="utf-8")
block = """
        # getAllMessage IM cloud (WebSocket + API)
        location /im/ {
            proxy_pass http://127.0.0.1:8787/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            proxy_buffering off;
        }

"""
if "location /im/" in text:
    print("already configured")
else:
    needle = "        # 处理Vue Router的history模式\n        location / {"
    if needle not in text:
        raise SystemExit("needle not found")
    text = text.replace(needle, block + needle, 1)
    p.write_text(text, encoding="utf-8")
    print("patched")

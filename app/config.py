# -*- coding: utf-8 -*-
"""应用配置与常量。"""

from __future__ import annotations

import os
import re
import socket

def _load_dotenv(path: str) -> None:
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip()
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass

_load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cloud.env"))

MAX_BODY = 48 * 1024
MAX_WS_BODY = 8 * 1024
MAX_RECORDS = 400
DISPLAY_LIMIT = 120
RENDER_INTERVAL_MS = 350
FILTER_INTERVAL_MS = 250
FILTER_TYPES = {"xhr", "fetch"}

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_DATA = os.path.join(ROOT_DIR, "edge_profile")
ACCOUNTS_FILE = os.path.join(ROOT_DIR, "accounts.json")
ACCOUNTS_DIR = os.path.join(ROOT_DIR, "accounts")
MAX_ACCOUNTS = 6
CHAT_PANEL_WIDTH = 520
API_PANEL_WIDTH = 480
EDGE_HOME = "edge://newtab"
XHS_CHAT_HOME = "https://www.xiaohongshu.com/chat"
DOUYIN_IM_HOME = "https://www.douyin.com/notice/"
IM_KEEPALIVE_SEC = 15
IM_NAV_COOLDOWN_SEC = 25

IM_HEX_ID = re.compile(r"^[0-9a-f]{24}$")

DEFAULT_CONV_ID = "5dd0cf300000000001007890"
DEFAULT_UID = "674fb26a000000001d02f89f"

PLATFORM_XHS = "xhs"
PLATFORM_DOUYIN = "douyin"
PLATFORM_LABELS = {PLATFORM_XHS: "小红书", PLATFORM_DOUYIN: "抖音"}

IM_PROTO_TEMPLATE_B64 = (
    "CAFKjwEKJDA0NjliN2EyLWNhN2MtNDI5Yi05N2Y1LWZhYmQzMTY0Nzc3MBCOgPi0gzQaACIYNjc0"
    "ZmIyNmEwMDAwMDAwMDFkMDJmODlmKhg1ZGQwY2YzMDAwMDAwMDAwMDEwMDc4OTAyDmhlbGxv6L+Y"
    "5Zyo5ZCXOAFCEuS8muaOkumYn+eahOaguOahg0gAWgBgAQ=="
)
IM_TEMPLATE_TEXT = "hello还在吗"

# --- 方案 A：PC 监听 Agent（无本地聊天 UI）---
AGENT_MODE = os.environ.get("AGENT_MODE", "1") not in ("0", "false", "False")
# 默认关闭上云；在 cloud.env 或环境变量里配置 CLOUD_WS_URL 后才会上报
CLOUD_WS_URL = os.environ.get("CLOUD_WS_URL", "").strip()
CLOUD_API_TOKEN = os.environ.get("CLOUD_API_TOKEN", "").strip()
AGENT_ID = os.environ.get("AGENT_ID") or socket.gethostname()[:32]
SHOW_API_PANEL = os.environ.get("SHOW_API_PANEL", "0") in ("1", "true", "True")

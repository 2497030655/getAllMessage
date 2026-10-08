# -*- coding: utf-8 -*-
"""云端服务配置。"""
from __future__ import annotations

import os

HOST = os.environ.get("CLOUD_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLOUD_PORT", "8787"))
PARSE_WORKERS = int(os.environ.get("CLOUD_PARSE_WORKERS", "4"))
PARSE_QUEUE_SIZE = int(os.environ.get("CLOUD_PARSE_QUEUE_SIZE", "2000"))
API_TOKEN = os.environ.get("CLOUD_API_TOKEN", "").strip()

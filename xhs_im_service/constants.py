# -*- coding: utf-8 -*-
"""本服务自用常量（不依赖主程序）。"""
from __future__ import annotations

import re

MAX_BODY = 48 * 1024
MAX_WS_BODY = 8 * 1024
IM_HEX_ID = re.compile(r"^[0-9a-f]{24}$")
DEFAULT_CONV_ID = "5dd0cf300000000001007890"
PLATFORM_XHS = "xhs"

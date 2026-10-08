# -*- coding: utf-8 -*-
"""时间与 WebSocket body 截断。"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Optional

from xhs_im_service.constants import MAX_WS_BODY


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def safe_body(text: Optional[str], limit: int = MAX_WS_BODY) -> str:
    if not text:
        return ""
    if len(text) > limit:
        return text[:limit] + "\n… [truncated]"
    return text


def format_payload(payload: Any) -> str:
    if isinstance(payload, bytes):
        try:
            return safe_body(payload.decode("utf-8"), MAX_WS_BODY)
        except UnicodeDecodeError:
            raw = base64.b64encode(payload).decode("ascii")
            return safe_body(raw, MAX_WS_BODY)
    return safe_body(str(payload), MAX_WS_BODY)

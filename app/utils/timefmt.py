# -*- coding: utf-8 -*-
"""时间与 body 截断。"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Optional

from app.config import MAX_BODY, MAX_WS_BODY

def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")

def safe_body(text: Optional[str], limit: int = MAX_BODY) -> str:
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

def try_format_json(text: Optional[str]) -> str:
    if not text:
        return ""
    stripped = text.strip()
    if not stripped:
        return text
    try:
        return json.dumps(json.loads(stripped), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return text

# -*- coding: utf-8 -*-
"""聊天文本过滤与展示名工具。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from xhs_im_service.constants import IM_HEX_ID


def is_im_junk_text(s: str) -> bool:
    if not s:
        return True
    if IM_HEX_ID.match(s):
        return True
    if re.fullmatch(r"[0-9a-f]{24}(\.[0-9a-f]{24})+(\.[0-9a-f]+)?", s):
        return True
    parts = s.split(".")
    if len(parts) >= 2 and all(re.fullmatch(r"[0-9a-f]+", p) for p in parts):
        return True
    if re.fullmatch(r"[\$0-9a-f\-]+", s) and len(s) > 20:
        return True
    if re.match(r"^seq-\d+~", s) or "last_live_recheck_time" in s:
        return True
    if "src-wss" in s and "~" in s:
        return True
    if re.match(r"^on[A-Z]{2}", s):
        return True
    if "msg_type" in s and (
        "toast_content" in s or "status_code" in s or "update_time" in s
    ):
        return True
    if re.search(r"J\d{12,}", s):
        return True
    lower = s.lower()
    if "aweme://" in lower or "hunter_popup" in lower or "dynamic_router" in lower:
        return True
    if "conversation_id" in lower or "conversation_short_id" in lower:
        return True
    if "://" in s and ("aweme" in lower or "conversation" in lower):
        return True
    if '","link"' in s or '"link":"' in s or '","link":' in s:
        return True
    if "%3a" in lower or "%2f" in lower or "\\u0026" in s:
        return True
    if s.count('"') >= 2 and "{" not in s and "://" in s:
        return True
    return False


def looks_like_json_object(s: str) -> bool:
    t = (s or "").strip()
    return bool(t.startswith("{") and t.endswith("}") and '"' in t)


def is_garbled_text(s: str) -> bool:
    if not s:
        return True
    if "\ufffd" in s:
        return True
    if re.search(r"[\u4e00-\u9fff]", s):
        return bool(re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", s))
    return False


def is_likely_human_chat(s: str) -> bool:
    if is_im_junk_text(s) or is_garbled_text(s):
        return False
    cleaned = (s or "").strip()
    if looks_like_json_object(cleaned) and (
        '"content"' in cleaned
        or '"front_chain"' in cleaned
        or '"nickname"' in cleaned
        or '"content_type"' in cleaned
    ):
        return False
    if cleaned.startswith("{") or cleaned.startswith("["):
        return False
    if re.search(r"[\u4e00-\u9fff]", cleaned):
        return len(cleaned) <= 500
    if not cleaned or len(cleaned) > 500:
        return False
    if re.search(r"seq-|msg_type|status_code|toast_content|last_live", cleaned):
        return False
    if re.match(r"^on[A-Z]{2}", cleaned):
        return False
    if re.fullmatch(r"[\w\s.,!?…~'\"()-]+", cleaned, re.UNICODE):
        return bool(re.search(r"[a-zA-Z\u4e00-\u9fff]", cleaned))
    return False


def is_valid_chat_content(s: str) -> bool:
    return is_likely_human_chat(s)


def is_valid_display_name(name: str) -> bool:
    s = (name or "").strip()
    if not s or len(s) > 40:
        return False
    if IM_HEX_ID.match(s):
        return False
    if is_im_junk_text(s) or is_garbled_text(s):
        return False
    if re.fullmatch(r"[0-9a-f]{6,}", s):
        return False
    if s in (
        "未知用户",
        "选择联系人",
        "消息",
        "私信",
        "发消息",
        "发消息…",
        "小红书",
        "通知",
        "全部",
        "未读",
        "搜索",
        "聊天",
        "联系人",
        "设置",
        "更多",
        "首页",
        "我",
        "发现",
        "市集",
        "发布",
        "关注",
        "粉丝",
        "赞和收藏",
        "@我的",
        "系统消息",
        "陌生人消息",
    ):
        return False
    if len(s) > 24 and re.search(r"[。！？，,.!?]", s):
        return False
    return bool(
        re.search(r"[\u4e00-\u9fff]", s) or re.search(r"[a-zA-Z]{2}", s)
    )


def extract_display_name_from_obj(obj: Dict[str, Any]) -> str:
    for key in (
        "nickname",
        "user_name",
        "username",
        "nick_name",
        "sender_nickname",
        "sender_name",
        "display_name",
        "name",
    ):
        v = str(obj.get(key, "")).strip()
        if is_valid_display_name(v):
            return v
    return ""


def is_chat_text(s: str) -> bool:
    if not s or len(s) > 500:
        return False
    if s[0] in "{[\\":
        return False
    if IM_HEX_ID.match(s):
        return False
    if s.startswith("$") and len(s) > 20:
        return False
    if re.fullmatch(r"[\$0-9a-f\-]+", s) and len(s) > 15:
        return False
    if re.fullmatch(r"[a-zA-Z]", s):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", s)) or (
        len(s) >= 2 and s.isprintable()
    )


def is_media_placeholder(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    if re.fullmatch(r"\[[^\[\]]{1,20}\]", t):
        return True
    return t in (
        "[图片]",
        "[表情]",
        "[动画表情]",
        "[语音]",
        "[视频]",
        "[卡片]",
        "[文件]",
        "[位置]",
        "[笔记]",
    )


def is_displayable_message(text: str, image_url: str = "") -> bool:
    if image_url:
        return True
    if is_media_placeholder(text):
        return True
    return is_valid_chat_content(text)


def pick_chat_text(strings: List[str]) -> Optional[str]:
    candidates = [s for s in strings if is_chat_text(s)]
    if not candidates:
        return None
    scored: List[Tuple[int, str]] = []
    for s in candidates:
        score = len(s)
        if re.search(r"[\u4e00-\u9fff]", s):
            score += 80
        if re.search(r"[a-zA-Z]{2,}", s):
            score += 20
        scored.append((score, s))
    scored.sort(key=lambda x: x[0])
    return scored[-1][1]

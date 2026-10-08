# -*- coding: utf-8 -*-
"""消息列表可见性过滤。"""
from __future__ import annotations

from typing import Any, Dict, List

from app.utils.text import (
    is_displayable_message,
    is_valid_display_name,
)
from app.platforms.xhs.payload import normalize_chat_payload


def filter_visible_messages(
    messages: List[Dict[str, Any]], nickname: str = ""
) -> List[Dict[str, Any]]:
    """去掉 id 拼接串、昵称误识别等非聊天正文；拆开误存的 IM JSON。"""
    visible: List[Dict[str, Any]] = []
    nick = (nickname or "").strip()
    for m in messages:
        text = str(m.get("text", "")).strip()
        text, extracted_nick, unpacked_url, unpacked_kind = normalize_chat_payload(
            text, nick
        )
        if unpacked_url and (not text or text.startswith("{")):
            text = (
                "[图片]"
                if (unpacked_kind or "image") == "image"
                else ("[表情]" if unpacked_kind == "emoji" else "[图片]")
            )
        if extracted_nick and is_valid_display_name(extracted_nick):
            nick = extracted_nick
            m["_extracted_nickname"] = extracted_nick
        m["text"] = text
        m.pop("image_url", None)
        m.pop("data_uri", None)
        if not is_displayable_message(text):
            continue
        if nick and text == nick and m.get("direction") == "down":
            continue
        visible.append(m)
    return visible

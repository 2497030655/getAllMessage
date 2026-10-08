# -*- coding: utf-8 -*-
"""小红书媒体 URL / 类型识别。"""
from __future__ import annotations

import json
import re
from typing import Any

from xhs_im_service.util.text import is_media_placeholder, looks_like_json_object


def extract_image_url_from_value(value: Any, depth: int = 0) -> str:
    if depth > 6 or value is None:
        return ""
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return ""
        if looks_like_json_object(s):
            try:
                return extract_image_url_from_value(json.loads(s), depth + 1)
            except json.JSONDecodeError:
                pass
        if re.match(r"https?://", s, re.I):
            lower = s.lower()
            if any(
                k in lower
                for k in (
                    "xhscdn",
                    "xiaohongshu",
                    "sns-img",
                    "sns-avatar",
                    "ci.xiaohongshu",
                    "picasso",
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".webp",
                    "/img/",
                    "image",
                )
            ):
                return s.split("?")[0] + (("?" + s.split("?", 1)[1]) if "?" in s else "")
            if re.search(r"\.(jpg|jpeg|png|gif|webp)(\?|$)", lower):
                return s
        return ""
    if isinstance(value, dict):
        for key in (
            "link",
            "url",
            "origin_url",
            "originUrl",
            "image_url",
            "imageUrl",
            "gif_url",
            "gifUrl",
            "thumb",
            "thumbnail",
            "thumb_url",
            "cover",
            "src",
            "image",
            "pic",
            "pic_url",
            "big_url",
            "original",
        ):
            found = extract_image_url_from_value(value.get(key), depth + 1)
            if found:
                return found
        for v in value.values():
            found = extract_image_url_from_value(v, depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for v in value:
            found = extract_image_url_from_value(v, depth + 1)
            if found:
                return found
    return ""


def classify_xhs_media(
    content_type: Any, front: str, image_url: str, content_obj: Any
) -> str:
    ct = str(content_type) if content_type is not None else ""
    front = (front or "").strip()
    blob = json.dumps(content_obj, ensure_ascii=False) if content_obj else ""
    blob_l = blob.lower()
    if (
        "表情" in front
        or "动画表情" in front
        or "emotion" in blob_l
        or "sticker" in blob_l
        or "emoji" in blob_l
        or re.fullmatch(r"\[[^\[\]]+R\]", front)
        or ct in ("4", "5", "6")
    ):
        if image_url or is_media_placeholder(front) or re.fullmatch(
            r"\[[^\[\]]+R\]", front
        ):
            return "emoji"
    if ct in ("2", "3") or "图片" in front or image_url:
        return "image"
    if is_media_placeholder(front):
        return "other"
    return "text"

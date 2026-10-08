# -*- coding: utf-8 -*-
"""小红书 IM JSON 载荷解析（独立实现，不依赖主程序）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from xhs_im_service.constants import DEFAULT_CONV_ID, IM_HEX_ID, PLATFORM_XHS
from xhs_im_service.parsing.media import (
    classify_xhs_media,
    extract_image_url_from_value,
)
from xhs_im_service.util.protobuf import grab_json_field, pick_conv_id
from xhs_im_service.util.text import (
    extract_display_name_from_obj,
    is_media_placeholder,
    is_valid_chat_content,
    looks_like_json_object,
)


def try_parse_xhs_payload_text(text: str) -> Optional[Dict[str, Any]]:
    t = (text or "").strip()
    if not looks_like_json_object(t):
        return None
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        objs = find_xhs_im_json_objects(t)
        return objs[0] if objs else None
    if not isinstance(obj, dict):
        return None
    inner = obj.get("content")
    if isinstance(inner, str) and looks_like_json_object(inner):
        try:
            nested = json.loads(inner.replace('\\"', '"'))
            if isinstance(nested, dict) and (
                "content" in nested or "front_chain" in nested
            ):
                obj = nested
        except json.JSONDecodeError:
            pass
    return parse_xhs_im_message_obj(obj)


def normalize_chat_payload(
    text: str, nickname: str = ""
) -> Tuple[str, str, str, str]:
    parsed = try_parse_xhs_payload_text(text)
    if parsed:
        return (
            str(parsed.get("content", "")).strip(),
            str(parsed.get("nickname", "") or nickname).strip(),
            str(parsed.get("image_url", "")).strip(),
            str(parsed.get("msg_kind", "text") or "text"),
        )
    url = extract_image_url_from_value(text)
    if url and text.strip() == url:
        return "[图片]", (nickname or "").strip(), url, "image"
    return (text or "").strip(), (nickname or "").strip(), "", "text"


def parse_xhs_im_message_obj(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    content_type = obj.get("content_type")
    raw_content = str(obj.get("content") or "").strip()
    front = str(obj.get("front_chain") or "").strip()
    nickname = extract_display_name_from_obj(obj)

    if looks_like_json_object(raw_content) and (
        '"content"' in raw_content
        and '"nickname"' in raw_content
        and '"content_type"' in raw_content
    ):
        try:
            nested = json.loads(raw_content.replace('\\"', '"'))
            if isinstance(nested, dict):
                return parse_xhs_im_message_obj(nested)
        except json.JSONDecodeError:
            objs = find_xhs_im_json_objects(raw_content)
            if objs:
                return objs[0]

    content_obj: Any = None
    if looks_like_json_object(raw_content):
        try:
            content_obj = json.loads(raw_content.replace('\\"', '"'))
        except json.JSONDecodeError:
            content_obj = None

    image_url = extract_image_url_from_value(content_obj)
    if not image_url:
        image_url = extract_image_url_from_value(obj)
    if not image_url and raw_content:
        image_url = extract_image_url_from_value(raw_content)

    msg_kind = classify_xhs_media(content_type, front, image_url, content_obj)

    if msg_kind == "text" and (
        content_type is None or str(content_type) in ("1", "")
    ):
        text = raw_content if not looks_like_json_object(raw_content) else ""
        if not text:
            if front and not is_media_placeholder(front) and front != nickname:
                text = front
        if not text or not is_valid_chat_content(text):
            if image_url:
                msg_kind = "image"
            else:
                return None
        elif nickname and text == nickname:
            return None
        else:
            return {
                "content": text,
                "nickname": nickname,
                "sender": str(obj.get("sender", "")).strip(),
                "receiver": str(obj.get("receiver", "")).strip(),
                "content_type": content_type,
                "msg_kind": "text",
                "image_url": "",
            }

    if image_url or is_media_placeholder(front) or msg_kind in ("image", "emoji", "other"):
        if msg_kind == "text":
            msg_kind = "image" if image_url else "other"
        if msg_kind == "image":
            preview = front if is_media_placeholder(front) else "[图片]"
        elif msg_kind == "emoji":
            preview = front if front else "[表情]"
        else:
            preview = front if front else "[消息]"
        if (
            raw_content
            and not looks_like_json_object(raw_content)
            and is_valid_chat_content(raw_content)
            and not image_url
        ):
            preview = raw_content
        return {
            "content": preview,
            "nickname": nickname,
            "sender": str(obj.get("sender", "")).strip(),
            "receiver": str(obj.get("receiver", "")).strip(),
            "content_type": content_type,
            "msg_kind": msg_kind,
            "image_url": image_url,
        }

    return None


def find_xhs_im_json_objects(blob: str) -> List[Dict[str, Any]]:
    if not blob:
        return []
    results: List[Dict[str, Any]] = []
    seen: set = set()

    def extract_balanced_json(src: str, start: int) -> Optional[str]:
        if start < 0 or start >= len(src) or src[start] != "{":
            return None
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(src)):
            ch = src[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[start : i + 1]
        return None

    markers = (
        '"content"',
        '\\"content\\"',
        '"front_chain"',
        '\\"front_chain\\"',
        '"content_type"',
        '\\"content_type\\"',
    )
    for marker in markers:
        idx = 0
        while True:
            pos = blob.find(marker, idx)
            if pos < 0:
                break
            start = blob.rfind("{", 0, pos)
            if start < 0:
                idx = pos + len(marker)
                continue
            fragment = extract_balanced_json(blob, start)
            parsed_obj: Optional[Dict[str, Any]] = None
            if fragment:
                for candidate in (fragment, fragment.replace('\\"', '"')):
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            parsed_obj = parse_xhs_im_message_obj(obj)
                            if parsed_obj:
                                break
                    except json.JSONDecodeError:
                        continue
            if parsed_obj:
                key = (
                    parsed_obj.get("content"),
                    parsed_obj.get("nickname"),
                    parsed_obj.get("sender"),
                )
                if key not in seen:
                    seen.add(key)
                    results.append(parsed_obj)
            idx = pos + len(marker)
    return results


def resolve_incoming_conv_id(sender: str, receiver: str, my_uid: str = "") -> str:
    me = str(my_uid or "").strip()
    if me:
        if sender and sender != me:
            return sender
        if receiver and receiver != me:
            return receiver
        return sender or receiver or DEFAULT_CONV_ID
    if sender:
        return sender
    if receiver:
        return receiver
    return DEFAULT_CONV_ID


def resolve_xhs_conv_id(
    msg: Dict[str, Any],
    full_body: str = "",
    proto_strings: Optional[List[str]] = None,
    my_uid: str = "",
    account_id: str = "",
) -> str:
    del account_id  # 独立服务不查联系人库
    sender = str(msg.get("sender", ""))
    receiver = str(msg.get("receiver", ""))
    conv_id = resolve_incoming_conv_id(sender, receiver, my_uid)
    if conv_id != DEFAULT_CONV_ID:
        return conv_id

    for field in ("conversation_id", "chat_id", "conv_id", "session_id"):
        v = str(msg.get(field, "")).strip()
        if v and IM_HEX_ID.match(v):
            return v

    if full_body:
        for field in ("sender", "receiver"):
            v = grab_json_field(full_body, field)
            if not v:
                continue
            if my_uid:
                if v != my_uid:
                    return v
            else:
                return v
        for field in ("chat_id", "conversation_id", "conv_id"):
            v = grab_json_field(full_body, field)
            if v and IM_HEX_ID.match(v):
                return v

    if proto_strings:
        picked = pick_conv_id(proto_strings, my_uid)
        if picked:
            return picked

    return DEFAULT_CONV_ID


def xhs_msg_to_event(
    msg: Dict[str, Any],
    url: str,
    time: str,
    full_body: str = "",
    proto_strings: Optional[List[str]] = None,
    my_uid: str = "",
    account_id: str = "",
) -> Optional[Dict[str, Any]]:
    parsed = parse_xhs_im_message_obj(msg)
    if not parsed:
        return None
    conv_id = resolve_xhs_conv_id(
        parsed, full_body, proto_strings, my_uid=my_uid, account_id=account_id
    )
    sender = str(parsed.get("sender", "")).strip()
    receiver = str(parsed.get("receiver", "")).strip()
    me = str(my_uid or "").strip()
    direction = "down"
    if me and IM_HEX_ID.match(me):
        if sender == me and receiver and receiver != me:
            direction = "up"
            conv_id = receiver
        elif receiver == me and sender and sender != me:
            direction = "down"
            conv_id = sender
        elif sender == me:
            direction = "up"
    elif sender and receiver and sender == receiver:
        conv_id = sender
    text = str(parsed.get("content") or "").strip()
    kind = str(parsed.get("msg_kind", "text") or "text")
    if not text and kind in ("image", "emoji", "other"):
        text = "[图片]" if kind == "image" else ("[表情]" if kind == "emoji" else "[消息]")
    return {
        "direction": direction,
        "text": text,
        "conv_id": conv_id,
        "nickname": parsed.get("nickname", ""),
        "url": url,
        "time": time,
        "platform": PLATFORM_XHS,
        "msg_kind": parsed.get("msg_kind", "text"),
        "content_type": parsed.get("content_type"),
        "account_id": account_id,
    }

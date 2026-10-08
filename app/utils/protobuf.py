# -*- coding: utf-8 -*-
"""Protobuf / Base64 辅助。"""
from __future__ import annotations

import base64
import re
from typing import List, Optional, Tuple

from app.config import IM_HEX_ID, MAX_WS_BODY
from app.utils.text import is_chat_text, is_garbled_text, pick_chat_text

def parse_protobuf_strings(raw: bytes) -> List[str]:
    """从 Protobuf（含嵌套）中提取字符串字段。"""
    results: List[str] = []
    seen: set = set()

    def add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            results.append(s)

    def read_varint(data: bytes, pos: int) -> Tuple[int, int]:
        value = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            value |= (b & 0x7f) << shift
            if b & 0x80 == 0:
                break
            shift += 7
        return value, pos

    def parse_chunk(data: bytes) -> None:
        i, n = 0, len(data)
        while i < n:
            tag = data[i]
            wire_type = tag & 0x07
            i += 1
            if wire_type == 0:
                _, i = read_varint(data, i)
            elif wire_type == 1:
                i += 8
            elif wire_type == 2:
                length, i = read_varint(data, i)
                if i + length > n:
                    break
                chunk = data[i:i + length]
                i += length
                parse_chunk(chunk)
                try:
                    s = chunk.decode("utf-8")
                    if is_chat_text(s):
                        add(s)
                except UnicodeDecodeError:
                    pass
            elif wire_type == 5:
                i += 4
            else:
                break

    parse_chunk(raw)
    for i in range(2, len(raw)):
        tag = raw[i - 2]
        if (tag & 0x07) != 2:
            continue
        ln = raw[i - 1]
        if ln < 2 or ln > 120:
            continue
        if i + ln > len(raw):
            continue
        chunk = raw[i:i + ln]
        try:
            s = chunk.decode("utf-8")
            if s.isprintable() and is_chat_text(s):
                add(s)
        except UnicodeDecodeError:
            pass
    return results


def parse_protobuf_hex_ids(raw: bytes) -> List[str]:
    """提取 24 位 hex 用户/会话 ID。聊天字符串解析会故意丢掉这些 ID。"""
    results: List[str] = []
    seen: set = set()

    def add(s: str) -> None:
        if s and s not in seen and IM_HEX_ID.match(s):
            seen.add(s)
            results.append(s)

    def read_varint(data: bytes, pos: int) -> Tuple[int, int]:
        value = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            value |= (b & 0x7f) << shift
            if b & 0x80 == 0:
                break
            shift += 7
        return value, pos

    def parse_chunk(data: bytes) -> None:
        i, n = 0, len(data)
        while i < n:
            tag = data[i]
            wire_type = tag & 0x07
            i += 1
            if wire_type == 0:
                _, i = read_varint(data, i)
            elif wire_type == 1:
                i += 8
            elif wire_type == 2:
                length, i = read_varint(data, i)
                if i + length > n:
                    break
                chunk = data[i:i + length]
                i += length
                if length == 24:
                    try:
                        add(chunk.decode("ascii"))
                    except UnicodeDecodeError:
                        pass
                parse_chunk(chunk)
            elif wire_type == 5:
                i += 4
            else:
                break

    parse_chunk(raw)
    n = len(raw)
    for i in range(2, n):
        if raw[i - 1] != 24 or i + 24 > n:
            continue
        if (raw[i - 2] & 0x07) != 2:
            continue
        try:
            add(raw[i : i + 24].decode("ascii"))
        except UnicodeDecodeError:
            pass
    return results

def extract_send_text_from_protobuf(raw: bytes) -> Optional[str]:
    """从 sendMessage Protobuf 提取正文（仅解析合法 string 字段）。"""
    candidates: List[str] = []
    n = len(raw)
    for i in range(2, n):
        if (raw[i - 2] & 0x07) != 2:
            continue
        ln = raw[i - 1]
        if not (2 <= ln <= 200) or i + ln > n:
            continue
        try:
            s = raw[i:i + ln].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if is_chat_text(s) and not is_garbled_text(s):
            candidates.append(s)
    return pick_chat_text(candidates)

def pick_conv_id(strings: List[str], my_uid: str = "") -> Optional[str]:
    hex_ids = [s for s in strings if IM_HEX_ID.match(s)]
    me = str(my_uid or "").strip()
    if me:
        for h in hex_ids:
            if h != me:
                return h
        return None
    # 不知道自己的 uid 时不要用内置 DEFAULT_UID 去猜，避免多账号串身份
    return hex_ids[0] if hex_ids else None

def try_b64_decode_ws(text: str) -> Optional[bytes]:
    s = (text or "").strip()
    if not s or s[0] in "{[":
        return None
    compact = re.sub(r"\s+", "", s)
    if len(compact) < 16 or not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        return None
    try:
        return base64.b64decode(compact, validate=False)
    except Exception:
        return None

def _grab_json_field(blob: str, name: str) -> str:
    for pat in (
        rf'\\"{name}\\":\\"([^\\"]*)\\"',
        rf'"{name}":"([^"]*)"',
        rf'"{name}":\s*"([^"]*)"',
    ):
        m = re.search(pat, blob)
        if m:
            return m.group(1)
    return ""

def _grab_json_field_near(blob: str, name: str, pos: int, window: int = 480) -> str:
    start = max(0, pos - window)
    end = min(len(blob), pos + window)
    return _grab_json_field(blob[start:end], name)

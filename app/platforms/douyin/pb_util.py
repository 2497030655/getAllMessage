# -*- coding: utf-8 -*-
"""抖音 IM Protobuf 编解码（发信 cmd=100 / 会话初始化解析）。"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# 真实 get_by_conversation 请求信封模板（仅复用静态字段，替换 cmd + body）
_ENVELOPE_TEMPLATE_B64 = (
    "CK0CEKZOGgUwLjEuNiIAKAMwADoTZmVmMWE4MDpwL2x6Zy9zdG9yZUJC6hI/CiQwOjE6NTEwNjAx"
    "Mjg5Nzk1NjYyOjE4OTI3MTc3ODU3NzgwMzIQARi/hInwjMXSg2ogASiQjsH7nKT8AjAySgEwWglk"
    "b3V5aW5fcGNyBjM2MDAwMHoTCgtzZXNzaW9uX2FpZBIENjM4M3oQCgtzZXNzaW9uX2RpZBIBMHoV"
    "CghhcHBfbmFtZRIJZG91eWluX3BjehUKD3ByaW9yaXR5X3JlZ2lvbhICY256fQoKdXNlcl9hZ2Vu"
    "dBJvTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQv"
    "NTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEzMC4wLjAuMCBTYWZhcmkvNTM3LjM2"
    "ehYKDmNvb2tpZV9lbmFibGVkEgR0cnVlehkKEGJyb3dzZXJfbGFuZ3VhZ2USBXpoLUNOehkKEGJy"
    "b3dzZXJfcGxhdGZvcm0SBVdpbjMyehcKDGJyb3dzZXJfbmFtZRIHTW96aWxsYXp6Cg9icm93c2Vy"
    "X3ZlcnNpb24SZzUuMCAoV2luZG93cyBOVCAxMC4wOyBXaW42NDsgeDY0KSBBcHBsZVdlYktpdC81"
    "MzcuMzYgKEtIVE1MLCBsaWtlIEdlY2tvKSBDaHJvbWUvMTMwLjAuMC4wIFNhZmFyaS81MzcuMzZ6"
    "FgoOYnJvd3Nlcl9vbmxpbmUSBHRydWV6FAoMc2NyZWVuX3dpZHRoEgQxNTM2ehQKDXNjcmVl"
    "bl9oZWlnaHQSAzg2NHoiCgdyZWZlcmVyEhdodHRwczovL3d3dy5kb3V5aW4uY29tL3oeCg10aW1l"
    "em9uZV9uYW1lEg1Bc2lhL1NoYW5naGFpeg0KCGRldmljZUlkEgEweg0KCGlzLXJldHJ5EgEwkAEB"
    "qgEKZG91eWluX3dlYrIBB3dlYl9zZGs="
)

SEND_URL = "https://imapi.douyin.com/v1/message/send"


def _read_varint(b: bytes, i: int) -> Tuple[int, int]:
    s = r = 0
    while True:
        if i >= len(b):
            raise IndexError("varint")
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not (x & 0x80):
            return r, i
        s += 7


def _get_fields(b: bytes) -> Dict[int, list]:
    out: Dict[int, list] = {}
    i, end = 0, len(b)
    while i < end:
        try:
            tag, i = _read_varint(b, i)
        except IndexError:
            break
        fn, wt = tag >> 3, tag & 7
        if fn == 0:
            break
        try:
            if wt == 0:
                v, i = _read_varint(b, i)
            elif wt == 1:
                v = b[i : i + 8]
                i += 8
            elif wt == 5:
                v = b[i : i + 4]
                i += 4
            elif wt == 2:
                ln, i = _read_varint(b, i)
                v = b[i : i + ln]
                i += ln
            else:
                break
        except IndexError:
            break
        out.setdefault(fn, []).append(v)
    return out


def _first(d: Dict[int, list], k: int, default=None):
    v = d.get(k)
    return v[0] if v else default


def _s(v) -> str:
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except Exception:
            return ""
    return "" if v is None else str(v)


def _enc_varint(n: int) -> bytes:
    out = bytearray()
    n = int(n)
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _enc_tag(fn: int, wt: int) -> bytes:
    return _enc_varint((fn << 3) | wt)


def _enc_v(fn: int, n: int) -> bytes:
    return _enc_tag(fn, 0) + _enc_varint(n)


def _enc_ld(fn: int, data: bytes) -> bytes:
    return _enc_tag(fn, 2) + _enc_varint(len(data)) + data


def _rebuild_envelope(cmd: int, request_body: bytes, template: Optional[bytes] = None) -> bytes:
    tmpl = template or base64.b64decode(_ENVELOPE_TEMPLATE_B64)
    out = bytearray()
    i, n = 0, len(tmpl)
    while i < n:
        tag, j = _read_varint(tmpl, i)
        fn, wt = tag >> 3, tag & 7
        start = i
        if wt == 0:
            _, j = _read_varint(tmpl, j)
        elif wt == 2:
            ln, j = _read_varint(tmpl, j)
            j += ln
        elif wt == 1:
            j += 8
        elif wt == 5:
            j += 4
        else:
            break
        if fn == 1:
            out += _enc_v(1, cmd)
        elif fn == 8:
            out += _enc_ld(8, request_body)
        else:
            out += tmpl[start:j]
        i = j
    return bytes(out)


def build_send_request(
    conv_id: str,
    conv_type: int,
    conv_short_id: int,
    ticket: str,
    text: str,
    client_msg_id: Optional[str] = None,
    stime_ms: Optional[int] = None,
    envelope_template: Optional[bytes] = None,
) -> bytes:
    """构造 imapi message/send 请求体（cmd 100）。"""
    client_msg_id = client_msg_id or str(uuid.uuid4())
    stime_ms = int(stime_ms or int(time.time() * 1000))
    content = json.dumps(
        {
            "mention_users": [],
            "aweType": 700,
            "richTextInfos": [],
            "text": text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    def _ext(k: str, v: str) -> bytes:
        return _enc_ld(5, _enc_ld(1, k.encode()) + _enc_ld(2, v.encode()))

    body100 = (
        _enc_ld(1, conv_id.encode("utf-8"))
        + _enc_v(2, int(conv_type))
        + _enc_v(3, int(conv_short_id))
        + _enc_ld(4, content.encode("utf-8"))
        + _ext("s:client_message_id", client_msg_id)
        + _ext("s:stime", str(stime_ms))
        + _ext("s:mentioned_users", "")
        + _enc_v(6, 7)
        + _enc_ld(7, ticket.encode("utf-8"))
        + _enc_ld(8, client_msg_id.encode("utf-8"))
    )
    return _rebuild_envelope(100, _enc_ld(100, body100), envelope_template)


def parse_send_response(resp: bytes) -> dict:
    if not resp:
        return {"ok": False, "msg": "空响应"}
    env = _get_fields(resp)
    msg = _s(_first(env, 4, b""))
    return {
        "ok": msg == "OK",
        "msg": msg or "unknown",
        "cmd": _first(env, 1) or 0,
        "error_code": _first(env, 3) or 0,
    }


def extract_send_fields(raw: bytes) -> Dict[str, Any]:
    """从真实 send 请求体里抠 conv_id / short_id / ticket / text。"""
    out: Dict[str, Any] = {}
    env = _get_fields(raw)
    body = _first(env, 8)
    if not isinstance(body, bytes):
        return out
    body_f = _get_fields(body)
    inner = _first(body_f, 100)
    if not isinstance(inner, bytes):
        # 有的包 body 直接就是 SendMessageRequestBody
        inner = body
    f = _get_fields(inner)
    conv_id = _s(_first(f, 1, b""))
    if conv_id:
        out["conversation_id"] = conv_id
    if isinstance(_first(f, 2), int):
        out["conversation_type"] = _first(f, 2)
    if isinstance(_first(f, 3), int):
        out["conversation_short_id"] = _first(f, 3)
    content = _first(f, 4)
    if isinstance(content, bytes):
        try:
            obj = json.loads(content.decode("utf-8"))
            if isinstance(obj, dict) and obj.get("text"):
                out["text"] = str(obj["text"])
        except Exception:
            pass
    ticket = _s(_first(f, 7, b""))
    if ticket:
        out["ticket"] = ticket
    return out


def parse_init_conversations(raw: bytes) -> List[Dict[str, Any]]:
    """解析 get_message_by_init 响应，提取会话 ticket / short_id。"""
    if not raw:
        return []
    env = _get_fields(raw)
    self_uid = _s(_first(env, 13))
    body_raw = _first(env, 6)
    if not isinstance(body_raw, bytes):
        return []
    body = _get_fields(body_raw)
    b2043_raw = _first(body, 2043)
    if not isinstance(b2043_raw, bytes):
        return []
    b2043 = _get_fields(b2043_raw)
    out: List[Dict[str, Any]] = []
    for cb in b2043.get(1, []):
        if not isinstance(cb, bytes):
            continue
        conv = _get_fields(cb)
        core = _get_fields(_first(conv, 1, b"") or b"")
        conv_id = _s(_first(core, 1, b""))
        if not conv_id:
            continue
        item = {
            "conversation_id": conv_id,
            "conversation_short_id": _first(core, 2),
            "conversation_type": _first(core, 3) or 1,
            "ticket": _s(_first(core, 4, b"")),
            "self_uid": self_uid,
        }
        if isinstance(item["conversation_short_id"], bytes):
            try:
                item["conversation_short_id"] = int(_s(item["conversation_short_id"]) or 0)
            except Exception:
                item["conversation_short_id"] = 0
        out.append(item)
    return out


def harvest_meta_from_bytes(raw: bytes) -> Dict[str, Any]:
    """从任意 WS/HTTP 二进制里尽量抠会话元数据。"""
    meta: Dict[str, Any] = {}
    blob = raw.decode("utf-8", errors="ignore")
    m = re.search(r"0:\d+:\d{5,}:\d{5,}", blob)
    if m:
        meta["conversation_id"] = m.group(0)
    for pat, key in (
        (r'"conversation_id"\s*:\s*"([^"]+)"', "conversation_id"),
        (r'"conversation_short_id"\s*:\s*"?(\d+)"?', "conversation_short_id"),
        (r'"ticket"\s*:\s*"([^"]+)"', "ticket"),
    ):
        mm = re.search(pat, blob)
        if mm:
            meta[key] = int(mm.group(1)) if key.endswith("short_id") else mm.group(1)
    # protobuf 字符串字段兜底
    for s in re.findall(r"[\x20-\x7e]{8,120}", blob):
        if s.startswith("0:") and s.count(":") >= 3 and "conversation_id" not in meta:
            meta["conversation_id"] = s.split("\x00")[0]
        if "ticket" not in meta and 16 <= len(s) <= 64 and re.fullmatch(r"[A-Za-z0-9_\-]+", s):
            # 弱启发，仅当邻近有 conversation 时采用
            if "conversation" in blob[max(0, blob.find(s) - 40) : blob.find(s) + 40]:
                meta["ticket"] = s
    return meta

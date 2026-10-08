# -*- coding: utf-8 -*-
"""抖音 IM 解析器。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.config import (
    IM_PROTO_TEMPLATE_B64,
    IM_TEMPLATE_TEXT,
    PLATFORM_DOUYIN,
)
from app.utils.protobuf import try_b64_decode_ws, extract_send_text_from_protobuf
from app.utils.text import (
    contact_display_name,
    is_valid_chat_content,
    is_valid_display_name,
)

if TYPE_CHECKING:
    from app.context import AppContext


class DouyinImParser:
    """负责抖音 frontier-im WebSocket 解析。"""

    def __init__(self, app: "AppContext") -> None:
        self.app = app

    def douyin_conv_key(self, conversation_id: str) -> str:
        cid = (conversation_id or "").strip()
        if not cid:
            return "douyin_unknown"
        # 统一 0:1:A:B / 0:1:B:A，避免同一人拆成两条
        parts = cid.split(":")
        if len(parts) == 4 and parts[0] == "0":
            a, b = sorted([parts[2], parts[3]])
            cid = f"0:{parts[1]}:{a}:{b}"
        return "dy_" + cid.replace(":", "_")[:72]

    def extract_douyin_json_objects(self, raw: bytes) -> List[Dict[str, Any]]:
        text = raw.decode("utf-8", errors="ignore")
        objs: List[Dict[str, Any]] = []
        for m in re.finditer(r"\{[^{}]*\"command_type\"[^{}]*\}", text):
            try:
                objs.append(json.loads(m.group()))
            except json.JSONDecodeError:
                pass
        return objs
    def parse_douyin_ws_meta(self, body: str) -> Optional[Dict[str, Any]]:
        raw = try_b64_decode_ws(body)
        if not raw:
            return None
        objs = self.extract_douyin_json_objects(raw)
        return objs[0] if objs else None
    def extract_douyin_text_from_raw(self, raw: bytes) -> Optional[str]:
        blob = raw.decode("utf-8", errors="ignore")
        if re.match(r"^seq-\d+~", blob.strip()) or "msg_type" in blob[:80]:
            return None
        candidates: List[str] = []
        for pat in (
            r'"text"\s*:\s*"([^"]{1,200})"',
            r'"content"\s*:\s*"([^"]{1,200})"',
            r'\\"text\\":\\"([^\\"]{1,200})\\"',
            r'\\"content\\":\\"([^\\"]{1,200})\\"',
        ):
            for m in re.finditer(pat, blob):
                candidate = m.group(1).strip()
                if is_valid_chat_content(candidate):
                    candidates.append(candidate)
        if candidates:
            # 优先较短、无链接痕迹的正文（如「好吧」）
            candidates.sort(key=lambda x: (":" in x or "/" in x, len(x)))
            return candidates[0]
        candidate = extract_send_text_from_protobuf(raw)
        if candidate and is_valid_chat_content(candidate):
            return candidate
        return None
    def extract_douyin_display_name(self, raw: bytes) -> str:
        blob = raw.decode("utf-8", errors="ignore")
        for key in ("nickname", "user_name", "username", "nick_name", "sender_name"):
            for pat in (
                rf'"{key}"\s*:\s*"([^"]{1,40})"',
                rf'\\"{key}\\":\\"([^\\"]{1,40})\\"',
            ):
                for m in re.finditer(pat, blob):
                    if is_valid_display_name(m.group(1)):
                        return m.group(1)
        return ""
    def ensure_douyin_contact(
        self, conversation_id: str, ws_url: str = "", account_id: str = ""
    ) -> str:
        raw = self.douyin_conv_key(conversation_id)
        if raw == "douyin_unknown":
            return raw
        account_id = account_id or self.app.accounts.active_id
        key = self.app.contacts.make_key(account_id, raw)
        created = key not in self.app.contacts._contacts
        if created:
            self.app.contacts._contacts[key] = {
                "key": key,
                "conv_id": raw,
                "account_id": account_id,
                "nickname": "",
                "messages": [],
                "template_b64": IM_PROTO_TEMPLATE_B64,
                "template_text": IM_TEMPLATE_TEXT,
                "ws_url": ws_url,
                "unread": 0,
                "platform": PLATFORM_DOUYIN,
                "douyin_conversation_id": conversation_id,
            }
        c = self.app.contacts._contacts[key]
        if ws_url:
            c["ws_url"] = ws_url
        try:
            self.app.douyin_send.apply_meta_to_contact(key, conversation_id)
        except Exception:
            pass
        if created:
            self.app.bridge.post_contact(key)
        return key
    def extract_douyin_im_events(
        self, body: str, url: str, time: str, account_id: str = ""
    ) -> List[Dict[str, Any]]:
        """抖音 frontier-im 二进制 WS↓（Protobuf + 内嵌 JSON）。"""
        raw = try_b64_decode_ws(body)
        if not raw:
            return []
        # 尝试解 PushFrame / gzip，提高 conversation_id 命中率
        try:
            from app.platforms.douyin.pb_util import _get_fields, _first, _s
            import gzip

            frame = _get_fields(raw)
            penc = _s(_first(frame, 6, b""))
            payload = _first(frame, 8, b"")
            if isinstance(payload, bytes) and payload:
                if penc == "gzip" or payload[:2] == b"\x1f\x8b":
                    try:
                        payload = gzip.decompress(payload)
                    except Exception:
                        pass
                raw_inner = payload
            else:
                raw_inner = raw
        except Exception:
            raw_inner = raw

        events: List[Dict[str, Any]] = []
        text = self.extract_douyin_text_from_raw(raw_inner) or self.extract_douyin_text_from_raw(
            raw
        )
        conv_id = ""
        short_id = None
        ticket = ""
        for src in (raw_inner, raw):
            for mobj in self.extract_douyin_json_objects(src):
                cid = str(mobj.get("conversation_id", ""))
                if cid and not conv_id:
                    conv_id = cid
                if mobj.get("conversation_short_id") is not None and short_id is None:
                    try:
                        short_id = int(mobj.get("conversation_short_id"))
                    except Exception:
                        pass
                if mobj.get("ticket") and not ticket:
                    ticket = str(mobj.get("ticket"))
            if not conv_id:
                from app.platforms.douyin.pb_util import harvest_meta_from_bytes

                meta = harvest_meta_from_bytes(src)
                conv_id = str(meta.get("conversation_id") or conv_id or "")
                if short_id is None and meta.get("conversation_short_id") is not None:
                    short_id = meta.get("conversation_short_id")
                if not ticket and meta.get("ticket"):
                    ticket = str(meta.get("ticket"))
            if conv_id:
                break
        # MessageBody.field1 常为 conversation_id
        if not conv_id:
            try:
                from app.platforms.douyin.pb_util import _get_fields, _first, _s
                import re as _re

                blob = raw_inner.decode("utf-8", errors="ignore")
                m = _re.search(r"0:\d+:\d{6,}:\d{6,}", blob)
                if m:
                    conv_id = m.group(0)
            except Exception:
                pass
        if not text and not conv_id:
            return events
        # 没有会话 ID 不建联系人（避免 douyin_unknown 刷屏）
        if not conv_id:
            return events
        # 推送摘要「私信了你: xxx」不是会话正文
        if text and (text.startswith("私信了你") or text.startswith("私信了你:")):
            return events
        conv_key = self.ensure_douyin_contact(conv_id, url, account_id)
        try:
            self.app.douyin_send.remember_session_meta(
                conv_id,
                {
                    "conversation_id": conv_id,
                    "conversation_short_id": short_id,
                    "ticket": ticket,
                },
                account_id=account_id,
            )
        except Exception:
            pass
        if not text:
            return events
        nick = self.extract_douyin_display_name(raw_inner) or self.extract_douyin_display_name(
            raw
        )
        if not nick:
            existing = self.app.contacts.get(conv_key)
            nick = contact_display_name(existing) if existing else "抖音用户"
        events.append(
            {
                "direction": "down",
                "text": text,
                "conv_id": conv_key,
                "nickname": nick,
                "url": url,
                "time": time,
                "platform": PLATFORM_DOUYIN,
                "douyin_conversation_id": conv_id,
                "account_id": account_id,
            }
        )
        return events

# -*- coding: utf-8 -*-
"""小红书 IM WebSocket 下行解析器。"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional

from xhs_im_service.parsing.payload import (
    find_xhs_im_json_objects,
    normalize_chat_payload,
    parse_xhs_im_message_obj,
    xhs_msg_to_event,
)
from xhs_im_service.util.protobuf import (
    grab_json_field,
    grab_json_field_near,
    parse_protobuf_hex_ids,
    parse_protobuf_strings,
)
from xhs_im_service.util.text import (
    is_displayable_message,
    is_valid_chat_content,
    looks_like_json_object,
)


class XhsImParser:
    """负责小红书 WebSocket ↓ 推送解析（无外部 App 依赖）。"""

    def extract_ws_down_events(
        self,
        body_down: str,
        url: str,
        time: str,
        account_id: str = "",
        my_uid: str = "",
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        seen: set = set()

        def push(ev: Optional[Dict[str, Any]]) -> None:
            if not ev:
                return
            text, nick, unpacked_url, unpacked_kind = normalize_chat_payload(
                str(ev.get("text", "")), str(ev.get("nickname", ""))
            )
            if unpacked_url and (
                not text or looks_like_json_object(str(ev.get("text", "")))
            ):
                text = (
                    "[图片]"
                    if (unpacked_kind or "image") == "image"
                    else "[表情]"
                )
            if not text:
                return
            ev = dict(ev)
            ev["text"] = text
            ev.pop("image_url", None)
            if nick:
                ev["nickname"] = nick
            if nick and str(ev.get("text", "")).strip() == str(nick).strip():
                return
            if not is_displayable_message(ev["text"]):
                return
            key = (ev.get("conv_id"), ev.get("direction"), ev.get("text"))
            if key in seen:
                return
            seen.add(key)
            events.append(ev)

        body_down = body_down.strip()
        if not body_down:
            return events

        for msg in find_xhs_im_json_objects(body_down):
            push(
                xhs_msg_to_event(
                    msg, url, time, body_down, my_uid=my_uid, account_id=account_id
                )
            )

        seen_b64: set = set()
        try:
            data = json.loads(body_down)

            def walk_b64(obj: Any) -> None:
                if isinstance(obj, str):
                    s = obj.strip()
                    if len(s) < 20 or not re.fullmatch(r"[A-Za-z0-9+/=]+", s):
                        return
                    if s in seen_b64:
                        return
                    seen_b64.add(s)
                    push(
                        self._parse_nested_push_item(
                            s, url, time, body_down, account_id, my_uid
                        )
                    )
                    return
                if isinstance(obj, dict):
                    d_val = obj.get("d")
                    if isinstance(d_val, str) and len(d_val) >= 20:
                        if d_val not in seen_b64:
                            seen_b64.add(d_val)
                            push(
                                self._parse_nested_push_item(
                                    d_val, url, time, body_down, account_id, my_uid
                                )
                            )
                    for v in obj.values():
                        walk_b64(v)
                elif isinstance(obj, list):
                    for v in obj:
                        walk_b64(v)

            walk_b64(data)
        except json.JSONDecodeError:
            pass

        for pat in (
            r'\\"content\\":\\"([^\\"]*)\\"',
            r'\\"front_chain\\":\\"([^\\"]*)\\"',
            r'"content"\s*:\s*"([^"]*)"',
            r'"front_chain"\s*:\s*"([^"]*)"',
        ):
            for m in re.finditer(pat, body_down):
                text = m.group(1).strip()
                if not is_valid_chat_content(text):
                    continue
                pos = m.start()
                msg = {
                    "content": text,
                    "nickname": grab_json_field_near(body_down, "nickname", pos),
                    "sender": grab_json_field_near(body_down, "sender", pos),
                    "receiver": grab_json_field_near(body_down, "receiver", pos),
                }
                push(
                    xhs_msg_to_event(
                        msg, url, time, body_down, my_uid=my_uid, account_id=account_id
                    )
                )

        return events

    def parse_im_push_payload(self, nested_b64: str) -> Optional[Dict[str, Any]]:
        try:
            raw = base64.b64decode(nested_b64)
        except Exception:
            return None

        blob = raw.decode("utf-8", errors="ignore")
        inner_json: Optional[Dict[str, Any]] = None
        for marker in ('{"content"', '{\\"content\\"', '{"', '{\\"'):
            idx = blob.find(marker)
            if idx >= 0:
                fragment = blob[idx:]
                for candidate in (fragment, fragment.replace('\\"', '"')):
                    try:
                        end = candidate.rfind("}") + 1
                        if end > 1:
                            inner_json = json.loads(candidate[:end])
                            break
                    except json.JSONDecodeError:
                        continue
            if inner_json:
                break

        if inner_json:
            parsed = parse_xhs_im_message_obj(inner_json)
            if parsed:
                return {
                    "content": parsed["content"],
                    "nickname": parsed["nickname"],
                    "sender": parsed["sender"],
                    "receiver": parsed["receiver"],
                }

        for msg in find_xhs_im_json_objects(blob):
            return {
                "content": msg["content"],
                "nickname": msg.get("nickname", ""),
                "sender": msg.get("sender", ""),
                "receiver": msg.get("receiver", ""),
            }

        content = grab_json_field(blob, "content").strip()
        if not content:
            content = grab_json_field(blob, "front_chain").strip()
        if not content or not is_valid_chat_content(content):
            return None

        return {
            "content": content,
            "nickname": grab_json_field(blob, "nickname"),
            "sender": grab_json_field(blob, "sender"),
            "receiver": grab_json_field(blob, "receiver"),
        }

    def _parse_nested_push_item(
        self,
        nested_b64: str,
        url: str,
        time: str,
        full_body: str,
        account_id: str = "",
        my_uid: str = "",
    ) -> Optional[Dict[str, Any]]:
        try:
            parsed = self.parse_im_push_payload(nested_b64)
            if not parsed or not parsed.get("content"):
                return None
            raw_pb = base64.b64decode(nested_b64)
            proto_strings = parse_protobuf_strings(raw_pb) + parse_protobuf_hex_ids(
                raw_pb
            )
            return xhs_msg_to_event(
                parsed,
                url,
                time,
                full_body,
                proto_strings,
                my_uid=my_uid,
                account_id=account_id,
            )
        except Exception:
            return None

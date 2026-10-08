# -*- coding: utf-8 -*-
"""消息解析器：NetworkRecord → ImMessage。"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from xhs_im_service.constants import DEFAULT_CONV_ID
from xhs_im_service.interfaces import IMessageParser
from xhs_im_service.models import ImMessage, NetworkRecord
from xhs_im_service.parsing.xhs_parser import XhsImParser
from xhs_im_service.util.protobuf import (
    extract_send_text_from_protobuf,
    parse_protobuf_hex_ids,
)
from xhs_im_service.util.text import is_garbled_text

logger = logging.getLogger("xhs_im_service.parser")


class XhsMessageParser(IMessageParser):
    """将 WebSocket 抓包记录解析为 ImMessage（完全自包含）。"""

    def __init__(self, account_id: str = "default") -> None:
        self._account_id = account_id
        self._my_uid = ""
        self._down_parser = XhsImParser()

    def set_my_uid(self, uid: str) -> None:
        self._my_uid = str(uid or "").strip()

    def parse(self, record: NetworkRecord) -> List[ImMessage]:
        if record.kind != "WebSocket":
            return []

        method = record.method
        url = record.url
        time_s = record.time
        account_id = record.account_id or self._account_id
        my_uid = self._my_uid
        events: List[Dict[str, Any]] = []

        if method == "WS↑":
            body_up = record.request_body or ""
            if "sendMessage" in body_up:
                ev = self._parse_send_message(
                    body_up, url, time_s, account_id, my_uid
                )
                if ev:
                    events.append(ev)
        elif method == "WS↓":
            body_down = record.response_body or ""
            if body_down:
                events = self._down_parser.extract_ws_down_events(
                    body_down,
                    url,
                    time_s,
                    account_id=account_id,
                    my_uid=my_uid,
                )

        result: List[ImMessage] = []
        for ev in events:
            ev.setdefault("account_id", account_id)
            text = str(ev.get("text") or "").strip()
            nick = str(ev.get("nickname") or "").strip()
            if not text:
                continue
            if nick and text == nick:
                continue
            result.append(ImMessage.from_event(ev))
        return result

    def _parse_send_message(
        self,
        body_up: str,
        url: str,
        time_s: str,
        account_id: str,
        my_uid: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(body_up)
            inner_b64 = data.get("b", {}).get("d", {}).get("b")
            if not inner_b64 or not isinstance(inner_b64, str):
                return None
            raw = base64.b64decode(inner_b64)
            text = extract_send_text_from_protobuf(raw)
            if not text or is_garbled_text(text):
                return None
            hex_ids = parse_protobuf_hex_ids(raw)
            me = str(my_uid or "").strip()
            if me and me not in hex_ids:
                me = ""
            if me:
                conv_id = next((h for h in hex_ids if h != me), "") or DEFAULT_CONV_ID
            elif len(hex_ids) >= 2:
                conv_id = hex_ids[1]
            elif hex_ids:
                conv_id = hex_ids[0]
            else:
                conv_id = DEFAULT_CONV_ID
            return {
                "direction": "up",
                "text": text,
                "conv_id": conv_id,
                "nickname": "",
                "url": url,
                "time": time_s,
                "platform": "xhs",
                "msg_kind": "text",
                "account_id": account_id,
            }
        except Exception:
            logger.exception("parse sendMessage failed")
            return None

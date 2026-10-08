# -*- coding: utf-8 -*-
"""联系人 / 会话状态仓库。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from app.config import (
    DEFAULT_CONV_ID,
    IM_PROTO_TEMPLATE_B64,
    IM_TEMPLATE_TEXT,
    PLATFORM_DOUYIN,
    PLATFORM_XHS,
)
from app.utils.text import (
    apply_contact_nickname,
    extract_display_name_from_obj,
    is_displayable_message,
    is_garbled_text,
    looks_like_json_object,
)
from app.utils.timefmt import now_str
from app.platforms.xhs.payload import normalize_chat_payload

if TYPE_CHECKING:
    from app.context import AppContext


def make_contact_key(account_id: str, conv_id: str) -> str:
    account_id = str(account_id or "").strip()
    conv_id = str(conv_id or "").strip()
    if not conv_id:
        return ""
    prefix = f"{account_id}::"
    if account_id and conv_id.startswith(prefix):
        return conv_id
    if account_id:
        return f"{account_id}::{conv_id}"
    return conv_id


def split_contact_key(key: str) -> Tuple[str, str]:
    key = str(key or "")
    if "::" in key:
        account_id, conv_id = key.split("::", 1)
        return account_id, conv_id
    return "", key


class ContactStore:
    """按账号 + 会话 ID 管理多联系人聊天。"""

    def __init__(self, app: Optional["AppContext"] = None) -> None:
        self.app = app
        self._contacts: Dict[str, Dict[str, Any]] = {}
        self._active: Optional[str] = None
        self._active_platform: str = PLATFORM_XHS
        self._active_by_ap: Dict[Tuple[str, str], Optional[str]] = {}

    def _account_id(self, explicit: str = "") -> str:
        if explicit:
            return explicit
        if self.app is not None:
            return self.app.accounts.active_id or ""
        return ""

    @staticmethod
    def make_key(account_id: str, conv_id: str) -> str:
        return make_contact_key(account_id, conv_id)

    def infer_platform(
        self, conv_id: str, ws_url: str = "", explicit: str = ""
    ) -> str:
        if explicit in (PLATFORM_XHS, PLATFORM_DOUYIN):
            return explicit
        raw = split_contact_key(conv_id)[1]
        if (
            str(raw).startswith("dy_")
            or "frontier-im" in ws_url
            or "douyin.com" in ws_url
        ):
            return PLATFORM_DOUYIN
        return PLATFORM_XHS

    def platform_unread(self, platform: str, account_id: str = "") -> int:
        aid = self._account_id(account_id)
        total = 0
        for c in self._contacts.values():
            if c.get("platform", PLATFORM_XHS) != platform:
                continue
            if aid and c.get("account_id") != aid:
                continue
            total += int(c.get("unread", 0))
        return total

    def account_unread(self, account_id: str) -> int:
        total = 0
        for c in self._contacts.values():
            if c.get("account_id") == account_id:
                total += int(c.get("unread", 0))
        return total

    def get_active_platform(self) -> str:
        return self._active_platform

    def set_active_platform(self, platform: str) -> None:
        if platform not in (PLATFORM_XHS, PLATFORM_DOUYIN):
            return
        self._active_platform = platform
        aid = self._account_id()
        self._active = self._active_by_ap.get((aid, platform))

    def set_active_account(self, account_id: str) -> None:
        self._active = self._active_by_ap.get((account_id, self._active_platform))

    def ensure_xhs_contact(
        self, conv_id: str, account_id: str, nickname: str = ""
    ) -> str:
        key = make_contact_key(account_id, conv_id)
        if key not in self._contacts:
            self._contacts[key] = {
                "key": key,
                "conv_id": conv_id,
                "account_id": account_id,
                "nickname": nickname,
                "messages": [],
                "template_b64": IM_PROTO_TEMPLATE_B64,
                "template_text": IM_TEMPLATE_TEXT,
                "ws_url": "",
                "unread": 0,
                "platform": PLATFORM_XHS,
            }
        elif nickname:
            apply_contact_nickname(self._contacts[key], nickname)
        return key

    def drop_account(self, account_id: str) -> None:
        drop = [
            k
            for k, c in self._contacts.items()
            if c.get("account_id") == account_id
        ]
        for key in drop:
            self._contacts.pop(key, None)
        if self._active in drop:
            self._active = None
        for ap_key in list(self._active_by_ap):
            if ap_key[0] == account_id:
                self._active_by_ap.pop(ap_key, None)

    def upsert_from_event(self, event: Dict[str, Any], ws_url: str = "") -> str:
        raw_conv = str(event.get("conv_id") or DEFAULT_CONV_ID)
        account_id = str(event.get("account_id") or self._account_id())
        _, raw_conv = split_contact_key(raw_conv) if "::" in raw_conv else ("", raw_conv)
        key = make_contact_key(account_id, raw_conv)
        platform = self.infer_platform(
            raw_conv, ws_url, str(event.get("platform", ""))
        )
        if key not in self._contacts:
            self._contacts[key] = {
                "key": key,
                "conv_id": raw_conv,
                "account_id": account_id,
                "nickname": extract_display_name_from_obj(event)
                if isinstance(event, dict)
                else "",
                "messages": [],
                "template_b64": IM_PROTO_TEMPLATE_B64,
                "template_text": IM_TEMPLATE_TEXT,
                "ws_url": ws_url,
                "unread": 0,
                "platform": platform,
            }
        c = self._contacts[key]
        c["platform"] = platform
        c["account_id"] = account_id
        c["conv_id"] = raw_conv
        c["key"] = key
        text, nick_from_text, unpacked_url, unpacked_kind = normalize_chat_payload(
            str(event.get("text", "")), str(event.get("nickname", ""))
        )
        event = dict(event)
        event["text"] = text
        if nick_from_text:
            event["nickname"] = nick_from_text
        if unpacked_url and not text:
            event["text"] = (
                "[图片]"
                if (unpacked_kind or "image") == "image"
                else "[表情]"
            )
            text = event["text"]
        elif unpacked_url and looks_like_json_object(text):
            event["text"] = "[图片]" if (unpacked_kind or "image") == "image" else "[表情]"
            text = event["text"]
        direction = event.get("direction")
        # 发出去的包里经常是自己的昵称或其它账号模板里的名字，不能覆盖对方
        if direction != "up":
            apply_contact_nickname(
                c, str(event.get("nickname", "")), text
            )
        if ws_url:
            c["ws_url"] = ws_url
        if event.get("template_b64"):
            c["template_b64"] = event["template_b64"]
            tpl = event.get("template_text") or text
            if tpl and not is_garbled_text(str(tpl)) and not looks_like_json_object(str(tpl)):
                c["template_text"] = str(tpl)

        if not is_displayable_message(text):
            return key

        msgs = c["messages"]

        if direction == "up":
            if msgs and msgs[-1].get("direction") == "up":
                if msgs[-1].get("local"):
                    msgs[-1].pop("local", None)
                return key
            msgs.append(
                {
                    "direction": "up",
                    "text": text,
                    "time": event.get("time", now_str()),
                }
            )
            return key

        if (
            msgs
            and msgs[-1].get("direction") == "up"
            and msgs[-1].get("text") == text
        ):
            if msgs[-1].get("local"):
                msgs[-1].pop("local", None)
            return key

        if msgs:
            last = msgs[-1]
            if last.get("direction") == direction and last.get("text") == text:
                return key

        msgs.append(
            {
                "direction": direction,
                "text": text,
                "time": event.get("time", now_str()),
            }
        )
        if direction == "down" and key != self._active:
            c["unread"] = c.get("unread", 0) + 1
        return key

    def set_active(self, conv_id: Optional[str]) -> None:
        self._active = conv_id
        if conv_id and conv_id in self._contacts:
            c = self._contacts[conv_id]
            c["unread"] = 0
            plat = c.get("platform", PLATFORM_XHS)
            aid = str(c.get("account_id") or "")
            self._active_by_ap[(aid, plat)] = conv_id
            self._active_platform = plat

    def get_active(self) -> Optional[Dict[str, Any]]:
        if self._active and self._active in self._contacts:
            return self._contacts[self._active]
        return None

    def get(self, conv_id: str, account_id: str = "") -> Optional[Dict[str, Any]]:
        if not conv_id:
            return None
        found = self._contacts.get(conv_id)
        if found is not None:
            return found
        aid = self._account_id(account_id)
        if aid:
            return self._contacts.get(make_contact_key(aid, conv_id))
        return None

    def list_contacts(
        self, platform: Optional[str] = None, account_id: str = ""
    ) -> List[Dict[str, Any]]:
        plat = platform or self._active_platform
        aid = self._account_id(account_id)

        def last_time(c: Dict[str, Any]) -> str:
            msgs = c.get("messages") or []
            return msgs[-1]["time"] if msgs else ""

        items = []
        for c in self._contacts.values():
            if c.get("platform", PLATFORM_XHS) != plat:
                continue
            if aid and c.get("account_id") != aid:
                continue
            if plat == PLATFORM_DOUYIN:
                msgs = c.get("messages") or []
                if not msgs and c.get("key") != self._active and c.get("conv_id") != self._active:
                    continue
            items.append(c)
        return sorted(items, key=last_time, reverse=True)

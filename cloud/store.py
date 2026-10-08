# -*- coding: utf-8 -*-
"""云端内存存储（可后续换 PostgreSQL）。"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional, Set

from app.models.contact_store import make_contact_key, split_contact_key


class CloudStore:
    """线程安全（asyncio Lock）的会话与消息仓库。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._contacts: Dict[str, Dict[str, Any]] = {}
        self._message_ids: Set[str] = set()
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._account_meta: Dict[str, Dict[str, str]] = {}

    async def register_agent(self, agent_id: str, info: Dict[str, Any]) -> None:
        async with self._lock:
            self._agents[agent_id] = {**info, "online": True}

    async def unregister_agent(self, agent_id: str) -> None:
        async with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id]["online"] = False

    async def set_account_meta(
        self,
        account_id: str,
        xhs_uid: str = "",
        douyin_uid: str = "",
        agent_id: str = "",
    ) -> None:
        async with self._lock:
            meta = self._account_meta.setdefault(account_id, {})
            if xhs_uid:
                meta["xhs_uid"] = xhs_uid
            if douyin_uid:
                meta["douyin_uid"] = douyin_uid
            if agent_id:
                meta["agent_id"] = agent_id

    async def get_account_meta(self, account_id: str) -> Dict[str, str]:
        async with self._lock:
            return dict(self._account_meta.get(account_id, {}))

    async def agent_for_account(self, account_id: str) -> Optional[str]:
        async with self._lock:
            meta = self._account_meta.get(account_id, {})
            aid = meta.get("agent_id", "")
            if aid and self._agents.get(aid, {}).get("online"):
                return aid
            for agent_id, info in self._agents.items():
                if info.get("online"):
                    return agent_id
            return None

    async def upsert_contact(self, contact: Dict[str, Any]) -> str:
        key = str(contact.get("key") or "")
        async with self._lock:
            self._contacts[key] = contact
            return key

    async def append_message(
        self, conv_key: str, message: Dict[str, Any]
    ) -> Optional[str]:
        msg_id = str(message.get("message_id") or uuid.uuid4().hex)
        async with self._lock:
            if msg_id in self._message_ids:
                return None
            c = self._contacts.get(conv_key)
            if c is None:
                return None
            msgs = c.setdefault("messages", [])
            text = str(message.get("text") or "")
            direction = message.get("direction")
            if msgs and msgs[-1].get("direction") == direction and msgs[-1].get("text") == text:
                return None
            self._message_ids.add(msg_id)
            msgs.append(
                {
                    "message_id": msg_id,
                    "direction": direction,
                    "text": text,
                    "time": message.get("time", ""),
                }
            )
            if direction == "down":
                c["unread"] = int(c.get("unread", 0)) + 1
            return msg_id

    async def list_conversations(
        self, account_id: str = "", platform: str = ""
    ) -> List[Dict[str, Any]]:
        async with self._lock:
            items: List[Dict[str, Any]] = []
            for c in self._contacts.values():
                if account_id and c.get("account_id") != account_id:
                    continue
                if platform and c.get("platform") != platform:
                    continue
                msgs = c.get("messages") or []
                preview = msgs[-1]["text"] if msgs else ""
                items.append(
                    {
                        "key": c.get("key"),
                        "conv_id": c.get("conv_id"),
                        "account_id": c.get("account_id"),
                        "platform": c.get("platform"),
                        "nickname": c.get("nickname", ""),
                        "unread": c.get("unread", 0),
                        "preview": preview,
                        "updated_at": msgs[-1]["time"] if msgs else "",
                    }
                )
            items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
            return items

    async def get_conversation(self, conv_key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            c = self._contacts.get(conv_key)
            return dict(c) if c else None

    async def mark_read(self, conv_key: str) -> None:
        async with self._lock:
            c = self._contacts.get(conv_key)
            if c:
                c["unread"] = 0

    async def resolve_conv_key(
        self, account_id: str, conv_id: str
    ) -> str:
        return make_contact_key(account_id, split_contact_key(conv_id)[1])

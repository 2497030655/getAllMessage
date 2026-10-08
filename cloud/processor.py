# -*- coding: utf-8 -*-
"""云端解析：复用 PC 端 parser，原始抓包 → IM 事件。"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.config import PLATFORM_XHS
from app.models.contact_store import ContactStore
from app.platforms.douyin.parser import DouyinImParser
from app.platforms.xhs.parser import XhsImParser
from app.services.record_pipeline import RecordPipeline

if TYPE_CHECKING:
    from cloud.store import CloudStore


class _NoopBridge:
    def post_record(self, entry: dict) -> None:
        return

    def post_contact(self, conv_id: str) -> None:
        return

    def post_send_result(self, result: dict) -> None:
        return

    def post_url(self, url: str, account_id: str = "") -> None:
        return


class _NoopDomSync:
    def schedule_scrape_chat_username(self, conv_id: str) -> None:
        return


class _CloudAccounts:
    """供 parser 读取 xhs_uid / douyin_uid。"""

    def __init__(self, store: "CloudStore") -> None:
        self._store = store
        self.active_id = "default"

    async def xhs_uid_async(self, account_id: str) -> str:
        meta = await self._store.get_account_meta(account_id or self.active_id)
        return meta.get("xhs_uid", "")

    def xhs_uid(self, account_id: str = "") -> str:
        # RecordPipeline 同步调用；meta 在 process 前已写入 store 缓存
        aid = account_id or self.active_id
        return getattr(self, "_uid_cache", {}).get(aid, {}).get("xhs_uid", "")

    def set_uid_cache(self, account_id: str, xhs_uid: str = "", douyin_uid: str = "") -> None:
        cache = getattr(self, "_uid_cache", None)
        if cache is None:
            cache = {}
            self._uid_cache = cache
        entry = cache.setdefault(account_id, {})
        if xhs_uid:
            entry["xhs_uid"] = xhs_uid
        if douyin_uid:
            entry["douyin_uid"] = douyin_uid


class CloudParseApp:
    """最小 AppContext，仅用于 RecordPipeline + parser。"""

    def __init__(self, store: "CloudStore") -> None:
        self.bridge = _NoopBridge()
        self.dom_sync = _NoopDomSync()
        self.accounts = _CloudAccounts(store)
        self.contacts = ContactStore(self)
        self.xhs_parser = XhsImParser(self)
        self.douyin_parser = DouyinImParser(self)
        self.pipeline = RecordPipeline(self)


class CaptureProcessor:
    def __init__(self, store: "CloudStore") -> None:
        self.store = store
        self._app = CloudParseApp(store)
        self._seen: set = set()

    async def sync_meta(self, account_id: str) -> None:
        meta = await self.store.get_account_meta(account_id)
        self._app.accounts.set_uid_cache(
            account_id,
            meta.get("xhs_uid", ""),
            meta.get("douyin_uid", ""),
        )
        self._app.accounts.active_id = account_id or "default"

    async def process(self, record: Dict[str, Any]) -> List[Dict[str, Any]]:
        rid = str(record.get("id") or "")
        if rid and rid in self._seen:
            return []
        if rid:
            self._seen.add(rid)
            if len(self._seen) > 50000:
                self._seen.clear()

        account_id = str(record.get("account_id") or "default")
        await self.sync_meta(account_id)

        pipeline = self._app.pipeline
        entry = dict(record)
        pipeline.update_send_template_from_record(entry)
        enriched = pipeline.enrich_chat_record(entry)

        if enriched.get("method") == "WS↓":
            ws_url = str(enriched.get("url", ""))
            body = str(enriched.get("responseBody") or "")
            if "frontier-im" in ws_url or "douyin.com" in ws_url:
                meta = self._app.douyin_parser.parse_douyin_ws_meta(body)
                if meta:
                    cid = str(meta.get("conversation_id", ""))
                    if cid:
                        self._app.douyin_parser.ensure_douyin_contact(
                            cid, ws_url, account_id
                        )

        events = pipeline.extract_im_events(enriched)
        if not events and enriched.get("kind") == "WebSocket":
            ws_url = str(enriched.get("url", ""))
            body = str(
                enriched.get("responseBody") or enriched.get("requestBody") or ""
            )
            if "frontier-im" not in ws_url and "douyin.com" not in ws_url:
                for chat in pipeline.extract_chat_from_ws(enriched):
                    ev = self._app.xhs_parser._event_from_chat_dict(
                        chat,
                        ws_url,
                        str(enriched.get("time", "")),
                        body,
                        account_id=account_id,
                        my_uid=self._app.accounts.xhs_uid(account_id),
                    )
                    if ev:
                        events.append(ev)

        pushed: List[Dict[str, Any]] = []
        for ev in events:
            if not ev.get("text") and not ev.get("image_url"):
                continue
            if ev.get("image_url") and not ev.get("text"):
                ev["text"] = "[图片]"
            text = str(ev.get("text") or "").strip()
            nick = str(ev.get("nickname") or "").strip()
            # 过滤「消息正文 = 用户昵称」的脏数据
            if not text or (nick and text == nick):
                continue
            ws_url = str(enriched.get("url", ""))
            conv_key = self._app.contacts.upsert_from_event(ev, ws_url)
            contact = self._app.contacts.get(conv_key)
            if contact is None:
                continue
            # 会话昵称优先用事件里的 nickname（不要把正文当昵称）
            if nick and not contact.get("nickname"):
                contact["nickname"] = nick
            await self.store.upsert_contact(dict(contact))
            msg_id = await self.store.append_message(
                conv_key,
                {
                    "message_id": uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{conv_key}:{ev.get('direction')}:{text}:{ev.get('time')}",
                    ).hex,
                    "direction": ev.get("direction"),
                    "text": text,
                    "time": ev.get("time"),
                },
            )
            if msg_id is None:
                continue
            pushed.append(
                {
                    "type": "im_message",
                    "message_id": msg_id,
                    "conv_key": conv_key,
                    "account_id": account_id,
                    "platform": contact.get("platform", PLATFORM_XHS),
                    "conv_id": contact.get("conv_id"),
                    "nickname": contact.get("nickname", "") or nick,
                    "direction": ev.get("direction"),
                    "text": text,
                    "time": ev.get("time"),
                }
            )
        return pushed

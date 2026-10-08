# -*- coding: utf-8 -*-
"""小红书聊天页 DOM 同步。"""
from __future__ import annotations

import asyncio
import re
from typing import Optional, TYPE_CHECKING

from playwright.async_api import Page

from app.config import PLATFORM_XHS
from app.models.contact_store import split_contact_key
from app.platforms.xhs.scrape_js import SCRAPE_CHAT_JS
from app.utils.text import apply_contact_nickname, is_valid_display_name, sanitize_contact_nickname

if TYPE_CHECKING:
    from app.context import AppContext


class XhsDomSyncService:
    def __init__(self, app: "AppContext") -> None:
        self.app = app

    def schedule_scrape_chat_username(self, conv_id: str) -> None:
        self.schedule_sync_xhs_chat_dom(conv_id)

    def schedule_sync_xhs_chat_dom(self, conv_id: str = "", delay: bool = True) -> None:
        contact = self.app.contacts.get(conv_id) if conv_id else self.app.contacts.get_active()
        account_id = str((contact or {}).get("account_id") or self.app.accounts.active_id or "")
        session = self.app.browser.session_for(account_id)
        if session is None or session.loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._sync_xhs_chat_dom(conv_id, delay=delay, account_id=account_id),
            session.loop,
        )

    async def try_scrape_chat_username(self, page: Page) -> Optional[str]:
        try:
            data = await page.evaluate(SCRAPE_CHAT_JS)
            name = str((data or {}).get("nickname") or "").strip()
            if is_valid_display_name(name):
                return name
        except Exception:
            pass
        return None

    async def _sync_xhs_chat_dom(
        self, conv_id: str = "", delay: bool = True, account_id: str = ""
    ) -> None:
        page = self.app.sender.find_target_page(PLATFORM_XHS, account_id)
        if page is None:
            return
        url = page.url or ""
        if "xiaohongshu.com/chat" not in url:
            return
        m = re.search(r"/chat/([0-9a-f]{24})", url)
        if not m:
            return
        page_conv = m.group(1)
        raw_conv = split_contact_key(conv_id)[1] if conv_id else ""
        if raw_conv and raw_conv != page_conv:
            return
        key = self.app.contacts.ensure_xhs_contact(page_conv, account_id)
        try:
            if delay:
                await asyncio.sleep(0.5)
            data = await page.evaluate(SCRAPE_CHAT_JS)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        c = self.app.contacts.get(key)
        if c is None:
            return
        c["platform"] = PLATFORM_XHS
        sanitize_contact_nickname(c)
        changed = False
        nick = str(data.get("nickname") or "").strip()
        if apply_contact_nickname(c, nick):
            changed = True
        if changed:
            if account_id == self.app.accounts.active_id:
                self.app.contacts.set_active_platform(PLATFORM_XHS)
                if self.app.contacts.get_active_platform() == PLATFORM_XHS:
                    self.app.contacts.set_active(key)
            self.app.bridge.post_contact(key)

    async def _scrape_and_apply_chat_username(self, conv_id: str) -> None:
        await self._sync_xhs_chat_dom(conv_id)

# -*- coding: utf-8 -*-
"""Playwright Edge：只抓小红书 IM WebSocket。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import Optional

from playwright.async_api import Page, WebSocket, async_playwright

from xhs_im_service.config import ServiceConfig
from xhs_im_service.interfaces import INetworkCapture, RecordHandler
from xhs_im_service.models import NetworkRecord

logger = logging.getLogger("xhs_im_service.browser")

_IM_HEX = re.compile(r"^[0-9a-f]{24}$", re.I)

_DETECT_UID_JS = """
() => {
  try {
    const keys = Object.keys(window.localStorage || {});
    for (const k of keys) {
      const v = window.localStorage.getItem(k) || "";
      if (/userId|user_id|uid/i.test(k) && /^[0-9a-f]{24}$/i.test(v.trim())) {
        return { xhs_uid: v.trim().toLowerCase() };
      }
    }
    const html = document.documentElement.innerHTML || "";
    const m = html.match(/"userId"\\s*:\\s*"([0-9a-f]{24})"/i)
      || html.match(/"user_id"\\s*:\\s*"([0-9a-f]{24})"/i);
    if (m) return { xhs_uid: m[1].toLowerCase() };
  } catch (e) {}
  return {};
}
"""


class XhsBrowserCapture(INetworkCapture):
    """打开 Edge 聊天页，监听 apppush 等 WebSocket，产出 NetworkRecord。"""

    def __init__(self, config: ServiceConfig) -> None:
        self._config = config
        self._handler: Optional[RecordHandler] = None
        self._my_uid = str(config.my_uid or "").strip()
        self._stopping = False
        self._context = None
        self._pw = None

    def set_record_handler(self, handler: RecordHandler) -> None:
        self._handler = handler

    def set_my_uid(self, uid: str) -> None:
        self._my_uid = str(uid or "").strip()

    def get_my_uid(self) -> str:
        return self._my_uid

    def _ws_interesting(self, ws_url: str) -> bool:
        keywords = self._config.ws_url_keywords
        if not keywords:
            return True
        u = (ws_url or "").lower()
        return any(k.lower() in u for k in keywords)

    def _emit(self, record: NetworkRecord) -> None:
        if self._handler is None:
            return
        try:
            self._handler(record)
        except Exception:
            logger.exception("record handler failed")

    def _on_websocket(self, ws: WebSocket, page: Page) -> None:
        ws_url = ws.url
        if not self._ws_interesting(ws_url):
            return

        from xhs_im_service.util.timefmt import format_payload, now_str

        account_id = self._config.account_id

        def on_frame_sent(payload) -> None:
            try:
                text = format_payload(payload)
                self._emit(
                    NetworkRecord(
                        id=str(uuid.uuid4()),
                        time=now_str(),
                        method="WS↑",
                        url=ws_url,
                        kind="WebSocket",
                        request_body=text,
                        response_body=None,
                        account_id=account_id,
                    )
                )
            except Exception:
                logger.exception("framesent failed")

        def on_frame_received(payload) -> None:
            try:
                text = format_payload(payload)
                self._emit(
                    NetworkRecord(
                        id=str(uuid.uuid4()),
                        time=now_str(),
                        method="WS↓",
                        url=ws_url,
                        kind="WebSocket",
                        request_body=None,
                        response_body=text,
                        account_id=account_id,
                    )
                )
            except Exception:
                logger.exception("framereceived failed")

        ws.on("framesent", on_frame_sent)
        ws.on("framereceived", on_frame_received)
        logger.info("watching ws: %s", ws_url[:120])

    async def _detect_uid(self, page: Page) -> None:
        if self._my_uid:
            return
        try:
            data = await page.evaluate(_DETECT_UID_JS)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        uid = str(data.get("xhs_uid") or "").strip().lower()
        url = page.url or ""
        peer = ""
        m = re.search(r"/chat/([0-9a-f]{24})", url, re.I)
        if m:
            peer = m.group(1).lower()
        if uid and peer and uid == peer:
            return
        if uid and _IM_HEX.match(uid):
            self._my_uid = uid
            logger.info("detected my_uid=%s", uid)

    def _bind_page(self, page: Page) -> None:
        page.on("websocket", lambda w: self._on_websocket(w, page))
        page.on(
            "framenavigated",
            lambda frame: (
                asyncio.create_task(self._detect_uid(page))
                if frame == page.main_frame
                else None
            ),
        )
        asyncio.create_task(self._detect_uid(page))

    async def run(self) -> None:
        cfg = self._config
        os.makedirs(cfg.profile_dir, exist_ok=True)
        logger.info(
            "launch Edge channel=%s profile=%s url=%s",
            cfg.edge_channel,
            cfg.profile_dir,
            cfg.chat_url,
        )
        self._stopping = False
        self._pw = await async_playwright().start()
        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                cfg.profile_dir,
                channel=cfg.edge_channel,
                headless=cfg.headless,
                no_viewport=True,
                ignore_default_args=["--enable-automation"],
                args=[
                    f"--window-size={cfg.window_width},{cfg.window_height}",
                ],
            )
            self._context.on("page", lambda p: self._bind_page(p))
            page = (
                self._context.pages[0]
                if self._context.pages
                else await self._context.new_page()
            )
            self._bind_page(page)
            await page.goto(cfg.chat_url, wait_until="domcontentloaded")
            await self._detect_uid(page)
            logger.info("browser ready url=%s my_uid=%s", page.url, self._my_uid or "(unknown)")
            print(
                "[xhs_im_service] Edge 已打开小红书聊天页。"
                "登录后收发私信，解析结果将打印到控制台。Ctrl+C 退出。",
                flush=True,
            )
            while not self._stopping:
                await asyncio.sleep(0.5)
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        self._stopping = True
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

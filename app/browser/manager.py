# -*- coding: utf-8 -*-
"""多开浏览器：每个账号一个独立 Edge 进程。"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict, Optional, TYPE_CHECKING, Tuple

from app.browser.session import EdgeBrowserSession
from app.models.account_store import Account

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page
    from app.context import AppContext

logger = logging.getLogger("capture")


class BrowserManager:
    """同时拉起多个临时 Edge，窗口错开摆放；登录态不落盘。"""

    def __init__(self, app: "AppContext") -> None:
        self.app = app
        self._sessions: Dict[str, EdgeBrowserSession] = {}
        self.edge_x = 520
        self.edge_w = 800
        self.edge_h = 900

    def session_for(self, account_id: Optional[str] = None) -> Optional[EdgeBrowserSession]:
        aid = account_id or self.app.accounts.active_id
        return self._sessions.get(aid or "")

    def sessions(self) -> Dict[str, EdgeBrowserSession]:
        return dict(self._sessions)

    @property
    def context(self) -> Optional["BrowserContext"]:
        session = self.session_for()
        return session.context if session else None

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        session = self.session_for()
        return session.loop if session else None

    @property
    def active_page(self) -> Optional["Page"]:
        session = self.session_for()
        return session.active_page if session else None

    @property
    def pending(self) -> dict:
        session = self.session_for()
        return session.pending if session else {}

    def clear_all_pending(self) -> None:
        for session in self._sessions.values():
            session.pending.clear()

    def cascade_box(self, index: int) -> Tuple[int, int, int, int]:
        ox = 44 * index
        oy = 40 * index
        return (
            self.edge_x + ox,
            oy,
            max(560, self.edge_w - ox),
            max(500, self.edge_h - oy),
        )

    def start_all(self, edge_x: int, edge_width: int, screen_height: int) -> None:
        self.edge_x = edge_x
        self.edge_w = edge_width
        self.edge_h = screen_height
        for i, acc in enumerate(self.app.accounts.list()):
            self.start_one(acc, index=i)

    def start_one(self, acc: Account, index: Optional[int] = None) -> EdgeBrowserSession:
        existing = self._sessions.get(acc.id)
        if existing is not None:
            return existing
        if index is None:
            index = len(self._sessions)
        x, y, w, h = self.cascade_box(index)
        session = EdgeBrowserSession(
            self.app, acc.id, self.app.accounts.fresh_profile_dir(acc.id)
        )
        self._sessions[acc.id] = session
        thread = threading.Thread(
            target=session.start_edge_thread,
            args=(x, w, h, y),
            daemon=True,
            name=f"edge-{acc.id}",
        )
        thread.start()
        logger.info(
            "started Edge account=%s name=%s pos=%s,%s size=%sx%s",
            acc.id,
            acc.name,
            x,
            y,
            w,
            h,
        )
        return session

    def bring_to_front(self, account_id: str) -> None:
        session = self._sessions.get(account_id)
        if session is None or session.loop is None:
            return
        asyncio.run_coroutine_threadsafe(session.bring_to_front(), session.loop)

    def stop_one(self, account_id: str) -> None:
        session = self._sessions.pop(account_id, None)
        if session is None:
            return
        if session.loop is None:
            session._stopping = True
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(session.shutdown(), session.loop)
            fut.result(timeout=8)
        except Exception:
            logger.exception("stop Edge failed account=%s", account_id)

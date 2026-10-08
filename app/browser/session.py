# -*- coding: utf-8 -*-
"""Edge / Playwright 浏览器会话。"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
import time
import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    Response,
    WebSocket,
    async_playwright,
)

from app.config import (
    DOUYIN_IM_HOME,
    EDGE_HOME,
    FILTER_TYPES,
    IM_HEX_ID,
    IM_KEEPALIVE_SEC,
    IM_NAV_COOLDOWN_SEC,
    PLATFORM_DOUYIN,
    PLATFORM_XHS,
    XHS_CHAT_HOME,
)
from app.scripts import DETECT_IDENTITY_JS, IM_WS_ALIVE_JS, WS_HOOK_SCRIPT
from app.utils.timefmt import format_payload, now_str, safe_body


def _safe_post_data(request: Request) -> str:
    """二进制 POST 体不会因 utf-8 解码崩溃。"""
    try:
        text = request.post_data
        if text is not None:
            return safe_body(text)
    except Exception:
        pass
    try:
        data = request.post_data_buffer
        if data:
            return safe_body(base64.b64encode(bytes(data)).decode("ascii"))
    except Exception:
        pass
    return ""


async def _post_data_bytes(request: Request) -> Optional[bytes]:
    try:
        buf = request.post_data_buffer
        if buf:
            return bytes(buf)
    except Exception:
        pass
    try:
        text = request.post_data
        if text:
            return text.encode("utf-8", errors="ignore")
    except Exception:
        pass
    return None

if TYPE_CHECKING:
    from app.context import AppContext

logger = logging.getLogger("capture")


class EdgeBrowserSession:
    """单个账号的 Edge 临时上下文、页面绑定与网络监听。"""

    def __init__(self, app: "AppContext", account_id: str, profile_dir: str) -> None:
        self.app = app
        self.account_id = account_id
        self.profile_dir = profile_dir
        self.context: Optional[BrowserContext] = None
        self.active_page: Optional[Page] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.pending: Dict[int, Dict[str, Any]] = {}
        self._stopping = False
        self._im_nav_at: Dict[str, float] = {}
        self._win_x = 0
        self._win_y = 0
        self._win_w = 800
        self._win_h = 900

    def find_page(self):
        return self.app.sender.find_target_page(account_id=self.account_id)

    def _tag(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        entry["account_id"] = self.account_id
        return entry

    async def open_edge_homepage(self, page: Page) -> None:
        """Playwright 默认 about:blank 会白屏，跳转到 Edge 新标签页首页。"""
        url = page.url or ""
        if url != "about:blank":
            return
        try:
            await page.goto(EDGE_HOME, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass

    async def on_request(self, request: Request) -> None:
        try:
            url = request.url or ""
            # imapi 发信/会话初始化：即使 resource_type 不在过滤集也要采集
            is_imapi = "imapi.douyin.com" in url
            if request.resource_type not in FILTER_TYPES and not is_imapi:
                return
            rid = str(uuid.uuid4())
            body_bytes = await _post_data_bytes(request) if request.method in ("POST", "PUT", "PATCH") else None
            entry: Dict[str, Any] = {
                "id": rid,
                "time": now_str(),
                "method": request.method,
                "url": url,
                "resourceType": request.resource_type,
                "kind": "HTTP",
                "requestHeaders": dict(request.headers),
                "requestBody": _safe_post_data(request),
                "status": None,
                "responseHeaders": None,
                "responseBody": None,
                "durationMs": None,
                "error": None,
            }
            self.pending[id(request)] = {
                "entry": entry,
                "start": time.monotonic(),
                "body_bytes": body_bytes,
            }
            if is_imapi and body_bytes:
                try:
                    self.app.douyin_send.ingest_binary(
                        url, body_bytes, is_response=False, account_id=self.account_id
                    )
                except Exception:
                    logger.exception("ingest imapi request failed")
            if request.resource_type in FILTER_TYPES or is_imapi:
                self.app.pipeline.emit_record(self._tag(entry))
        except Exception:
            logger.exception("on_request failed")

    async def on_response(self, response: Response) -> None:
        try:
            request = response.request
            url = request.url or ""
            is_imapi = "imapi.douyin.com" in url
            if (
                request.resource_type not in FILTER_TYPES
                and id(request) not in self.pending
                and not is_imapi
            ):
                return
            info = self.pending.get(id(request))
            if info is None:
                entry: Dict[str, Any] = {
                    "id": str(uuid.uuid4()),
                    "time": now_str(),
                    "method": request.method,
                    "url": url,
                    "resourceType": request.resource_type,
                    "kind": "HTTP",
                    "requestHeaders": dict(request.headers),
                    "requestBody": _safe_post_data(request),
                    "status": None,
                    "responseHeaders": None,
                    "responseBody": None,
                    "durationMs": None,
                    "error": None,
                }
                start = time.monotonic()
            else:
                entry = info["entry"]
                start = info["start"]
            entry["status"] = response.status
            entry["responseHeaders"] = dict(response.headers)
            entry["durationMs"] = round((time.monotonic() - start) * 1000, 1)
            resp_bytes: Optional[bytes] = None
            try:
                body = await response.body()
                resp_bytes = body
                try:
                    entry["responseBody"] = safe_body(body.decode("utf-8"))
                except UnicodeDecodeError:
                    entry["responseBody"] = safe_body(
                        base64.b64encode(body).decode("ascii")
                    )
            except Exception as e:
                entry["error"] = str(e)
            if is_imapi and resp_bytes:
                try:
                    self.app.douyin_send.ingest_binary(
                        url, resp_bytes, is_response=True, account_id=self.account_id
                    )
                except Exception:
                    logger.exception("ingest imapi response failed")
            if request.resource_type in FILTER_TYPES or is_imapi or info is not None:
                self.app.pipeline.emit_record(self._tag(entry))
            self.pending.pop(id(request), None)
        except Exception:
            logger.exception("on_response failed")

    async def on_request_failed(self, request: Request) -> None:
        try:
            info = self.pending.get(id(request))
            if info is None:
                return
            entry = info["entry"]
            entry["error"] = request.failure or "request failed"
            entry["durationMs"] = round((time.monotonic() - info["start"]) * 1000, 1)
            self.app.pipeline.emit_record(self._tag(entry))
            self.pending.pop(id(request), None)
        except Exception:
            logger.exception("on_request_failed failed")

    def on_websocket(self, ws: WebSocket, page: Page) -> None:
        ws_url = ws.url

        def on_frame_sent(payload: Any) -> None:
            try:
                text = format_payload(payload)
                if "frontier-im" in ws_url or "douyin.com" in ws_url:
                    try:
                        self.app.douyin_send.ingest_ws_frame(
                            ws_url, payload, account_id=self.account_id
                        )
                    except Exception:
                        logger.exception("ingest douyin ws↑ failed")
                    hint = ""
                    try:
                        raw = payload if isinstance(payload, bytes) else None
                        if raw is None and isinstance(payload, str):
                            try:
                                raw = base64.b64decode(payload)
                            except Exception:
                                raw = None
                        if raw:
                            hint = (
                                self.app.douyin_parser.extract_douyin_text_from_raw(raw)
                                or ""
                            )
                    except Exception:
                        hint = ""
                    self.app.sender.remember_douyin_send_frame(
                        payload, hint, account_id=self.account_id
                    )
                self.app.pipeline.emit_record(
                    self._tag(
                        {
                            "id": str(uuid.uuid4()),
                            "time": now_str(),
                            "method": "WS↑",
                            "url": ws_url,
                            "resourceType": "websocket",
                            "kind": "WebSocket",
                            "requestBody": text,
                            "responseBody": None,
                            "status": 101,
                            "durationMs": 0,
                            "error": None,
                        }
                    )
                )
            except Exception:
                logger.exception("framesent failed")

        def on_frame_received(payload: Any) -> None:
            try:
                if "frontier-im" in ws_url or "douyin.com" in ws_url:
                    try:
                        self.app.douyin_send.ingest_ws_frame(
                            ws_url, payload, account_id=self.account_id
                        )
                    except Exception:
                        logger.exception("ingest douyin ws↓ failed")
                text = format_payload(payload)
                self.app.pipeline.emit_record(
                    self._tag(
                        {
                            "id": str(uuid.uuid4()),
                            "time": now_str(),
                            "method": "WS↓",
                            "url": ws_url,
                            "resourceType": "websocket",
                            "kind": "WebSocket",
                            "requestBody": None,
                            "responseBody": text,
                            "status": 101,
                            "durationMs": 0,
                            "error": None,
                        }
                    )
                )
            except Exception:
                logger.exception("framereceived failed")

        # 先注册收发包，避免后续注入失败导致整条链路中断
        ws.on("framesent", on_frame_sent)
        ws.on("framereceived", on_frame_received)
        if "apppush" in ws_url or "frontier-im" in ws_url:
            try:
                asyncio.create_task(self.app.sender.inject_ws_trackers(page))
            except Exception:
                logger.exception("inject_ws_trackers schedule failed")

    def bind_page(self, page: Page) -> None:
        self.active_page = page
        asyncio.create_task(self.app.sender.setup_page_scripts(page))
        page.on("request", lambda r: asyncio.create_task(self.on_request(r)))
        page.on("response", lambda r: asyncio.create_task(self.on_response(r)))
        page.on(
            "requestfailed",
            lambda r: asyncio.create_task(self.on_request_failed(r)),
        )
        page.on("websocket", lambda w: self.on_websocket(w, page))
        page.on(
            "framenavigated",
            lambda frame: (
                self.app.bridge.post_url(page.url, self.account_id)
                if frame == page.main_frame
                else None
            ),
        )
        asyncio.create_task(self.detect_identity(page))

    def on_new_page(self, page: Page) -> None:
        self.bind_page(page)
        page.on("close", lambda: self.restore_active_page())
        asyncio.create_task(self.open_edge_homepage(page))

    def restore_active_page(self) -> None:
        if self.context and self.context.pages:
            self.active_page = self.context.pages[-1]
            self.app.bridge.post_url(self.active_page.url, self.account_id)

    async def detect_identity(self, page: Page) -> None:
        try:
            data = await page.evaluate(DETECT_IDENTITY_JS)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        url = page.url or ""
        peer = ""
        m = re.search(r"/chat/([0-9a-f]{24})", url, re.I)
        if m:
            peer = m.group(1).lower()
        uid = str(data.get("xhs_uid") or "").strip()
        # 聊天页 URL 里的 id 是对方，不能当成自己
        if uid and peer and uid.lower() == peer:
            logger.info(
                "skip xhs_uid=%s, it is the chat peer account=%s",
                uid,
                self.account_id,
            )
        elif uid and IM_HEX_ID.match(uid.lower()) and "xiaohongshu" in url:
            self.app.accounts.set_xhs_uid(self.account_id, uid.lower())
            self.app.cloud_agent.upload_meta(
                self.account_id, xhs_uid=uid.lower(), page_url=url
            )
        dy = str(data.get("douyin_uid") or "").strip()
        if dy and "douyin" in url:
            self.app.accounts.set_douyin_uid(self.account_id, dy)
            self.app.cloud_agent.upload_meta(
                self.account_id, douyin_uid=dy, page_url=url
            )

    async def bring_to_front(self) -> None:
        page = self.active_page
        if page is None and self.context and self.context.pages:
            page = self.context.pages[-1]
        if page is None or self.context is None:
            return
        try:
            cdp = await self.context.new_cdp_session(page)
            info = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": info["windowId"],
                    "bounds": {
                        "left": self._win_x,
                        "top": self._win_y,
                        "width": self._win_w,
                        "height": self._win_h,
                        "windowState": "normal",
                    },
                },
            )
            await page.bring_to_front()
        except Exception:
            logger.exception("bring_to_front failed account=%s", self.account_id)

    async def shutdown(self) -> None:
        self._stopping = True
        if self.context is not None:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
        self._purge_profile()

    def _purge_profile(self) -> None:
        path = str(self.profile_dir or "")
        if not path or not os.path.isdir(path):
            return
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            logger.exception("purge temp profile failed %s", path)

    async def run_edge(
        self, edge_x: int, edge_width: int, screen_height: int, edge_y: int = 0
    ) -> None:
        self._win_x, self._win_y = edge_x, edge_y
        self._win_w, self._win_h = edge_width, screen_height
        logger.info(
            "starting Edge account=%s profile=%s", self.account_id, self.profile_dir
        )
        pw = await async_playwright().start()
        try:
            self.context = await pw.chromium.launch_persistent_context(
                self.profile_dir,
                channel="msedge",
                headless=False,
                no_viewport=True,
                ignore_default_args=["--enable-automation"],
                args=[
                    f"--window-position={edge_x},{edge_y}",
                    f"--window-size={edge_width},{screen_height}",
                ],
            )
            self.loop = asyncio.get_running_loop()
            await self.context.add_init_script(WS_HOOK_SCRIPT)
            self.context.on("page", self.on_new_page)
            page = (
                self.context.pages[0]
                if self.context.pages
                else await self.context.new_page()
            )
            self.bind_page(page)
            await self.open_edge_homepage(page)
            self.app.bridge.post_url(page.url, self.account_id)
            logger.info(
                "Edge ready account=%s url=%s", self.account_id, page.url
            )
            while not self._stopping:
                await asyncio.sleep(0.5)
        except Exception:
            if not self._stopping:
                logger.exception("run_edge crashed account=%s", self.account_id)
                raise
        finally:
            if self.context:
                try:
                    await self.context.close()
                except Exception:
                    pass
                self.context = None
            await pw.stop()
            self._purge_profile()

    def start_edge_thread(
        self,
        edge_x: int,
        edge_width: int,
        screen_height: int,
        edge_y: int = 0,
    ) -> None:
        try:
            asyncio.run(self.run_edge(edge_x, edge_width, screen_height, edge_y))
        except Exception:
            if not self._stopping:
                logger.exception("Edge thread exited account=%s", self.account_id)

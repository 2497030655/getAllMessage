# -*- coding: utf-8 -*-
"""PC 端云端 Agent：上报原始抓包，接收发信指令。"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.context import AppContext

logger = logging.getLogger("capture.cloud")

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore


class CloudAgent:
    """后台 WebSocket 客户端，与云端长连接。"""

    def __init__(self, app: "AppContext") -> None:
        self.app = app
        self._outbox: queue.Queue = queue.Queue(maxsize=5000)
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self.connected = False
        self.agent_id = ""

    def start(self) -> None:
        from app.config import CLOUD_WS_URL

        if not CLOUD_WS_URL:
            logger.info("CLOUD_WS_URL empty, cloud upload disabled")
            return
        if websockets is None:
            logger.error("websockets not installed, run: pip install websockets")
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="cloud-agent",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        asyncio.run(self._connect_loop())

    async def _connect_loop(self) -> None:
        from app.config import AGENT_ID, CLOUD_API_TOKEN, CLOUD_WS_URL
        import uuid

        while True:
            # 每次连接使用唯一 id，避免同名重连时服务端把「新连接」误标离线
            session_id = f"{AGENT_ID}-{uuid.uuid4().hex[:8]}"
            sep = "&" if "?" in CLOUD_WS_URL else "?"
            url = f"{CLOUD_WS_URL}{sep}agent_id={session_id}&token={CLOUD_API_TOKEN}"
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._loop = asyncio.get_running_loop()
                    self.connected = True
                    self.agent_id = session_id
                    logger.info("cloud connected %s", url)
                    self.app.bridge.post_url("cloud:connected", session_id)
                    # 尽早绑定账号 → agent，供发信路由
                    try:
                        aid = self.app.accounts.active_id or "default"
                        acc = self.app.accounts.get(aid) or self.app.accounts.get_active()
                        self.upload_meta(
                            aid,
                            xhs_uid=(acc.xhs_uid if acc else "") or "",
                            douyin_uid=(acc.douyin_uid if acc else "") or "",
                        )
                    except Exception:
                        logger.exception("upload_meta on connect failed")
                    await self._drain_outbox(ws)
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    send_task = asyncio.create_task(self._send_loop(ws))
                    done, pending = await asyncio.wait(
                        [recv_task, send_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
            except Exception:
                logger.exception("cloud connection lost")
            finally:
                self.connected = False
                self._ws = None
                self.app.bridge.post_url("cloud:disconnected", self.agent_id or "")
            await asyncio.sleep(3)

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "hello_ack":
                self.agent_id = str(msg.get("agent_id") or "")
                self._notify_status()
                # 连接成功后立刻绑定账号，保证云端能路由发信
                try:
                    aid = self.app.accounts.active_id or "default"
                    acc = self.app.accounts.get(aid) or self.app.accounts.get_active()
                    self.upload_meta(
                        aid,
                        xhs_uid=(acc.xhs_uid if acc else "") or "",
                        douyin_uid=(acc.douyin_uid if acc else "") or "",
                    )
                except Exception:
                    logger.exception("upload_meta on hello_ack failed")
            elif mtype == "send_message":
                self._dispatch_send(msg)
            elif mtype == "pong":
                pass

    async def _send_loop(self, ws) -> None:
        while True:
            payload = await asyncio.get_running_loop().run_in_executor(
                None, self._outbox.get
            )
            try:
                await ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                logger.exception("cloud send failed")
                try:
                    self._outbox.put_nowait(payload)
                except Exception:
                    pass
                break

    async def _drain_outbox(self, ws) -> None:
        while True:
            try:
                payload = self._outbox.get_nowait()
            except queue.Empty:
                break
            try:
                await ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                self._outbox.put(payload)
                break

    def _dispatch_send(self, msg: Dict[str, Any]) -> None:
        text = str(msg.get("text") or "")
        conv_key = str(msg.get("conv_key") or msg.get("conv_id") or "")
        task_id = str(msg.get("task_id") or "")
        account_id = str(msg.get("account_id") or "")
        if not text:
            self.post_send_result(task_id, False, "empty text")
            return
        if account_id:
            self.app.accounts.set_active(account_id)

        def _on_done(fut) -> None:
            try:
                result = fut.result()
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            self.post_send_result(
                task_id,
                bool(result.get("ok")),
                str(result.get("error") or ""),
                result,
            )

        session = self.app.browser.session_for(account_id or None)
        if session is None or session.loop is None:
            self.post_send_result(task_id, False, "browser session not ready")
            return
        fut = asyncio.run_coroutine_threadsafe(
            self.app.sender.send_im_message(text, conv_key or None),
            session.loop,
        )
        fut.add_done_callback(_on_done)

    def _enqueue(self, payload: Dict[str, Any]) -> None:
        try:
            self._outbox.put_nowait(payload)
        except queue.Full:
            logger.warning("cloud outbox full, dropping message")

    def upload_record(self, entry: Dict[str, Any]) -> None:
        from app.config import CLOUD_WS_URL

        if not CLOUD_WS_URL:
            return
        body = {
            "type": "capture_record",
            "id": entry.get("id"),
            "time": entry.get("time"),
            "account_id": entry.get("account_id"),
            "kind": entry.get("kind"),
            "method": entry.get("method"),
            "url": entry.get("url"),
            "resourceType": entry.get("resourceType"),
            "requestHeaders": entry.get("requestHeaders"),
            "requestBody": entry.get("requestBody"),
            "responseHeaders": entry.get("responseHeaders"),
            "responseBody": entry.get("responseBody"),
            "status": entry.get("status"),
            "durationMs": entry.get("durationMs"),
            "error": entry.get("error"),
        }
        self._enqueue(body)

    def upload_im_events(self, events: list) -> None:
        """上报 PC 本地已解析的 IM 事件（避免云端把昵称当正文）。"""
        from app.config import CLOUD_WS_URL

        if not CLOUD_WS_URL or not events:
            return
        self._enqueue({"type": "im_events", "events": events})

    def upload_meta(
        self,
        account_id: str,
        xhs_uid: str = "",
        douyin_uid: str = "",
        page_url: str = "",
    ) -> None:
        from app.config import CLOUD_WS_URL

        if not CLOUD_WS_URL:
            return
        self._enqueue(
            {
                "type": "agent_meta",
                "account_id": account_id,
                "xhs_uid": xhs_uid,
                "douyin_uid": douyin_uid,
                "page_url": page_url,
            }
        )

    def post_send_result(
        self,
        task_id: str,
        ok: bool,
        error: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "type": "send_result",
            "task_id": task_id,
            "ok": ok,
            "error": error or None,
        }
        if detail:
            payload["detail"] = {
                k: detail[k]
                for k in ("method", "conv_id", "account_id", "page")
                if k in detail
            }
        self._enqueue(payload)

    def _notify_status(self) -> None:
        self.app.bridge.post_url(
            f"cloud:{'connected' if self.connected else 'disconnected'}",
            self.agent_id,
        )

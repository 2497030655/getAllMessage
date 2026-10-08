# -*- coding: utf-8 -*-
"""消息发送服务。"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

from playwright.async_api import Page

from app.config import DEFAULT_CONV_ID, IM_HEX_ID, PLATFORM_DOUYIN, PLATFORM_XHS
from app.models.contact_store import split_contact_key
from app.scripts import WS_SEND_JS, WS_TRACKER_SCRIPT
from app.utils.protobuf import parse_protobuf_hex_ids

if TYPE_CHECKING:
    from app.context import AppContext


def _peer_hex(value: str) -> str:
    raw = split_contact_key(str(value or ""))[1]
    return raw if IM_HEX_ID.match(raw) else ""


def _replace_same_len(raw: bytearray, old: str, new: str) -> bool:
    if not old or not new or old == new:
        return True
    if len(old) != len(new):
        return False
    blob = old.encode("utf-8")
    pos = raw.find(blob)
    if pos < 0:
        return False
    raw[pos : pos + len(blob)] = new.encode("utf-8")
    return True


class MessageSender:
    def __init__(self, app: "AppContext") -> None:
        self.app = app
        self._dy_tpl: Dict[str, bytes] = {}
        self._dy_tpl_text: Dict[str, str] = {}

    def remember_douyin_send_frame(
        self, payload: Any, text_hint: str = "", account_id: str = ""
    ) -> None:
        """缓存抖音发出帧，便于之后按模板替换文本重发。"""
        raw: Optional[bytes] = None
        if isinstance(payload, bytes):
            raw = payload
        elif isinstance(payload, str):
            s = payload.strip()
            if s.startswith("b64:"):
                s = s[4:]
            try:
                raw = base64.b64decode(s)
            except Exception:
                return
        if not raw or len(raw) < 8:
            return
        aid = account_id or self.app.accounts.active_id or ""
        self._dy_tpl[aid] = raw
        if text_hint:
            self._dy_tpl_text[aid] = text_hint

    def build_im_send_payload(
        self,
        text: str,
        conv_id: str = DEFAULT_CONV_ID,
        uid: str = "",
        template_b64: Optional[str] = None,
        template_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """仿照 sendMessage 结构构造 IM 发送包。"""
        proto_b64 = template_b64 or self.app.pipeline.im_proto_template_b64
        old_text_str = template_text or self.app.pipeline.im_template_text
        raw = bytearray(base64.b64decode(proto_b64))
        old_text = old_text_str.encode("utf-8")
        new_text = text.encode("utf-8")
        idx = raw.find(old_text)
        if idx < 0:
            raise ValueError("模板中未找到示例文本，请重新抓取一条 sendMessage")
        if raw[idx - 1] != len(old_text):
            raise ValueError("Protobuf 模板格式变化，无法替换文本")
        raw[idx - 1] = len(new_text)
        raw[idx : idx + len(old_text)] = new_text
        del raw[idx + len(new_text) : idx + len(old_text)]
        msg_uuid = str(uuid.uuid4())
        old_id = b"$0469b7a2-ca7c-429b-97f5-fabd31647770"
        new_id = f"${msg_uuid}".encode("utf-8")
        id_pos = raw.find(old_id)
        if id_pos > 0 and raw[id_pos - 1] == len(old_id):
            raw[id_pos - 1] = len(new_id)
            raw[id_pos : id_pos + len(old_id)] = new_id

        peer = _peer_hex(conv_id)
        uid = str(uid or "").strip()
        hexes = parse_protobuf_hex_ids(bytes(raw))
        old_uid = hexes[0] if hexes else ""
        old_conv = hexes[1] if len(hexes) >= 2 else ""
        if uid and uid in hexes:
            old_uid = uid
            old_conv = next((h for h in hexes if h != uid), old_conv)
        if peer and peer in hexes and peer != uid:
            old_conv = peer

        if uid and IM_HEX_ID.match(uid) and old_uid and old_uid != uid:
            if not _replace_same_len(raw, old_uid, uid):
                raise ValueError("无法把发送包改成当前账号身份，已取消以免用错账号")
        elif not uid or not IM_HEX_ID.match(uid):
            raise ValueError("当前账号身份未知，拒绝用模板里的其他账号身份发送")

        if peer and old_conv and old_conv != peer:
            if not _replace_same_len(raw, old_conv, peer):
                raise ValueError("无法把发送包改成当前会话，已取消以免发错人")
        elif not peer:
            raise ValueError("会话 ID 无效，无法确定发送对象")
        if uid.encode("utf-8") not in raw or peer.encode("utf-8") not in raw:
            raise ValueError("发送包身份/会话替换失败，已取消以免用错账号或发错人")
        inner_b64 = base64.b64encode(bytes(raw)).decode("ascii")
        outer_m = f"{uuid.uuid4().hex[:14]}-{uuid.uuid4().hex[:12]}"
        return {
            "v": 1,
            "t": 3,
            "m": outer_m,
            "b": {
                "d": {
                    "a": 2,
                    "c": "sendMessage",
                    "biz": "im",
                    "b": inner_b64,
                    "e": {},
                    "s": "rrmp.b.i",
                }
            },
        }

    def build_douyin_send_bytes(self, text: str, account_id: str = "") -> bytes:
        """用缓存的抖音发出帧替换正文。"""
        aid = account_id or self.app.accounts.active_id or ""
        template = self._dy_tpl.get(aid)
        template_text = self._dy_tpl_text.get(aid, "")
        if not template:
            raise ValueError("尚无抖音发送模板：请先在抖音页手动发一条消息")
        raw = bytearray(template)
        old = (template_text or "").encode("utf-8")
        new = text.encode("utf-8")
        if old and old in raw:
            idx = raw.find(old)
            # protobuf length-delimited: 前一字节常为长度
            if idx > 0 and raw[idx - 1] == len(old) and len(new) < 128:
                raw[idx - 1] = len(new)
                raw[idx : idx + len(old)] = new
                del raw[idx + len(new) : idx + len(old)]
                return bytes(raw)
            if len(old) == len(new):
                raw[idx : idx + len(old)] = new
                return bytes(raw)
        raise ValueError("无法在抖音模板中替换文本，请再手动发一条更新模板")

    def find_target_page(
        self,
        platform: Optional[str] = None,
        account_id: Optional[str] = None,
        conv_id: Optional[str] = None,
    ) -> Optional[Page]:
        """按账号 + 平台优先选对应站点的标签页。"""
        session = self.app.browser.session_for(account_id)
        if session is None or session.context is None:
            return session.active_page if session else None
        pages = list(session.context.pages)
        if not pages:
            return session.active_page

        def url_of(p: Page) -> str:
            return p.url or ""

        peer = _peer_hex(conv_id or "")
        if peer:
            for p in pages:
                if f"/chat/{peer}" in url_of(p):
                    return p

        if platform == PLATFORM_DOUYIN:
            for p in pages:
                u = url_of(p)
                if "douyin.com" in u and any(
                    k in u for k in ("im", "message", "chat", "notice")
                ):
                    return p
            for p in pages:
                if "douyin.com" in url_of(p):
                    return p
            return None

        for p in pages:
            u = url_of(p)
            if "xiaohongshu.com" in u and ("/chat" in u or "chat" in u):
                return p
        for p in pages:
            if "xiaohongshu.com" in url_of(p):
                return p
        if platform == PLATFORM_XHS:
            return None
        return session.active_page or pages[0]

    async def inject_ws_trackers(self, page: Page) -> None:
        for frame in page.frames:
            try:
                await frame.evaluate(WS_TRACKER_SCRIPT)
            except Exception:
                pass

    async def setup_page_scripts(self, page: Page) -> None:
        try:
            await page.add_init_script(WS_TRACKER_SCRIPT)
        except Exception:
            pass

    async def try_ui_send(self, page: Page, text: str) -> Dict[str, Any]:
        """在聊天输入框发送（会触发真实 WS↑，最可靠）。"""
        selectors = [
            "[contenteditable='true']",
            "div.input-box [contenteditable='true']",
            ".chat-input [contenteditable='true']",
            "[role='textbox']",
            "textarea",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).last
                if await loc.count() == 0:
                    continue
                await loc.scroll_into_view_if_needed(timeout=2000)
                await loc.click(timeout=4000)
                await loc.fill(text)
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.3)
                return {"ok": True, "method": "ui", "selector": sel, "url": page.url}
            except Exception:
                continue
        try:
            loc = page.locator("[contenteditable='true']").last
            await loc.click(timeout=4000)
            await page.keyboard.type(text, delay=20)
            await page.keyboard.press("Enter")
            return {"ok": True, "method": "ui-type", "url": page.url}
        except Exception as e:
            return {"ok": False, "error": f"界面发送失败: {e}"}

    async def try_ws_protocol_send(
        self, page: Page, payload_str: str
    ) -> Dict[str, Any]:
        await self.inject_ws_trackers(page)
        last_result: Dict[str, Any] = {"ok": False, "error": "未找到可用 WebSocket"}
        for frame in page.frames:
            try:
                result = await frame.evaluate(WS_SEND_JS, payload_str)
                if result and result.get("ok"):
                    return result
                last_result = result or last_result
            except Exception as e:
                last_result = {"ok": False, "error": str(e)}
        return last_result

    async def ensure_chat_page(self, page: Page, conv_id: str) -> bool:
        """打开对应会话页；打不开就返回 False，调用方不得继续往输入框打字。"""
        peer = _peer_hex(conv_id)
        if not peer:
            return False
        if f"/chat/{peer}" in (page.url or ""):
            return True
        try:
            await page.goto(
                f"https://www.xiaohongshu.com/chat/{peer}",
                wait_until="domcontentloaded",
                timeout=25000,
            )
            await self.inject_ws_trackers(page)
            await asyncio.sleep(0.5)
        except Exception:
            return False
        return f"/chat/{peer}" in (page.url or "")

    async def ensure_douyin_page(self, page: Page, account_id: str = "") -> Page:
        """确保在抖音域：优先已有 douyin 标签；否则跳到 www.douyin.com。"""
        found = self.find_target_page(PLATFORM_DOUYIN, account_id)
        if found is not None:
            page = found
        url = page.url or ""
        if "douyin.com" in url and "about:blank" not in url:
            await self.inject_ws_trackers(page)
            return page
        try:
            await page.goto(
                "https://www.douyin.com/",
                wait_until="domcontentloaded",
                timeout=25000,
            )
            await self.inject_ws_trackers(page)
            await asyncio.sleep(1.0)
        except Exception:
            pass
        return page

    async def send_im_message(
        self, text: str, conv_id: Optional[str] = None
    ) -> Dict[str, Any]:
        contact = (
            self.app.contacts.get(conv_id)
            if conv_id
            else self.app.contacts.get_active()
        )
        store_key = (
            str(contact.get("key") or conv_id or "")
            if contact
            else (conv_id or "")
        )
        peer = _peer_hex(
            str(contact.get("conv_id") or "") if contact else (conv_id or "")
        )
        account_id = str((contact or {}).get("account_id") or "") or (
            self.app.accounts.active_id or ""
        )
        platform = (
            contact.get("platform", PLATFORM_XHS) if contact else PLATFORM_XHS
        )
        template_b64 = contact.get("template_b64") if contact else None
        template_text = contact.get("template_text") if contact else None

        if not account_id:
            return {"ok": False, "error": "无法确定用哪个账号发送"}

        page = self.find_target_page(platform, account_id, conv_id=peer)
        if page is None:
            page = self.find_target_page(None, account_id, conv_id=peer)
        if page is None:
            return {"ok": False, "error": "该账号的浏览器页面未就绪"}

        if platform == PLATFORM_DOUYIN:
            return await self._send_douyin(
                page, text, store_key or peer, account_id
            )

        if not peer:
            return {"ok": False, "error": "会话 ID 无效，无法确定发送对象"}

        opened = await self.ensure_chat_page(page, peer)
        on_peer = opened and f"/chat/{peer}" in (page.url or "")
        ui_result: Dict[str, Any] = {
            "ok": False,
            "error": "未能打开对方聊天页，已取消发送以免发错人",
        }
        if on_peer:
            ui_result = await self.try_ui_send(page, text)
            if ui_result.get("ok"):
                ui_result["conv_id"] = store_key or peer
                ui_result["account_id"] = account_id
                return ui_result

        browser_session = self.app.browser.session_for(account_id)
        if browser_session is not None:
            await browser_session.detect_identity(page)
        uid = self.app.accounts.xhs_uid(account_id)
        if not uid or not IM_HEX_ID.match(uid):
            ui_result["error"] = (
                ui_result.get("error")
                or "未能识别当前账号身份，已取消协议发送以免用错账号"
            )
            return ui_result
        if not on_peer:
            return ui_result

        try:
            payload = self.build_im_send_payload(
                text, peer, uid, template_b64, template_text
            )
            payload_str = json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            ui_result["error"] = str(e)
            ui_result["ws_error"] = str(e)
            return ui_result
        ws_result = await self.try_ws_protocol_send(page, payload_str)
        if ws_result.get("ok"):
            ws_result["payload"] = payload
            ws_result["page"] = page.url
            ws_result["method"] = "ws"
            ws_result["conv_id"] = store_key or peer
            ws_result["account_id"] = account_id
            return ws_result
        ws_result["payload"] = payload
        ws_result["page"] = page.url
        ws_result["ui_error"] = ui_result.get("error")
        ws_result["conv_id"] = store_key or peer
        ws_result["account_id"] = account_id
        return ws_result

    async def _send_douyin(
        self, page: Page, text: str, active_conv: str, account_id: str = ""
    ) -> Dict[str, Any]:
        """抖音：只用该账号、该会话的 imapi 发信，避免打到当前打开的其他人。"""
        page = await self.ensure_douyin_page(page, account_id)
        if "douyin.com" not in (page.url or ""):
            return {
                "ok": False,
                "error": "未找到抖音标签页，请先在该账号的 Edge 打开任意抖音页面并登录",
            }

        imapi = await self.app.douyin_send.send_via_imapi(
            page, text, active_conv, account_id=account_id
        )
        if imapi.get("ok"):
            imapi["account_id"] = account_id
            return imapi
        return {
            "ok": False,
            "error": imapi.get("error")
            or "未能按该会话协议发送。已取消界面发送，避免发到当前打开的其他人",
            "conv_id": active_conv,
            "account_id": account_id,
        }

    def schedule_send_im(
        self, text: str, conv_id: Optional[str] = None
    ) -> None:
        contact = (
            self.app.contacts.get(conv_id)
            if conv_id
            else self.app.contacts.get_active()
        )
        account_id = str((contact or {}).get("account_id") or "")
        if not account_id:
            self.app.bridge.post_send_result(
                {"ok": False, "error": "联系人未绑定账号，无法发送"}
            )
            return
        session = self.app.browser.session_for(account_id)
        if session is None or session.loop is None:
            self.app.bridge.post_send_result(
                {"ok": False, "error": "该账号的浏览器线程未启动"}
            )
            return
        asyncio.run_coroutine_threadsafe(
            self._send_im_and_notify(text, conv_id), session.loop
        )

    async def _send_im_and_notify(
        self, text: str, conv_id: Optional[str] = None
    ) -> None:
        try:
            result = await self.send_im_message(text, conv_id)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        self.app.bridge.post_send_result(result)

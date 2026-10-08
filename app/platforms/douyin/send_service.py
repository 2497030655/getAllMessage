# -*- coding: utf-8 -*-
"""抖音发信：imapi HTTP Protobuf（收消息后可直接回）。"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

from app.config import ROOT_DIR
from app.models.contact_store import split_contact_key
from app.platforms.douyin.pb_util import (
    SEND_URL,
    build_send_request,
    extract_send_fields,
    harvest_meta_from_bytes,
    parse_init_conversations,
    parse_send_response,
)

if TYPE_CHECKING:
    from playwright.async_api import Page
    from app.context import AppContext

logger = logging.getLogger("capture")

LEGACY_STATE_PATH = os.path.join(ROOT_DIR, "douyin_im_state.json")

IMAPI_SEND_JS = """
async ({ url, bodyB64, contentType }) => {
  try {
    const bin = Uint8Array.from(atob(bodyB64), c => c.charCodeAt(0));
    const headers = { 'content-type': contentType || 'application/x-protobuf' };
    const resp = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: bin
    });
    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let b64 = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      b64 += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return {
      ok: resp.ok,
      status: resp.status,
      bodyB64: btoa(b64),
      url: resp.url
    };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}
"""


class DouyinSendService:
    """采集 imapi 发信模板 + 会话 ticket，协议回复。"""

    def __init__(self, app: "AppContext", account_id: str = "") -> None:
        self.app = app
        self.account_id = account_id
        self.envelope_template: Optional[bytes] = None
        self.last_send_url: str = SEND_URL
        self.last_content_type: str = "application/x-protobuf"
        self.last_send_text: str = ""
        self._session_meta: Dict[str, Dict[str, Any]] = {}
        self._load_state()
        self.prune_empty_contacts()

    def _path(self) -> str:
        if self.account_id:
            return os.path.join(
                self.app.accounts.state_dir(self.account_id), "douyin_im_state.json"
            )
        return LEGACY_STATE_PATH

    @staticmethod
    def _normalize_conv_id(cid: str) -> str:
        parts = str(cid).split(":")
        if len(parts) == 4 and parts[0] == "0":
            a, b = sorted([parts[2], parts[3]])
            return f"0:{parts[1]}:{a}:{b}"
        return str(cid)

    def remember_session_meta(self, conversation_id: str, meta: Dict[str, Any]) -> None:
        """只缓存发信参数，不创建左侧联系人。"""
        cid = str(conversation_id or "").strip()
        if not cid:
            return
        key = self._normalize_conv_id(cid)
        slot = self._session_meta.setdefault(key, {"conversation_id": cid})
        if meta.get("ticket"):
            slot["ticket"] = str(meta["ticket"])
        if meta.get("conversation_short_id") is not None:
            try:
                slot["conversation_short_id"] = int(meta["conversation_short_id"])
            except Exception:
                pass
        if meta.get("conversation_type") is not None:
            try:
                slot["conversation_type"] = int(meta["conversation_type"])
            except Exception:
                pass
        # 若联系人已存在则同步字段
        conv_key = self.app.contacts.make_key(
            self.account_id, self.app.douyin_parser.douyin_conv_key(cid)
        )
        c = self.app.contacts.get(conv_key)
        if c:
            self.apply_meta_to_contact(conv_key, cid)

    def apply_meta_to_contact(self, conv_key: str, conversation_id: str = "") -> None:
        c = self.app.contacts.get(conv_key)
        if not c:
            return
        cid = conversation_id or str(c.get("douyin_conversation_id") or "")
        meta = self._session_meta.get(self._normalize_conv_id(cid)) or {}
        if not meta:
            # 再按现有 contact 的 id 找
            meta = self._session_meta.get(self._normalize_conv_id(str(c.get("douyin_conversation_id") or ""))) or {}
        if meta.get("ticket"):
            c["douyin_ticket"] = meta["ticket"]
        if meta.get("conversation_short_id") is not None:
            c["douyin_short_id"] = meta["conversation_short_id"]
        if meta.get("conversation_type") is not None:
            c["douyin_type"] = meta["conversation_type"]
        if cid:
            c["douyin_conversation_id"] = cid

    def prune_empty_contacts(self) -> None:
        """清掉无消息的抖音占位联系人（init 全量同步造成的）。"""
        drop = []
        for key, c in list(self.app.contacts._contacts.items()):
            if c.get("platform") != "douyin":
                continue
            if self.account_id and c.get("account_id") not in ("", self.account_id):
                continue
            msgs = c.get("messages") or []
            if msgs:
                continue
            if key == self.app.contacts._active:
                continue
            drop.append(key)
        for key in drop:
            self.app.contacts._contacts.pop(key, None)
        if drop:
            logger.info("pruned empty douyin contacts: %s", len(drop))

    def _load_state(self) -> None:
        return

    def _save_state(self) -> None:
        return

    def _merge_contact_meta(self, conversation_id: str, meta: Dict[str, Any]) -> str:
        """兼容旧调用：只记 meta；有联系人才回填。"""
        self.remember_session_meta(conversation_id, meta)
        return self.app.douyin_parser.douyin_conv_key(conversation_id)

    def remember_http_send(
        self,
        url: str,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if not body or "imapi.douyin.com" not in url:
            return
        if "message/send" not in url and "/send" not in url:
            return
        headers = headers or {}
        self.last_send_url = url.split("?")[0] if url else SEND_URL
        ct = headers.get("content-type") or headers.get("Content-Type")
        if ct:
            self.last_content_type = ct.split(";")[0].strip()
        self.envelope_template = body
        fields = extract_send_fields(body)
        if fields.get("text"):
            self.last_send_text = str(fields["text"])
        cid = fields.get("conversation_id")
        if cid:
            self._merge_contact_meta(str(cid), fields)
            logger.info(
                "captured douyin send template conv=%s text=%s",
                cid,
                fields.get("text", "")[:40],
            )
        else:
            logger.info("captured douyin send body len=%s (fields incomplete)", len(body))
        self._save_state()

    def ingest_binary(self, url: str, body: bytes, is_response: bool = False) -> None:
        """从 imapi 请求/响应或 WS 帧里收获会话元数据。"""
        if not body:
            return
        # 任意 imapi 请求体都可作为信封模板（cmd+body 结构一致）
        if (not is_response) and "imapi.douyin.com" in url and len(body) > 80:
            if not self.envelope_template or "message/send" in url:
                self.envelope_template = body
                if "message/send" in url:
                    self.last_send_url = url.split("?")[0]
                self._save_state()
                logger.info("saved douyin envelope from %s len=%s", url[:80], len(body))
        if "get_message_by_init" in url or (
            is_response and "imapi.douyin.com" in url and "get_message" in url
        ):
            if is_response:
                for item in parse_init_conversations(body):
                    cid = item.get("conversation_id")
                    if cid:
                        self._merge_contact_meta(str(cid), item)
                self._save_state()
            return
        if "message/send" in url and not is_response:
            self.remember_http_send(url, body)
            return
        meta = harvest_meta_from_bytes(body)
        cid = meta.get("conversation_id")
        if cid and (meta.get("ticket") or meta.get("conversation_short_id") is not None):
            self._merge_contact_meta(str(cid), meta)
            self._save_state()

    def ingest_ws_frame(self, ws_url: str, payload: Any) -> None:
        if "frontier-im" not in ws_url and "douyin.com" not in ws_url:
            return
        raw: Optional[bytes] = None
        if isinstance(payload, (bytes, bytearray)):
            raw = bytes(payload)
        elif isinstance(payload, str):
            s = payload.strip()
            if s.startswith("b64:"):
                s = s[4:]
            try:
                raw = base64.b64decode(s)
            except Exception:
                return
        if not raw:
            return
        meta = harvest_meta_from_bytes(raw)
        cid = meta.get("conversation_id")
        if cid:
            self._merge_contact_meta(str(cid), meta)
            # 收到消息也刷新磁盘，保证 ticket/short_id 可复用
            if meta.get("ticket") or meta.get("conversation_short_id") is not None:
                self._save_state()

    def contact_send_params(self, conv_key: str) -> Optional[Dict[str, Any]]:
        c = self.app.contacts.get(conv_key)
        if c:
            self.apply_meta_to_contact(conv_key, str(c.get("douyin_conversation_id") or ""))
        params = self._params_from_contact(c) if c else None
        if params:
            return params
        # 直接从 session meta 找
        if c and c.get("douyin_conversation_id"):
            meta = self._session_meta.get(
                self._normalize_conv_id(str(c["douyin_conversation_id"]))
            )
            if meta and meta.get("ticket") and meta.get("conversation_short_id") is not None:
                return {
                    "conversation_id": str(meta.get("conversation_id") or c["douyin_conversation_id"]),
                    "conversation_type": int(meta.get("conversation_type") or 1),
                    "conversation_short_id": int(meta["conversation_short_id"]),
                    "ticket": str(meta["ticket"]),
                }
        raw = split_contact_key(conv_key)[1]
        if raw.startswith("dy_"):
            parts = raw[3:].split("_")
            if len(parts) >= 4 and parts[0] == "0":
                cid = self._normalize_conv_id(":".join(parts))
                meta = self._session_meta.get(cid)
                if meta and meta.get("ticket") and meta.get("conversation_short_id") is not None:
                    return {
                        "conversation_id": str(meta.get("conversation_id") or cid),
                        "conversation_type": int(meta.get("conversation_type") or 1),
                        "conversation_short_id": int(meta["conversation_short_id"]),
                        "ticket": str(meta["ticket"]),
                    }
        return self._params_from_state_file(conv_key, c)

    def _params_from_contact(self, c: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not c:
            return None
        cid = c.get("douyin_conversation_id")
        ticket = c.get("douyin_ticket")
        short_id = c.get("douyin_short_id")
        if not cid or not ticket or short_id is None:
            return None
        return {
            "conversation_id": str(cid),
            "conversation_type": int(c.get("douyin_type") or 1),
            "conversation_short_id": int(short_id),
            "ticket": str(ticket),
        }

    def _params_from_state_file(
        self, conv_key: str, c: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        path = self._path()
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        want = ""
        if c and c.get("douyin_conversation_id"):
            want = self._normalize_conv_id(str(c["douyin_conversation_id"]))
        else:
            raw = split_contact_key(conv_key)[1]
            if raw.startswith("dy_"):
                parts = raw[3:].split("_")
                if len(parts) >= 4 and parts[0] == "0":
                    want = self._normalize_conv_id(":".join(parts))
        if not want:
            return None
        for item in data.get("conversations") or []:
            cid = str(item.get("conversation_id") or "")
            if not cid:
                continue
            if self._normalize_conv_id(cid) != want:
                continue
            if not item.get("ticket") or item.get("conversation_short_id") is None:
                continue
            return {
                "conversation_id": cid,
                "conversation_type": int(item.get("conversation_type") or 1),
                "conversation_short_id": int(item["conversation_short_id"]),
                "ticket": str(item["ticket"]),
            }
        return None

    async def send_via_imapi(
        self, page: "Page", text: str, conv_key: str
    ) -> Dict[str, Any]:
        params = self.contact_send_params(conv_key)
        if not params:
            logger.warning("douyin send missing ticket conv_key=%s", conv_key)
            return {
                "ok": False,
                "error": (
                    "缺少抖音会话 ticket/short_id。"
                    "请打开抖音页并进入私信列表同步一次，或对该会话手动发一条"
                ),
            }
        try:
            body = build_send_request(
                params["conversation_id"],
                params["conversation_type"],
                params["conversation_short_id"],
                params["ticket"],
                text,
                client_msg_id=str(uuid.uuid4()),
                stime_ms=int(time.time() * 1000),
                envelope_template=self.envelope_template,
            )
        except Exception as e:
            logger.exception("build_send_request failed")
            return {"ok": False, "error": f"构造发信包失败: {e}"}

        url = self.last_send_url or SEND_URL
        headers = {
            "content-type": self.last_content_type or "application/x-protobuf",
            "referer": "https://www.douyin.com/",
            "origin": "https://www.douyin.com",
            "accept": "*/*",
        }
        logger.info(
            "douyin imapi send conv=%s short=%s url=%s body=%s",
            params["conversation_id"],
            params["conversation_short_id"],
            url,
            len(body),
        )

        # 1) 优先用浏览器 Cookie 上下文直发（比页面 fetch 更稳）
        try:
            api = page.context.request
            resp = await api.post(url, data=body, headers=headers, timeout=20000)
            status = resp.status
            resp_raw = await resp.body()
            parsed = parse_send_response(resp_raw)
            logger.info(
                "douyin imapi http=%s msg=%s code=%s",
                status,
                parsed.get("msg"),
                parsed.get("error_code"),
            )
            if parsed.get("ok") or (status == 200 and parsed.get("msg") == "OK"):
                self.last_send_text = text
                self._save_state()
                return {
                    "ok": True,
                    "method": "imapi",
                    "status": status,
                    "conv_id": conv_key,
                    "page": page.url,
                }
            http_err = (
                f"imapi 返回: {parsed.get('msg')} "
                f"(code={parsed.get('error_code')}, http={status})"
            )
        except Exception as e:
            logger.exception("douyin context.request.post failed")
            http_err = f"浏览器上下文发信失败: {e}"

        # 2) 回退：在抖音页内 fetch（同源 Cookie）
        body_b64 = base64.b64encode(body).decode("ascii")
        last: Dict[str, Any] = {"ok": False, "error": http_err}
        for frame in page.frames:
            try:
                result = await frame.evaluate(
                    IMAPI_SEND_JS,
                    {
                        "url": url,
                        "bodyB64": body_b64,
                        "contentType": headers["content-type"],
                    },
                )
            except Exception as e:
                last = {"ok": False, "error": f"{http_err}; fetch: {e}"}
                continue
            if not result:
                continue
            if result.get("error") and not result.get("bodyB64"):
                last = {"ok": False, "error": f"{http_err}; fetch: {result.get('error')}"}
                continue
            resp_b64 = result.get("bodyB64") or ""
            try:
                resp_raw = base64.b64decode(resp_b64) if resp_b64 else b""
            except Exception:
                resp_raw = b""
            parsed = parse_send_response(resp_raw)
            if parsed.get("ok") or (
                result.get("status") == 200 and parsed.get("msg") == "OK"
            ):
                self.last_send_text = text
                self._save_state()
                return {
                    "ok": True,
                    "method": "imapi-fetch",
                    "status": result.get("status"),
                    "conv_id": conv_key,
                    "page": page.url,
                }
            last = {
                "ok": False,
                "error": (
                    f"imapi 返回: {parsed.get('msg')} "
                    f"(code={parsed.get('error_code')}, http={result.get('status')})"
                ),
                "status": result.get("status"),
            }
        return last


class DouyinSendHub:
    """按账号隔离的抖音发信服务。"""

    def __init__(self, app: "AppContext") -> None:
        self.app = app
        self._by: Dict[str, DouyinSendService] = {}
        for acc in app.accounts.list():
            self.for_account(acc.id)

    def for_account(self, account_id: str = "") -> DouyinSendService:
        aid = account_id or self.app.accounts.active_id or "default"
        if aid not in self._by:
            self._by[aid] = DouyinSendService(self.app, aid)
        return self._by[aid]

    def ingest_binary(
        self,
        url: str,
        body: bytes,
        is_response: bool = False,
        account_id: str = "",
    ) -> None:
        self.for_account(account_id).ingest_binary(url, body, is_response)

    def ingest_ws_frame(
        self, ws_url: str, payload: Any, account_id: str = ""
    ) -> None:
        self.for_account(account_id).ingest_ws_frame(ws_url, payload)

    def remember_session_meta(
        self,
        conversation_id: str,
        meta: Dict[str, Any],
        account_id: str = "",
    ) -> None:
        self.for_account(account_id).remember_session_meta(conversation_id, meta)

    def apply_meta_to_contact(
        self, conv_key: str, conversation_id: str = ""
    ) -> None:
        contact = self.app.contacts.get(conv_key)
        aid = str((contact or {}).get("account_id") or "")
        self.for_account(aid).apply_meta_to_contact(conv_key, conversation_id)

    def contact_send_params(self, conv_key: str) -> Optional[Dict[str, Any]]:
        contact = self.app.contacts.get(conv_key)
        aid = str((contact or {}).get("account_id") or "")
        return self.for_account(aid).contact_send_params(conv_key)

    async def send_via_imapi(
        self, page: "Page", text: str, conv_key: str, account_id: str = ""
    ) -> Dict[str, Any]:
        if not account_id:
            contact = self.app.contacts.get(conv_key)
            account_id = str((contact or {}).get("account_id") or "")
        return await self.for_account(account_id).send_via_imapi(page, text, conv_key)

    def drop_account(self, account_id: str) -> None:
        self._by.pop(account_id, None)


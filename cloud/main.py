# -*- coding: utf-8 -*-
"""FastAPI 云端入口：PC 抓包接入、解析 worker、移动端 API。"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cloud.config import API_TOKEN, HOST, PARSE_QUEUE_SIZE, PARSE_WORKERS, PORT
from cloud.hub import ConnectionHub
from cloud.processor import CaptureProcessor
from cloud.store import CloudStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cloud")

app = FastAPI(title="getAllMessage Cloud", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = CloudStore()
hub = ConnectionHub()
processor = CaptureProcessor(store)
parse_queue: asyncio.Queue = asyncio.Queue(maxsize=PARSE_QUEUE_SIZE)
pending_sends: Dict[str, Dict[str, Any]] = {}


def _auth(token: Optional[str]) -> None:
    if API_TOKEN and token != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


async def _ingest_parsed_event(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把 PC 已解析事件写入 store，并返回移动端推送体。"""
    text = str(ev.get("text") or "").strip()
    nick = str(ev.get("nickname") or "").strip()
    if not text or (nick and text == nick):
        return None
    account_id = str(ev.get("account_id") or "default")
    conv_key = str(ev.get("conv_key") or "").strip()
    conv_id = str(ev.get("conv_id") or "").strip()
    platform = str(ev.get("platform") or "xhs")
    if not conv_key:
        if not conv_id:
            return None
        conv_key = f"{account_id}::{conv_id}"
    contact = {
        "key": conv_key,
        "conv_id": conv_id or conv_key.split("::")[-1],
        "account_id": account_id,
        "platform": platform,
        "nickname": nick,
        "unread": 0,
        "messages": [],
    }
    existing = await store.get_conversation(conv_key)
    if existing:
        contact = dict(existing)
        if nick and not contact.get("nickname"):
            contact["nickname"] = nick
    await store.upsert_contact(contact)
    msg_id = await store.append_message(
        conv_key,
        {
            "message_id": uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{conv_key}:{ev.get('direction')}:{text}:{ev.get('time')}",
            ).hex,
            "direction": ev.get("direction") or "down",
            "text": text,
            "time": ev.get("time") or "",
        },
    )
    if msg_id is None:
        return None
    return {
        "type": "im_message",
        "message_id": msg_id,
        "conv_key": conv_key,
        "account_id": account_id,
        "platform": platform,
        "conv_id": contact.get("conv_id"),
        "nickname": contact.get("nickname") or nick,
        "direction": ev.get("direction") or "down",
        "text": text,
        "time": ev.get("time") or "",
    }


class SendRequest(BaseModel):
    account_id: str = "default"
    conv_key: str = ""
    conv_id: str = ""
    platform: str = "xhs"
    text: str = Field(min_length=1)


async def parse_worker(worker_id: int) -> None:
    logger.info("parse worker %s started", worker_id)
    while True:
        record = await parse_queue.get()
        try:
            messages = await processor.process(record)
            for msg in messages:
                await hub.broadcast_mobile(msg)
        except Exception:
            logger.exception("parse worker %s failed", worker_id)
        finally:
            parse_queue.task_done()


@app.on_event("startup")
async def startup() -> None:
    for i in range(PARSE_WORKERS):
        asyncio.create_task(parse_worker(i))
    logger.info(
        "cloud started workers=%s queue=%s listen=%s:%s",
        PARSE_WORKERS,
        PARSE_QUEUE_SIZE,
        HOST,
        PORT,
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    agents = await hub.agent_ids_online()
    return {
        "ok": True,
        "agents_online": len(agents),
        "mobile_queue": parse_queue.qsize(),
    }


@app.get("/api/conversations")
async def list_conversations(
    account_id: str = "",
    platform: str = "",
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _auth(authorization)
    items = await store.list_conversations(account_id, platform)
    return {"items": items}


@app.get("/api/conversations/{conv_key}/messages")
async def get_messages(
    conv_key: str,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _auth(authorization)
    conv = await store.get_conversation(conv_key)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"conversation": conv, "messages": conv.get("messages") or []}


@app.post("/api/messages/send")
async def send_message(
    body: SendRequest,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _auth(authorization)
    conv_key = body.conv_key
    if not conv_key and body.conv_id:
        conv_key = await store.resolve_conv_key(body.account_id, body.conv_id)
    if not conv_key:
        raise HTTPException(status_code=400, detail="conv_key or conv_id required")

    online = await hub.agent_ids_online()
    agent_id = await store.agent_for_account(body.account_id)
    if agent_id not in online:
        agent_id = online[0] if online else ""
    if not agent_id:
        raise HTTPException(status_code=503, detail="no pc agent online")

    task_id = uuid.uuid4().hex
    payload = {
        "type": "send_message",
        "task_id": task_id,
        "account_id": body.account_id,
        "platform": body.platform,
        "conv_key": conv_key,
        "conv_id": body.conv_id,
        "text": body.text,
    }
    pending_sends[task_id] = {"status": "pending", "payload": payload}
    ok = await hub.send_to_agent(agent_id, payload)
    if not ok:
        pending_sends.pop(task_id, None)
        raise HTTPException(status_code=503, detail="failed to dispatch to PC agent")
    return {"ok": True, "task_id": task_id, "agent_id": agent_id}


@app.get("/api/messages/send/{task_id}")
async def send_status(
    task_id: str,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    _auth(authorization)
    item = pending_sends.get(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="task not found")
    return item


@app.websocket("/ws/agent")
async def ws_agent(ws: WebSocket) -> None:
    await ws.accept()
    agent_id = ws.query_params.get("agent_id") or uuid.uuid4().hex[:10]
    token = ws.query_params.get("token") or ws.headers.get("authorization", "")
    if API_TOKEN and token != API_TOKEN:
        await ws.close(code=4401)
        return

    await hub.register_agent(agent_id, ws)
    await store.register_agent(agent_id, {"agent_id": agent_id})
    # 立刻绑定 default，避免尚未上报 agent_meta 时发信判定离线
    await store.set_account_meta("default", agent_id=agent_id)
    await ws.send_text(
        json.dumps({"type": "hello_ack", "agent_id": agent_id}, ensure_ascii=False)
    )

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "agent_meta":
                account_id = str(msg.get("account_id") or "default")
                await store.set_account_meta(
                    account_id,
                    xhs_uid=str(msg.get("xhs_uid") or ""),
                    douyin_uid=str(msg.get("douyin_uid") or ""),
                    agent_id=agent_id,
                )
                await processor.sync_meta(account_id)
            elif mtype == "capture_record":
                msg.setdefault("account_id", msg.get("account_id") or "default")
                try:
                    parse_queue.put_nowait(msg)
                except asyncio.QueueFull:
                    logger.warning("parse queue full, dropping record")
            elif mtype == "im_events":
                # PC 本地解析结果：直接入库并推送（跳过云端二次解析）
                for ev in msg.get("events") or []:
                    try:
                        pushed = await _ingest_parsed_event(ev)
                        if pushed:
                            await hub.broadcast_mobile(pushed)
                    except Exception:
                        logger.exception("ingest im_events failed")
            elif mtype == "send_result":
                task_id = str(msg.get("task_id") or "")
                if task_id in pending_sends:
                    pending_sends[task_id] = {
                        "status": "done" if msg.get("ok") else "failed",
                        "result": msg,
                    }
                await hub.broadcast_mobile(msg)
            elif mtype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister_agent(agent_id, ws)
        # 同 agent_id 重连时，旧连接 finally 不能把新连接标成离线
        if agent_id not in await hub.agent_ids_online():
            await store.unregister_agent(agent_id)


@app.websocket("/ws/mobile")
async def ws_mobile(ws: WebSocket) -> None:
    token = ws.query_params.get("token") or ws.headers.get("authorization", "")
    if API_TOKEN and token != API_TOKEN:
        await ws.close(code=4401)
        return
    await ws.accept()
    await hub.register_mobile(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister_mobile(ws)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "cloud.main:app",
        host=HOST,
        port=PORT,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""WebSocket 连接管理与移动端广播。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger("cloud.hub")


class ConnectionHub:
    """管理 PC Agent 与移动端 WebSocket 连接。"""

    def __init__(self) -> None:
        self._agents: Dict[str, WebSocket] = {}
        self._mobiles: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register_agent(self, agent_id: str, ws: WebSocket) -> None:
        async with self._lock:
            old = self._agents.get(agent_id)
            if old is not None and old is not ws:
                try:
                    await old.close()
                except Exception:
                    pass
            self._agents[agent_id] = ws
        logger.info("agent connected: %s", agent_id)

    async def unregister_agent(self, agent_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if self._agents.get(agent_id) is ws:
                del self._agents[agent_id]
        logger.info("agent disconnected: %s", agent_id)

    async def register_mobile(self, ws: WebSocket) -> None:
        async with self._lock:
            self._mobiles.add(ws)
        logger.info("mobile connected, total=%s", len(self._mobiles))

    async def unregister_mobile(self, ws: WebSocket) -> None:
        async with self._lock:
            self._mobiles.discard(ws)

    async def send_to_agent(self, agent_id: str, payload: Dict[str, Any]) -> bool:
        async with self._lock:
            ws = self._agents.get(agent_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception:
            logger.exception("send_to_agent failed %s", agent_id)
            return False

    async def broadcast_mobile(self, payload: Dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        async with self._lock:
            targets = list(self._mobiles)
        dead: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._mobiles.discard(ws)

    async def agent_ids_online(self) -> List[str]:
        async with self._lock:
            return list(self._agents.keys())

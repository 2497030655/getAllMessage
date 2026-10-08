# -*- coding: utf-8 -*-
"""领域模型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class NetworkRecord:
    """浏览器抓到的一条网络记录（以 WebSocket 为主）。"""

    id: str
    time: str
    method: str  # WS↑ / WS↓
    url: str
    kind: str = "WebSocket"
    request_body: Optional[str] = None
    response_body: Optional[str] = None
    account_id: str = "default"

    def to_pipeline_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "method": self.method,
            "url": self.url,
            "kind": self.kind,
            "requestBody": self.request_body,
            "responseBody": self.response_body,
            "account_id": self.account_id,
        }


@dataclass
class ImMessage:
    """解析后的小红书私信。"""

    text: str
    direction: str  # up=自己发出 / down=对方发来
    conv_id: str
    nickname: str = ""
    time: str = ""
    platform: str = "xhs"
    msg_kind: str = "text"
    account_id: str = "default"
    url: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_event(cls, event: Dict[str, Any]) -> "ImMessage":
        return cls(
            text=str(event.get("text") or ""),
            direction=str(event.get("direction") or "down"),
            conv_id=str(event.get("conv_id") or ""),
            nickname=str(event.get("nickname") or ""),
            time=str(event.get("time") or ""),
            platform=str(event.get("platform") or "xhs"),
            msg_kind=str(event.get("msg_kind") or "text"),
            account_id=str(event.get("account_id") or "default"),
            url=str(event.get("url") or ""),
            raw=dict(event),
        )

    def to_dict(self) -> Dict[str, Any]:
        """控制台打印用：优先输出解析后的原始事件字段。"""
        if self.raw:
            return dict(self.raw)
        data = asdict(self)
        data.pop("raw", None)
        return data

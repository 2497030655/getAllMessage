# -*- coding: utf-8 -*-
"""抽象接口（依赖倒置）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List

from xhs_im_service.models import ImMessage, NetworkRecord

RecordHandler = Callable[[NetworkRecord], None]
MessageHandler = Callable[[ImMessage], None]


class IMessageSink(ABC):
    """消息输出目标。"""

    @abstractmethod
    def on_message(self, message: ImMessage) -> None:
        raise NotImplementedError


class IMessageParser(ABC):
    """网络记录 → 结构化私信。"""

    @abstractmethod
    def parse(self, record: NetworkRecord) -> List[ImMessage]:
        raise NotImplementedError

    @abstractmethod
    def set_my_uid(self, uid: str) -> None:
        raise NotImplementedError


class INetworkCapture(ABC):
    """浏览器网络抓取。"""

    @abstractmethod
    def set_record_handler(self, handler: RecordHandler) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_my_uid(self, uid: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_my_uid(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def run(self) -> None:
        """启动浏览器并阻塞直到结束。"""
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

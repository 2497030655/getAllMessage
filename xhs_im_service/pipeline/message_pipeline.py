# -*- coding: utf-8 -*-
"""抓包 → 解析 → 输出 流水线。"""
from __future__ import annotations

import logging
from typing import List

from xhs_im_service.interfaces import (
    IMessageParser,
    IMessageSink,
    INetworkCapture,
)
from xhs_im_service.models import ImMessage, NetworkRecord

logger = logging.getLogger("xhs_im_service.pipeline")


class MessagePipeline:
    """
    协调 Capture / Parser / Sink。

    职责单一：收到 NetworkRecord 后解析，再交给一个或多个 Sink。
    """

    def __init__(
        self,
        capture: INetworkCapture,
        parser: IMessageParser,
        sinks: List[IMessageSink],
    ) -> None:
        self._capture = capture
        self._parser = parser
        self._sinks = list(sinks)
        self._capture.set_record_handler(self.on_record)

    def on_record(self, record: NetworkRecord) -> None:
        try:
            uid = self._capture.get_my_uid()
            if uid:
                self._parser.set_my_uid(uid)
            messages = self._parser.parse(record)
            for msg in messages:
                self._dispatch(msg)
        except Exception:
            logger.exception("pipeline on_record failed method=%s", record.method)

    def _dispatch(self, message: ImMessage) -> None:
        for sink in self._sinks:
            try:
                sink.on_message(message)
            except Exception:
                logger.exception("sink failed: %s", type(sink).__name__)

    async def run(self) -> None:
        await self._capture.run()

    async def stop(self) -> None:
        await self._capture.stop()

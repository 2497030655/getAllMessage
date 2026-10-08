# -*- coding: utf-8 -*-
"""服务门面：组装 Capture / Parser / Sink。"""
from __future__ import annotations

import logging
from typing import List, Optional

from xhs_im_service.browser.capture_session import XhsBrowserCapture
from xhs_im_service.config import ServiceConfig
from xhs_im_service.interfaces import IMessageSink, INetworkCapture, IMessageParser
from xhs_im_service.parsing.message_parser import XhsMessageParser
from xhs_im_service.pipeline.message_pipeline import MessagePipeline
from xhs_im_service.sinks.console_sink import ConsoleMessageSink

logger = logging.getLogger("xhs_im_service")


class XhsImCaptureService:
    """
    小红书私信抓取与解析服务（Facade）。

    面向对象组装：
    - INetworkCapture  → XhsBrowserCapture
    - IMessageParser   → XhsMessageParser
    - IMessageSink     → ConsoleMessageSink（可替换）
    - MessagePipeline  → 串联上述组件
    """

    def __init__(
        self,
        config: Optional[ServiceConfig] = None,
        capture: Optional[INetworkCapture] = None,
        parser: Optional[IMessageParser] = None,
        sinks: Optional[List[IMessageSink]] = None,
    ) -> None:
        self.config = config or ServiceConfig.from_env()
        self._capture = capture or XhsBrowserCapture(self.config)
        self._parser = parser or XhsMessageParser(account_id=self.config.account_id)
        if self.config.my_uid:
            self._capture.set_my_uid(self.config.my_uid)
            self._parser.set_my_uid(self.config.my_uid)
        self._sinks = sinks or [ConsoleMessageSink(as_json=self.config.print_json)]
        self._pipeline = MessagePipeline(self._capture, self._parser, self._sinks)

    async def run(self) -> None:
        logger.info("XhsImCaptureService starting")
        await self._pipeline.run()

    async def stop(self) -> None:
        await self._pipeline.stop()

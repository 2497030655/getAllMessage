# -*- coding: utf-8 -*-
"""Qt 信号总线：浏览器线程 ↔ UI 线程（线程安全）。"""

from __future__ import annotations

import logging
import queue
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("capture")


class EdgeBridge(QObject):
    """跨线程事件桥。

    后台线程不要直接依赖 slot 是否排队成功：统一走 queue，
    由主线程 QTimer 取出后再发 Signal，保证 UI 一定能收到。
    """

    record_added = Signal(object)
    url_changed = Signal(object)
    send_result = Signal(object)
    contact_updated = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._pump: Optional[QTimer] = None

    def start_ui_pump(self) -> None:
        """在主线程（QApplication 已创建后）启动泵。"""
        if self._pump is not None:
            return
        self._pump = QTimer()
        self._pump.setInterval(50)
        self._pump.timeout.connect(self._drain_queue)
        self._pump.start()

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "record":
                    self.record_added.emit(payload)
                elif kind == "url":
                    self.url_changed.emit(payload)
                elif kind == "send":
                    self.send_result.emit(payload)
                elif kind == "contact":
                    self.contact_updated.emit(str(payload))
            except Exception:
                logger.exception("bridge drain failed: %s", kind)

    def post_record(self, entry: dict) -> None:
        self._queue.put(("record", entry))

    def post_url(self, url: str, account_id: str = "") -> None:
        self._queue.put(("url", {"url": url, "account_id": account_id}))

    def post_send_result(self, result: dict) -> None:
        self._queue.put(("send", result))

    def post_contact(self, conv_id: str) -> None:
        self._queue.put(("contact", conv_id))

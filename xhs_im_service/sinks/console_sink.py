# -*- coding: utf-8 -*-
"""控制台输出。"""
from __future__ import annotations

import json
import sys

from xhs_im_service.interfaces import IMessageSink
from xhs_im_service.models import ImMessage


class ConsoleMessageSink(IMessageSink):
    """把解析结果打印到标准输出。"""

    def __init__(self, as_json: bool = True) -> None:
        self._as_json = as_json

    def on_message(self, message: ImMessage) -> None:
        data = message.to_dict()
        if self._as_json:
            line = json.dumps(data, ensure_ascii=False)
        else:
            line = (
                f"[{data.get('time', '')}] "
                f"{data.get('direction', '')} "
                f"{data.get('nickname') or data.get('conv_id', '')}: "
                f"{data.get('text', '')}"
            )
        print(line, flush=True)
        sys.stdout.flush()

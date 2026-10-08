# -*- coding: utf-8 -*-
"""应用上下文：集中管理单例依赖（面向对象组合根）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.bridge import EdgeBridge

if TYPE_CHECKING:
    from app.browser.manager import BrowserManager
    from app.models.account_store import AccountStore
    from app.models.contact_store import ContactStore
    from app.platforms.douyin.parser import DouyinImParser
    from app.platforms.douyin.send_service import DouyinSendHub
    from app.platforms.xhs.dom_sync import XhsDomSyncService
    from app.platforms.xhs.parser import XhsImParser
    from app.services.cloud_agent import CloudAgent
    from app.services.message_sender import MessageSender
    from app.services.record_pipeline import RecordPipeline


class AppContext:
    """组合根：各服务通过本对象互相访问，避免散落全局变量。"""

    _instance: Optional["AppContext"] = None

    def __init__(self) -> None:
        self.bridge = EdgeBridge()
        self.accounts: AccountStore
        self.contacts: ContactStore
        self.browser: BrowserManager
        self.xhs_parser: XhsImParser
        self.douyin_parser: DouyinImParser
        self.douyin_send: DouyinSendHub
        self.pipeline: RecordPipeline
        self.sender: MessageSender
        self.dom_sync: XhsDomSyncService
        self.cloud_agent: CloudAgent
        AppContext._instance = self

    @classmethod
    def get(cls) -> "AppContext":
        if cls._instance is None:
            raise RuntimeError("AppContext 尚未初始化，请先调用 create_app()")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None


def get_app() -> AppContext:
    return AppContext.get()

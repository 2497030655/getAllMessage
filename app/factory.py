# -*- coding: utf-8 -*-
"""应用组装（组合根）。"""
from __future__ import annotations

from app.browser.manager import BrowserManager
from app.context import AppContext
from app.models.account_store import AccountStore
from app.models.contact_store import ContactStore
from app.platforms.douyin.parser import DouyinImParser
from app.platforms.douyin.send_service import DouyinSendHub
from app.platforms.xhs.dom_sync import XhsDomSyncService
from app.platforms.xhs.parser import XhsImParser
from app.services.cloud_agent import CloudAgent
from app.services.message_sender import MessageSender
from app.services.record_pipeline import RecordPipeline


def create_app() -> AppContext:
    """创建并装配全部服务。"""
    AppContext.reset()
    app = AppContext()
    app.accounts = AccountStore()
    app.contacts = ContactStore(app)
    app.browser = BrowserManager(app)
    app.xhs_parser = XhsImParser(app)
    app.douyin_parser = DouyinImParser(app)
    app.douyin_send = DouyinSendHub(app)
    app.pipeline = RecordPipeline(app)
    app.sender = MessageSender(app)
    app.dom_sync = XhsDomSyncService(app)
    app.cloud_agent = CloudAgent(app)
    app.cloud_agent.start()
    return app

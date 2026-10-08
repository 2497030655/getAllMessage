# -*- coding: utf-8 -*-
"""服务配置。"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import tempfile


@dataclass
class ServiceConfig:
    """小红书 IM 抓取服务配置。"""

    chat_url: str = "https://www.xiaohongshu.com/chat"
    edge_channel: str = "msedge"
    profile_dir: str = field(
        default_factory=lambda: os.path.join(
            tempfile.gettempdir(), "xhs_im_service_profile"
        )
    )
    # 仅关注小红书推送相关 WebSocket（空则不过滤）
    ws_url_keywords: tuple = ("apppush", "xiaohongshu", "xhs")
    headless: bool = False
    window_width: int = 1280
    window_height: int = 900
    # 手动填写自己的小红书 uid（24 位 hex）；空则尝试页面自动探测
    my_uid: str = ""
    account_id: str = "default"
    # 解析结果是否打印原始 dict（JSON）
    print_json: bool = True

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        cfg = cls()
        cfg.chat_url = os.environ.get("XHS_CHAT_URL", cfg.chat_url)
        cfg.my_uid = os.environ.get("XHS_MY_UID", cfg.my_uid)
        cfg.profile_dir = os.environ.get("XHS_PROFILE_DIR", cfg.profile_dir)
        cfg.headless = os.environ.get("XHS_HEADLESS", "").strip() in (
            "1",
            "true",
            "True",
        )
        return cfg

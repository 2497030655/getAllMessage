# -*- coding: utf-8 -*-
"""UI 小工具。"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from app.utils.text import avatar_initial, format_list_time

__all__ = ["avatar_initial", "format_list_time", "style_clear_button"]


def style_clear_button(btn: QPushButton) -> None:
    btn.setMinimumWidth(96)
    btn.setMinimumHeight(32)
    btn.setStyleSheet(
        "QPushButton{background:#dc2626;color:#fff;border:none;border-radius:4px;"
        "padding:6px 14px;font-size:13px;font-weight:600;}"
        "QPushButton:hover{background:#b91c1c;}"
    )

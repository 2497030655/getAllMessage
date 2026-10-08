# -*- coding: utf-8 -*-
"""PC 监听端状态面板（无聊天 UI）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AGENT_ID, CLOUD_WS_URL, MAX_ACCOUNTS
from app.context import get_app


class AgentPanel(QMainWindow):
    """显示云端连接、账号数量；不含聊天功能。"""

    WIDTH = 320

    def __init__(self, x: int, y: int, height: int) -> None:
        super().__init__()
        self.setWindowTitle("监听 Agent")
        self.setGeometry(x, y, self.WIDTH, height)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("PC 监听端")
        title.setStyleSheet("font-size:16px;font-weight:700;")

        self.cloud_label = QLabel()
        self.agent_label = QLabel(f"Agent ID: {AGENT_ID}")
        self.account_label = QLabel()
        self.hint = QLabel(
            "请在右侧 Edge 登录小红书/抖音。\n"
            "消息由云端解析并推送到安卓端。"
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#64748b;font-size:12px;")

        add_btn = QPushButton("+ 多开账号")
        add_btn.clicked.connect(self._add_account)
        add_btn.setStyleSheet(
            "QPushButton{background:#111827;color:#fff;border:none;"
            "border-radius:6px;padding:8px;font-weight:600;}"
            "QPushButton:hover{background:#1f2937;}"
        )

        layout.addWidget(title)
        layout.addWidget(self.cloud_label)
        layout.addWidget(self.agent_label)
        layout.addWidget(self.account_label)
        layout.addWidget(self.hint)
        layout.addStretch(1)
        layout.addWidget(add_btn)

        app = get_app()
        app.bridge.url_changed.connect(self._on_url)
        self._refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _refresh(self) -> None:
        app = get_app()
        cloud = app.cloud_agent
        status = "已连接" if cloud.connected else "未连接"
        color = "#16a34a" if cloud.connected else "#dc2626"
        self.cloud_label.setText(
            f'云端: <span style="color:{color};font-weight:600;">{status}</span>'
            f"<br><span style='color:#64748b;font-size:11px;'>{CLOUD_WS_URL or '未配置'}</span>"
        )
        self.cloud_label.setTextFormat(Qt.TextFormat.RichText)
        n = app.accounts.count()
        self.account_label.setText(f"账号数: {n} / {MAX_ACCOUNTS}")

    def _on_url(self, payload) -> None:
        if isinstance(payload, dict):
            url = str(payload.get("url") or "")
            if url.startswith("cloud:"):
                self._refresh()

    def _add_account(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        app = get_app()
        if app.accounts.count() >= MAX_ACCOUNTS:
            QMessageBox.warning(self, "提示", f"最多 {MAX_ACCOUNTS} 个账号")
            return
        name, ok = QInputDialog.getText(
            self, "新账号", "备注名:", text=f"账号{app.accounts.count() + 1}"
        )
        if not ok or not name.strip():
            return
        try:
            acc = app.accounts.add(name.strip())
            idx = app.accounts.count() - 1
            x, y, w, h = app.browser.cascade_box(idx)
            app.browser.start_one(acc, index=idx)
            self._refresh()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

# -*- coding: utf-8 -*-
"""接口监听面板。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    DISPLAY_LIMIT,
    FILTER_INTERVAL_MS,
    MAX_RECORDS,
    RENDER_INTERVAL_MS,
    ROOT_DIR,
)
from app.context import get_app
from app.ui.helpers import style_clear_button

class ApiPanel(QMainWindow):
    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        super().__init__()
        self.records: List[Dict[str, Any]] = []
        self.type_filter = "all"
        self.setWindowTitle("接口监听")
        self.setGeometry(x, y, width, height)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._render_list)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_INTERVAL_MS)
        self._filter_timer.timeout.connect(self._render_list)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel("接口监听")
        header.setStyleSheet("font-weight:600;font-size:14px;padding:2px 0;")

        action_row = QHBoxLayout()
        self.count_label = QLabel("0 条")
        self.count_label.setStyleSheet("color:#64748b;font-size:12px;")
        self.btn_clear = QPushButton("清除接口")
        style_clear_button(self.btn_clear)
        self.btn_clear.clicked.connect(self._clear)
        action_row.addWidget(self.count_label)
        action_row.addStretch(1)
        action_row.addWidget(self.btn_clear)

        type_row = QHBoxLayout()
        self.btn_type_all = QPushButton("全部")
        self.btn_type_http = QPushButton("HTTP")
        self.btn_type_ws = QPushButton("WebSocket")
        for btn in (self.btn_type_all, self.btn_type_http, self.btn_type_ws):
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton{padding:4px 10px;border:1px solid #dadce0;border-radius:4px;}"
                "QPushButton:checked{background:#1a73e8;color:#fff;border-color:#1a73e8;}"
            )
        self.btn_type_all.setChecked(True)
        self.btn_type_all.clicked.connect(lambda: self._set_type_filter("all"))
        self.btn_type_http.clicked.connect(lambda: self._set_type_filter("http"))
        self.btn_type_ws.clicked.connect(lambda: self._set_type_filter("ws"))

        type_row.addWidget(self.btn_type_all)
        type_row.addWidget(self.btn_type_http)
        type_row.addWidget(self.btn_type_ws)
        type_row.addStretch()

        self.api_filter = QLineEdit()
        self.api_filter.setPlaceholderText("过滤聊天内容，如：在的、你好…")
        self.api_filter.textChanged.connect(self._schedule_filter_render)

        self.api_list = QListWidget()
        self.api_list.currentRowChanged.connect(self._show_detail)

        self.api_detail = QTextEdit()
        self.api_detail.setReadOnly(True)
        self.api_detail.setStyleSheet("font-family:Consolas,monospace;font-size:12px;")

        btn_row = QHBoxLayout()
        btn_export = QPushButton("导出 JSON")
        btn_clear_bottom = QPushButton("清除接口")
        style_clear_button(btn_clear_bottom)
        btn_clear_bottom.clicked.connect(self._clear)
        btn_export.clicked.connect(self._export)
        btn_row.addWidget(btn_export)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_clear_bottom)

        layout.addWidget(header)
        layout.addLayout(action_row)
        layout.addLayout(type_row)
        layout.addWidget(self.api_filter)
        layout.addWidget(self.api_list, 2)
        layout.addWidget(self.api_detail, 3)
        layout.addLayout(btn_row)

        get_app().bridge.record_added.connect(self._on_record)
        get_app().bridge.url_changed.connect(self._on_url_changed)
        get_app().bridge.send_result.connect(self._on_send_result)

    def _on_send_result(self, result: Dict[str, Any]) -> None:
        if result.get("ok"):
            return
        err = str(result.get("error", "未知错误"))
        diag = result.get("diag")
        if diag:
            err += f"\n\n诊断: hook={diag.get('hooked')}, ws数={diag.get('count')}"
            for u in diag.get("urls", []):
                err += f"\n  · state={u.get('state')} {u.get('url', '')[:60]}"
        if result.get("page"):
            err += f"\n页面: {result.get('page')}"
        QMessageBox.warning(self, "发送失败", err)

    def _schedule_render(self) -> None:
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _schedule_filter_render(self) -> None:
        if not self._filter_timer.isActive():
            self._filter_timer.start()

    def _trim_records(self) -> None:
        if len(self.records) > MAX_RECORDS:
            self.records = self.records[:MAX_RECORDS]

    def _set_type_filter(self, kind: str) -> None:
        self.type_filter = kind
        self.btn_type_all.setChecked(kind == "all")
        self.btn_type_http.setChecked(kind == "http")
        self.btn_type_ws.setChecked(kind == "ws")
        self._render_list()

    def _record_kind(self, rec: Dict[str, Any]) -> str:
        return rec.get("kind") or (
            "WebSocket" if rec.get("resourceType") == "websocket" else "HTTP"
        )

    def _match_filter(self, rec: Dict[str, Any], filt: str) -> bool:
        if not filt:
            return True
        filt = filt.lower()
        url = str(rec.get("url", "")).lower()
        method = str(rec.get("method", "")).lower()
        if filt in url or filt in method or filt in str(rec.get("kind", "")).lower():
            return True
        for field in ("requestBody", "responseBody", "chatPreview"):
            text = str(rec.get(field, ""))
            if len(text) > 4096:
                text = text[:4096]
            if filt in text.lower():
                return True
        return False

    def _filtered_records(self) -> List[Dict[str, Any]]:
        filt = self.api_filter.text().lower()
        result: List[Dict[str, Any]] = []
        for rec in self.records:
            kind = self._record_kind(rec)
            if self.type_filter == "http" and kind != "HTTP":
                continue
            if self.type_filter == "ws" and kind != "WebSocket":
                continue
            if self._match_filter(rec, filt):
                result.append(rec)
        return result

    def _on_url_changed(self, payload) -> None:
        if isinstance(payload, dict):
            url = str(payload.get("url") or "")
            account_id = str(payload.get("account_id") or "")
        else:
            url = str(payload)
            account_id = ""
        acc = get_app().accounts.get(account_id)
        prefix = f"{acc.name} — " if acc else ""
        self.setWindowTitle(f"接口监听 — {prefix}{url[:40]}")

    def _on_record(self, data: Dict[str, Any]) -> None:
        if self._record_kind(data) == "WebSocket":
            self.records.insert(0, data)
            self._trim_records()
            self._schedule_render()
            return
        if data.get("status") is not None or data.get("error"):
            for i, rec in enumerate(self.records):
                if rec.get("id") == data.get("id"):
                    self.records[i] = data
                    self._trim_records()
                    self._schedule_render()
                    return
        self.records.insert(0, data)
        self._trim_records()
        self._schedule_render()

    def _render_list(self) -> None:
        filtered = self._filtered_records()
        http_n = sum(1 for r in self.records if self._record_kind(r) == "HTTP")
        ws_n = sum(1 for r in self.records if self._record_kind(r) == "WebSocket")
        hidden = max(0, len(filtered) - DISPLAY_LIMIT)
        count_txt = f"{len(self.records)} 条 (HTTP {http_n} / WS {ws_n})"
        if hidden:
            count_txt += f" · 显示前 {DISPLAY_LIMIT} 条"
        self.count_label.setText(count_txt)

        show = filtered[:DISPLAY_LIMIT]
        self.api_list.setUpdatesEnabled(False)
        self.api_list.blockSignals(True)
        self.api_list.clear()
        for rec in show:
            kind = self._record_kind(rec)
            method = rec.get("method", "?")
            status = rec.get("status")
            status_txt = str(status) if status is not None else "…"
            url = rec.get("url", "")
            if len(url) > 50:
                url = url[:50] + "…"
            im_mark = "·IM" if get_app().pipeline.is_im_related(rec) else ""
            if kind == "WebSocket":
                tag = f"[WebSocket{im_mark}]"
            else:
                tag = "[HTTP]"
            chat = rec.get("chatPreview")
            chat_tip = f"  「{chat}」" if chat else ""
            aid = rec.get("account_id")
            acc = get_app().accounts.get(str(aid or ""))
            acc_tip = f"{acc.name} " if acc else ""
            item = QListWidgetItem(
                f"{acc_tip}{tag} [{method}] {status_txt}{chat_tip}  {url}"
            )
            if chat and rec.get("method") == "WS↓":
                item.setForeground(QColor("#c2410c"))
            elif chat and rec.get("method") == "WS↑":
                item.setForeground(QColor("#16a34a"))
            elif get_app().pipeline.is_im_related(rec):
                item.setForeground(QColor("#ea580c"))
            elif kind == "WebSocket":
                item.setForeground(QColor("#7c3aed"))
            else:
                item.setForeground(QColor("#0d9488"))
            self.api_list.addItem(item)
        self.api_list.blockSignals(False)
        self.api_list.setUpdatesEnabled(True)

    def _show_detail(self, row: int) -> None:
        if row < 0:
            return
        filtered = self._filtered_records()
        show = filtered[:DISPLAY_LIMIT]
        if row >= len(show):
            return
        self.api_detail.setPlainText(get_app().pipeline.format_record_detail(show[row]))

    def _clear(self) -> None:
        self._render_timer.stop()
        self._filter_timer.stop()
        self.records.clear()
        get_app().browser.clear_all_pending()
        self.api_list.clear()
        self.api_detail.clear()
        self._render_list()

    def _export(self) -> None:
        path = os.path.join(
            ROOT_DIR,
            f"api-capture-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "导出成功", f"已保存到:\n{path}")

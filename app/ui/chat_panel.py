# -*- coding: utf-8 -*-
"""消息页：联系人列表 + 聊天区。"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    MAX_ACCOUNTS,
    PLATFORM_DOUYIN,
    PLATFORM_LABELS,
    PLATFORM_XHS,
)
from app.context import get_app
from app.ui.helpers import avatar_initial, format_list_time
from app.utils.messages import filter_visible_messages
from app.utils.text import (
    apply_contact_nickname,
    contact_display_name,
    is_displayable_message,
    is_valid_chat_content,
    is_valid_display_name,
)
from app.utils.timefmt import now_str

class ContactChatPanel(QMainWindow):
    """消息页：左侧联系人列表 + 右侧聊天区（仿微信/千牛布局）。"""

    LIST_WIDTH = 200

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        super().__init__()
        self.setWindowTitle("消息")
        self.setGeometry(x, y, width, height)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("QSplitter::handle{background:#e5e7eb;}")

        left_panel = QWidget()
        left_panel.setMinimumWidth(self.LIST_WIDTH)
        left_panel.setMaximumWidth(280)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        filter_bar = QWidget()
        filter_bar.setStyleSheet(
            "background:#f7f7f7;border-bottom:1px solid #e5e7eb;"
        )
        filter_layout = QVBoxLayout(filter_bar)
        filter_layout.setContentsMargins(8, 8, 8, 8)
        filter_layout.setSpacing(6)

        acct_row = QHBoxLayout()
        acct_row.setSpacing(6)
        self.account_combo = QComboBox()
        self.account_combo.setMaxVisibleItems(12)
        self.account_combo.setMinimumHeight(30)
        self.account_combo.setStyleSheet(
            "QComboBox{background:#111827;color:#f9fafb;border:1px solid #1f2937;"
            "border-radius:6px;padding:4px 10px;font-size:13px;font-weight:600;}"
            "QComboBox:hover{background:#1f2937;}"
            "QComboBox::drop-down{border:none;width:22px;}"
            "QComboBox QAbstractItemView{background:#111827;color:#f9fafb;"
            "selection-background-color:#3b82f6;selection-color:#ffffff;"
            "border:1px solid #374151;outline:none;}"
        )
        self.account_combo.currentIndexChanged.connect(self._on_account_combo)
        self.account_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.account_combo.customContextMenuRequested.connect(self._on_account_combo_menu)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(30, 30)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setToolTip("多开一个独立 Edge 登录新账号")
        add_btn.setStyleSheet(
            "QPushButton{background:#111827;color:#fff;border:none;border-radius:6px;"
            "font-size:16px;font-weight:700;}"
            "QPushButton:hover{background:#1f2937;}"
        )
        add_btn.clicked.connect(self._add_account)

        more_btn = QPushButton("⋯")
        more_btn.setFixedSize(30, 30)
        more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        more_btn.setToolTip("重命名 / 关闭当前账号")
        more_btn.setStyleSheet(
            "QPushButton{background:#e5e7eb;color:#111827;border:none;border-radius:6px;"
            "font-size:14px;font-weight:700;}"
            "QPushButton:hover{background:#d1d5db;}"
        )
        more_btn.clicked.connect(self._open_account_menu)
        self.account_dot = QLabel()
        self.account_dot.setFixedSize(8, 8)
        self.account_dot.setStyleSheet("background:#ef4444;border-radius:4px;")
        self.account_dot.hide()
        acct_row.addWidget(self.account_combo, 1)
        acct_row.addWidget(self.account_dot)
        acct_row.addWidget(add_btn)
        acct_row.addWidget(more_btn)

        plat_row = QHBoxLayout()
        plat_row.setSpacing(6)
        self.platform_combo = QComboBox()
        self.platform_combo.setMinimumHeight(30)
        self.platform_combo.setStyleSheet(
            "QComboBox{background:#ffffff;color:#111827;border:1px solid #d1d5db;"
            "border-radius:6px;padding:4px 10px;font-size:13px;font-weight:600;}"
            "QComboBox:hover{background:#f9fafb;}"
            "QComboBox::drop-down{border:none;width:22px;}"
            "QComboBox QAbstractItemView{background:#ffffff;color:#111827;"
            "selection-background-color:#111827;selection-color:#ffffff;"
            "border:1px solid #d1d5db;outline:none;}"
        )
        for plat in (PLATFORM_XHS, PLATFORM_DOUYIN):
            self.platform_combo.addItem(PLATFORM_LABELS[plat], plat)
        self.platform_combo.currentIndexChanged.connect(self._on_platform_combo)

        self.platform_dot = QLabel()
        self.platform_dot.setFixedSize(8, 8)
        self.platform_dot.setStyleSheet("background:#ef4444;border-radius:4px;")
        self.platform_dot.hide()
        plat_row.addWidget(self.platform_combo, 1)
        plat_row.addWidget(self.platform_dot)

        filter_layout.addLayout(acct_row)
        filter_layout.addLayout(plat_row)
        self._rebuild_account_bar()
        self._update_platform_buttons()

        self.contact_list = QListWidget()
        self.contact_list.setStyleSheet(
            "QListWidget{background:#f7f7f7;border:none;outline:none;}"
            "QListWidget::item{ border-bottom:1px solid #ececec; }"
            "QListWidget::item:selected{ background:#e8e8e8; }"
            "QListWidget::item:hover{ background:#efefef; }"
        )
        self.contact_list.currentRowChanged.connect(self._on_contact_selected)

        left_layout.addWidget(filter_bar)
        left_layout.addWidget(self.contact_list, 1)

        right_panel = QWidget()
        right_panel.setMinimumWidth(280)
        right_panel.setStyleSheet("background:#f5f5f5;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.chat_header = QFrame()
        self.chat_header.setFixedHeight(52)
        self.chat_header.setStyleSheet(
            "background:#fff;border-bottom:1px solid #e5e7eb;"
        )
        header_layout = QHBoxLayout(self.chat_header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        self.header_avatar = QLabel("?")
        self.header_avatar.setFixedSize(36, 36)
        self.header_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_avatar.setStyleSheet(
            "background:#94a3b8;color:#fff;border-radius:18px;font-weight:600;"
        )
        self.header_name = QLabel("选择联系人")
        self.header_name.setStyleSheet("font-weight:600;font-size:15px;color:#111;")
        header_layout.addWidget(self.header_avatar)
        header_layout.addWidget(self.header_name, 1)

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setAcceptRichText(True)
        pal = self.chat_log.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor("#f5f5f5"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#111111"))
        self.chat_log.setPalette(pal)
        self.chat_log.setStyleSheet(
            "QTextEdit{background:#f5f5f5;border:none;padding:8px;"
            "font-family:'Segoe UI','Microsoft YaHei',sans-serif;font-size:14px;}"
        )

        input_frame = QFrame()
        input_frame.setFixedHeight(56)
        input_frame.setStyleSheet(
            "background:#fff;border-top:1px solid #e5e7eb;"
        )
        input_row = QHBoxLayout(input_frame)
        input_row.setContentsMargins(12, 8, 12, 8)
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("发消息…")
        self.msg_input.setStyleSheet(
            "QLineEdit{background:#f5f5f5;color:#111111;border:1px solid #e5e7eb;"
            "border-radius:18px;padding:8px 14px;font-size:14px;}"
            "QLineEdit::placeholder{color:#9ca3af;}"
        )
        self.msg_input.returnPressed.connect(self._send_message)
        btn_send = QPushButton("发送")
        btn_send.setFixedWidth(64)
        btn_send.setStyleSheet(
            "QPushButton{background:#3b82f6;color:#fff;border:none;"
            "border-radius:16px;padding:8px;font-weight:600;}"
            "QPushButton:hover{background:#2563eb;}"
        )
        btn_send.clicked.connect(self._send_message)
        input_row.addWidget(self.msg_input, 1)
        input_row.addWidget(btn_send)

        right_layout.addWidget(self.chat_header)
        right_layout.addWidget(self.chat_log, 1)
        right_layout.addWidget(input_frame)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([self.LIST_WIDTH, width - self.LIST_WIDTH])

        root_layout.addWidget(splitter)

        self._show_empty_state()

        get_app().bridge.contact_updated.connect(self._on_contact_updated)
        get_app().bridge.url_changed.connect(self._on_url_changed)
        get_app().bridge.send_result.connect(self._on_send_result)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self._refresh_contact_list)

        self._dom_sync_timer = QTimer(self)
        self._dom_sync_timer.setInterval(2500)
        self._dom_sync_timer.timeout.connect(self._tick_dom_sync)
        self._dom_sync_timer.start()

    def _tick_dom_sync(self) -> None:
        active = get_app().contacts.get_active()
        if not active:
            return
        if active.get("platform", PLATFORM_XHS) != PLATFORM_XHS:
            return
        get_app().dom_sync.schedule_sync_xhs_chat_dom(
            str(active.get("key") or active.get("conv_id") or ""), delay=False
        )

    def _show_empty_state(self) -> None:
        self.chat_log.setHtml(
            "<html><body style='background:#f5f5f5;color:#9ca3af;"
            "font-family:Microsoft YaHei,Segoe UI,sans-serif;text-align:center;"
            "padding:48px 16px;'>"
            "<p style='font-size:15px;color:#6b7280;'>选择左侧联系人</p>"
            "<p style='font-size:13px;'>账号不保存。点 + 可临时多开，关掉即清空</p>"
            "</body></html>"
        )

    def _bubble_html(
        self, m: Dict[str, Any], contact: Optional[Dict[str, Any]] = None
    ) -> str:
        text = html.escape(str(m.get("text", "")), quote=False)
        t = html.escape(str(m.get("time", "")), quote=False)
        time_p = (
            f"<p style='text-align:center;color:#9ca3af;font-size:11px;"
            f"margin:12px 0;'>{t}</p>"
        )
        align = "right" if m.get("direction") == "up" else "left"
        margin = (
            "6px 8px 6px 40px" if align == "right" else "6px 40px 6px 8px"
        )
        if align == "right":
            return (
                time_p
                + f"<p style='text-align:right;margin:{margin};'>"
                f"<span style='display:inline-block;background-color:#3b82f6;"
                f"color:#ffffff;padding:10px 14px;border-radius:12px;'>"
                f"{text}</span></p>"
            )
        return (
            time_p
            + f"<p style='text-align:left;margin:{margin};'>"
            f"<span style='display:inline-block;background-color:#ffffff;"
            f"color:#111111;padding:10px 14px;border-radius:12px;"
            f"border:1px solid #e5e7eb;'>{text}</span></p>"
        )

    def _render_all_messages(self, c: Dict[str, Any]) -> None:
        msgs = filter_visible_messages(
            c.get("messages", []), contact_display_name(c)
        )
        for m in msgs:
            nick = m.pop("_extracted_nickname", None)
            if nick:
                apply_contact_nickname(c, nick, str(m.get("text", "")))
        c["messages"] = msgs
        parts = [self._bubble_html(m, c) for m in msgs]
        body = "".join(parts) if parts else (
            "<p style='text-align:center;color:#9ca3af;padding:40px;'>暂无消息</p>"
        )
        self.chat_log.setHtml(
            "<html><head><meta charset='utf-8'></head>"
            f"<body style='background:#f5f5f5;font-family:Microsoft YaHei,Segoe UI,sans-serif;'>"
            f"{body}</body></html>"
        )
        self.chat_log.verticalScrollBar().setValue(
            self.chat_log.verticalScrollBar().maximum()
        )
        self._update_header(c)

    def _ensure_contact(self, conv_id: str, nickname: str = "", account_id: str = "") -> str:
        aid = account_id or get_app().accounts.active_id
        return get_app().contacts.ensure_xhs_contact(conv_id, aid, nickname)

    def _apply_platform_btn_styles(self) -> None:
        self._update_platform_buttons()

    def _update_platform_buttons(self) -> None:
        combo = self.platform_combo
        combo.blockSignals(True)
        active = get_app().contacts.get_active_platform()
        for i in range(combo.count()):
            plat = str(combo.itemData(i) or "")
            label = PLATFORM_LABELS.get(plat, plat)
            combo.setItemText(i, label)
            if plat == active:
                combo.setCurrentIndex(i)
        combo.blockSignals(False)

        other_unread = 0
        for plat in (PLATFORM_XHS, PLATFORM_DOUYIN):
            if plat != active:
                other_unread += get_app().contacts.platform_unread(plat)
        if other_unread > 0:
            self.platform_dot.show()
        else:
            self.platform_dot.hide()

    def _on_platform_combo(self, index: int) -> None:
        plat = str(self.platform_combo.itemData(index) or "")
        self._switch_platform(plat)

    def _switch_platform(self, plat: str) -> None:
        if not plat or plat == get_app().contacts.get_active_platform():
            self._update_platform_buttons()
            return
        get_app().contacts.set_active_platform(plat)
        self._update_platform_buttons()
        self._refresh_contact_list()
        active = get_app().contacts._active
        if active:
            self._show_contact(active)
        else:
            self._show_empty_state()

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def _make_contact_row(self, c: Dict[str, Any]) -> QWidget:
        nick = contact_display_name(c)
        msgs = c.get("messages") or []
        preview = "暂无消息"
        time_txt = ""
        if msgs:
            last = msgs[-1]
            preview = str(last.get("text", ""))
            if not is_displayable_message(preview):
                preview = "暂无消息"
            if len(preview) > 24:
                preview = preview[:24] + "…"
            time_txt = format_list_time(str(last.get("time", "")))
        unread = int(c.get("unread", 0) or 0)

        row = QWidget()
        row.setAutoFillBackground(True)
        row.setStyleSheet("background:transparent;color:#111827;")
        row.setFixedHeight(64)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)

        avatar_box = QWidget()
        avatar_box.setFixedSize(48, 44)
        avatar = QLabel(avatar_initial(nick), avatar_box)
        avatar.setGeometry(0, 0, 44, 44)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            "background:#cbd5e1;color:#334155;border-radius:22px;font-weight:600;font-size:16px;"
        )
        if unread:
            dot = QLabel(avatar_box)
            dot.setGeometry(34, 0, 10, 10)
            dot.setStyleSheet(
                "background:#ef4444;border-radius:5px;border:1px solid #f7f7f7;"
            )

        mid = QVBoxLayout()
        mid.setSpacing(2)
        name_row = QHBoxLayout()
        name_lbl = QLabel(nick)
        name_lbl.setStyleSheet("font-weight:600;font-size:14px;color:#111827;")
        time_lbl = QLabel(time_txt)
        time_lbl.setStyleSheet("color:#9ca3af;font-size:11px;")
        name_row.addWidget(name_lbl, 1)
        name_row.addWidget(time_lbl)
        preview_lbl = QLabel(preview)
        preview_lbl.setStyleSheet("color:#4b5563;font-size:12px;")
        mid.addLayout(name_row)
        mid.addWidget(preview_lbl)

        layout.addWidget(avatar_box)
        layout.addLayout(mid, 1)
        return row

    def _on_url_changed(self, payload) -> None:
        if isinstance(payload, dict):
            url = str(payload.get("url") or "")
            account_id = str(payload.get("account_id") or "")
        else:
            url = str(payload)
            account_id = get_app().accounts.active_id
        m = re.search(r"/chat/([0-9a-f]{24})", url)
        if not m:
            return
        raw_conv = m.group(1)
        key = self._ensure_contact(raw_conv, account_id=account_id)
        if account_id and account_id != get_app().accounts.active_id:
            return
        get_app().contacts.set_active_platform(PLATFORM_XHS)
        get_app().contacts.set_active(key)
        get_app().dom_sync.schedule_sync_xhs_chat_dom(key)
        self._schedule_refresh()
        self._show_contact(key)

    def _on_contact_updated(self, conv_id: str) -> None:
        # 仅刷新角标；列表防抖，避免每条消息全量重建导致卡顿/切不过去
        self._update_platform_buttons()
        self._apply_account_btn_styles()
        self._schedule_refresh()
        if get_app().contacts._active == conv_id:
            c = get_app().contacts.get(conv_id)
            if c:
                self._render_all_messages(c)

    def _refresh_contact_list(self) -> None:
        self._update_platform_buttons()
        self._apply_account_btn_styles()
        contacts = get_app().contacts.list_contacts()
        current = get_app().contacts._active
        self.contact_list.blockSignals(True)
        self.contact_list.clear()
        select_row = -1
        for c in contacts:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, c.get("key") or c["conv_id"])
            item.setSizeHint(QSize(0, 64))
            item.setBackground(QColor("#f7f7f7"))
            item.setForeground(QColor("#111827"))
            self.contact_list.addItem(item)
            self.contact_list.setItemWidget(item, self._make_contact_row(c))
            if (c.get("key") or c["conv_id"]) == current:
                select_row = self.contact_list.count() - 1
        if select_row >= 0:
            self.contact_list.setCurrentRow(select_row)
        self.contact_list.blockSignals(False)

    def _on_contact_selected(self, row: int) -> None:
        if row < 0:
            return
        item = self.contact_list.item(row)
        if item is None:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if conv_id == get_app().contacts._active:
            get_app().contacts.set_active(conv_id)  # 清未读
            self._show_contact(conv_id)
            # 只轻量更新当前行，避免再次全量 clear
            self._schedule_refresh()
            return
        get_app().contacts.set_active(conv_id)
        self._show_contact(conv_id)
        self._schedule_refresh()

    def _update_header(self, c: Dict[str, Any]) -> None:
        nick = contact_display_name(c)
        plat = c.get("platform", PLATFORM_XHS)
        label = PLATFORM_LABELS.get(plat, "")
        acc = get_app().accounts.get(str(c.get("account_id") or ""))
        acc_name = acc.name if acc else ""
        parts = [p for p in (acc_name, label, nick) if p]
        title = " · ".join(parts) if parts else nick
        self.header_name.setText(title)
        self.header_avatar.setText(avatar_initial(nick))

    def _show_contact(self, conv_id: str) -> None:
        c = get_app().contacts.get(conv_id)
        if not c:
            self._show_empty_state()
            return
        self._update_header(c)
        self._render_all_messages(c)

    def _append_line(
        self,
        m: Dict[str, Any],
        contact: Optional[Dict[str, Any]] = None,
        scroll: bool = True,
    ) -> None:
        cursor = self.chat_log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(self._bubble_html(m, contact))
        if scroll:
            self.chat_log.setTextCursor(cursor)
            self.chat_log.ensureCursorVisible()

    def _send_message(self) -> None:
        text = self.msg_input.text().strip()
        if not text:
            return
        conv_id = get_app().contacts._active
        if not conv_id:
            QMessageBox.warning(self, "提示", "请先选择联系人，或打开一个聊天页")
            return
        self.msg_input.clear()
        c = get_app().contacts.get(conv_id)
        if c:
            msg = {
                "direction": "up",
                "text": text,
                "time": now_str(),
                "local": True,
            }
            c["messages"].append(msg)
            self._update_header(c)
            self._render_all_messages(c)
            self._schedule_refresh()
        get_app().sender.schedule_send_im(text, conv_id)

    def _account_btn_text(self, acc) -> str:
        return acc.name

    def _rebuild_account_bar(self) -> None:
        combo = self.account_combo
        combo.blockSignals(True)
        combo.clear()
        active = get_app().accounts.active_id
        select = 0
        for i, acc in enumerate(get_app().accounts.list()):
            combo.addItem(self._account_btn_text(acc), acc.id)
            if acc.id == active:
                select = i
        if combo.count():
            combo.setCurrentIndex(select)
        combo.blockSignals(False)
        self._refresh_account_dot()

    def _refresh_account_dot(self) -> None:
        active = get_app().accounts.active_id
        other_unread = 0
        for acc in get_app().accounts.list():
            if acc.id != active:
                other_unread += get_app().contacts.account_unread(acc.id)
        self.account_dot.setVisible(other_unread > 0)

    def _apply_account_btn_styles(self) -> None:
        combo = self.account_combo
        combo.blockSignals(True)
        active = get_app().accounts.active_id
        ids = [str(combo.itemData(i) or "") for i in range(combo.count())]
        live = [acc.id for acc in get_app().accounts.list()]
        if ids != live:
            combo.blockSignals(False)
            self._rebuild_account_bar()
            return
        for i, acc in enumerate(get_app().accounts.list()):
            combo.setItemText(i, self._account_btn_text(acc))
            if acc.id == active:
                combo.setCurrentIndex(i)
        other_unread = 0
        for acc in get_app().accounts.list():
            if acc.id != active:
                other_unread += get_app().contacts.account_unread(acc.id)
        self.account_dot.setVisible(other_unread > 0)
        combo.blockSignals(False)

    def _on_account_combo(self, index: int) -> None:
        aid = str(self.account_combo.itemData(index) or "")
        if not aid or aid == get_app().accounts.active_id:
            return
        self._switch_account(aid)

    def _current_account_id(self) -> str:
        return str(self.account_combo.currentData() or get_app().accounts.active_id or "")

    def _open_account_menu(self) -> None:
        aid = self._current_account_id()
        if not aid:
            return
        menu = QMenu(self)
        act_rename = menu.addAction("重命名")
        act_remove = menu.addAction("关闭此浏览器")
        chosen = menu.exec(self.account_combo.mapToGlobal(self.account_combo.rect().bottomLeft()))
        if chosen == act_rename:
            self._rename_account(aid)
        elif chosen == act_remove:
            self._remove_account(aid)

    def _on_account_combo_menu(self, pos) -> None:
        aid = self._current_account_id()
        if not aid:
            return
        menu = QMenu(self)
        act_rename = menu.addAction("重命名")
        act_remove = menu.addAction("关闭此浏览器")
        chosen = menu.exec(self.account_combo.mapToGlobal(pos))
        if chosen == act_rename:
            self._rename_account(aid)
        elif chosen == act_remove:
            self._remove_account(aid)

    def _switch_account(self, account_id: str) -> None:
        if not account_id:
            return
        get_app().accounts.set_active(account_id)
        get_app().contacts.set_active_account(account_id)
        get_app().browser.bring_to_front(account_id)
        self._apply_account_btn_styles()
        self._update_platform_buttons()
        self._refresh_contact_list()
        active = get_app().contacts._active
        if active:
            self._show_contact(active)
        else:
            self._show_empty_state()

    def _account_menu(self, account_id: str, pos=None) -> None:
        self._open_account_menu()

    def _add_account(self) -> None:
        app = get_app()
        if app.accounts.count() >= MAX_ACCOUNTS:
            QMessageBox.warning(self, "提示", f"最多同时多开 {MAX_ACCOUNTS} 个浏览器")
            return
        name, ok = QInputDialog.getText(
            self, "多开浏览器", "新账号名称：", text=f"账号{app.accounts.count() + 1}"
        )
        if not ok:
            return
        try:
            acc = app.accounts.add(name.strip() or f"账号{app.accounts.count() + 1}")
        except ValueError as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        app.browser.start_one(acc)
        self._rebuild_account_bar()
        self._switch_account(acc.id)
        QMessageBox.information(
            self,
            "已多开",
            f"已打开「{acc.name}」的独立 Edge 窗口，请在该窗口登录。"
            "账号和登录都不会保存，关掉程序即清空。",
        )

    def _rename_account(self, account_id: str) -> None:
        acc = get_app().accounts.get(account_id)
        if acc is None:
            return
        name, ok = QInputDialog.getText(self, "重命名", "账号名称：", text=acc.name)
        if not ok or not name.strip():
            return
        get_app().accounts.rename(account_id, name.strip())
        self._rebuild_account_bar()

    def _remove_account(self, account_id: str) -> None:
        acc = get_app().accounts.get(account_id)
        if acc is None:
            return
        if get_app().accounts.count() <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个浏览器账号")
            return
        ret = QMessageBox.question(
            self,
            "关闭此浏览器",
            f"关闭「{acc.name}」的 Edge 窗口？\n不会保留该窗口的登录数据。",
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        get_app().browser.stop_one(account_id)
        get_app().contacts.drop_account(account_id)
        get_app().douyin_send.drop_account(account_id)
        get_app().accounts.remove(account_id)
        self._rebuild_account_bar()
        self._switch_account(get_app().accounts.active_id)

    def _on_send_result(self, result: Dict[str, Any]) -> None:
        if result.get("ok"):
            return
        err = str(result.get("error", "未知错误"))
        self.chat_log.append(
            f'<div style="color:#dc2626;text-align:center;margin:8px;">'
            f'发送失败: {html.escape(err)}</div>'
        )

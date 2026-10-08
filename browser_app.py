# -*- coding: utf-8 -*-
"""入口：PC 监听 Agent + Edge（无本地聊天 UI）。"""
from __future__ import annotations

import logging
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))


def _write_crash(text: str) -> None:
    path = os.path.join(ROOT, "startup_error.log")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    try:
        print(text, file=sys.stderr)
    except Exception:
        pass


try:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox
except Exception:
    _write_crash("导入 PySide6 失败，请运行 start.bat 重建虚拟环境。\n\n" + traceback.format_exc())
    raise

from app.config import API_PANEL_WIDTH, ROOT_DIR, SHOW_API_PANEL
from app.factory import create_app
from app.ui.agent_panel import AgentPanel


def _setup_logging() -> None:
    log_path = os.path.join(ROOT_DIR, "capture.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def main() -> None:
    _setup_logging()
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("getAllMessage Agent")

    try:
        app_ctx = create_app()
        app_ctx.bridge.start_ui_pump()

        screen = QGuiApplication.primaryScreen().geometry()
        agent_w = AgentPanel.WIDTH
        panel_w = min(API_PANEL_WIDTH, screen.width() // 4) if SHOW_API_PANEL else 0
        edge_width = max(720, screen.width() - agent_w - panel_w)
        edge_x = agent_w + panel_w

        agent_panel = AgentPanel(0, 0, screen.height())
        agent_panel.show()

        if SHOW_API_PANEL:
            from app.ui.api_panel import ApiPanel

            panel = ApiPanel(agent_w, 0, panel_w, screen.height())
            panel.show()

        app_ctx.browser.start_all(edge_x, edge_width, screen.height())
    except Exception:
        text = traceback.format_exc()
        logging.exception("startup failed")
        _write_crash(text)
        QMessageBox.critical(None, "启动失败", text[-2000:])
        raise

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _write_crash(traceback.format_exc())
        raise

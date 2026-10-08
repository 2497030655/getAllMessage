# -*- coding: utf-8 -*-
"""入口：python -m xhs_im_service"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path


def _ensure_package_parent_on_path() -> None:
    """把本服务父目录加入 path，便于独立运行。"""
    root = Path(__file__).resolve().parent.parent
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


def main() -> None:
    _ensure_package_parent_on_path()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from xhs_im_service.config import ServiceConfig
    from xhs_im_service.service import XhsImCaptureService

    cfg = ServiceConfig.from_env()
    svc = XhsImCaptureService(cfg)
    try:
        asyncio.run(svc.run())
    except KeyboardInterrupt:
        print("\n[xhs_im_service] 已退出", flush=True)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""多账号仓库：全部仅存在于本次运行，不写磁盘。"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from typing import List, Optional

from app.config import (
    ACCOUNTS_DIR,
    ACCOUNTS_FILE,
    MAX_ACCOUNTS,
    ROOT_DIR,
    USER_DATA,
)

logger = logging.getLogger("capture")


@dataclass
class Account:
    id: str
    name: str
    profile_dir: str = ""
    xhs_uid: str = ""
    douyin_uid: str = ""


class AccountStore:
    """账号、登录态、UID 都不落盘；每次打开从「账号1」开始。"""

    def __init__(self) -> None:
        self._accounts: List[Account] = []
        self._active_id: str = ""
        self._reset()

    @property
    def active_id(self) -> str:
        return self._active_id

    def list(self) -> List[Account]:
        return list(self._accounts)

    def count(self) -> int:
        return len(self._accounts)

    def get(self, account_id: str) -> Optional[Account]:
        for acc in self._accounts:
            if acc.id == account_id:
                return acc
        return None

    def get_active(self) -> Optional[Account]:
        return self.get(self._active_id) or (self._accounts[0] if self._accounts else None)

    def xhs_uid(self, account_id: str = "") -> str:
        acc = self.get(account_id or self._active_id)
        return (acc.xhs_uid if acc else "") or ""

    def state_dir(self, account_id: str) -> str:
        path = os.path.join(tempfile.gettempdir(), "getAllMessage", account_id or "default")
        os.makedirs(path, exist_ok=True)
        return path

    def fresh_profile_dir(self, account_id: str) -> str:
        """本次运行专用的临时 Edge 目录，关闭后删除。"""
        base = os.path.join(tempfile.gettempdir(), "getAllMessage")
        os.makedirs(base, exist_ok=True)
        return tempfile.mkdtemp(prefix=f"{account_id or 'acc'}-", dir=base)

    def set_active(self, account_id: str) -> None:
        if self.get(account_id) is None:
            return
        self._active_id = account_id

    def set_xhs_uid(self, account_id: str, uid: str) -> bool:
        acc = self.get(account_id)
        uid = str(uid or "").strip()
        if acc is None or not uid or acc.xhs_uid == uid:
            return False
        acc.xhs_uid = uid
        return True

    def set_douyin_uid(self, account_id: str, uid: str) -> bool:
        acc = self.get(account_id)
        uid = str(uid or "").strip()
        if acc is None or not uid or acc.douyin_uid == uid:
            return False
        acc.douyin_uid = uid
        return True

    def rename(self, account_id: str, name: str) -> None:
        acc = self.get(account_id)
        name = str(name or "").strip()
        if acc is None or not name:
            return
        acc.name = name

    def add(self, name: str) -> Account:
        if self.count() >= MAX_ACCOUNTS:
            raise ValueError(f"最多支持 {MAX_ACCOUNTS} 个账号")
        name = str(name or "").strip() or f"账号{self.count() + 1}"
        aid = uuid.uuid4().hex[:10]
        acc = Account(id=aid, name=name)
        self._accounts.append(acc)
        self._active_id = aid
        logger.info("added ephemeral account %s", aid)
        return acc

    def remove(self, account_id: str) -> Optional[Account]:
        if self.count() <= 1:
            raise ValueError("至少保留一个账号")
        acc = self.get(account_id)
        if acc is None:
            return None
        self._accounts = [a for a in self._accounts if a.id != account_id]
        if self._active_id == account_id:
            self._active_id = self._accounts[0].id
        return acc

    def save(self) -> None:
        return

    def _reset(self) -> None:
        self._wipe_saved_login()
        acc = Account(id="default", name="账号1")
        self._accounts = [acc]
        self._active_id = acc.id

    def _wipe_saved_login(self) -> None:
        """清掉历史上留下的账号列表、登录态、发信缓存。"""
        targets = [
            ACCOUNTS_FILE,
            ACCOUNTS_DIR,
            USER_DATA,
            os.path.join(ROOT_DIR, "douyin_im_state.json"),
            os.path.join(tempfile.gettempdir(), "getAllMessage"),
        ]
        for path in targets:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    logger.info("removed %s", path)
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info("removed dir %s", path)
            except Exception:
                logger.exception("wipe failed %s", path)

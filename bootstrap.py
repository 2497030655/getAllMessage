# -*- coding: utf-8 -*-
"""启动引导：兼容 Python 3.9 与 3.12（及中间版本）。"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT, "venv")
VENV_PY = os.path.join(VENV_DIR, "Scripts", "python.exe")
REQ = os.path.join(ROOT, "requirements.txt")
APP = os.path.join(ROOT, "browser_app.py")


def _run(args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop("timeout", 20), **kwargs)


def venv_python_works() -> bool:
    if not os.path.isfile(VENV_PY):
        return False
    try:
        r = _run([VENV_PY, "-c", "import sys; print(sys.version_info[:2])"])
        return r.returncode == 0
    except Exception:
        return False


def iter_host_pythons():
    """本机可用的 Python，3.12 优先，同时保留 3.9。"""
    seen = set()
    for ver in ("3.12", "3.11", "3.10", "3.9"):
        try:
            r = _run(["py", f"-{ver}", "-c", "import sys; print(sys.executable)"])
        except Exception:
            continue
        exe = (r.stdout or "").strip()
        if r.returncode == 0 and exe and os.path.isfile(exe) and exe.lower() not in seen:
            seen.add(exe.lower())
            yield exe
    for cand in (sys.executable, shutil_which("python"), shutil_which("python3")):
        if cand and os.path.isfile(cand) and cand.lower() not in seen:
            seen.add(cand.lower())
            yield cand


def shutil_which(name: str) -> str:
    from shutil import which

    return which(name) or ""


def recreate_venv() -> str:
    last_err = "未找到 Python 3.9–3.12"
    for host in iter_host_pythons():
        print(f"使用 {host} 创建虚拟环境…")
        try:
            subprocess.check_call([host, "-m", "venv", VENV_DIR, "--clear"])
        except Exception as e:
            last_err = str(e)
            continue
        if venv_python_works():
            return VENV_PY
        last_err = "venv 创建后仍无法启动 python.exe"
    raise RuntimeError(last_err)


def ensure_deps() -> None:
    check = _run([VENV_PY, "-c", "import PySide6, playwright"])
    if check.returncode == 0:
        return
    print("正在安装依赖（PySide6_Essentials / playwright，清华镜像）…")
    pip_base = [
        VENV_PY,
        "-m",
        "pip",
        "install",
        "-i",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "--trusted-host",
        "pypi.tuna.tsinghua.edu.cn",
        "--default-timeout",
        "60",
    ]
    subprocess.check_call(pip_base + ["-U", "pip"])
    subprocess.check_call(pip_base + ["-r", REQ])


def main() -> int:
    os.chdir(ROOT)
    if not venv_python_works():
        print("虚拟环境不可用（常见于从另一台电脑拷贝，或 Python 3.9/3.12 换了路径）。")
        recreate_venv()
    ensure_deps()
    return subprocess.call([VENV_PY, APP])


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        print(f"\n启动失败: {e}")
        code = 1
    if code:
        try:
            input("按回车退出…")
        except Exception:
            pass
    sys.exit(code)

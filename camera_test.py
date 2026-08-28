"""相机测试：启动 AMCap 预览软件，由人工确认画面。"""
from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_AMCAP_PATH = Path(__file__).resolve().parent / "amcap+v3.0.9.exe"

_process: subprocess.Popen | None = None


def amcap_path() -> Path:
    return DEFAULT_AMCAP_PATH


def is_running() -> bool:
    return _process is not None and _process.poll() is None


def start_preview(exe_path: str | Path | None = None) -> subprocess.Popen:
    """启动相机预览软件。已在运行则先关闭再开。"""
    path = Path(exe_path) if exe_path is not None else DEFAULT_AMCAP_PATH
    if not path.is_file():
        raise FileNotFoundError(f"相机软件不存在: {path}")
    stop_preview()
    global _process
    _process = subprocess.Popen(
        [str(path)],
        cwd=str(path.parent),
    )
    return _process


def stop_preview() -> None:
    """关闭由本模块启动的相机预览进程。未启动或已退出时静默返回。"""
    global _process
    proc = _process
    _process = None
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

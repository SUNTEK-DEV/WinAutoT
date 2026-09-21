"""相机测试：启动 AMCap 预览软件，由人工确认画面。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import app_paths

_process: subprocess.Popen | None = None


def amcap_path() -> Path:
    return app_paths.amcap_path()


def is_running() -> bool:
    return _process is not None and _process.poll() is None


def start_preview(exe_path: str | Path | None = None) -> subprocess.Popen:
    """启动相机预览软件。已在运行则先关闭再开。"""
    path = Path(exe_path) if exe_path is not None else amcap_path()
    if not path.is_file():
        import i18n
        raise FileNotFoundError(i18n.t("camera.missing", path=path))
    stop_preview(image_name=path.name)
    global _process
    _process = subprocess.Popen(
        [str(path)],
        cwd=str(path.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return _process


def stop_preview(image_name: str | None = None) -> None:
    """关闭由本模块启动的相机预览进程（含子进程）。未启动时静默返回。

    句柄仅在进程确认退出后清除；杀不掉则保留，便于下次再杀。
    启动器退出后子进程可能仍占用相机，因此再按映像名清理一次。
    """
    global _process
    proc = _process
    name = image_name or app_paths.AMCAP_NAME
    if proc is not None and proc.poll() is None:
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass
    _kill_image(name)
    if proc is not None and proc.poll() is None:
        return
    _process = None


def _kill_tree(pid: int) -> None:
    """结束 pid 及其子进程。Windows 用 taskkill /T，避免启动器留下预览窗口。"""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        import os
        import signal
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _kill_image(name: str) -> None:
    if sys.platform != "win32" or not name:
        return
    subprocess.run(
        ["taskkill", "/IM", name, "/T", "/F"],
        capture_output=True,
        check=False,
    )

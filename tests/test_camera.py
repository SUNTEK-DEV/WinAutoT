"""camera_test.py 单元测试（不启动真实 AMCap）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import camera_test


@pytest.fixture(autouse=True)
def _reset_process():
    camera_test._process = None
    yield
    camera_test._process = None


@pytest.fixture
def kill_helpers():
    with patch.object(camera_test, "_kill_tree") as tree, \
            patch.object(camera_test, "_kill_image") as image:
        yield {"tree": tree, "image": image}


def test_start_preview_missing_exe(tmp_path: Path):
    missing = tmp_path / "no-such.exe"
    with pytest.raises(FileNotFoundError):
        camera_test.start_preview(missing)


def test_start_preview_launches_exe(tmp_path: Path, kill_helpers):
    exe = tmp_path / "amcap+v3.0.9.exe"
    exe.write_bytes(b"")
    fake = MagicMock()
    fake.poll.return_value = None
    with patch.object(camera_test.subprocess, "Popen", return_value=fake) as popen:
        proc = camera_test.start_preview(exe)
    popen.assert_called_once_with(
        [str(exe)],
        cwd=str(tmp_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert proc is fake
    assert camera_test.is_running()
    kill_helpers["image"].assert_called()


def test_stop_preview_kills_tree(kill_helpers):
    fake = MagicMock()
    fake.poll.side_effect = [None, 0]
    fake.pid = 4321
    camera_test._process = fake
    camera_test.stop_preview()
    kill_helpers["tree"].assert_called_once_with(4321)
    kill_helpers["image"].assert_called_once()
    fake.wait.assert_called()
    assert camera_test._process is None
    assert not camera_test.is_running()


def test_stop_preview_noop_when_idle(kill_helpers):
    camera_test.stop_preview()
    kill_helpers["tree"].assert_not_called()
    kill_helpers["image"].assert_called_once()
    assert camera_test._process is None


def test_stop_preview_skips_already_exited(kill_helpers):
    fake = MagicMock()
    fake.poll.return_value = 0
    camera_test._process = fake
    camera_test.stop_preview()
    kill_helpers["tree"].assert_not_called()
    fake.kill.assert_not_called()
    assert camera_test._process is None


def test_stop_preview_keeps_handle_if_still_alive(kill_helpers):
    fake = MagicMock()
    fake.poll.return_value = None
    fake.pid = 1
    fake.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=1)
    camera_test._process = fake
    camera_test.stop_preview()
    fake.kill.assert_called()
    assert camera_test._process is fake


def test_start_preview_closes_previous(tmp_path: Path, kill_helpers):
    exe = tmp_path / "amcap+v3.0.9.exe"
    exe.write_bytes(b"")
    old = MagicMock()
    old.poll.side_effect = [None, 0]
    old.pid = 100
    camera_test._process = old
    new = MagicMock()
    new.poll.return_value = None
    with patch.object(camera_test.subprocess, "Popen", return_value=new):
        camera_test.start_preview(exe)
    kill_helpers["tree"].assert_called_once_with(100)
    assert camera_test._process is new


def test_kill_tree_uses_taskkill():
    with patch.object(camera_test.sys, "platform", "win32"), \
            patch.object(camera_test.subprocess, "run") as run:
        camera_test._kill_tree(99)
    cmd = run.call_args[0][0]
    assert cmd == ["taskkill", "/PID", "99", "/T", "/F"]


def test_kill_image_uses_taskkill():
    with patch.object(camera_test.sys, "platform", "win32"), \
            patch.object(camera_test.subprocess, "run") as run:
        camera_test._kill_image("amcap+v3.0.9.exe")
    cmd = run.call_args[0][0]
    assert cmd == ["taskkill", "/IM", "amcap+v3.0.9.exe", "/T", "/F"]

"""camera_test.py 单元测试（不启动真实 AMCap）。"""
from __future__ import annotations

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


def test_start_preview_missing_exe(tmp_path: Path):
    missing = tmp_path / "no-such.exe"
    with pytest.raises(FileNotFoundError):
        camera_test.start_preview(missing)


def test_start_preview_launches_exe(tmp_path: Path):
    exe = tmp_path / "amcap+v3.0.9.exe"
    exe.write_bytes(b"")
    fake = MagicMock()
    fake.poll.return_value = None
    with patch.object(camera_test.subprocess, "Popen", return_value=fake) as popen:
        proc = camera_test.start_preview(exe)
    popen.assert_called_once_with([str(exe)], cwd=str(tmp_path))
    assert proc is fake
    assert camera_test.is_running()


def test_stop_preview_terminates_process():
    fake = MagicMock()
    fake.poll.return_value = None
    camera_test._process = fake
    camera_test.stop_preview()
    fake.terminate.assert_called_once()
    fake.wait.assert_called_once()
    assert camera_test._process is None
    assert not camera_test.is_running()


def test_stop_preview_noop_when_idle():
    camera_test.stop_preview()
    assert camera_test._process is None


def test_stop_preview_skips_already_exited():
    fake = MagicMock()
    fake.poll.return_value = 0
    camera_test._process = fake
    camera_test.stop_preview()
    fake.terminate.assert_not_called()
    assert camera_test._process is None


def test_start_preview_closes_previous(tmp_path: Path):
    exe = tmp_path / "amcap+v3.0.9.exe"
    exe.write_bytes(b"")
    old = MagicMock()
    old.poll.return_value = None
    camera_test._process = old
    new = MagicMock()
    new.poll.return_value = None
    with patch.object(camera_test.subprocess, "Popen", return_value=new):
        camera_test.start_preview(exe)
    old.terminate.assert_called_once()
    assert camera_test._process is new

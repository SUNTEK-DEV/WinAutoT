"""app_paths.py 单元测试：开发态与冻结（打包）态的根目录解析。"""
from __future__ import annotations

import sys
from pathlib import Path

import app_paths


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_app_dir_is_project_root_when_not_frozen():
    assert app_paths.app_dir() == PROJECT_ROOT


def test_app_dir_uses_exe_parent_when_frozen(monkeypatch, tmp_path: Path):
    exe = tmp_path / "WinAutoTest.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert app_paths.app_dir() == tmp_path


def test_reports_dir_is_under_app_dir():
    assert app_paths.reports_dir() == app_paths.app_dir() / "reports"


def test_reports_dir_follows_frozen_exe(monkeypatch, tmp_path: Path):
    exe = tmp_path / "WinAutoTest.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert app_paths.reports_dir() == tmp_path / "reports"


def test_amcap_in_source_tree():
    assert app_paths.amcap_path() == PROJECT_ROOT / app_paths.AMCAP_NAME


def test_amcap_prefers_file_next_to_exe(monkeypatch, tmp_path: Path):
    exe = tmp_path / "WinAutoTest.exe"
    bundled = tmp_path / app_paths.AMCAP_NAME
    bundled.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert app_paths.amcap_path() == bundled


def test_amcap_falls_back_to_meipass(monkeypatch, tmp_path: Path):
    exe_dir = tmp_path / "dist"
    meipass = tmp_path / "_internal"
    exe_dir.mkdir()
    meipass.mkdir()
    bundled = meipass / app_paths.AMCAP_NAME
    bundled.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "WinAutoTest.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert app_paths.amcap_path() == bundled

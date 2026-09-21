"""Guard portable-build launcher files against Unix line endings."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _assert_crlf(name: str) -> None:
    data = (ROOT / name).read_bytes()
    assert b"\n" in data, f"{name} is empty"
    assert b"\r\n" in data, f"{name} must use CRLF (cmd.exe flash-exits on LF)"
    leftover = data.replace(b"\r\n", b"")
    assert b"\n" not in leftover, f"{name} still has bare LF"


def test_build_bat_uses_crlf():
    _assert_crlf("build.bat")


def test_run_bat_uses_crlf():
    _assert_crlf("run.bat")

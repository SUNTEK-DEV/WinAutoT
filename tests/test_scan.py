"""scan_test.py 单元测试：帧切分对齐 Android ScannerSerialClient。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scan_test


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_sanitize_chunk_strips_null_and_normalizes_newlines():
    text = scan_test.sanitize_chunk(b"AB\x00C\r\nD\rE")
    assert text == "ABC\nD\nE"


def test_sanitize_frame_trims():
    assert scan_test.sanitize_frame("  SN-001 \n") == "SN-001"
    assert scan_test.sanitize_frame(None) == ""


def test_newline_frame_returned_immediately():
    clock = FakeClock()
    assembler = scan_test.FrameAssembler(time_fn=clock)
    assert assembler.feed(b"HELLO\n") == "HELLO"


def test_crlf_and_cr_are_frame_breaks():
    clock = FakeClock()
    assembler = scan_test.FrameAssembler(time_fn=clock)
    assert assembler.feed(b"A\r\nB\r") == "A"
    assert assembler.extract() == "B"


def test_two_frames_in_one_chunk_yield_one_at_a_time():
    clock = FakeClock()
    assembler = scan_test.FrameAssembler(time_fn=clock)
    assert assembler.feed(b"one\ntwo\n") == "one"
    assert assembler.extract() == "two"
    assert assembler.extract() is None


def test_idle_flush_after_timeout():
    clock = FakeClock()
    assembler = scan_test.FrameAssembler(idle_timeout=0.12, time_fn=clock)
    assert assembler.feed(b"NOCR") is None
    clock.advance(0.11)
    assert assembler.extract() is None
    clock.advance(0.02)
    assert assembler.extract() == "NOCR"


def test_empty_frame_after_trim_is_ignored():
    clock = FakeClock()
    assembler = scan_test.FrameAssembler(time_fn=clock)
    assert assembler.feed(b"   \n") is None


def test_clear_drops_partial_frame():
    clock = FakeClock()
    assembler = scan_test.FrameAssembler(time_fn=clock)
    assembler.feed(b"partial")
    assembler.clear()
    assert assembler.feed(b"OK\n") == "OK"


def test_read_single_scan_success_on_newline():
    client = scan_test.ScannerClient("COM9")
    fake = MagicMock()
    fake.is_open = True
    fake.read.side_effect = [b"QR-123\n"]
    client._serial = fake
    result = client.read_single_scan(timeout=0.5, sleep_fn=lambda _: None)
    assert result.success
    assert result.content == "QR-123"
    assert result.message == ""


def test_read_single_scan_timeout():
    client = scan_test.ScannerClient("COM9")
    fake = MagicMock()
    fake.is_open = True
    fake.read.return_value = b""
    client._serial = fake
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.advance(seconds)

    result = client.read_single_scan(
        timeout=0.05, sleep_fn=sleep, time_fn=clock)
    assert not result.success
    assert result.content == ""
    assert result.message


def test_read_single_scan_stop_event():
    client = scan_test.ScannerClient("COM9")
    fake = MagicMock()
    fake.is_open = True
    fake.read.return_value = b""
    client._serial = fake
    result = client.read_single_scan(
        timeout=5.0, should_stop=lambda: True, sleep_fn=lambda _: None)
    assert not result.success


def test_read_single_scan_requires_open_port():
    client = scan_test.ScannerClient("COM9")
    result = client.read_single_scan(timeout=0.01)
    assert not result.success


def test_scan_result_helpers():
    ok = scan_test.ScanReadResult.ok("ABC")
    assert ok.success and ok.content == "ABC"
    bad = scan_test.ScanReadResult.fail("timeout")
    assert not bad.success
    assert bad.message == "timeout"


def test_summary_pass_and_fail():
    assert "ABC" in scan_test.ScanReadResult.ok("ABC").summary()
    fail = scan_test.ScanReadResult.fail("扫码超时")
    assert fail.summary().startswith("[FAIL]")

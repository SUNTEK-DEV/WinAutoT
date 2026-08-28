"""report.py 单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import report


def test_empty_report_is_pending():
    r = report.TestReport()
    assert r.overall == report.PENDING
    assert r.passed_count == 0
    assert r.failed_count == 0


def test_all_pass_is_pass():
    r = report.TestReport(device_sn="SN1")
    r.add_item("LED-红", "manual").mark(report.PASSED, "ok")
    r.add_item("MIC", "auto").mark(report.PASSED, "ok")
    assert r.overall == report.PASSED
    assert r.passed_count == 2


def test_any_fail_is_fail():
    r = report.TestReport()
    r.add_item("A", "manual").mark(report.PASSED)
    r.add_item("B", "auto").mark(report.FAILED, "no sound")
    assert r.overall == report.FAILED
    assert r.failed_count == 1


def test_skip_is_not_overall_pass():
    r = report.TestReport()
    r.add_item("LED", "manual").mark(report.SKIPPED, "no port")
    r.add_item("MIC", "auto").mark(report.PASSED)
    assert r.overall == report.SKIPPED
    assert r.skipped_count == 1


def test_pending_blocks_overall_pass():
    r = report.TestReport()
    r.add_item("A", "manual").mark(report.PASSED)
    r.add_item("B", "manual")
    assert r.overall == report.PENDING


def test_reset_clears_results():
    r = report.TestReport()
    r.add_item("A", "manual").mark(report.FAILED, "x")
    r.reset()
    assert r.items[0].status == report.PENDING
    assert r.items[0].detail == ""


def test_export_txt_and_csv(tmp_path: Path):
    r = report.TestReport(device_sn="ABC-001", operator="tester")
    r.add_item("LED-红", "manual").mark(report.PASSED, "目视正常")
    r.add_item("MIC", "auto").mark(report.FAILED, "RMS 过低")
    txt = r.save_text(tmp_path)
    csv_path = r.save_csv(tmp_path)
    assert txt.exists()
    assert csv_path.exists()
    body = txt.read_text(encoding="utf-8-sig")
    assert "ABC-001" in body
    assert "FAIL" in body
    csv_body = csv_path.read_text(encoding="utf-8-sig")
    assert "LED-红" in csv_body

"""测试报告模块：汇总测试项结果，导出 TXT/CSV 报告。"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PASSED = "PASS"
FAILED = "FAIL"
PENDING = "待测"
SKIPPED = "跳过"


@dataclass
class TestItemResult:
    """单个测试项的结果。"""
    name: str                     # 测试项名称，如 "LED-红色"
    method: str                   # auto=自动判定 / manual=人工确认
    status: str = PENDING         # PASS / FAIL / 待测 / 跳过
    detail: str = ""              # 判定依据或人工备注
    timestamp: str = ""

    def mark(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        self.timestamp = datetime.now().strftime("%H:%M:%S")


@dataclass
class TestReport:
    """整机组测试报告。"""
    device_sn: str = ""
    operator: str = ""
    items: list[TestItemResult] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def add_item(self, name: str, method: str) -> TestItemResult:
        item = TestItemResult(name=name, method=method)
        self.items.append(item)
        return item

    @property
    def passed_count(self) -> int:
        return sum(1 for i in self.items if i.status == PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for i in self.items if i.status == FAILED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for i in self.items if i.status == SKIPPED)

    @property
    def overall(self) -> str:
        if not self.items:
            return PENDING
        if any(i.status == FAILED for i in self.items):
            return FAILED
        if any(i.status == PENDING for i in self.items):
            return PENDING
        # 跳过项不算通过：产线报告不能在未测 LED 时给出 PASS
        if any(i.status == SKIPPED for i in self.items):
            return SKIPPED
        if all(i.status == PASSED for i in self.items):
            return PASSED
        return PENDING

    def reset(self) -> None:
        for item in self.items:
            item.status = PENDING
            item.detail = ""
            item.timestamp = ""
        self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 导出 -----------------------------------------------------------

    def to_text(self) -> str:
        lines = [
            "=" * 56,
            "WinAutoTest 部件连线检测报告",
            "=" * 56,
            f"整机编号: {self.device_sn or '(未填写)'}",
            f"操作员:   {self.operator or '(未填写)'}",
            f"开始时间: {self.started_at}",
            f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"总判定:   {self.overall}  "
            f"(通过 {self.passed_count} / 失败 {self.failed_count} "
            f"/ 共 {len(self.items)} 项)",
            "-" * 56,
        ]
        for item in self.items:
            line = f"[{item.status:>4}] {item.name}"
            if item.detail:
                line += f"  | {item.detail}"
            if item.timestamp:
                line += f"  @{item.timestamp}"
            lines.append(line)
        lines.append("=" * 56)
        return "\n".join(lines)

    def save_text(self, out_dir: str | Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sn = "".join(c for c in self.device_sn if c.isalnum()) or "noSN"
        path = out_dir / f"report_{sn}_{stamp}.txt"
        path.write_text(self.to_text(), encoding="utf-8-sig")
        return path

    def save_csv(self, out_dir: str | Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sn = "".join(c for c in self.device_sn if c.isalnum()) or "noSN"
        path = out_dir / f"report_{sn}_{stamp}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["整机编号", self.device_sn])
            writer.writerow(["操作员", self.operator])
            writer.writerow(["开始时间", self.started_at])
            writer.writerow(["总判定", self.overall])
            writer.writerow([])
            writer.writerow(["测试项", "判定方式", "结果", "详情", "时间"])
            for item in self.items:
                writer.writerow([item.name, item.method, item.status,
                                 item.detail, item.timestamp])
        return path

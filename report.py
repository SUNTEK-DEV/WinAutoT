"""测试报告模块：汇总测试项结果，导出 TXT/CSV 报告。"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def _display_item_name(name: str) -> str:
    import i18n
    key = f"item.{name}"
    if key in i18n.STRINGS.get(i18n.lang(), {}):
        return i18n.item_name(name)
    return name


PASSED = "PASS"
FAILED = "FAIL"
PENDING = "PENDING"
SKIPPED = "SKIPPED"


@dataclass
class TestItemResult:
    """单个测试项的结果。"""
    name: str                     # 测试项 ID，如 "led_red"；导出时再翻译
    method: str                   # auto=自动判定 / manual=人工确认
    status: str = PENDING         # PASS / FAIL / PENDING / SKIPPED
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
        import i18n
        blank = i18n.t("report.blank")
        lines = [
            "=" * 56,
            i18n.t("report.title"),
            "=" * 56,
            f"{i18n.t('report.sn')}: {self.device_sn or blank}",
            f"{i18n.t('report.operator')}:   {self.operator or blank}",
            f"{i18n.t('report.started')}: {self.started_at}",
            f"{i18n.t('report.ended')}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"{i18n.t('report.overall')}:   {i18n.status_label(self.overall)}  "
            f"{i18n.t('report.counts', passed=self.passed_count, failed=self.failed_count, total=len(self.items))}",
            "-" * 56,
        ]
        for item in self.items:
            line = (f"[{i18n.status_label(item.status):>8}] "
                    f"{_display_item_name(item.name)}")
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
            import i18n
            writer.writerow([i18n.t("report.sn"), self.device_sn])
            writer.writerow([i18n.t("report.operator"), self.operator])
            writer.writerow([i18n.t("report.started"), self.started_at])
            writer.writerow([i18n.t("report.overall"), i18n.status_label(self.overall)])
            writer.writerow([])
            writer.writerow([
                i18n.t("report.col_item"), i18n.t("report.col_method"),
                i18n.t("report.col_result"), i18n.t("report.col_detail"),
                i18n.t("report.col_time"),
            ])
            for item in self.items:
                writer.writerow([
                    _display_item_name(item.name),
                    i18n.method_label(item.method),
                    i18n.status_label(item.status),
                    item.detail,
                    item.timestamp,
                ])
        return path

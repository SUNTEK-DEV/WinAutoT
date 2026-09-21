"""扫码枪串口模块，协议对齐 Android ScannerSerialClient。

- 波特率 9600 8N1
- 一帧：换行（\\n / \\r\\n / \\r）或 120ms 空闲
- 去掉 NUL，trim 后为空的帧丢弃
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import serial

import i18n

BAUDRATE = 9600
BUFFER_SIZE = 256
FRAME_IDLE_TIMEOUT = 0.12
DEFAULT_READ_TIMEOUT = 0.05
DEFAULT_SCAN_TIMEOUT = 20.0


def sanitize_chunk(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def sanitize_frame(frame: str | None) -> str:
    if frame is None:
        return ""
    return frame.replace("\x00", "").strip()


class FrameAssembler:
    """把串口字节流切成扫码枪一帧，行为对齐 Java extractFrame()。"""

    def __init__(
        self,
        idle_timeout: float = FRAME_IDLE_TIMEOUT,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_timeout = idle_timeout
        self._time = time_fn
        self._buf = ""
        self._last_data_at = 0.0

    def feed(self, data: bytes) -> str | None:
        if data:
            self._buf += sanitize_chunk(data)
            self._last_data_at = self._time()
        return self.extract()

    def extract(self) -> str | None:
        newline_index = self._buf.find("\n")
        if newline_index >= 0:
            frame = sanitize_frame(self._buf[:newline_index])
            self._buf = self._buf[newline_index + 1:]
            return frame or None
        if not self._buf:
            return None
        if self._time() - self._last_data_at < self.idle_timeout:
            return None
        frame = sanitize_frame(self._buf)
        self._buf = ""
        return frame or None

    def clear(self) -> None:
        self._buf = ""
        self._last_data_at = 0.0


@dataclass
class ScanReadResult:
    success: bool
    content: str = ""
    message: str = ""

    @staticmethod
    def ok(content: str) -> "ScanReadResult":
        return ScanReadResult(True, content, "")

    @staticmethod
    def fail(message: str) -> "ScanReadResult":
        return ScanReadResult(False, "", message)

    def summary(self) -> str:
        if self.success:
            return i18n.t("result.scan_ok", status="PASS", content=self.content)
        return i18n.t("result.scan_fail", status="FAIL", error=self.message)


class ScannerClient:
    """打开扫码枪 COM 口，阻塞读取一帧。"""

    def __init__(self, port: str, baudrate: int = BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self._serial: serial.Serial | None = None

    def open(self) -> None:
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=DEFAULT_READ_TIMEOUT,
            write_timeout=1.0,
            dsrdtr=False,
            rtscts=False,
        )
        try:
            self._serial.dtr = False
            self._serial.rts = False
        except Exception:
            pass

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def __enter__(self) -> "ScannerClient":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def read_single_scan(
        self,
        timeout: float = DEFAULT_SCAN_TIMEOUT,
        should_stop: Callable[[], bool] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> ScanReadResult:
        """等到一帧扫码内容，超时 / 中断 / 未打开则失败。"""
        clock = time_fn or time.monotonic
        sleep = sleep_fn or time.sleep
        if not self.is_open:
            return ScanReadResult.fail(i18n.t("scan.not_open"))
        assembler = FrameAssembler(time_fn=clock)
        deadline = clock() + timeout
        try:
            while clock() < deadline:
                if should_stop is not None and should_stop():
                    return ScanReadResult.fail(i18n.t("scan.interrupted"))
                chunk = self._serial.read(BUFFER_SIZE)
                frame = assembler.feed(chunk or b"")
                if frame:
                    return ScanReadResult.ok(frame)
                sleep(0.03)
        except (serial.SerialException, OSError) as exc:
            return ScanReadResult.fail(i18n.t("scan.read_error", error=exc))
        return ScanReadResult.fail(i18n.t("scan.timeout"))

"""LED 串口通讯模块（基于 LED-通讯指令 V6.5 协议）。

协议要点：
- 串口波特率 9600，正确指令会自动回显所发字符
- 状态灯 RGB 全彩：3 字节 HEX（R G B），如 FF 00 00 = 红色
- 状态灯闪烁：7 字节（R G B 开灯时长 关灯时长 次数 结束状态）
- 补光灯亮度：4C <亮度0-100> 23（HEX）
- 字符串指令：VERSION 查询版本（返回 FY-LED-vX.X）、L0001# 七色、L99RRGGBB# 全色
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import serial
import serial.tools.list_ports

BAUDRATE = 9600
DEFAULT_READ_TIMEOUT = 0.3
# 探测 LED 控制器时发送的版本查询指令（字符串格式）
PROBE_COMMAND = b"VERSION"


@dataclass
class LedPort:
    """一个候选串口及其探测结果。"""
    device: str
    description: str = ""
    is_led_controller: bool = False
    version: str = ""

    @property
    def label(self) -> str:
        tag = "LED控制器" if self.is_led_controller else "其他设备"
        return f"{self.device} - {self.description or '未知设备'} ({tag})"


def list_serial_ports() -> list[LedPort]:
    """枚举系统串口。"""
    return [
        LedPort(device=p.device, description=p.description or "")
        for p in serial.tools.list_ports.comports()
    ]


class LedController:
    """通过串口控制 LED 状态灯 / 补光灯。

    用法：
        with LedController("COM3") as led:
            led.set_color(255, 0, 0)     # 红色常亮
            led.set_off()                # 关灯
    """

    def __init__(self, port: str, baudrate: int = BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self._serial: serial.Serial | None = None

    # ---- 连接管理 -------------------------------------------------------

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
        # 避免 USB-UART 打开时拉低 DTR 导致 MCU 复位
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

    def __enter__(self) -> "LedController":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # ---- 底层收发 -------------------------------------------------------

    def _write(self, data: bytes) -> int:
        if not self.is_open:
            raise RuntimeError("串口未打开")
        return self._serial.write(data)

    def _read_reply(self, expect_len: int, settle: float = 0.15) -> bytes:
        """读取设备回显。协议规定：正确指令自动返回所发送的字符。"""
        deadline = time.monotonic() + settle + DEFAULT_READ_TIMEOUT
        buf = bytearray()
        while time.monotonic() < deadline and len(buf) < expect_len:
            chunk = self._serial.read(max(1, expect_len - len(buf)))
            buf.extend(chunk)
        return bytes(buf)

    def send_hex(self, data: bytes) -> bytes:
        """发送 HEX 指令并返回回显。"""
        n = self._write(data)
        if n != len(data):
            raise RuntimeError(f"写入不完整: {n}/{len(data)} 字节")
        return self._read_reply(expect_len=len(data))

    # ---- 状态灯（HEX 协议） ---------------------------------------------

    def set_color(self, r: int, g: int, b: int) -> bytes:
        """状态灯常亮，RGB 各 0-255。返回设备回显。"""
        self._validate_rgb(r, g, b)
        return self.send_hex(bytes([r, g, b]))

    def set_off(self) -> bytes:
        return self.set_color(0, 0, 0)

    def set_blink(self, r: int, g: int, b: int,
                  on_ms: int = 600, off_ms: int = 400,
                  count: int = 100, end_on: bool = False) -> bytes:
        """状态灯闪烁。时长单位 10ms，次数 0=无限，end_on=结束保持常亮。"""
        self._validate_rgb(r, g, b)
        if not (10 <= on_ms <= 2550 and 10 <= off_ms <= 2550):
            raise ValueError("on_ms/off_ms 需在 10-2550 范围（10ms 步进）")
        if not (0 <= count <= 255):
            raise ValueError("count 需在 0-255（0=无限）")
        packet = bytes([r, g, b, on_ms // 10, off_ms // 10, count, 1 if end_on else 0])
        return self.send_hex(packet)

    # ---- 补光灯（HEX 协议） ---------------------------------------------

    def set_fill_light(self, brightness: int) -> bytes:
        """补光灯亮度 0-100。仅带补光灯的设备支持。"""
        if not (0 <= brightness <= 100):
            raise ValueError("亮度需在 0-100")
        return self.send_hex(bytes([0x4C, brightness, 0x23]))

    def query_fill_light(self) -> int:
        """查询补光灯亮度，返回 0-100，失败返回 -1。"""
        reply = self.send_hex(bytes([0x4C, 0xFF, 0x23]))
        if len(reply) >= 2:
            value = reply[1]
            if 0 <= value <= 100:
                return value
        return -1

    # ---- 字符串指令（兼容协议） -----------------------------------------

    def send_text(self, text: str) -> str:
        """发送字符串指令（如 VERSION、L0001#），返回文本回显。"""
        payload = text.encode("ascii")
        self._write(payload)
        reply = self._read_reply(expect_len=len(payload) + 16, settle=0.25)
        return reply.decode("ascii", errors="replace")

    # ---- 探测 -----------------------------------------------------------

    @staticmethod
    def probe_port(port: str, baudrate: int = BAUDRATE) -> LedPort | None:
        """向指定串口发送 VERSION，返回 FY 开头即为 LED 控制器。"""
        try:
            with LedController(port, baudrate) as led:
                reply = led.send_text(PROBE_COMMAND.decode("ascii"))
        except (serial.SerialException, OSError, RuntimeError):
            return None
        if not reply:
            return None
        cleaned = reply.strip()
        if cleaned.startswith("FY"):
            return LedPort(device=port, description="LED controller",
                           is_led_controller=True, version=cleaned)
        return None

    def probe_in_place(self) -> LedPort | None:
        """在已打开的串口上发 VERSION，不关闭句柄（避免 CH340 重开 Access denied）。"""
        try:
            reply = self.send_text(PROBE_COMMAND.decode("ascii"))
        except (serial.SerialException, OSError, RuntimeError):
            return None
        if not reply:
            return None
        cleaned = reply.strip()
        if cleaned.startswith("FY"):
            return LedPort(device=self.port, description="LED controller",
                           is_led_controller=True, version=cleaned)
        return None

    @staticmethod
    def probe_all_ports(ports: list[str] | None = None) -> list[LedPort]:
        """逐个探测串口，返回探测成功的 LED 控制器列表。"""
        if ports is None:
            ports = [p.device for p in list_serial_ports()]
        found: list[LedPort] = []
        for device in ports:
            result = LedController.probe_port(device)
            if result is not None:
                found.append(result)
        return found

    # ---- 内部 -----------------------------------------------------------

    @staticmethod
    def _validate_rgb(r: int, g: int, b: int) -> None:
        for name, v in (("R", r), ("G", g), ("B", b)):
            if not (0 <= v <= 255):
                raise ValueError(f"{name} 通道值 {v} 超出 0-255")

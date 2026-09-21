"""serial_led.py 协议组包 / 校验单元测试（不依赖真实串口）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import serial_led


def _controller_with_mock() -> tuple[serial_led.LedController, MagicMock]:
    led = serial_led.LedController("COM99")
    mock = MagicMock()
    mock.is_open = True
    mock.write.side_effect = lambda data: len(data)
    mock.read.return_value = b""
    led._serial = mock
    return led, mock


def test_set_color_sends_three_bytes():
    led, mock = _controller_with_mock()
    mock.read.return_value = b"\xff\x00\x00"
    reply = led.set_color(255, 0, 0)
    mock.write.assert_called_once_with(b"\xff\x00\x00")
    assert reply == b"\xff\x00\x00"


def test_set_off_is_black():
    led, mock = _controller_with_mock()
    mock.read.return_value = b"\x00\x00\x00"
    led.set_off()
    mock.write.assert_called_once_with(b"\x00\x00\x00")


def test_set_fill_light_hex():
    led, mock = _controller_with_mock()
    mock.read.return_value = b"\x4c\x64\x23"
    led.set_fill_light(100)
    mock.write.assert_called_once_with(b"\x4c\x64\x23")


def test_set_fill_light_rejects_out_of_range():
    led, _ = _controller_with_mock()
    with pytest.raises(ValueError):
        led.set_fill_light(101)
    with pytest.raises(ValueError):
        led.set_fill_light(-1)


def test_set_color_rejects_out_of_range():
    led, _ = _controller_with_mock()
    with pytest.raises(ValueError):
        led.set_color(256, 0, 0)


def test_set_blink_packet():
    led, mock = _controller_with_mock()
    mock.read.return_value = b"\xff\x00\x00\x3c\x28\x64\x00"
    led.set_blink(255, 0, 0, on_ms=600, off_ms=400, count=100, end_on=False)
    mock.write.assert_called_once_with(b"\xff\x00\x00\x3c\x28\x64\x00")


def test_query_fill_light_parses_brightness():
    led, mock = _controller_with_mock()
    mock.read.return_value = b"\x4c\x3c\x23"
    value = led.query_fill_light()
    mock.write.assert_called_once_with(b"\x4c\xff\x23")
    assert value == 60


def test_write_before_open_raises():
    led = serial_led.LedController("COM99")
    with pytest.raises(RuntimeError):
        led.set_color(1, 2, 3)


def test_led_port_label():
    p = serial_led.LedPort(device="COM3", description="USB Serial",
                           is_led_controller=True, version="FY-LED-V6.5")
    assert "COM3" in p.label
    assert "LED控制器" in p.label
    import i18n
    i18n.set_lang(i18n.EN)
    assert "LED controller" in p.label


def test_probe_in_place_fy_version():
    led, mock = _controller_with_mock()
    mock.read.return_value = b"FY-LED-V6.5"
    result = led.probe_in_place()
    assert result is not None
    assert result.is_led_controller
    assert "FY-LED" in result.version

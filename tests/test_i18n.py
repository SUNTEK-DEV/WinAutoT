"""i18n.py 单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import i18n


def setup_function():
    i18n.set_lang(i18n.ZH)


def teardown_function():
    i18n.set_lang(i18n.ZH)


def test_default_is_chinese():
    assert i18n.lang() == i18n.ZH
    assert "部件" in i18n.t("app.title")


def test_toggle_to_english_and_back():
    assert i18n.toggle_lang() == i18n.EN
    assert i18n.t("app.title").startswith("WinAutoTest")
    assert i18n.t("btn.lang") == "中文"
    assert i18n.toggle_lang() == i18n.ZH
    assert i18n.t("btn.lang") == "English"


def test_item_names_both_languages():
    assert i18n.item_name("camera") == "相机预览"
    i18n.set_lang(i18n.EN)
    assert i18n.item_name("camera") == "Camera preview"


def test_format_kwargs():
    text = i18n.t("led.connected", port="COM3", version="FY")
    assert "COM3" in text
    assert "FY" in text


def test_unknown_key_returns_key():
    assert i18n.t("no.such.key") == "no.such.key"


def test_status_and_method_labels():
    assert i18n.status_label("PENDING") == "待测"
    assert i18n.method_label("manual") == "人工"
    i18n.set_lang(i18n.EN)
    assert i18n.status_label("PENDING") == "Pending"
    assert i18n.method_label("auto") == "Auto"


def test_test_specs_cover_camera():
    ids = [item_id for item_id, _ in i18n.TEST_SPECS]
    assert "camera" in ids
    assert "led_red" in ids
    assert "scanner" in ids
    assert dict(i18n.TEST_SPECS)["scanner"] == "auto"


def test_zh_en_keys_match():
    assert set(i18n.STRINGS[i18n.ZH]) == set(i18n.STRINGS[i18n.EN])


def test_invalid_lang_rejected():
    import pytest
    with pytest.raises(ValueError):
        i18n.set_lang("fr")

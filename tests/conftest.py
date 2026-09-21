"""测试夹具：每个用例结束后还原界面语言。"""
from __future__ import annotations

import pytest

import i18n


@pytest.fixture(autouse=True)
def _reset_language():
    i18n.set_lang(i18n.ZH)
    yield
    i18n.set_lang(i18n.ZH)

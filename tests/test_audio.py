"""audio_test.py 信号处理单元测试（不依赖真实声卡）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_test


def test_rms_zero():
    assert audio_test._rms(np.zeros(1000)) == 0.0
    assert audio_test._rms(np.array([])) == 0.0


def test_rms_known_sine():
    t = np.linspace(0, 1, audio_test.SAMPLE_RATE, endpoint=False)
    sine = np.sin(2 * np.pi * 1000 * t) * 0.5
    rms = audio_test._rms(sine)
    assert abs(rms - 0.5 / np.sqrt(2)) < 0.01


def test_make_tone_shape_and_fade():
    tone = audio_test._make_tone(1000.0, 0.2, 0.6)
    assert tone.shape[0] == int(audio_test.SAMPLE_RATE * 0.2)
    assert tone[0] == 0.0
    assert abs(tone[-1]) < 1e-6
    assert np.max(np.abs(tone)) <= 0.6 + 1e-9


def test_loopback_pass_when_signal_present():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.001, size=(int(0.5 * audio_test.SAMPLE_RATE), 1)).astype(np.float32)
    t = np.linspace(0, 1.0, audio_test.SAMPLE_RATE, endpoint=False)
    rec = (np.sin(2 * np.pi * 1000 * t) * 0.2).astype(np.float32).reshape(-1, 1)

    with patch.object(audio_test, "_record", return_value=noise), \
         patch.object(audio_test.sd, "playrec", return_value=rec), \
         patch.object(audio_test.sd, "wait"):
        result = audio_test.run_loopback_test("left")
    assert result.passed
    assert result.channel == "left"
    assert result.snr_db > 6


def test_loopback_fail_when_silent():
    silence = np.zeros((audio_test.SAMPLE_RATE, 1), dtype=np.float32)
    with patch.object(audio_test, "_record", return_value=silence), \
         patch.object(audio_test.sd, "playrec", return_value=silence), \
         patch.object(audio_test.sd, "wait"):
        result = audio_test.run_loopback_test("right")
    assert not result.passed
    assert result.channel == "right"


def test_invalid_channel():
    import pytest
    with pytest.raises(ValueError):
        audio_test.run_loopback_test("center")


def test_loopback_fail_on_broadband_noise():
    """环境噪声能量够大但不是 1kHz，不能判 PASS。"""
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 0.001, size=(int(0.5 * audio_test.SAMPLE_RATE), 1)).astype(np.float32)
    rec = rng.normal(0, 0.2, size=(audio_test.SAMPLE_RATE, 1)).astype(np.float32)
    with patch.object(audio_test, "_record", return_value=noise), \
         patch.object(audio_test.sd, "playrec", return_value=rec), \
         patch.object(audio_test.sd, "wait"):
        result = audio_test.run_loopback_test("left")
    assert not result.passed
    assert "1kHz" in result.reason


def test_band_energy_ratio_on_1khz():
    t = np.linspace(0, 1, audio_test.SAMPLE_RATE, endpoint=False)
    sine = np.sin(2 * np.pi * 1000 * t)
    ratio = audio_test._band_energy_ratio(sine, 1000.0)
    assert ratio > 0.5


def test_summary_uses_fractional_rms():
    r = audio_test.LoopbackResult(
        channel="left", recorded_rms=0.023, noise_rms=0.001,
        snr_db=27.2, tone_peak_bin=21, passed=True, reason="ok")
    text = r.summary()
    assert "0.0230" in text
    assert "PASS" in text

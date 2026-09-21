"""音频测试模块：扬声器播放 + 麦克风录音回环自动检测。

检测原理：
1. 扬声器播放 1 kHz 测试音，同时通过麦克风录音；
2. 对录音计算 RMS、SNR，并检查 1 kHz 附近是否有频谱峰值；
3. 左右声道分别播放。单麦无法判定声道接反，接反需人工听音项确认。

人工项（听音确认）由 GUI 层组织，本模块只负责自动回环检测。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48000
# float32 量程 [-1, 1]。0.015 ≈ -36 dBFS，扬声器近场拾音通常远高于此
DEFAULT_RMS_THRESHOLD = 0.015
# 播放增益（0-1），防止大音量爆音
DEFAULT_PLAY_GAIN = 0.6


@dataclass
class AudioDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    hostapi: str

    @property
    def is_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def is_output(self) -> bool:
        return self.max_output_channels > 0


def list_audio_devices() -> list[AudioDeviceInfo]:
    """枚举可用的输入/输出设备（仅 WASAPI/MME 直通名称）。"""
    devices: list[AudioDeviceInfo] = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] == 0 and d["max_output_channels"] == 0:
            continue
        try:
            hostapi = sd.query_hostapis(d["hostapi"])["name"]
        except (IndexError, KeyError):
            hostapi = "?"
        devices.append(AudioDeviceInfo(
            index=i,
            name=str(d["name"]),
            max_input_channels=int(d["max_input_channels"]),
            max_output_channels=int(d["max_output_channels"]),
            hostapi=hostapi,
        ))
    return devices


def default_devices() -> tuple[int | None, int | None]:
    """返回 (默认输入设备索引, 默认输出设备索引)。"""
    try:
        dev = sd.default.device
        # sounddevice 返回 [input, output]，-1 表示无默认
        inp = int(dev[0]) if dev[0] is not None and int(dev[0]) >= 0 else None
        out = int(dev[1]) if dev[1] is not None and int(dev[1]) >= 0 else None
        return inp, out
    except Exception:
        return None, None


@dataclass
class LoopbackResult:
    """一次回环检测的结果。"""
    channel: str            # "left" / "right"
    recorded_rms: float     # 录音整体 RMS
    noise_rms: float        # 播放前底噪 RMS
    snr_db: float           # 信噪比
    tone_peak_bin: int      # 主频 bin（用于诊断）
    passed: bool
    reason: str = ""

    def summary(self) -> str:
        import i18n
        status = "PASS" if self.passed else "FAIL"
        return (f"[{status}] {self.channel}: RMS={self.recorded_rms:.4f} "
                f"{i18n.t('audio.noise')}={self.noise_rms:.4f} SNR={self.snr_db:.1f}dB "
                f"{self.reason}")


def _make_tone(freq: float, duration_s: float, gain: float) -> np.ndarray:
    """生成单声道测试音：正弦 + 端点淡入淡出，避免爆音。"""
    t = np.linspace(0.0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t) * gain
    # 20ms 淡入淡出
    fade = int(0.02 * SAMPLE_RATE)
    env = np.ones_like(wave)
    env[:fade] = np.linspace(0.0, 1.0, fade)
    env[-fade:] = np.linspace(1.0, 0.0, fade)
    return wave * env


def _record(duration_s: float, input_device: int | None,
            channels: int = 1) -> np.ndarray:
    recording = sd.rec(
        int(duration_s * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=channels,
        dtype="float32",
        device=input_device,
    )
    sd.wait()
    return recording


def _rms(signal: np.ndarray) -> float:
    if signal.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(signal.astype(np.float64)))))


def measure_input_rms(duration_s: float = 1.0,
                      input_device: int | None = None) -> float:
    """录一段环境/输入信号，返回 RMS（float32 量程）。"""
    rec = _record(duration_s, input_device)
    return _rms(rec[:, 0] if rec.ndim > 1 else rec)


def _dominant_frequency(signal: np.ndarray) -> int:
    spectrum = np.abs(np.fft.rfft(signal))
    return int(np.argmax(spectrum)) if spectrum.size else 0


def _tone_bin(freq: float, n_samples: int) -> int:
    return int(round(freq * n_samples / SAMPLE_RATE))


def _band_energy_ratio(signal: np.ndarray, freq: float = 1000.0,
                       half_width_hz: float = 80.0) -> float:
    """1 kHz 附近能量 / 全频谱能量。用于排除环境噪声误判。"""
    spectrum = np.abs(np.fft.rfft(signal.astype(np.float64))) ** 2
    total = float(np.sum(spectrum))
    if total <= 0:
        return 0.0
    center = _tone_bin(freq, signal.size)
    half = max(1, int(half_width_hz * signal.size / SAMPLE_RATE))
    lo = max(0, center - half)
    hi = min(spectrum.size, center + half + 1)
    return float(np.sum(spectrum[lo:hi]) / total)


def _stereo_tone(channel: str, duration_s: float, gain: float) -> np.ndarray:
    tone = _make_tone(1000.0, duration_s, gain)
    zeros = np.zeros_like(tone)
    if channel == "left":
        return np.column_stack([tone, zeros])
    if channel == "right":
        return np.column_stack([zeros, tone])
    return np.column_stack([tone, tone])


def play_manual_tone(channel: str = "both", duration_s: float = 2.0,
                     output_device: int | None = None,
                     gain: float = DEFAULT_PLAY_GAIN,
                     blocking: bool = True) -> None:
    """播放指定声道的 1kHz 测试音。blocking=False 时立即返回，需自行 sd.stop()。"""
    stereo = _stereo_tone(channel, duration_s, gain)
    sd.play(stereo, samplerate=SAMPLE_RATE, device=output_device, loop=not blocking)
    if blocking:
        sd.wait()


def stop_playback() -> None:
    try:
        sd.stop()
    except Exception:
        pass


def run_loopback_test(channel: str = "left",
                      input_device: int | None = None,
                      output_device: int | None = None,
                      gain: float = DEFAULT_PLAY_GAIN,
                      rms_threshold: float = DEFAULT_RMS_THRESHOLD,
                      snr_threshold_db: float = 6.0) -> LoopbackResult:
    """单声道回环自动检测。

    流程：录 0.5s 底噪 → 播放测试音同时录音 1.2s → 分析 RMS/SNR。
    channel: "left" / "right" / "both"
    """
    if channel not in ("left", "right", "both"):
        import i18n
        raise ValueError(i18n.t("audio.invalid_channel", channel=channel))

    # 1. 录底噪
    noise = _record(0.5, input_device)
    noise_rms = _rms(noise[:, 0] if noise.ndim > 1 else noise)

    # 2. 播放测试音 + 同步录音
    stereo = _stereo_tone(channel, 1.0, gain)

    recording = sd.playrec(
        stereo,
        samplerate=SAMPLE_RATE,
        channels=1,
        device=(input_device, output_device),
        dtype="float32",
        blocking=True,
    )

    # 3. 分析：去掉首尾 0.1s 过渡，取中段
    signal = recording[:, 0]
    margin = int(0.1 * SAMPLE_RATE)
    core = signal[margin:-margin] if signal.size > 2 * margin else signal
    signal_rms = _rms(core)

    snr_db = 20.0 * np.log10(max(signal_rms, 1e-9) / max(noise_rms, 1e-9))
    peak_bin = _dominant_frequency(core)
    tone_ratio = _band_energy_ratio(core, 1000.0)
    expected_bin = _tone_bin(1000.0, core.size)
    bin_tolerance = max(2, int(80.0 * core.size / SAMPLE_RATE))
    tone_ok = abs(peak_bin - expected_bin) <= bin_tolerance and tone_ratio >= 0.15

    passed = (signal_rms >= rms_threshold
              and snr_db >= snr_threshold_db
              and tone_ok)
    import i18n
    if passed:
        reason = i18n.t("audio.pickup_ok", ratio=tone_ratio)
    elif signal_rms < rms_threshold:
        reason = i18n.t("audio.rms_low", threshold=rms_threshold)
    elif not tone_ok:
        reason = i18n.t("audio.no_tone", peak=peak_bin, ratio=tone_ratio)
    else:
        reason = i18n.t("audio.snr_low", threshold=snr_threshold_db)

    return LoopbackResult(
        channel=channel,
        recorded_rms=signal_rms,
        noise_rms=noise_rms,
        snr_db=float(snr_db),
        tone_peak_bin=peak_bin,
        passed=passed,
        reason=reason,
    )

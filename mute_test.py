"""mute_test.py —— 测「系统静音时，回环还能不能录到声音」

用法：
    python mute_test.py            # 当前系统状态测一次
    （先别静音跑一次，再点静音跑一次，对比两次的 RMS）

会播放 1.5 秒 440Hz 提示音，同时录 2 秒回环，打印电平。
"""

from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np

from bot.config import ROOT, load_config


def make_tone(path: Path, rate: int = 16000, seconds: float = 1.5) -> None:
    t = np.arange(int(rate * seconds)) / rate
    tone = (0.25 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    pcm = (np.clip(tone, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main() -> int:
    cfg = load_config()
    tone_path = ROOT / "_tone.wav"
    make_tone(tone_path)

    try:
        import soundcard as sc
    except Exception as exc:
        print("缺少 soundcard：", exc)
        return 2

    name = str(cfg.get("audio_loopback_name") or "").strip()
    try:
        mic = sc.get_microphone(name, include_loopback=True) if name else sc.get_microphone(
            str(sc.default_speaker().name), include_loopback=True
        )
    except Exception as exc:
        print("拿不到回环设备 %r：%s" % (name, exc))
        return 2

    print("回环设备：%s" % mic.name)
    print("先播提示音，再录 2 秒……")

    import winsound

    winsound.PlaySound(str(tone_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    time.sleep(0.15)
    with mic.recorder(samplerate=48000) as rec:
        data = np.asarray(rec.record(numframes=48000 * 2))
    if data.ndim == 2:
        data = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(data))))
    peak = float(np.max(np.abs(data)))
    print("\n电平 RMS=%.5f  峰值=%.5f" % (rms, peak))

    if rms > 0.002:
        print("→ 现在能录到声音。把系统静音后再跑一次，对比这个数字：")
        print("   如果静音后还是 >0.002，你就可以直接静音跑；")
        print("   如果静音后变成 0.000x，就必须用 VB-CABLE 虚拟声卡。")
        return 0
    print("→ 没录到声音：要么设备名不对，要么系统已静音/音量为 0。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

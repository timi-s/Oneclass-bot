"""实验：比较 16k / 48k 回环录音的电平，确认采样率没把声音录丢"""

import time
import wave
from pathlib import Path

import numpy as np


def tone(path: Path, rate: int = 48000, seconds: float = 1.5) -> None:
    t = np.arange(int(rate * seconds)) / rate
    x = (0.25 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def capture(rate: int, wav: Path) -> float:
    import soundcard as sc
    import winsound

    mic = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
    winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
    time.sleep(0.15)
    with mic.recorder(samplerate=rate) as rec:
        data = np.asarray(rec.record(numframes=int(rate * 2)))
    if data.ndim == 2:
        data = data.mean(axis=1)
    return float(np.sqrt(np.mean(np.square(data))))


def main() -> None:
    p = Path("_tone48.wav")
    tone(p, 48000)
    for rate in (48000, 16000, 44100):
        try:
            rms = capture(rate, p)
            print("rate=%-6d RMS=%.5f" % (rate, rms))
        except Exception as exc:
            print("rate=%-6d 失败: %s" % (rate, exc))
    p.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

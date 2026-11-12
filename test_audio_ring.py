"""test_audio_ring.py —— 常驻录音环形缓冲 + 学习页自动放音的采集逻辑"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from bot.audio_solver import AudioRing

RATE = 16000


class FakeAudio:
    """capturing=True 时，collect 会先取缓冲快照。"""

    def __init__(self, captured: np.ndarray):
        self.captured = captured
        self.capturing = True
        self.calls = []

    def snapshot(self, seconds):
        self.calls.append(("snapshot", seconds))
        return self.captured

    def record_samples(self, click_speaker, seconds=None):
        self.calls.append(("record", seconds))
        click_speaker()
        return self.captured


def main() -> int:
    checks = []

    # 1) 环形缓冲只保留最近 N 秒
    ring = AudioRing(RATE, seconds=2.0)
    ring.push(np.zeros(RATE, dtype=np.float32))
    ring.push(np.full(RATE, 0.5, dtype=np.float32))
    snap = ring.snapshot(1.0)
    checks.append(("保留最近 1 秒", len(snap) == RATE and abs(float(snap.mean()) - 0.5) < 0.01,
                   (len(snap), round(float(snap.mean()), 2))))

    ring2 = AudioRing(RATE, seconds=1.0)
    for _ in range(5):
        ring2.push(np.full(RATE // 2, 0.3, dtype=np.float32))
    checks.append(("超出容量自动丢弃旧的", len(ring2.snapshot(2.0)) == RATE, len(ring2.snapshot(2.0))))

    # 2) 学习页：页面自动播放时，直接从缓冲里拿到声音，不必点喇叭
    from bot.windows_dpi import enable_dpi_awareness

    enable_dpi_awareness()
    from PIL import Image
    from bot.controller import WordBot
    from bot.vision import Vision

    sample = Path("learn_sample.jpg")
    if not sample.exists():
        print("缺少 learn_sample.jpg，跳过模板部分")
    else:
        img = Image.open(sample).convert("RGB")
        tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(RATE * 1.5) / RATE)).astype(np.float32)
        cfg = {
            "region": [0, 0, img.width, img.height],
            "loop_interval": 0.3,
            "after_click_delay": 0.1,
            "input_backend": "win32",
            "ocr_max_side": 512,
            "ocr_threads": 3,
            "audio_templates": True,
            "audio_capture": False,
            "audio_template_seconds": 1.5,
            "fallback_points": {"speaker": [0.5, 0.27]},
        }
        tmp = Path("_test_tmp")
        tmp.mkdir(exist_ok=True)
        bot = WordBot(cfg, tmp)
        bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
        bot.audio = FakeAudio(tone)
        bot.audio_index.templates.clear()
        items = bot.vision.read(img)
        bot.collect_audio_template(items, img)
        kinds = [c[0] for c in bot.audio.calls]
        checks.append(("自动放音时直接用缓冲", kinds[:1] == ["snapshot"], kinds))
        checks.append(("模板里出现 salary", "salary" in bot.audio_index.templates, list(bot.audio_index.templates)))
        shutil.rmtree(tmp, ignore_errors=True)

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nAUDIO_RING: %d/%d passed" % (ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""test_learn_speaker.py —— 学习页小喇叭定位 + 模板采集

学习页（背单词）的喇叭是音标行右边的小图标，不是听写页的大橙圆。
样本：learn_sample.jpg（你 13:20 拍的页面，单词 salary）
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import Vision

SAMPLE = Path("learn_sample.jpg")


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, w, h):
        self.clicks = []
        self.region = FakeRegion(w, h)

    def foreground_click_rel(self, nx, ny, delay=0.2):
        self.clicks.append((round(float(nx), 3), round(float(ny), 3)))

    def click_rel(self, nx, ny, delay=None):
        self.clicks.append((round(float(nx), 3), round(float(ny), 3)))

    def click_abs(self, x, y, delay=None):
        self.clicks.append((round(float(x)), round(float(y))))

    def capture(self):
        return Image.open(SAMPLE).convert("RGB")

    def save_debug(self, *a, **k):
        return Path(".")


class FakeAudio:
    def __init__(self):
        self.calls = 0
        self.capturing = False

    def snapshot(self, seconds):
        import numpy as np
        return np.zeros(0, dtype=np.float32)

    def record_samples(self, click_speaker, seconds=None):
        self.calls += 1
        click_speaker()
        t = np.arange(int(16000 * 1.2)) / 16000
        return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def make_bot(w, h):
    cfg = {
        "region": [0, 0, w, h],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "audio_templates": True,
        "audio_capture": False,
        "audio_template_seconds": 1.2,
        "fallback_points": {"speaker": [0.5, 0.27], "dictation_input": [0.49, 0.38]},
    }
    bot = WordBot(cfg, Path("_test_tmp"))
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(w, h)
    bot.audio = FakeAudio()
    bot.audio_index.templates.clear()
    return bot


def main() -> int:
    if not SAMPLE.exists():
        print("缺少 learn_sample.jpg，跳过")
        return 0

    img = Image.open(SAMPLE).convert("RGB")
    bot = make_bot(img.width, img.height)
    items = bot.vision.read(img)

    checks = []

    nx, ny = bot.learn_speaker_point(items, img)
    checks.append(("喇叭落在音标行右侧", 0.55 < nx < 0.85 and 0.27 < ny < 0.36, (round(nx, 3), round(ny, 3))))

    st = bot.detect_state(items)
    checks.append(("识别为 learn_hidden", st == "learn_hidden", st))

    bot.collect_audio_template(items, img)
    checks.append(("录了一次模板", bot.audio.calls == 1, bot.audio.calls))
    checks.append(("模板里出现 salary", "salary" in bot.audio_index.templates, list(bot.audio_index.templates)))

    # 同一个词不会重复录
    bot.collect_audio_template(items, img)
    checks.append(("不重复录同一个词", bot.audio.calls == 1, bot.audio.calls))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nLEARN_SPEAKER: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

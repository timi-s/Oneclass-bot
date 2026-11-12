"""test_dictation_once.py —— 同一道听写题只录一次，输入后直接点「确定」

场景：循环每 0.3 秒跑一轮，同一道听写页会被扫到很多次。
要求：只在第一次录音识别，之后复用识别结果；不做重复录音。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw, ImageFont

from bot.controller import WordBot
from bot.vision import Vision

DICT = Path("dictation_sample.png")


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, image):
        self.image = image.copy()
        self.record_calls = 0
        self.calls = []
        self.region = FakeRegion(image.width, image.height)

    def capture(self):
        return self.image

    def foreground_type_rel(self, nx, ny, text, delay=0.35, submit_key=None):
        self.calls.append(("type", text, submit_key))

    def press_key(self, key):
        self.calls.append(("key", key))

    def foreground_click_rel(self, nx, ny, delay=0.2):
        self.calls.append(("click", round(nx, 3), round(ny, 3)))
        d = ImageDraw.Draw(self.image)
        w, h = self.image.size
        d.rectangle([0, int(h * 0.155), w, int(h * 0.20)], fill="white")
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 34)
        d.text((int(w * 0.08), int(h * 0.90)), "下一词", font=font, fill="black")

    def click_abs(self, x, y, delay=None):
        self.calls.append(("click_abs", round(float(x))))

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("click_rel", round(float(nx), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


class FakeAudio:
    def __init__(self):
        self.records = 0
        self.capturing = False

    def snapshot(self, seconds):
        return np.zeros(0, dtype=np.float32)

    def record_after_click(self, click_speaker, seconds=None):
        self.records += 1
        click_speaker()
        return Path("_test_tmp/last.wav")

    def record_samples(self, click_speaker, seconds=None):
        self.records += 1
        click_speaker()
        t = np.arange(int(16000 * 1.0)) / 16000
        return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    def transcribe(self, path, vocab):
        return "cast", "cast"


def make_bot(image):
    cfg = {
        "region": [0, 0, image.width, image.height],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "dictation_mode": "whisper",
        "dictation_max_attempts": 1,
        "speech_match_threshold": 60,
        "audio_templates": False,
        "audio_capture": False,
        "fallback_points": {"speaker": [0.5, 0.27], "dictation_input": [0.49, 0.44],
                            "dictation_confirm": [0.49, 0.45]},
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(image)
    bot.audio = FakeAudio()
    return bot


def main() -> int:
    if not DICT.exists():
        print("缺少 dictation_sample.png，跳过")
        return 0

    img = Image.open(DICT).convert("RGB")
    bot = make_bot(img)
    items = bot.vision.read(img)

    # 同一页连续触发两次 handle_dictation
    bot.handle_dictation(items, img)
    first_records = bot.audio.records
    bot.handle_dictation(items, img)
    second_records = bot.audio.records

    checks = [
        ("第一次录了一次音", first_records == 1, first_records),
        ("第二次不再录音（复用结果）", second_records == 1, second_records),
        ("输入后按空格提交", any(c[0] == "type" and c[2] == "space" for c in bot.screen.calls), bot.screen.calls),
    ]

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nDICTATION_ONCE: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

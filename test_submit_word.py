"""test_submit_word.py —— 听写提交：敲字 → 空格上屏 → 点「确定」

中文输入法下，敲完字母框里还是“拼音”，必须按空格上屏；
之后才点「确定」真正提交。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import Vision

DICT = Path("dictation_sample.png")


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, image):
        self.image = image.copy()
        self.calls = []
        self.region = FakeRegion(image.width, image.height)

    def capture(self):
        return self.image

    def foreground_type_rel(self, nx, ny, text, delay=0.35, submit_key=None):
        self.calls.append(("type", round(nx, 3), round(ny, 3), text, submit_key))

    def press_key(self, key):
        self.calls.append(("key", key))

    def foreground_click_rel(self, nx, ny, delay=0.2):
        self.calls.append(("click", round(nx, 3), round(ny, 3)))

    def click_abs(self, x, y, delay=None):
        self.calls.append(("click_abs", round(float(x))))

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("click_rel", round(float(nx), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


def make_bot(image):
    cfg = {
        "region": [0, 0, image.width, image.height],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "dictation_submit_key": "space",
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
    return bot


def main() -> int:
    if not DICT.exists():
        print("缺少 dictation_sample.png，跳过")
        return 0

    img = Image.open(DICT).convert("RGB")
    bot = make_bot(img)
    items = bot.vision.read(img)

    bot.submit_word(items, img, "cast")
    calls = bot.screen.calls
    kinds = [c[0] for c in calls]

    checks = [
        ("只敲了一次字", kinds.count("type") == 1, kinds),
        ("敲字后按空格上屏", calls and calls[0][4] == "space", calls),
        ("然后点了「确定」", kinds == ["type", "click"], kinds),
        ("确定点落在按钮上", abs(calls[-1][1] - 0.507) < 0.06 and abs(calls[-1][2] - 0.539) < 0.08,
         calls[-1]),
    ]

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nSUBMIT_WORD: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

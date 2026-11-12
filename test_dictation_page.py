"""test_dictation_page.py —— 用你 12:21 的听写页截图验证：
   1) 识别为 test_dictation
   2) 喇叭能被颜色定位（不依赖手工校准）
   3) 输入位置能落在「请填写你听到的单词」那行
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import Vision


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, w, h):
        self.clicked = []
        self.region = FakeRegion(w, h)

    def click_abs(self, x, y, delay=None):
        self.clicked.append((round(float(x)), round(float(y))))

    def click_rel(self, nx, ny, delay=None):
        self.clicked.append((round(float(nx), 3), round(float(ny), 3)))

    def foreground_click_rel(self, nx, ny, delay=None):
        self.clicked.append((round(float(nx), 3), round(float(ny), 3)))

    def foreground_fill_and_click_abs(self, ix, iy, word, cx, cy):
        self.clicked.append(("fill", word, round(ix), round(iy), round(cx), round(cy)))

    def save_debug(self, *a, **k):
        return Path(".")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dictation_sample.png")
    if not path.exists():
        print("缺少样本截图 %s，跳过" % path)
        return 0

    img = Image.open(path).convert("RGB")
    vision = Vision(1.0, 0.45, 512, 3, False, False)
    items = vision.read(img)
    print("OCR：", [i.text[:20] for i in items])

    cfg = {
        "region": [0, 0, img.width, img.height],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "dictation_mode": "reveal",
        "fallback_points": {"speaker": [0.5, 0.27], "dictation_input": [0.49, 0.38]},
    }
    tmp = Path("_test_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    bot = WordBot(cfg, tmp)
    bot.vision = vision
    bot.screen = FakeScreen(img.width, img.height)

    checks = []
    state = bot.detect_state(items)
    checks.append(("识别为 test_dictation", state == "test_dictation", state))

    sp = bot.speaker_point(items, img)
    checks.append(("颜色定位到喇叭", abs(sp[0] - 0.507) < 0.06 and abs(sp[1] - 0.338) < 0.06, sp))

    ip = bot.input_point(items, img)
    checks.append(("输入点在喇叭与确定之间", 0.38 < ip[1] < 0.52, ip))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nDICTATION: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(tmp)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

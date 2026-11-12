"""test_exam_start.py —— 任务说明页（「开始测验」）识别与点击

用合成页面，不依赖外部截图：609x1063，底部有「开始测验」按钮。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw, ImageFont

from bot.controller import WordBot
from bot.vision import Vision

W, H = 609, 1063
BTN = (300, 1039)


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, w, h):
        self.calls = []
        self.region = FakeRegion(w, h)
        self._img = Image.new("RGB", (w, h), "white")

    def capture(self):
        return self._img

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("click", round(float(nx) * W), round(float(ny) * H)))

    def click_abs(self, x, y, delay=None):
        self.calls.append(("click", round(float(x)), round(float(y))))

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("click", round(float(nx) * W), round(float(ny) * H)))

    def save_debug(self, *a, **k):
        return Path(".")


def make_page() -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
    small = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 18)
    d.text((190, 340), "背单词", font=font, fill="black")
    d.text((30, 960), "*单词背诵/考试后开始不可以中途退出，否则无法保存学习/考试记录", font=small, fill="black")
    d.text((BTN[0] - 45, BTN[1] - 14), "开始测验", font=font, fill="black")
    return img


def main() -> int:
    img = make_page()
    cfg = {
        "region": [0, 0, W, H],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"start_memorize": [0.5, 0.95]},
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")

    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(W, H)
    items = bot.vision.read(img)
    print("OCR：", [i.text[:26] for i in items])

    checks = []
    st = bot.detect_state(items)
    checks.append(("说明页识别为 exam_start", st == "exam_start", st))

    bot.act(st, items, img)
    click = bot.screen.calls[-1] if bot.screen.calls else None
    checks.append(("点了「开始测验」", click is not None and abs(click[1] - BTN[0]) < 40
                   and abs(click[2] - BTN[1]) < 40, click))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nEXAM_START: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

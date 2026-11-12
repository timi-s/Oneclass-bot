"""test_detail_page.py —— 单词详情页（释义/例句/下一词）不能被当成隐藏释义页

现场现象：页面已经是「allege + 释义 + 例句 + 下一词」的详情页，
但底部橙色「下一词」OCR 认不到，于是被判成 learn_hidden，
脚本一直点空白 → 卡 80 多秒不动。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import Vision

SAMPLE = Path("sample_detail.png")


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

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("rel", round(float(nx), 3), round(float(ny), 3)))

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


def make_bot(image):
    cfg = {
        "region": [0, 0, image.width, image.height],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "verify_clicks": True,
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "mark_too_easy": True,
        "fallback_points": {"next_word": [0.5, 0.955], "know": [0.5, 0.9],
                            "reveal_answer": [0.5, 0.53]},
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
    checks = []
    img = Image.open(SAMPLE).convert("RGB")
    bot = make_bot(img)
    items = bot.vision.read(img)
    text = bot.vision.joined(items)

    checks.append(("识别到例句/释义", ("例句" in text) or ("释义" in text), text[:60]))
    checks.append(("判为 learn_detail（不是 learn_hidden）",
                   bot.detect_state(items) == "learn_detail", bot.detect_state(items)))

    # 详情页动作：应该点「下一词」（OCR 找不到就用兜底坐标，y 接近底部）
    bot.act("learn_detail", items, img)
    calls = bot.screen.calls
    hit_next = any(
        (c[0] == "abs" and c[2] > 0.85 * img.height)
        or (c[0] == "fg" and c[2] > 0.85)
        or (c[0] == "rel" and c[2] > 0.85)
        for c in calls
    )
    checks.append(("点了「下一词」而不是点空白", hit_next, calls))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nDETAIL_PAGE: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

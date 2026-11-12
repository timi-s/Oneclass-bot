"""test_choice_once.py —— 选择题答完只答一次，之后只翻页

你截图里的现象：答对后页面停在反馈态（底部「下一词」没被 OCR 认到），
状态还是 test_choice，脚本每 5 秒把同一题再答一遍。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import OCRItem, Vision

W, H = 609, 1063


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, w, h):
        self.calls = []
        self.region = FakeRegion(w, h)
        self.image = Image.new("RGB", (w, h), "white")

    def capture(self):
        return self.image

    def click_abs(self, x, y, delay=None):
        self.calls.append(("click_abs", round(float(x)), round(float(y))))

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("click_rel", round(float(nx), 3), round(float(ny), 3)))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fclick", round(float(nx), 3), round(float(ny), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


def page_items() -> list[OCRItem]:
    def item(text, y, x=280, w=240, h=34):
        return OCRItem(text, 0.95, x - w / 2, y - h / 2, x + w / 2, y + h / 2)

    return [
        item("单词测试5/100", 120, 280, 240, 40),
        item("请选择正确的释义", 180, 280, 300, 40),
        item("sunlight", 330, 280, 200, 70),
        item("v. 秘密的，机密的", 480, 300, 380, 40),
        item("v. 拉，拖；开具", 580, 300, 380, 40),
        item("n. 大学", 680, 300, 300, 40),
        item("n. 日光，阳光", 780, 300, 380, 40),
        item("下一词", 1020, 280, 200, 40),
    ]


def make_bot(w, h):
    cfg = {
        "region": [0, 0, w, h],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "choice_match_threshold": 42,
        "unknown_choice_strategy": "pause",
        "fallback_points": {"next_word": [0.5, 0.955]},
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(w, h)
    return bot


def main() -> int:
    bot = make_bot(W, H)
    items = page_items()
    img = bot.screen.image

    checks = []
    checks.append(("词库里有 sunlight", bool(bot.vocab.definition("sunlight")), bot.vocab.definition("sunlight")))

    # 第一次：正常作答（点选项）
    bot.act("test_choice", items, img)
    first = list(bot.screen.calls)
    checks.append(("第一次点了一个选项", any(c[0] == "click_abs" for c in first), first))

    # 第二次：同一页 → 不再作答，只翻页
    bot.act("test_choice", items, img)
    new_calls = bot.screen.calls[len(first):]
    option_clicks = [c for c in new_calls if c[0] == "click_abs" and abs(c[2] - 780) < 60]
    checks.append(("第二次没再点选项", not option_clicks, new_calls))
    flipped = [c for c in new_calls if (c[0] == "click_abs" and abs(c[2] - 1020) < 60)
               or (c[0] == "fclick" and abs(c[2] - 0.96) < 0.06)]
    checks.append(("第二次点了「下一词」", bool(flipped), new_calls))

    # 超过 25 秒后允许重新判断
    bot._choice_at = time.monotonic() - 30
    bot.act("test_choice", items, img)
    after = bot.screen.calls[len(first) + len(new_calls):]
    checks.append(("超时后允许重新作答", any(c[0] == "click_abs" for c in after), after))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nCHOICE_ONCE: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

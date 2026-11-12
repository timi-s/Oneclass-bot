"""test_stuck_pages.py —— 卡住时的自救：加载中等待、连续没推进强制重点、选项文字没认全"""

from __future__ import annotations

import shutil
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
        self.image = Image.new("RGB", (w, h), "white")
        self.calls = []
        self.region = FakeRegion(w, h)

    def capture(self):
        return self.image

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("rel", round(float(nx), 3), round(float(ny), 3)))

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3), clicks))

    def save_debug(self, *a, **k):
        return Path(".")


def item(text, y, x=280, w=300, h=34):
    return OCRItem(text, 0.95, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def make_bot():
    cfg = {
        "region": [0, 0, W, H],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "choice_match_threshold": 42,
        "unknown_choice_strategy": "pause",
        "mark_too_easy": True,
        "foreground_keywords": ["不存在的窗口标题"],
        "fallback_points": {
            "reveal_answer": [0.5, 0.53], "know": [0.5, 0.9],
            "next_word": [0.5, 0.955], "unknown": [0.5, 0.975],
        },
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(W, H)
    return bot


def main() -> int:
    checks = []

    # 1) 页面显示「资源玩命加载中」→ 不点击，只等待
    bot = make_bot()
    loading = [item("背单词", 60, 280, 200, 40), item("资源玩命加载中...", 900, 280, 380, 40)]
    bot.act("learn_hidden", loading, bot.screen.image)
    checks.append(("加载中不点击", bot.screen.calls == [], bot.screen.calls))

    # 2) 同一页连续多轮没推进 → 强制真实鼠标重点
    bot2 = make_bot()
    bot2._state_repeat = 3
    page = [item("背单词", 60), item("jet", 330, 280, 160, 70),
            item("英:[dʒet]", 420, 280, 300, 40), item("美：[dʒet]", 470, 280, 300, 40),
            item("-请跟读并默念单词释义点击屏幕显示答案-", 520, 300, 460, 40)]
    bot2.act("learn_hidden", page, bot2.screen.image)
    fg = [c for c in bot2.screen.calls if c[0] == "fg"]
    checks.append(("连续没推进时强制重点", len(fg) >= 1, bot2.screen.calls))

    # 3) 选项文字没认全（全是「小」）→ 不做选择，等重认
    bot3 = make_bot()
    garbage = [item("单词测试5/100", 120), item("请选择正确的释义", 180),
               item("criminal", 330, 280, 220, 70),
               item("小", 480), item("小", 580), item("小", 680)]
    before = len(bot3.screen.calls)
    bot3.act("test_choice", garbage, bot3.screen.image)
    new_calls = bot3.screen.calls[before:]
    checks.append(("选项没认全时不乱点", new_calls == [] , new_calls))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nSTUCK_PAGES: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""test_revealed_stuck.py —— 显示答案后按钮是浅灰字，OCR 认不到时不能一直卡住

现象：页面已经出现「认识/模糊/不认识」，但主 OCR 阈值太高没认到「认识」，
状态退回 learn_hidden，脚本一直点空白，永远不点「认识」。
要求：连续卡住时用低阈值重认，一旦认出「认识」就点它。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import OCRItem

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
        self.calls.append(("rel", round(float(nx), 3)))

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


class TwoLevelVision:
    """主阈值只认到提示行；低阈值才认到「认识」按钮。"""

    def __init__(self):
        self.min_score = 0.45

    def read(self, image):
        return []

    def joined(self, items):
        return ""

    def main_word(self, items, height, band):
        return None

    def find(self, items, *texts):
        for it in items:
            if any(t in it.text for t in texts):
                return it
        return None


class StubVision(TwoLevelVision):
    def read(self, image):
        if self.min_score <= 0.35:
            return [OCRItem("认识", 0.9, 200, 900, 400, 950)]
        return []

    def joined(self, items):
        return "|".join(i.text for i in items)


def item(text, y, x=300, w=300, h=40):
    return OCRItem(text, 0.95, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def make_bot(vision):
    cfg = {
        "region": [0, 0, W, H],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "keep_foreground_seconds": 5,
        "auto_foreground": True,
        "fallback_points": {"reveal_answer": [0.5, 0.53], "know": [0.5, 0.9]},
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = vision
    bot.screen = FakeScreen(W, H)
    return bot


def main() -> int:
    checks = []

    # 页面已经有「认识」按钮，但主阈值没认出来（joined 只有提示行）
    page = [item("背单词", 60), item("publicity", 330, 300, 200, 70),
            item("英:[pab'lɪsəti]", 420, 300, 320, 40),
            item("-请跟读并默念单词释义点击屏幕显示答案-", 470, 300, 460, 40)]

    bot = make_bot(StubVision())
    bot._state_repeat = 2          # 模拟已经卡了两轮
    bot.act("learn_hidden", page, bot.screen.image)
    calls = bot.screen.calls
    clicked_know = any(c[0] == "abs" and abs(c[2] - 925) < 60 for c in calls)
    checks.append(("低阈值认出「认识」后点了它", clicked_know, calls))

    # 完全没有「认识」按钮时，仍走强制重点逻辑（不会乱点 认识）
    class NoKnowVision(StubVision):
        def read(self, image):
            return []

        def joined(self, items):
            return ""

    bot2 = make_bot(NoKnowVision())
    bot2._state_repeat = 2
    bot2.act("learn_hidden", page, bot2.screen.image)
    c2 = bot2.screen.calls
    checks.append(("没认出按钮时仍然重点空白", any(c[0] == "fg" for c in c2), c2))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nREVEALED_STUCK: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

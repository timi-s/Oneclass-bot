"""test_too_easy_click.py —— 背单词时优先点右上角「标记为太简单（无需复习）」

用户要求：背单词页面点「无需复习」，而不是点「认识」。
但那个位置有时只是状态标签（点了没反应），所以必须校验画面，
点不动就退回「认识」，不能让页面卡住。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw

from bot.controller import WordBot
from bot.vision import OCRItem, Vision

W, H = 451, 1017


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    """too_easy_works=True 时，点右上角区域会让画面变化。"""

    def __init__(self, too_easy_works: bool):
        self.image = Image.new("RGB", (W, H), "white")
        self.too_easy_works = too_easy_works
        self.calls = []
        self.region = FakeRegion(W, H)

    def capture(self):
        return self.image

    def _change(self):
        d = ImageDraw.Draw(self.image)
        d.rectangle([0, 0, 30, 30], fill="black")

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))
        if self.too_easy_works and y < 300:      # 右上角标签
            self._change()

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("rel", round(float(nx), 3), round(float(ny), 3)))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3)))
        if self.too_easy_works and ny < 0.3:
            self._change()

    def save_debug(self, *a, **k):
        return Path(".")


def page_items():
    def item(text, y, x=222, w=380, h=34):
        return OCRItem(text, 0.95, x - w / 2, y - h / 2, x + w / 2, y + h / 2)

    return [
        item("背单词", 60, 222, 200, 40),
        item("标记为太简单", 180, 376, 170, 30),
        item("adapt", 300, 222, 200, 60),
        item("英:[ə'dæpt]", 400, 222, 300, 36),
        item("v. (使)适应；改编", 500, 222, 320, 40),
        item("认识", 844),
        item("模糊", 904),
        item("不认识", 965),
    ]


def make_bot(too_easy_works: bool):
    cfg = {
        "region": [0, 0, W, H],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "verify_clicks": True,
        "mark_too_easy": True,
        "audio_templates": False,
        "audio_capture": False,
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"know": [0.5, 0.83], "next_word": [0.5, 0.955]},
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(too_easy_works)
    return bot


def main() -> int:
    checks = []

    # 情况 A：点「无需复习」有效 → 点它，不点「认识」
    bot = make_bot(True)
    items = page_items()
    handled = bot.click_too_easy(items, bot.screen.image)
    calls = bot.screen.calls
    checks.append(("点的是右上角「标记为太简单」", any(c[0] == "abs" and c[2] < 300 for c in calls), calls))
    checks.append(("点成功返回 True", handled is True, handled))
    checks.append(("没有点「认识」", not any(c[0] == "abs" and c[2] > 800 for c in calls), calls))

    # 情况 B：点「无需复习」没反应 → 返回 False，交给「认识」
    bot2 = make_bot(False)
    handled2 = bot2.click_too_easy(page_items(), bot2.screen.image)
    checks.append(("点不动时返回 False", handled2 is False, handled2))
    checks.append(("点不动时尝试过真实鼠标", any(c[0] == "fg" for c in bot2.screen.calls),
                   bot2.screen.calls))

    # 情况 C：页面没有该标签 → 直接 False，不瞎点
    bot3 = make_bot(False)
    no_label = [i for i in page_items() if "标记" not in i.text]
    checks.append(("没有标签时不动作", bot3.click_too_easy(no_label, bot3.screen.image) is False,
                   bot3.screen.calls))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nTOO_EASY_CLICK: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""test_click_verify.py —— 后台点击按钮没生效时要改用真实鼠标再点一次

小程序的按钮（认识 / 标记为太简单 / 下一词）经常不吃 Win32 后台消息，
现象就是日志里一直「点击文字 认识」，但页面永远不动。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw

from bot.controller import WordBot
from bot.vision import OCRItem, Vision

W, H = 600, 1000


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    """后台点击不生效；只有真实鼠标点击才会让画面变化。"""

    def __init__(self, w, h):
        self.image = Image.new("RGB", (w, h), "white")
        self.calls = []
        self.region = FakeRegion(w, h)

    def capture(self):
        return self.image

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("rel", round(float(nx), 3)))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3), clicks))
        d = ImageDraw.Draw(self.image)
        d.rectangle([0, 0, 40, 40], fill="black")     # 真实点击让画面变化

    def save_debug(self, *a, **k):
        return Path(".")


def make_bot():
    cfg = {
        "region": [0, 0, W, H],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "verify_clicks": True,
        "auto_foreground": True,
        "foreground_keywords": ["不存在的窗口"],
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"know": [0.5, 0.85]},
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
    bot = make_bot()
    items = [OCRItem("认识", 0.95, 200, 600, 400, 660)]
    checks = []

    bot.click_text(items, "认识")
    calls = bot.screen.calls
    checks.append(("先试了后台点击", any(c[0] == "abs" for c in calls), calls))
    checks.append(("后台没生效后改用真实鼠标", any(c[0] == "fg" for c in calls), calls))
    fg = [c for c in calls if c[0] == "fg"]
    checks.append(("真实点击坐标正确", bool(fg) and abs(fg[0][1] - 0.5) < 0.05 and abs(fg[0][2] - 0.63) < 0.08,
                   fg))

    # 关掉校验时不应该有多余动作
    bot2 = make_bot()
    bot2.cfg["verify_clicks"] = False
    bot2.click_text(items, "认识")
    checks.append(("关闭校验时只点一次",
                   [c[0] for c in bot2.screen.calls] == ["abs"], bot2.screen.calls))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nCLICK_VERIFY: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

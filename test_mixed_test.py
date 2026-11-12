"""test_mixed_test.py —— 验证「听写题 / 选择题交替」时不会串台

真实页面：单词测试 N/100，两种题混着出。
- 听写页：请填写你听到的单词 + 橙色喇叭 + 确定 + 我不会
- 选择题页：选择正确的释义 + 四个释义选项
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import Vision

CHOICE = Path("logs/unknown_20261109_085358.png")   # 选择题页
DICT = Path("dictation_sample.png")                  # 听写页


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

    def foreground_fill_and_click_abs(self, *a):
        pass

    def save_debug(self, *a, **k):
        return Path(".")


def build(w, h, cfg_extra=None):
    cfg = {
        "region": [0, 0, w, h],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "dictation_mode": "reveal",
        "unknown_choice_strategy": "pause",
        "choice_match_threshold": 42,
        "fallback_points": {"speaker": [0.5, 0.27], "dictation_input": [0.49, 0.38]},
    }
    cfg.update(cfg_extra or {})
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.screen = FakeScreen(w, h)
    return bot


def main() -> int:
    checks = []

    # 选择题页
    if CHOICE.exists():
        img = Image.open(CHOICE).convert("RGB")
        v = Vision(1.0, 0.45, 512, 3, False, False)
        items = v.read(img)
        bot = build(img.width, img.height)
        bot.vision = v
        st = bot.detect_state(items)
        route = bot.route_test(items, img)
        checks.append(("选择题页 → test_choice", st == "test_choice", st))
        checks.append(("选择题页路由到 choice", route == "choice", route))
        bot.act(st, items, img)
        checks.append(("选择题点中了选项", any(isinstance(c, tuple) and len(c) == 2 for c in bot.screen.clicked),
                       bot.screen.clicked[-1] if bot.screen.clicked else None))
    else:
        print("跳过选择题样本（缺 %s）" % CHOICE)

    # 听写页
    if DICT.exists():
        img = Image.open(DICT).convert("RGB")
        v = Vision(1.0, 0.45, 512, 3, False, False)
        items = v.read(img)
        bot = build(img.width, img.height)
        bot.vision = v
        st = bot.detect_state(items)
        route = bot.route_test(items, img)
        checks.append(("听写页 → test_dictation", st == "test_dictation", st))
        checks.append(("听写页路由到 dictation", route == "dictation", route))
    else:
        print("跳过听写样本（缺 %s）" % DICT)

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nMIXED_TEST: %d/%d passed" % (ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

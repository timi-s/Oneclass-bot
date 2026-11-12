"""test_route_test.py —— 听写页不能被当成选择题，否则只会跳题（点我不会）

现场现象：
    页面状态：test_dictation | OCR=…|单词测试0/50|请填写你听到的单词|9|确定|我不会
    页面有选项 → 按选择题处理          ← route_test 把「9 / 确定 / 我不会」当成 3 个选项
    未识别到题目单词；unknown_choice_strategy=pause
    → 暂停 12 秒 → 自动点「我不会」→ 看起来就是“只会选下一个”
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import OCRItem, Vision

W, H = 596, 1117


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
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


def item(text, y, x=298, w=420, h=36):
    return OCRItem(text, 0.95, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def make_bot():
    cfg = {
        "region": [0, 0, W, H],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "verify_clicks": True,
        "dictation_mode": "whisper",
        "dictation_max_attempts": 1,
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"next_word": [0.5, 0.955], "unknown": [0.5, 0.975]},
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

    # 真实听写页的 OCR 内容（含 数字/确定/我不会/加载中）
    dictation_items = [
        item("背单词", 60),
        item("单词测试0/50", 120),
        item("请填写你听到的单词", 190),
        item("9", 330, 298, 60, 80),
        item("确定", 640),
        item("资源玩命加载中...", 760),
        item("我不会", 1040),
    ]
    checks = []
    checks.append(("听写页判为 dictation", bot.route_test(dictation_items, bot.screen.image) == "dictation",
                   bot.route_test(dictation_items, bot.screen.image)))

    # 只有数字/确定/我不会 也不能算选择题
    sparse = [item("背单词", 60), item("9", 300, 298, 60, 80), item("确定", 600),
              item("我不会", 1000)]
    checks.append(("零散文字不算选择题", bot.route_test(sparse, bot.screen.image) == "dictation",
                   bot.route_test(sparse, bot.screen.image)))

    # 真正的选择题：4 行像样的释义
    choice_items = [
        item("单词测试5/60", 120),
        item("请选择正确的释义", 190),
        item("sunlight", 330, 298, 200, 70),
        item("n. 日光，阳光", 500),
        item("v. 拉，拖；开具", 600),
        item("n. 大学", 700),
        item("v. 收集，采集", 800),
    ]
    checks.append(("选择题判为 choice", bot.route_test(choice_items, bot.screen.image) == "choice",
                   bot.route_test(choice_items, bot.screen.image)))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nROUTE_TEST: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

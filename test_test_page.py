"""test_test_page.py —— 用真实截图验证「单词测试」页面能被识别并作答

样本：logs\\unknown_20261109_085358.png（2026-11-09 08:53:58 保存的测试题页面）
页面文字：词测试0/100 / 选择正确的释义 / calm / 四个释义选项
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import OCRItem, Vision

SAMPLE = Path(r"logs\unknown_20261109_085358.png")


class FakeRegion:
    def __init__(self, height):
        self.height = height


class FakeScreen:
    def __init__(self, height=1052):
        self.clicked = []
        self.region = FakeRegion(height)

    def click_abs(self, x, y, delay=None):
        self.clicked.append((round(float(x)), round(float(y))))

    def click_rel(self, nx, ny, delay=None):
        self.clicked.append((round(float(nx), 2), round(float(ny), 2)))

    def save_debug(self, *a, **k):
        return Path(".")


def main() -> int:
    if not SAMPLE.exists():
        print("缺少样本截图，跳过：", SAMPLE)
        return 0

    img = Image.open(SAMPLE).convert("RGB")
    vision = Vision(1.0, 0.45, 512, 3, False, False)
    items = vision.read(img)

    cfg = {
        "region": [0, 0, img.width, img.height],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "unknown_choice_strategy": "pause",
        "choice_match_threshold": 42,
        "ocr_max_side": 512,
        "ocr_threads": 3,
    }
    tmp = Path("_test_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    shutil.copy("vocab.json", tmp / "vocab.json")   # 用真实词库，calm 在里面
    bot = WordBot(cfg, tmp)
    bot.vision = vision
    bot.screen = FakeScreen()

    checks = []
    state = bot.detect_state(items)
    checks.append(("测试页被识别为 test_choice", state == "test_choice", state))

    bottom_next = OCRItem("下一词", 1.0, 180, img.height - 60, 320, img.height - 10)
    bottom_done = OCRItem("完成", 1.0, 180, img.height - 60, 320, img.height - 10)
    s2 = bot.detect_state(items + [bottom_next])
    s3 = bot.detect_state(items + [bottom_done])
    checks.append(("答题后反馈页 → choice_feedback", s2 == "choice_feedback", s2))
    checks.append(("最后一题反馈页 → choice_feedback_final", s3 == "choice_feedback_final", s3))

    bot.handle_choice(items, img)
    clicked = bot.screen.clicked[-1] if bot.screen.clicked else None
    checks.append(("选中「adj. 静的，平静的」", clicked is not None and abs(clicked[0] - 238) < 12
                   and abs(clicked[1] - 658) < 12, clicked))

    # 选项还没加载出来时不能乱点、也不能触发 input() 阻塞
    bot.screen.clicked.clear()
    only_word = [it for it in items if it.text.strip().lower() == "calm"]
    bot.handle_choice(only_word, img)
    checks.append(("选项未加载时不下手", not bot.screen.clicked, bot.screen.clicked))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nTESTPAGE: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(tmp)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

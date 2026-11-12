"""test_guard.py —— 验证「黑屏 / 卡死保护」：
   1) 黑屏、纯白能被识别成 blank，正常页面不会
   2) 黑屏时只告警不点击，并尝试置前窗口（找不到窗口也不能崩）
   3) 画面长时间不动会周期性提醒
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw

from bot.controller import WordBot


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def page() -> Image.Image:
    img = Image.new("RGB", (536, 1049), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 300), "abandon", fill="black")
    d.rectangle([0, 900, 536, 1049], fill="#dddddd")
    return img


def main() -> int:
    cfg = {
        "region": [0, 0, 536, 1049],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 256,
        "ocr_threads": 2,
        "auto_foreground": True,
        "foreground_keywords": ["绝不存在的窗口标题xyz"],
        "stall_warn_seconds": 30,
        "debug": False,
    }
    bot = WordBot(cfg, Path("_test_tmp"))
    Path("_test_tmp").mkdir(exist_ok=True)

    black = Image.new("RGB", (536, 1049), "black")
    white = Image.new("RGB", (536, 1049), "white")

    checks = []
    checks.append(("全黑判定为 blank", bot.is_blank(black)))
    checks.append(("纯白判定为 blank", bot.is_blank(white)))
    checks.append(("正常页面不是 blank", not bot.is_blank(page())))

    # 黑屏处理：不应抛异常，应记录起始时间与告警
    bot._handle_blank(black)
    checks.append(("黑屏记录起始时间", bot._blank_since is not None))
    checks.append(("黑屏尝试置前不崩溃", True))

    # 卡死提醒
    cap = Capture()
    logging.getLogger("wordbot").addHandler(cap)
    bot.last_state = "learn_hidden"
    bot._stall_since = time.monotonic() - 40
    bot._check_stall()
    first = len([x for x in cap.lines if "没有变化" in x])
    bot._check_stall()  # 立刻再调一次，应被节流
    second = len([x for x in cap.lines if "没有变化" in x])
    logging.getLogger("wordbot").removeHandler(cap)
    checks.append(("静止 40 秒会告警", first == 1, first))
    checks.append(("15 秒内不重复刷屏", second == 1, second))

    # 正常帧应重置黑屏计时（模拟 run() 里的逻辑）
    if not bot.is_blank(page()):
        bot._blank_since = None
    checks.append(("恢复画面后重置计时", bot._blank_since is None))

    # 静止过久 → 暂停点击
    bot.cfg["stall_pause_seconds"] = 90
    bot._stall_since = time.monotonic() - 10
    checks.append(("静止 10 秒不暂停点击", bot.should_pause_clicking() is False))
    bot._stall_since = time.monotonic() - 100
    checks.append(("静止 100 秒暂停点击", bot.should_pause_clicking() is True))
    bot._stall_since = None
    checks.append(("画面恢复后解除暂停", bot.should_pause_clicking() is False))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nGUARD: %d/%d passed" % (ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""test_gate.py —— 验证「画面没变就跳过 OCR」的闸门逻辑"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw

from bot.controller import WordBot


def page(text: str) -> Image.Image:
    img = Image.new("RGB", (460, 1061), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 300), text, fill="black")
    return img


def main() -> int:
    cfg = {
        "region": [0, 0, 460, 1061],
        "loop_interval": 0.1,
        "ocr_recheck_seconds": 0.3,
        "ocr_skip_static": True,
        "ocr_scale": 1.0,
        "ocr_max_side": 256,
        "ocr_threads": 2,
        "ocr_use_cls": False,
        "after_click_delay": 0.1,
        "input_backend": "win32",
    }
    bot = WordBot(cfg, Path(".").resolve())
    a = page("A")
    b = page("B")

    results = []
    results.append(("第一帧必须 OCR", bot.should_ocr(a) is True))
    results.append(("同一帧第二三帧跳过", bot.should_ocr(a) is False and bot.should_ocr(a) is False))
    results.append(("换画面必须 OCR", bot.should_ocr(b) is True))
    results.append(("换了之后同帧跳过", bot.should_ocr(b) is False))

    # 静止超过 recheck 秒后强制再认一次
    forced = False
    for _ in range(6):
        if bot.should_ocr(b):
            forced = True
            break
        time.sleep(0.1)
    results.append(("静止超时后强制 OCR", forced))

    # 关掉跳过功能 → 永远 OCR
    bot.cfg["ocr_skip_static"] = False
    results.append(("关闭开关后每帧都 OCR", bot.should_ocr(b) is True and bot.should_ocr(b) is True))

    ok = 0
    for name, cond in results:
        print(("  OK   " if cond else "  FAIL ") + name)
        ok += 1 if cond else 0
    print("\nGATE: %d/%d passed" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

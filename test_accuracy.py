"""test_accuracy.py —— 验证「正确率抓取」：OCR 文本 → 正则 → accuracy.csv"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from bot.controller import WordBot

SAMPLES = [
    ("正确率：87.5%　用时 12:30", "87.5"),
    ("本次测验 正确率 96% 重新测验 完成测验", "96"),
    ("正确率: 100%", "100"),
    ("没有正确率字样的页面", None),
]


def main() -> int:
    tmp = Path("_test_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    cfg = {
        "region": [0, 0, 100, 100],
        "loop_interval": 0.1,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 256,
        "ocr_threads": 2,
    }
    bot = WordBot(cfg, tmp)

    ok = 0
    for text, expect in SAMPLES:
        got = bot.record_accuracy(text)
        cond = got == expect
        print(("  OK   " if cond else "  FAIL ") + "%-40s -> %s（期望 %s）" % (text[:36], got, expect))
        ok += 1 if cond else 0

    rows = list(csv.reader(open(tmp / "accuracy.csv", encoding="utf-8")))
    print("\nCSV 行数（含表头）:", len(rows))
    for r in rows:
        print("   ", r)
    cond = len(rows) == 4 and rows[0][0] == "time"
    print(("  OK   " if cond else "  FAIL ") + "只写入命中的 3 条 + 表头")
    ok += 1 if cond else 0

    shutil.rmtree(tmp)
    print("\nACCURACY: %d/%d passed" % (ok, len(SAMPLES) + 1))
    return 0 if ok == len(SAMPLES) + 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

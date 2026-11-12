"""calibrate_too_easy.py —— 校准「标记为太简单（无需复习）」按钮的位置

用法：
1. 小程序停在背单词答案页（右上角能看到「标记为太简单（无需复习）」）；
2. 双击 校准无需复习.cmd；
3. 看到倒计时后，把鼠标移到那个标签上，别动；
4. 倒计时结束自动记录，并把相对坐标写进 config.yaml 的 fallback_points.too_easy。

以后机器人点「无需复习」就用这个坐标，不再靠猜。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "site-packages"))

CONFIG = ROOT / "config.yaml"


def write_point(nx: float, ny: float) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    block = "  too_easy:\n  - %.4f\n  - %.4f\n" % (nx, ny)
    pattern = re.compile(r"^  too_easy:\r?\n(?:[ \t]*-[ \t]*[0-9.]+\r?\n)+", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(block, text, count=1)
    else:
        text = re.sub(r"^(fallback_points:[ \t]*\r?\n)", r"\1" + block, text,
                      count=1, flags=re.MULTILINE)
    CONFIG.write_text(text, encoding="utf-8")


def main() -> int:
    try:
        import yaml
    except Exception:
        print("缺少 pyyaml：请先双击 安装.cmd")
        return 2

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    region = cfg.get("region")
    if not isinstance(region, list) or len(region) != 4:
        print("config.yaml 里没有有效的 region，请先定位窗口。")
        return 2
    x0, y0, w, h = [int(v) for v in region]
    print("识别区域：left=%d top=%d 宽=%d 高=%d" % (x0, y0, w, h))
    print()
    print("请把小程序停在有「标记为太简单（无需复习）」的页面。")
    print("倒计时 6 秒，期间把鼠标移到该标签上，然后别动。")
    for left in range(6, 0, -1):
        print("  %d ..." % left)
        time.sleep(1)

    import pyautogui

    px, py = pyautogui.position()
    nx = (px - x0) / w
    ny = (py - y0) / h
    print()
    print("鼠标位置：(%d, %d) → 相对坐标 (%.4f, %.4f)" % (px, py, nx, ny))
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        print("⚠ 这个点不在识别区域内，请确认小程序位置没变，或先重新定位窗口。")
        return 1
    if ny > 0.45:
        print("⚠ 这个点在页面下半部分，不太像右上角的标签；仍然写入，但建议重试。")

    write_point(nx, ny)
    print()
    print("已写入 config.yaml：")
    print("  fallback_points:")
    print("    too_easy:")
    print("    - %.4f" % nx)
    print("    - %.4f" % ny)
    print()
    print("机器人点「无需复习」时会优先用这个坐标。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

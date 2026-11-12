"""test_extra_pages.py —— 测验总结页 + 任务超时弹窗的识别与点击

样本：sample_result.png（恭喜你完成了今日单词测试 / 正确率 84%）、
      sample_timeout.png（任务超时警告 + 绿色「再来一组」）

关键回归点：总结页以前被「单词测试」关键字误判成 test_choice，
会拿总结页当题目反复作答。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision import Vision

RESULT = Path("sample_result.png")
TIMEOUT = Path("sample_timeout.png")


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    def __init__(self, image):
        self.image = image.copy()
        self.calls = []
        self.region = FakeRegion(image.width, image.height)

    def capture(self):
        return self.image

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("rel", round(float(nx), 3), round(float(ny), 3)))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3)))

    def save_debug(self, *a, **k):
        return Path(".")


def make_bot(image):
    cfg = {
        "region": [0, 0, image.width, image.height],
        "loop_interval": 0.3,
        "after_click_delay": 0.1,
        "input_backend": "win32",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "auto_next_group": True,
        "max_extra_groups": 0,
        "extra_group_retry_seconds": 3.0,
        "fallback_points": {
            "test_result_finish": [0.74, 0.958],
            "timeout_next_group": [0.66, 0.56],
            "start_next_group": [0.5, 0.95],
            "next_word": [0.5, 0.955],
        },
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(image)
    return bot


def main() -> int:
    checks = []

    # ---------- 测验总结页 ----------
    if not RESULT.exists():
        print("缺少 sample_result.png，跳过总结页")
    else:
        img = Image.open(RESULT).convert("RGB")
        bot = make_bot(img)
        items = bot.vision.read(img)
        st = bot.detect_state(items)
        checks.append(("总结页识别为 test_result", st == "test_result", st))

        bot.act("test_result", items, img)
        calls = bot.screen.calls
        # 后台点击没让画面变化时会改用真实鼠标；两种记录坐标形式不同
        hit = calls[-1] if calls else None
        nx = None
        if hit:
            nx = hit[1] if hit[0] == "fg" else hit[1] / img.width
        checks.append(("点了「完成测验」", nx is not None and abs(nx - 0.74) < 0.12, calls[-1:]))
        checks.append(("记录了正确率", Path("_test_tmp/accuracy.csv").exists(),
                       Path("_test_tmp/accuracy.csv").exists()))

    # ---------- 任务超时弹窗 ----------
    if not TIMEOUT.exists():
        print("缺少 sample_timeout.png，跳过弹窗")
    else:
        img2 = Image.open(TIMEOUT).convert("RGB")
        bot2 = make_bot(img2)
        items2 = bot2.vision.read(img2)
        st2 = bot2.detect_state(items2)
        checks.append(("弹窗识别为 task_timeout", st2 == "task_timeout", st2))

        bot2.act("task_timeout", items2, img2)
        c2 = bot2.screen.calls
        checks.append(("点了绿色「再来一组」", bool(c2) and c2[-1][0] == "fg"
                       and 0.40 < c2[-1][2] < 0.80, c2[-1:]))
        checks.append(("没有点「我再想想」", not any("rel" == c[0] for c in c2), c2))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nEXTRA_PAGES: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

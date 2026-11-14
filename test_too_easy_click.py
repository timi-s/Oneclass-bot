"""test_too_easy_click.py —— 「标记为太简单（无需复习）」点击行为

实测结论（2026-11-12）：
· 标签可以点，单击后标签消失（不是整页变化）；
· 页面不会跳，必须再点「认识」才进入下一词；
· 双击可能把标记又取消，所以只单击。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw

from bot.controller import WordBot
from bot.vision import OCRItem, Vision

W, H = 447, 1015
CHIP = (0.835, 0.184)


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height = w, h


class FakeScreen:
    """点标签后：标签消失（那一小块变白），页面其余不变。"""

    def __init__(self, works: bool = True):
        self.image = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(self.image)
        x, y = int(W * CHIP[0]), int(H * CHIP[1])
        d.rectangle([x - 60, y - 16, x + 45, y + 16], fill=(230, 230, 230))
        self.works = works
        self.calls = []
        self.region = FakeRegion(W, H)
        self.know_clicked = False

    def capture(self):
        return self.image

    def click_rel(self, nx, ny, delay=None):
        self.calls.append(("rel", round(float(nx), 3), round(float(ny), 3)))

    def click_abs(self, x, y, delay=None):
        self.calls.append(("abs", round(float(x)), round(float(y))))

    def foreground_click_rel(self, nx, ny, delay=0.2, clicks=1):
        self.calls.append(("fg", round(float(nx), 3), round(float(ny), 3), clicks))
        if not self.works:
            return
        # 点标签：把那一块变白（标签消失）
        if abs(nx - CHIP[0]) < 0.13 and abs(ny - CHIP[1]) < 0.05:
            d = ImageDraw.Draw(self.image)
            x, y = int(W * CHIP[0]), int(H * CHIP[1])
            d.rectangle([x - 60, y - 16, x + 45, y + 16], fill="white")
        # 点「认识」（y≈0.83）：标记认识按钮被点
        if abs(ny - 0.83) < 0.05:
            self.know_clicked = True

    def save_debug(self, *a, **k):
        return Path(".")


def item(text, y, x=224, w=380, h=34):
    return OCRItem(text, 0.95, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def page_items(with_chip=True):
    rows = [
        item("背单词", 60, 224, 200, 40),
        item("emphasize", 300, 224, 200, 60),
        item("英:['emfəsaɪz]", 400, 224, 320, 36),
        item("vt. 强调，着重", 500, 224, 320, 40),
        item("认识", 844),
        item("模糊", 904),
        item("不认识", 965),
    ]
    if with_chip:
        rows.insert(1, item("标记为太简单", 185, 372, 170, 30))
    return rows


def make_bot(works=True):
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
        "fallback_points": {"know": [0.5, 0.83], "too_easy": list(CHIP)},
    }
    tmp = Path("_test_tmp")
    tmp.mkdir(exist_ok=True)
    if not (tmp / "vocab.json").exists():
        shutil.copy("vocab.json", tmp / "vocab.json")
    bot = WordBot(cfg, tmp)
    bot.vision = Vision(1.0, 0.45, 512, 3, False, False)
    bot.screen = FakeScreen(works)
    return bot


def main() -> int:
    checks = []

    # 1) 标签可点：单击 → 标签消失 → 再点认识
    bot = make_bot(True)
    ok = bot.click_too_easy(page_items(), bot.screen.image)
    calls = bot.screen.calls
    clicks_fg = [c for c in calls if c[0] == "fg"]
    checks.append(("标记成功返回 True", ok is True, ok))
    checks.append(("点的是标签位置", bool(clicks_fg) and abs(clicks_fg[0][1] - CHIP[0]) < 0.15,
                   clicks_fg[:1]))
    checks.append(("只单击（clicks=1，避免取消标记）",
                   bool(clicks_fg) and clicks_fg[0][3] == 1, clicks_fg[:1]))
    # 标记成功后不再盲目补点「认识」，交给主循环按新页面处理
    know_after = [c for c in calls
                  if (c[0] == "fg" and abs(c[2] - 0.83) < 0.06)
                  or (c[0] == "rel" and abs(c[2] - 0.83) < 0.06)
                  or (c[0] == "abs" and abs(c[2] - H * 0.83) < 60)]
    checks.append(("标记后不再补点「认识」", not know_after, calls))

    # 2) 标签点不动 → 返回 False，交给调用方点认识
    bot2 = make_bot(False)
    ok2 = bot2.click_too_easy(page_items(), bot2.screen.image)
    checks.append(("点不动时返回 False", ok2 is False, ok2))

    # 3) 页面没有标签 → 用校准坐标；点不动返回 False
    bot3 = make_bot(False)
    ok3 = bot3.click_too_easy(page_items(with_chip=False), bot3.screen.image)
    used = [c for c in bot3.screen.calls if c[0] == "fg"]
    checks.append(("没标签时用校准坐标", bool(used) and abs(used[0][1] - CHIP[0]) < 0.05, used[:1]))
    checks.append(("没标签且点不动时返回 False", ok3 is False, ok3))

    ok_count = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok_count += 1 if cond else 0
    print("\nTOO_EASY_CLICK: %d/%d passed" % (ok_count, len(checks)))
    shutil.rmtree(Path("_test_tmp"), ignore_errors=True)
    return 0 if ok_count == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""test_audio_crash_guard.py —— 复现「录音坏掉」的降级路径

对方电脑的真实崩溃链：
  1. SoundCard 打开回环设备抛 struct.error: integer 196608 does not fit 'unsigned short'
  2. 之后进程以 0xC0000374（堆损坏）退出
界面上看到的就是「启动机器人 → 立刻已停止」。

修法：先在子进程里试录，失败就 use_audio=False，主进程绝不碰声卡。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "site-packages"))

from bot.windows_dpi import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

import bot.audio_probe as probe  # noqa: E402
import bot.controller as ctl  # noqa: E402


class FakeScreen:
    def __init__(self):
        from PIL import Image

        class R:
            width, height = 300, 600

        self.region = R()
        self.image = Image.new("RGB", (300, 600), "white")

    def capture(self):
        return self.image

    def click_rel(self, *a, **k):
        pass

    def click_abs(self, *a, **k):
        pass

    def foreground_click_rel(self, *a, **k):
        pass

    def save_debug(self, *a, **k):
        return Path(".")


def build(tmp: Path, cfg_extra: dict | None = None):
    cfg = {
        "region": [0, 0, 300, 600],
        "loop_interval": 0.3,
        "input_backend": "win32",
        "verify_clicks": False,
        "audio_capture": True,
        "audio_templates": True,
        "dictation_mode": "whisper",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"know": [0.5, 0.8]},
    }
    cfg.update(cfg_extra or {})
    bot = ctl.WordBot(cfg, tmp)
    bot.screen = FakeScreen()
    return bot


def main() -> int:
    checks = []
    tmp = ROOT / "_test_tmp" / "crash"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copy(ROOT / "vocab.json", tmp / "vocab.json")

    real = probe.probe_subprocess
    try:
        # 1) 模拟对方电脑：声卡抛 struct.error（且可能带崩）
        probe.probe_subprocess = lambda *a, **k: (
            False, "struct.error: integer 196608 does not fit 'unsigned short'")
        bot = build(tmp)
        checks.append(("录音坏了 → 自动关闭录音", bot.use_audio is False, bot.use_audio))
        checks.append(("机器人仍能构造（不会崩）", isinstance(bot, ctl.WordBot), type(bot).__name__))
        stamp = tmp / "logs" / "smoke.txt"
        stamp.parent.mkdir(exist_ok=True)
        stamp.write_text("ok", encoding="utf-8")
        checks.append(("日志目录可写", stamp.exists(), stamp.name))

        # 2) 录音正常 → 正常开启
        probe.probe_subprocess = lambda *a, **k: (True, "录音正常")
        bot2 = build(tmp)
        checks.append(("录音正常 → 开启", bot2.use_audio is True, bot2.use_audio))
        bot2.audio.stop_capture()

        # 3) audio_capture 显式关掉 → 不探测也不开
        probe.probe_subprocess = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("不应该被调用"))
        bot3 = build(tmp, {"audio_capture": False})
        checks.append(("显式关闭录音时不探测", bot3.use_audio is False, bot3.use_audio))
    finally:
        probe.probe_subprocess = real

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nAUDIO_CRASH_GUARD: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(ROOT / "_test_tmp", ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

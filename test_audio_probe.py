"""test_audio_probe.py —— 录音设备坏掉时必须降级，绝不能崩

现场：别人电脑上 SoundCard 打开回环设备抛 struct.error
      integer 196608 does not fit 'unsigned short'
然后进程直接以 0xC0000374（堆损坏）退出 —— 看起来就是“启动后自动停止”。
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
from bot.controller import WordBot  # noqa: E402


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


def make_bot(tmp: Path):
    cfg = {
        "region": [0, 0, 300, 600],
        "loop_interval": 0.3,
        "input_backend": "win32",
        "verify_clicks": False,
        "audio_capture": True,
        "audio_templates": False,
        "dictation_mode": "whisper",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"know": [0.5, 0.8]},
    }
    bot = WordBot(cfg, tmp)
    bot.screen = FakeScreen()
    return bot


def main() -> int:
    checks = []
    tmp = ROOT / "_test_tmp" / "probe"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copy(ROOT / "vocab.json", tmp / "vocab.json")

    # 1) 录音不可用 → use_audio 自动关闭，且不抛异常
    real = probe.probe_subprocess
    probe.probe_subprocess = lambda *a, **k: (False, "struct.error: integer 196608 does not fit 'unsigned short'")
    try:
        bot = make_bot(tmp)
        checks.append(("录音坏掉时自动关闭", bot.use_audio is False, bot.use_audio))
        checks.append(("仍然能构造出机器人", bot is not None, type(bot).__name__))
    finally:
        probe.probe_subprocess = real

    # 2) 录音可用 → use_audio 保持 True
    probe.probe_subprocess = lambda *a, **k: (True, "录音正常")
    try:
        bot2 = make_bot(tmp)
        checks.append(("录音正常时保持开启", bot2.use_audio is True, bot2.use_audio))
        bot2.audio.stop_capture()
    finally:
        probe.probe_subprocess = real

    # 3) 子进程探测本身不会崩主进程（本机应返回 ok）
    ok, msg = probe.probe_subprocess()
    checks.append(("子进程探测可返回结果", isinstance(msg, str) and msg != "", msg[:40]))

    ok_count = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok_count += 1 if cond else 0
    print("\nAUDIO_PROBE: %d/%d passed" % (ok_count, len(checks)))
    shutil.rmtree(ROOT / "_test_tmp", ignore_errors=True)
    return 0 if ok_count == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

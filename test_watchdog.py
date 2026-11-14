"""test_watchdog.py —— 界面看门狗：机器人 45 秒没日志就自动杀掉

“卡死不动”是这次重建的核心要解决的问题，所以单独立一个测试。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "site-packages"))

import gui


class FakeProc:
    """假进程：poll() 一直返回 None（表示还活着）。"""

    def __init__(self):
        self.pid = 4242
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.killed = True


def main() -> int:
    checks = []

    # 1) 正常有日志时不该被杀
    tmp = ROOT / "_test_tmp"
    tmp.mkdir(exist_ok=True)
    log = tmp / "wd.log"
    log.write_text("", encoding="utf-8")
    gui.LOG_FILE = log
    tail = gui.LogTail(log)
    runner = gui.BotRunner(tail)
    runner.proc = FakeProc()
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("2026-11-12 15:00:00,000 | INFO | 页面状态：learn_hidden\n")
    lines, note = runner.tick()
    checks.append(("有新日志时正常返回", len(lines) == 1 and note is None, (lines, note)))
    checks.append(("进程仍算运行中", runner.running is True, runner.running))

    # 2) 超过阈值没有日志 → 判定卡死
    old = gui.SILENCE_LIMIT
    gui.SILENCE_LIMIT = 0.3
    try:
        runner.last_log_at = time.monotonic() - 5
        lines, note = runner.tick()
        checks.append(("超时判卡死并给出提示", note is not None and "卡死" in (note or ""), note))
        checks.append(("被标记为看门狗停止", runner.killed_by_watchdog is True,
                       runner.killed_by_watchdog))
    finally:
        gui.SILENCE_LIMIT = old

    # 3) 有日志就不该判卡死
    gui.LOG_FILE = log
    runner2 = gui.BotRunner(gui.LogTail(log))
    runner2.proc = FakeProc()
    runner2.last_log_at = time.monotonic() - 5
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("2026-11-12 15:00:01,000 | INFO | 点击文字 开始背诵\n")
    lines, note = runner2.tick()
    checks.append(("刚有日志不判卡死", note is None and len(lines) == 1, (lines, note)))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nWATCHDOG: %d/%d passed" % (ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

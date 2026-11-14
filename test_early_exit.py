"""test_early_exit.py —— 机器人启动后秒退，界面必须查得出原因

现场问题：别人装好后点「启动机器人」，几秒就变成「已停止」，
界面日志里一片空白（因为子进程输出被丢掉了），没法判断。
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "site-packages"))

import gui  # noqa: E402


def main() -> int:
    checks = []
    tmp = ROOT / "_test_tmp"
    tmp.mkdir(exist_ok=True)
    log = tmp / "console_test.log"
    gui.LOG_FILE = log
    log.write_text("", encoding="utf-8")

    # 用一条会立刻失败的命令模拟「秒退」
    cmd = [sys.executable, "-c",
           "import sys; print('假依赖导入成功', flush=True); "
           "sys.stderr.write('ModuleNotFoundError: No module named xxx\\n'); sys.exit(1)"]

    runner = gui.BotRunner(gui.LogTail(log), cmd=cmd)
    started = runner.start()
    checks.append(("能启动子进程", started is True, started))

    note = None
    exit_code = None
    for _ in range(30):
        lines, note = runner.tick()
        if note:
            break
        time.sleep(0.2)

    checks.append(("秒退时给出提示", note is not None, note[:60] if note else None))
    checks.append(("提示里带退出码", note is not None and "退出码 1" in note,
                   note[:80] if note else None))
    checks.append(("提示里带最后输出",
                   note is not None and "ModuleNotFoundError" in note,
                   note[-120:] if note else None))

    # console 日志文件应真的有内容
    text = (ROOT / "logs" / "bot_console.log")
    content = text.read_text(encoding="utf-8", errors="replace") if text.exists() else ""
    checks.append(("子进程输出落盘", "No module named xxx" in content, content[:80]))

    # 提示只出现一次，不会每轮刷屏
    _, note2 = runner.tick()
    checks.append(("只提示一次", note2 is None, note2))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nEARLY_EXIT: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

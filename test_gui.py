"""test_gui.py —— 图形界面的配置读写逻辑（不弹窗口）"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "site-packages"))

import gui


def main() -> int:
    base = gui.selftest()
    checks = []

    tmpdir = Path("_test_tmp")
    tmpdir.mkdir(exist_ok=True)
    log = tmpdir / "tail_test.log"
    log.write_text("line-1\nline-2\n", encoding="utf-8")
    tail = gui.LogTail(log)
    checks.append(("初始位置在文件末尾", tail.read_new() == [], None))
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("line-3\n")
    got = tail.read_new()
    checks.append(("能读到新增行", got == ["line-3"], got))
    checks.append(("同一行不会重复读", tail.read_new() == [], None))
    log.write_text("新文件\n", encoding="utf-8")
    got2 = tail.read_new()
    checks.append(("文件被清空后能重读", got2 == ["新文件"], got2))

    ok = 0
    for name, cond, extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if extra is None else "  <> %s" % (extra,)))
        ok += 1 if cond else 0
    print("\nGUI_TAIL: %d/%d passed" % (ok, len(checks)))
    return 0 if (base == 0 and ok == len(checks)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""核对两个版本、四个安装包是否都包含最新改动。"""

import zipfile
from pathlib import Path

CHECKS = {
    "bot/machine.py": ["def machine_id("],
    "bot/screen.py": ["_fit_to_screen", "screen_size"],
    "bot/audio_match.py": ["machine_ok", "_meta", "templates"],
    "bot/controller.py": ["标记为太简单", "click_too_easy"],
    "gui.py": ["console_tail", "机器人启动后自己退出了", "识别区域超出屏幕",
               "SILENCE_LIMIT", "致命问题"],
    "main.py": ["启动失败：", "依赖没装好", "_FRIENDLY"],
    "启动界面.cmd": ["import yaml, cv2, mss, pyautogui"],
    "诊断.cmd": ["run_diag"],
    "run_diag.py": ["屏幕尺寸", "发音模板"],
    "常见问题.txt": ["声卡", "audio_capture: false", "英文冒号"],
    "bot/audio_probe.py": ["probe_subprocess", "probe_inproc"],
}

PAID_EXTRA = {
    "bot/license.py": ["consume_word_for", "PRICE_TIERS", "ALL_WORDS", "reset_state",
                       "_load_state_ex", "_merge"],
    "activate.py": ["PRICE_TIERS"],
    "客户必读.txt": ["2862"],
}
PAID_FORBIDDEN = ["license.json", "private_key.pem", "生成激活码.py"]


def check_zip(path: Path, extra: dict, forbidden: list[str]) -> list[str]:
    problems: list[str] = []
    z = zipfile.ZipFile(path)
    names = z.namelist()
    files = {n for n in names if not n.endswith("/")}

    def read(rel: str) -> str | None:
        target = "oneclass-bot/" + rel
        if target not in files:
            return None
        return z.read(target).decode("utf-8", "replace")

    for rel, markers in CHECKS.items():
        data = read(rel)
        if data is None:
            problems.append("缺文件 %s" % rel)
            continue
        for marker in markers:
            if marker not in data:
                problems.append("%s 缺 %r" % (rel, marker))

    for rel, markers in extra.items():
        data = read(rel)
        if data is None:
            problems.append("缺文件 %s" % rel)
            continue
        for marker in markers:
            if marker not in data:
                problems.append("%s 缺 %r" % (rel, marker))

    for bad in forbidden:
        if any(bad in x for x in files):
            problems.append("不该包含 %s" % bad)
    return problems


def main() -> int:
    targets = [
        (Path(r"D:\oneclass-bot\一课英语助手-完整版.zip"), {}, []),
        (Path(r"D:\oneclass-bot\一课英语助手-轻量版.zip"), {}, []),
        (Path(r"D:\oneclass-bot-paid\一课英语助手-完整版.zip"), PAID_EXTRA, PAID_FORBIDDEN),
        (Path(r"D:\oneclass-bot-paid\一课英语助手-轻量版.zip"), PAID_EXTRA, PAID_FORBIDDEN),
    ]
    all_ok = True
    for path, extra, forbidden in targets:
        if not path.exists():
            print("❌ 不存在：%s" % path)
            all_ok = False
            continue
        problems = check_zip(path, extra, forbidden)
        size_mb = path.stat().st_size / 1024 / 1024
        if problems:
            all_ok = False
            print("❌ %s (%.1f MB)" % (path.name, size_mb))
            for item in problems:
                print("     %s" % item)
        else:
            print("✅ %-22s %6.1f MB   %s" % (path.name, size_mb, path.parent.name))
    print()
    print("总体：%s" % ("全部最新" if all_ok else "有缺失，需要重新打包"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

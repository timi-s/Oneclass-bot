"""打包.py —— 把项目打成可以发给别人的压缩包

由 打包分享.cmd 调用。两种模式：
  1 = 完整版（含 site-packages + models，约 950 MB）
  2 = 轻量版（只含代码，约 7 MB）
都会排除个人数据：词库、发音模板、日志、截图、git 历史。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "_打包临时"

EXCLUDE = [
    "logs", "vb-cable", ".tmp", "__pycache__", "legacy_patches",
    "_打包临时", "分享包", ".git", ".idea", ".vscode",
    # 开发时的临时东西，不发给别人
    "Oneclass", "original_backup",
]
EXCLUDE_FILES = [
    "vocab.json", "audio_templates.json", "wordbot.log", "accuracy.csv",
    "calibration_preview.png", "checkup.png", "dictation_sample.png",
    "learn_sample.jpg",
    # 一次性调试脚本
    "bench2.py", "bench3.py", "exp_rate.py", "log_analyze.py",
    "vocab_stats.py", "repair_config.py",
    "enable_background_mode.py", "enable_whisper_fallback.py",
    "fix_choice_feedback.py", "fix_choice_unknown.py", "fix_dictation_feedback.py",
    "calibrate_dictation_points.py", "calibrate_next_group_button.py",
    # 测试用样本图（本机才有，接收方不需要）
    "sample_result.png", "sample_timeout.png",
    # 界面截图工具（截图本身要给使用说明配图，保留）
    "_shot_gui.py",
]
HEAVY = ["site-packages", "models"]


def human(n: int) -> str:
    return "%.1f MB" % (n / 1024 / 1024) if n < 1024 ** 3 else "%.2f GB" % (n / 1024 ** 3)


def ask_mode() -> int:
    print("=" * 60)
    print("  把本项目打成压缩包，发给别人使用")
    print("=" * 60)
    print()
    print("  [1] 完整版（推荐）  含依赖 + 语音模型，约 950 MB")
    print("      对方解压后双击 安装.cmd 即可，基本不用再下载东西")
    print()
    print("  [2] 轻量版          只含代码，约 7 MB")
    print("      对方需要有网，安装依赖和模型（约 900 MB 下载）")
    print()
    while True:
        try:
            raw = input("请输入 1 或 2 后回车：").strip()
        except EOFError:
            return 1
        if raw in ("1", "2"):
            return int(raw)


def main() -> int:
    # 命令行直接给 1/2 就不问（方便自动化测试）
    if len(sys.argv) > 1 and sys.argv[1] in ("1", "2"):
        mode = int(sys.argv[1])
    else:
        mode = ask_mode()
    name = "一课英语助手-完整版" if mode == 1 else "一课英语助手-轻量版"
    excludes = list(EXCLUDE) + ([] if mode == 1 else HEAVY)

    if STAGE.exists():
        shutil.rmtree(STAGE, ignore_errors=True)
    target = STAGE / "oneclass-bot"

    print()
    print("正在收集文件 ……")

    def ignore(dirpath, names):
        skip = set()
        for n in names:
            if n in excludes or n in EXCLUDE_FILES:
                skip.add(n)
            if n.endswith(".zip") and n.startswith("一课英语助手"):
                skip.add(n)
        return skip

    shutil.copytree(ROOT, target, ignore=ignore, dirs_exist_ok=True,
                    copy_function=shutil.copyfile)

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    count = sum(1 for f in target.rglob("*") if f.is_file())
    print("  收集到 %d 个文件，%s" % (count, human(size)))

    print("正在压缩（完整版可能要几分钟）……")
    zip_path = ROOT / name
    if Path(str(zip_path) + ".zip").exists():
        Path(str(zip_path) + ".zip").unlink()

    archive = shutil.make_archive(str(zip_path), "zip", root_dir=str(STAGE), base_dir="oneclass-bot")
    out = Path(archive)
    shutil.rmtree(STAGE, ignore_errors=True)

    print()
    print("=" * 60)
    print("  打包完成")
    print("=" * 60)
    print()
    print("  文件：%s" % out)
    print("  大小：%s" % human(out.stat().st_size))
    print()
    print("  发给对方时说明：先看 安装说明.txt，然后双击 安装.cmd")
    print()
    print("  已自动排除：vocab.json / 发音模板 / logs / 截图 / .git")
    return 0


if __name__ == "__main__":
    sys.exit(main())

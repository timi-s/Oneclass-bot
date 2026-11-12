"""setup_cable.py —— 装好 VB-CABLE 之后，一键把回环设备写进 config.yaml

用法：
    python setup_cable.py --dry-run     # 只看会改成什么，不写文件
    python setup_cable.py               # 真正写入
    python setup_cable.py --name "CABLE Output (VB-Audio Virtual Cable)"
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from bot.config import CONFIG_PATH, ROOT, load_config


def list_devices() -> list[str]:
    import soundcard as sc

    return [m.name for m in sc.all_microphones(include_loopback=True)]


def find_cable(names: list[str]) -> str | None:
    for n in names:
        if "CABLE Output" in n:
            return n
    for n in names:
        if "CABLE" in n.upper() or "VB-AUDIO" in n.upper():
            return n
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--name", help="直接指定设备名，跳过自动查找")
    args = ap.parse_args()

    cfg = load_config()
    names = list_devices()
    print("可用录音/回环设备：")
    for n in names:
        print("  -", n)
    print("\n当前配置：%s" % cfg.get("audio_loopback_name"))

    target = args.name or find_cable(names)
    if not target:
        print("\n没找到 CABLE 设备。先装 VB-CABLE：")
        print("  1) 右键 %s → 以管理员身份运行 → Install Driver" % (ROOT / "vb-cable" / "VBCABLE_Setup_x64.exe"))
        print("  2) 重启电脑")
        print("  3) 设置 → 系统 → 声音 → 输出 → 选 CABLE Input (VB-Audio Virtual Cable)")
        print("  4) 再运行本脚本")
        return 1

    text = CONFIG_PATH.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^audio_loopback_name:.*$", "audio_loopback_name: " + target, text)
    if new == text:
        print("\nconfig.yaml 里找不到 audio_loopback_name 这一行，没改。")
        return 1

    if args.dry_run:
        print("\n（dry-run）会把配置改成：audio_loopback_name: %s" % target)
        return 0

    bak = CONFIG_PATH.with_suffix(".yaml.bak")
    shutil.copy2(CONFIG_PATH, bak)
    CONFIG_PATH.write_text(new, encoding="utf-8", newline="\n")
    print("\n已写入 config.yaml：audio_loopback_name: %s" % target)
    print("备份：%s" % bak)
    print("\n下一步：双击 whisper_check.cmd，播放一段有声音的内容，看 RMS 是否 > 0.002。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

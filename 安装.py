"""安装.py —— 一课英语助手的一键安装逻辑（中文提示）

由 安装.cmd 调用，不要在 GBK 控制台里直接双击运行。
做的事：
  1. 检查 Python 版本（需要 3.13，和 site-packages 里的二进制匹配）
  2. 检查 / 安装依赖到本目录的 site-packages
  3. 检查 / 下载语音模型 models/small.en
  4. 列出可用音频设备，方便填 audio_loopback_name
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site-packages"
MODEL = ROOT / "models" / "small.en" / "model.bin"
REQ = ROOT / "requirements-audio.txt"

DEPS = ["yaml", "cv2", "mss", "pyautogui", "rapidocr", "onnxruntime", "rapidfuzz", "pyperclip"]

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def title(text: str) -> None:
    print()
    print("=" * 60)
    print("  " + text)
    print("=" * 60)


def check_python() -> bool:
    v = sys.version_info
    print("[1/4] Python：%d.%d.%d（%s）" % (v.major, v.minor, v.micro, sys.executable))
    if (v.major, v.minor) != (3, 13):
        print()
        print("  [注意] 本包的依赖是按 Python 3.13 编译的（site-packages）。")
        print("         你现在是 %d.%d，多半会 import 失败。" % (v.major, v.minor))
        print("         请安装 Python 3.13：https://www.python.org/downloads/release/python-3139/")
        print()
        return False
    return True


def deps_ok() -> bool:
    code = "import " + ", ".join(DEPS)
    env = dict(os.environ, PYTHONPATH=str(SITE))
    try:
        r = subprocess.run([sys.executable, "-c", code], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def install_deps() -> bool:
    if not REQ.exists():
        print("  找不到 requirements-audio.txt，跳过依赖安装。")
        return False
    print("  正在安装依赖（约 400 MB，需要联网，可能要 5～15 分钟）……")
    cmd = [sys.executable, "-m", "pip", "install",
           "-r", str(REQ), "--target", str(SITE)]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print()
        print("  [失败] 直连 PyPI 装不上，改用清华镜像重试 ……")
        cmd += ["-i", MIRROR]
        r = subprocess.run(cmd)
    return r.returncode == 0


def ensure_model() -> bool:
    if MODEL.exists() and MODEL.stat().st_size > 100 * 1024 * 1024:
        print("  模型已存在：%.0f MB，跳过" % (MODEL.stat().st_size / 1024 / 1024))
        return True
    script = ROOT / "下载模型.py"
    if not script.exists():
        print("  找不到 下载模型.py，跳过（听写将不可用）")
        return False
    print("  正在下载语音模型（约 460 MB）……")
    r = subprocess.run([sys.executable, str(script)])
    return r.returncode == 0


def list_devices() -> None:
    script = ROOT / "list_audio_devices.py"
    if not script.exists():
        return
    env = dict(os.environ, PYTHONPATH=str(SITE))
    subprocess.run([sys.executable, str(script)], env=env)


def main() -> int:
    title("一课英语背单词助手  一键安装")
    print("安装目录：%s" % ROOT)

    ok_py = check_python()

    print()
    print("[2/4] 检查依赖 ……")
    if deps_ok():
        print("  依赖已就绪，跳过安装")
    else:
        if not install_deps():
            print()
            print("[失败] 依赖没装好。检查网络后重新双击 安装.cmd。")
            return 1

    print()
    print("[3/4] 检查语音模型 ……")
    if not ensure_model():
        print("  模型没准备好：听写题将无法自动作答（可选择我不会）。")

    print()
    print("[4/4] 列出可用音频设备 ……")
    list_devices()

    title("安装完成，接下来必须做 2 件事")
    print("""
  1) 打开电脑版微信，把「一课英语」小程序拖到固定位置，
     让白色内容区完整露出，然后双击：  启动界面.cmd
     （图形界面里点「扫描窗口」→「预览并确认定位」即可，
      也可以双击 calibrate.cmd 手动框选）

  2) 如果听写录不到声音：
     把上面列出的、带 loopback=True 的扬声器名字，
     原样填进 config.yaml 的 audio_loopback_name

  两种用法：
     启动界面.cmd  → 图形界面（推荐，能看日志、改设置）
     启动.cmd      → 纯命令行
  运行前自检（只截图不点击）：双击 checkup.cmd
""")
    if not ok_py:
        print("  另外：请先装好 Python 3.13，否则依赖装了也用不了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

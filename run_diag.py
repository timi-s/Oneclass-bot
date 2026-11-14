"""run_diag.py —— 一键诊断（给别人排「启动就停」用）

检查项：
1. Python 版本
2. 依赖能否导入（site-packages 是否生效）
3. config.yaml 能否解析、region 是否合理
4. 语音模型是否存在
5. 试着真正启动一次 main.py，把它的输出抓下来（最多 25 秒）

结果写到 diag_report.txt，方便直接发给卖家。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site-packages"
REPORT = ROOT / "diag_report.txt"

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def main() -> int:
    say("=" * 60)
    say("OneClass 助手 · 启动诊断")
    say("时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    say("目录：%s" % ROOT)
    say("=" * 60)

    say("\n[1] Python 版本：%d.%d.%d" % sys.version_info[:3])
    if sys.version_info[:2] != (3, 13):
        say("    ⚠ 依赖是按 Python 3.13 编译的，当前版本可能 import 失败")

    say("\n[2] 依赖导入")
    env = dict(os.environ, PYTHONPATH=str(SITE), PYTHONIOENCODING="utf-8")
    code = "import yaml, cv2, mss, pyautogui, rapidocr, onnxruntime, rapidfuzz, soundcard"
    r = subprocess.run([sys.executable, "-c", code], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        say("    ✅ 依赖齐全")
    else:
        say("    ❌ 依赖缺失：")
        for line in (r.stderr or "").strip().splitlines()[-6:]:
            say("       " + line)
        say("    → 双击 安装.cmd 重新装依赖")

    say("\n[3] 配置文件")
    try:
        import yaml

        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        region = cfg.get("region")
        say("    ✅ config.yaml 解析正常")
        say("    region = %s" % region)
        try:
            import ctypes

            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            say("    屏幕尺寸 = %dx%d（已按 DPI 感知）" % (sw, sh))
            if isinstance(region, list) and len(region) == 4:
                x, y, w, h = [int(v) for v in region]
                if x + w > sw or y + h > sh:
                    say("    ❌ 识别区域超出屏幕（右下角 %d,%d > %dx%d），请重新定位窗口"
                        % (x + w, y + h, sw, sh))
        except Exception:
            pass
        if not (isinstance(region, list) and len(region) == 4):
            say("    ❌ region 无效，需要重新定位窗口")
        say("    dictation_mode = %s" % cfg.get("dictation_mode"))
        say("    whisper_model = %s" % cfg.get("whisper_model"))
        model = ROOT / str(cfg.get("whisper_model") or "")
        say("    模型文件存在：%s" % (model / "model.bin").exists())
    except Exception as exc:  # noqa: BLE001
        say("    ❌ config.yaml 读取失败：%s" % exc)

    say("\n[3.5] 发音模板")
    tpl = ROOT / "audio_templates.json"
    if not tpl.exists():
        say("    没有模板（首次使用会边学边录，正常）")
    else:
        try:
            import json

            raw = json.loads(tpl.read_text(encoding="utf-8"))
            meta = raw.get("_meta") if isinstance(raw, dict) else None
            count = len(raw.get("templates") or {}) if meta else len(raw)
            say("    模板数量：%d 条" % count)
            say("    来源机器：%s" % ((meta or {}).get("machine") or "未知（老版本模板）"))
            say("    来源设备：%s" % ((meta or {}).get("device") or "-"))
            say("    ⚠ 模板必须是本机录的；不是本机的话程序会自动停用，只用 Whisper 识别")
        except Exception as exc:  # noqa: BLE001
            say("    ⚠ 模板文件读不出来：%s（删掉它即可重新积累）" % exc)

    say("\n[4] 试启动 main.py（最多 25 秒，会真的操作屏幕）")
    out = ROOT / "logs" / "diag_main.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", errors="replace") as fh:
        try:
            proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "main.py")],
                                    cwd=str(ROOT), env=env, stdout=fh,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            say("    ❌ 启动失败：%s" % exc)
            proc = None
    if proc is not None:
        deadline = time.time() + 25
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.5)
        if proc.poll() is None:
            say("    ✅ 进程 25 秒内没有退出（说明能正常运行）")
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        else:
            say("    ❌ 进程自己退出了，退出码 %s" % proc.returncode)
        say("\n    main.py 最后输出：")
        try:
            tail = out.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            for line in tail:
                say("      " + line)
        except Exception:
            say("      （读不到输出）")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n报告已保存：%s" % REPORT)
    print("把这个文件发给卖家即可定位问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

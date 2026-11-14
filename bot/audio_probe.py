"""audio_probe.py —— 本机回环录音自检（放在子进程里跑，崩了也不影响主程序）

有人的电脑上 SoundCard 打开回环设备会直接抛 struct.error：
    integer 196608 does not fit 'unsigned short'
甚至会带崩整个进程（0xC0000374 堆损坏）。
所以先在一个独立子进程里试录 0.5 秒：
· 成功  → 可以开常驻录音
· 失败  → 自动关闭录音（听写不可用，但背单词照常），绝不冒险在主线里调用
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_cfg() -> dict:
    try:
        import yaml

        return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def probe_inproc(seconds: float = 0.5) -> tuple[bool, str]:
    """当前进程里试录一次（只在 audio_probe 子进程里调用）。"""
    cfg = _load_cfg()
    rate = int(cfg.get("audio_rate", 48000) or 48000)
    try:
        import ctypes

        import numpy as np
        import soundcard as sc

        if hasattr(ctypes, "windll"):
            ctypes.windll.ole32.CoInitialize(None)
        name = str(cfg.get("audio_loopback_name", "") or "").strip()
        if name:
            mic = sc.get_microphone(name, include_loopback=True)
        else:
            mic = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
        with mic.recorder(samplerate=rate) as rec:
            data = np.asarray(rec.record(numframes=int(rate * seconds)))
        rms = float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0
        return True, "录音正常（RMS=%.4f，设备=%s）" % (rms, getattr(mic, "name", "?"))
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


def probe_subprocess(timeout: float = 12.0) -> tuple[bool, str]:
    """在独立子进程里自检：主进程绝不会因为声卡而崩。"""
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "site-packages")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run([sys.executable, "-m", "bot.audio_probe", "--json"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "录音自检超时（设备可能被占用）"
    except Exception as exc:  # noqa: BLE001
        return False, "录音自检启动失败：%s" % exc
    out = (r.stdout or "").strip().splitlines()
    payload = ""
    for line in reversed(out):
        if line.startswith("{"):
            payload = line
            break
    if payload:
        try:
            data = json.loads(payload)
            return bool(data.get("ok")), str(data.get("msg", ""))
        except Exception:
            pass
    if r.returncode == 0:
        return True, "录音可用"
    tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
    return False, "录音不可用（退出码 %s）：%s" % (r.returncode, tail[0][:120])


def main() -> int:
    ok, msg = probe_inproc()
    if "--json" in sys.argv:
        print(json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False))
    else:
        print(("✅ " if ok else "❌ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

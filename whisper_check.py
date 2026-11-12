"""whisper_check.py —— 听写链路自检

两种用法：
    python whisper_check.py                  # 录 3.2 秒系统回环音频，识别并打印
    python whisper_check.py --file a.wav      # 直接识别一个 wav

运行前把小程序停在听写题、点一下喇叭，让声音真的放出来。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

import numpy as np

from bot.audio_solver import AudioSolver
from bot.config import ROOT, load_config
from bot.vocab import VocabStore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="识别这个 wav，不录音")
    ap.add_argument("--seconds", type=float, help="录音秒数（默认取 config.audio_record_seconds）")
    args = ap.parse_args()

    cfg = load_config()
    solver = AudioSolver(cfg, ROOT / "logs")
    (ROOT / "logs").mkdir(exist_ok=True)

    print("模型：%s" % cfg.get("whisper_model"))
    print("设备：%s / %s" % (cfg.get("whisper_device", "cpu"), cfg.get("whisper_compute_type", "int8")))
    print("回环设备：%s" % cfg.get("audio_loopback_name") or "（默认扬声器）")

    if args.file:
        wav = Path(args.file)
        if not wav.exists():
            print("找不到文件：%s" % wav)
            return 2
        print("音频文件：%s" % wav)
    else:
        seconds = float(args.seconds or cfg.get("audio_record_seconds", 3.2))
        print("开始录 %.1f 秒……" % seconds)
        cfg2 = dict(cfg)
        cfg2["audio_record_seconds"] = seconds
        solver = AudioSolver(cfg2, ROOT / "logs")
        try:
            wav = solver.record_after_click(lambda: None)
        except Exception as exc:
            print("录音失败：%s" % exc)
            print("检查：扬声器是否在放声音、audio_loopback_name 是否填对（python list_audio_devices.py）。")
            return 2
        print("已录音：%s" % wav)

    vocab = VocabStore(ROOT / "vocab.json").words()
    print("词库参考词 %d 个" % len(vocab))

    try:
        samples = AudioSolver._read_wav(wav)
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        print("音频电平 RMS=%.4f（低于 0.002 基本就是静音）" % rms)
        if rms < 0.002:
            print("⚠️ 这段音频基本是静音：系统静音 / 音量 0 / 录的不是当前输出设备。")
    except Exception as exc:
        print("读取音频失败：%s" % exc)

    t0 = time.time()
    raw, heard = solver.transcribe(wav, vocab)
    cost = time.time() - t0
    print("\n识别原文：%r" % raw)
    print("最佳单词：%r" % heard)
    print("耗时：%.1f 秒" % cost)

    if not raw.strip():
        print("\n结果是空的：要么这段音频是静音，要么回环没录到声音。")
        return 1
    print("\n链路正常。可以用 dictation_mode: whisper 跑了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

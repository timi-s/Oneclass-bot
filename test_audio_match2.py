"""test_audio_match2.py —— 验证音频指纹比对：合成 12 个「词」，用带噪/变速/变音量的版本去查"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from bot.audio_match import AudioIndex, log_mel

SR = 16000


def synth(seed: int, dur: float = 0.9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * dur)) / SR
    f0 = rng.uniform(180, 900)
    x = np.zeros_like(t)
    for k, a in ((1, 1.0), (2, 0.5), (3, 0.3)):
        x += a * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28))
    env = np.exp(-2.5 * t)
    x = x * env + rng.normal(0, 0.01, len(t))
    return (x / (np.abs(x).max() + 1e-6)).astype(np.float32)


def speed(x: np.ndarray, factor: float) -> np.ndarray:
    n = int(len(x) / factor)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def main() -> int:
    tmp = Path("_test_audio")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    idx = AudioIndex(tmp / "templates.json")

    words = ["w%02d" % i for i in range(12)]
    for i, w in enumerate(words):
        idx.add(w, synth(i))
    idx.save()

    print("模板 %d 个，特征维度 %s" % (len(idx), log_mel(synth(0)).shape))

    queries = []
    for i, w in enumerate(words):
        base = synth(i)
        queries.append((w, "原样", base, True))
        queries.append((w, "加噪", base + np.random.default_rng(i).normal(0, 0.05, len(base)).astype(np.float32), True))
        queries.append((w, "音量30%", (base * 0.3).astype(np.float32), True))
        queries.append((w, "前加静音", np.concatenate([np.zeros(3200, dtype=np.float32), base]), True))
        # 变速会改音高：实际使用中学习/测试放的是同一段音频，不会变速，这里只做参考
        queries.append((w, "变速1.15(仅参考)", speed(base, 1.15), False))

    ok, total = 0, 0
    strict_ok, strict_total = 0, 0
    margins = []
    for expect, tag, q, strict in queries:
        best, dist, margin = idx.match(q)
        good = best == expect
        total += 1
        ok += 1 if good else 0
        if strict:
            strict_total += 1
            strict_ok += 1 if good else 0
        margins.append(margin)
        if not good and strict:
            print("  FAIL %s %-8s → %s (dist=%.2f margin=%.2f)" % (expect, tag, best, dist, margin))

    print("\n实际场景（原样/加噪/变音量/前加静音）：%d/%d" % (strict_ok, strict_total))
    print("全部（含变速参考项）：%d/%d，平均 margin %.3f" % (ok, total, float(np.mean(margins))))
    shutil.rmtree(tmp)
    return 0 if strict_ok == strict_total else 1


if __name__ == "__main__":
    raise SystemExit(main())

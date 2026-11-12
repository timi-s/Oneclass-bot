"""bench_match.py —— 音频指纹比对耗时（模板越多越慢，看看能撑到多少）"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from bot.audio_match import AudioIndex


def synth(seed: int, dur: float = 0.9, sr: int = 16000) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(sr * dur)) / sr
    f0 = rng.uniform(180, 900)
    x = np.zeros_like(t)
    for k, a in ((1, 1.0), (2, 0.5), (3, 0.3)):
        x += a * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28))
    x = x * np.exp(-2.5 * t) + rng.normal(0, 0.01, len(t))
    return (x / (np.abs(x).max() + 1e-6)).astype(np.float32)


def main() -> None:
    tmp = Path("_bench_audio.json")
    idx = AudioIndex(tmp)
    words = ["w%03d" % i for i in range(200)]
    for i, w in enumerate(words):
        idx.add(w, synth(i))

    query = synth(7) + np.random.default_rng(1).normal(0, 0.03, len(synth(7))).astype(np.float32)

    for n in (10, 30, 60, 120, 200):
        sub = AudioIndex(tmp)
        sub.templates = dict(list(idx.templates.items())[:n])
        t0 = time.perf_counter()
        sub.match(query)
        full = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        sub.match(query, candidates=[w for w, _ in sorted(idx.templates.items())[:8]])
        top8 = (time.perf_counter() - t0) * 1000
        print("模板 %3d 个：全量比对 %6.1f ms，候选 8 个 %5.1f ms" % (n, full, top8))

    tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

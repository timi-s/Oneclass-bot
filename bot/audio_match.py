"""audio_match.py —— 用「背单词阶段录下的发音」给听写题做音频指纹比对

思路：
  1) 背单词时页面会读音，录下来存成「单词 → 频谱特征」模板；
  2) 测试的听写题也读同一个词，录下来和模板比，找最像的那个。

好处：不依赖语音识别模型，同一个人、同一份音频，匹配非常稳。
代价：必须先在学习阶段把每个词的发音录一次。

特征：32 段对数梅尔谱（25ms 窗、10ms 步），用 DTW 算距离。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SR = 16000
N_FFT = 400
HOP = 160
N_BANDS = 32


def _mel_filterbank(sr: int = SR, n_fft: int = N_FFT, n_bands: int = N_BANDS) -> np.ndarray:
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)

    low, high = 80.0, sr / 2.0
    mels = np.linspace(hz2mel(low), hz2mel(high), n_bands + 2)
    freqs = mel2hz(mels)
    bins = np.floor((n_fft + 1) * freqs / sr).astype(int)
    fb = np.zeros((n_bands, n_fft // 2 + 1), dtype=np.float32)
    for i in range(n_bands):
        l, c, r = bins[i], bins[i + 1], bins[i + 2]
        if c == l:
            c = l + 1
        if r == c:
            r = c + 1
        fb[i, l:c] = np.linspace(0, 1, c - l, endpoint=False)
        fb[i, c:r] = np.linspace(1, 0, r - c, endpoint=False)
    return fb


_FB = _mel_filterbank()


def log_mel(samples: np.ndarray, sr: int = SR) -> np.ndarray:
    x = np.asarray(samples, dtype=np.float32).flatten()
    if x.size < N_FFT:
        x = np.pad(x, (0, N_FFT - x.size))
    if sr != SR:  # 线性重采样到 16k
        n_out = max(1, int(len(x) * SR / sr))
        t_in = np.linspace(0.0, 1.0, len(x), endpoint=False)
        t_out = np.linspace(0.0, 1.0, n_out, endpoint=False)
        x = np.interp(t_out, t_in, x).astype(np.float32)
    n_frames = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = x[idx]
    window = np.hanning(N_FFT).astype(np.float32)
    spec = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    energy = spec @ _FB.T
    feats = np.log(energy + 1e-8)
    # 每帧做均值方差归一化，抵消音量差异
    feats = (feats - feats.mean(axis=1, keepdims=True)) / (feats.std(axis=1, keepdims=True) + 1e-5)
    return feats.astype(np.float32)


def _trim_silence(samples: np.ndarray, ratio: float = 0.12) -> np.ndarray:
    x = np.asarray(samples, dtype=np.float32).flatten()
    if x.size == 0:
        return x
    frames = 1 + (len(x) - N_FFT) // HOP if len(x) >= N_FFT else 1
    if frames < 2:
        return x
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
    if idx[-1, -1] >= len(x):
        return x
    rms = np.sqrt((x[idx] ** 2).mean(axis=1))
    thr = max(rms.max() * ratio, 1e-4)
    keep = np.where(rms >= thr)[0]
    if keep.size == 0:
        return x
    start = max(0, HOP * keep[0] - N_FFT // 2)
    end = min(len(x), HOP * keep[-1] + N_FFT)
    return x[start:end]


def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """两条特征序列的归一化 DTW 距离。"""
    if a.size == 0 or b.size == 0:
        return 1e9
    n, m = len(a), len(b)
    band = max(10, int(0.35 * max(n, m)))
    dist = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    dist[0, 0] = 0.0
    diff = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2) if n * m <= 200000 else None
    if diff is None:  # 太大就逐行算
        diff = np.empty((n, m), dtype=np.float32)
        for i in range(n):
            diff[i] = np.linalg.norm(b - a[i], axis=1)

    for i in range(1, n + 1):
        lo = max(1, i - band)
        hi = min(m, i + band)
        for j in range(lo, hi + 1):
            cost = diff[i - 1, j - 1]
            best = min(dist[i - 1, j - 1], dist[i - 1, j], dist[i, j - 1])
            dist[i, j] = cost + best
    return float(dist[n, m] / max(n, m))


class AudioIndex:
    """单词 → 发音特征模板。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.templates: dict[str, np.ndarray] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for word, rows in data.items():
                    self.templates[word] = np.asarray(rows, dtype=np.float32)
            except Exception:
                self.templates = {}

    def __len__(self) -> int:
        return len(self.templates)

    def add(self, word: str, samples: np.ndarray, sr: int = SR, min_frames: int = 8) -> bool:
        word = (word or "").strip().lower()
        if not word:
            return False
        feats = log_mel(_trim_silence(samples), sr)
        if len(feats) < min_frames:
            return False
        self.templates.setdefault(word, feats)
        return True

    def save(self) -> None:
        data = {w: f.astype(np.float32).round(4).tolist() for w, f in self.templates.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def match(
        self,
        samples: np.ndarray,
        sr: int = SR,
        candidates: list[str] | None = None,
    ) -> tuple[str, float, float]:
        """返回 (最像的词, 距离, 与第二名的差距)。距离越小越像。

        candidates 用来先缩小范围（比如 whisper 已经听出个大概时只比最像的几个词），
        否则每题都要跟全部模板比一遍，词库大了会明显变慢。
        """
        feats = log_mel(_trim_silence(samples), sr)
        pool = self.templates
        if candidates:
            pool = {w: self.templates[w] for w in candidates if w in self.templates}
            if len(pool) < 2:  # 候选太少就退回全量
                pool = self.templates
        scored = sorted(
            ((dtw_distance(feats, tpl), w) for w, tpl in pool.items()),
            key=lambda x: x[0],
        )
        if not scored:
            return "", 1e9, 0.0
        best_d, best_w = scored[0]
        second = scored[1][0] if len(scored) > 1 else best_d * 2
        return best_w, best_d, float(second - best_d)

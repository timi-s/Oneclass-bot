"""bench3.py —— 细调线程数 / 检测边长，找准这台机器的甜点"""

from __future__ import annotations

import statistics
import time

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image
from rapidocr import RapidOCR

IMG = Image.open("bench_page.png").convert("RGB")
NEED = ["单词", "放弃", "下一词"]


def run(tag: str, threads: int, side: int, repeat: int = 4) -> float:
    params = {
        "Det.limit_type": "max",
        "Det.limit_side_len": side,
        "Global.use_cls": False,
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
    }
    ocr = RapidOCR(params=params)
    ocr(IMG)
    times, texts = [], []
    for _ in range(repeat):
        t0 = time.perf_counter()
        res = ocr(IMG)
        times.append((time.perf_counter() - t0) * 1000)
        texts = list(res.txts or [])
    joined = "".join(texts)
    hit = sum(1 for w in NEED if w in joined)
    avg = statistics.mean(times)
    print("  threads=%-2d side=%-4d %6.0f ms  %2d 段  命中 %d/3" % (threads, side, avg, len(texts), hit))
    return avg


def main() -> None:
    print("图片 %dx%d\n" % (IMG.width, IMG.height))
    print("A. 线程数（side=640）")
    best_t, best_ms = 0, 1e9
    for t in (1, 2, 3, 4, 5, 6):
        ms = run("t%d" % t, t, 640)
        if ms < best_ms:
            best_t, best_ms = t, ms

    print("\nB. 检测边长（threads=%d）" % best_t)
    for side in (448, 512, 576, 640, 768, 960):
        run("s%d" % side, best_t, side)

    print("\n结论：threads=%d，约 %.0f ms/帧" % (best_t, best_ms))


if __name__ == "__main__":
    main()

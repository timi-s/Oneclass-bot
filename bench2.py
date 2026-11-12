"""bench2.py —— OCR 参数矩阵：找出「够准 + 最快」的组合

不改动主程序，只是用 bench_page.png 试参数。
"""

from __future__ import annotations

import statistics
import time

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image
from rapidocr import RapidOCR

IMG = Image.open("bench_page.png").convert("RGB")
NEED = ["单词", "放弃", "下一词"]  # 只要这三类文字能认出来，页面状态就能判


def run(name: str, params: dict, scale: float = 1.0, repeat: int = 3) -> None:
    img = IMG
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    try:
        ocr = RapidOCR(params=params)
        ocr(img)  # 预热
        times, texts = [], []
        for _ in range(repeat):
            t0 = time.perf_counter()
            res = ocr(img)
            times.append((time.perf_counter() - t0) * 1000)
            texts = [t for t in (res.txts or [])]
        joined = "".join(texts)
        hit = [w for w in NEED if w in joined]
        print("  %-34s %6.0f ms  %2d 段  命中 %d/3 %s" % (
            name, statistics.mean(times), len(texts), len(hit), "" if len(hit) == 3 else "← " + str(hit)))
    except Exception as exc:
        print("  %-34s 失败：%s" % (name, exc))


def main() -> None:
    print("图片 %dx%d" % (IMG.width, IMG.height))
    print("\nA. 现状（默认参数）")
    run("default", {}, scale=1.0)
    run("default + scale1.6", {}, scale=1.6)

    print("\nB. 限制检测边长（limit_type=max）")
    for side in (960, 768, 640, 512):
        run("max=%d" % side, {"Det.limit_type": "max", "Det.limit_side_len": side})

    print("\nC. 关掉方向分类 cls")
    run("max=640 + no cls", {"Det.limit_type": "max", "Det.limit_side_len": 640, "Global.use_cls": False})

    print("\nD. 线程数")
    for th in (4, 8, 12):
        run("max=640 + %d threads" % th, {
            "Det.limit_type": "max", "Det.limit_side_len": 640,
            "EngineConfig.onnxruntime.intra_op_num_threads": th,
        })


if __name__ == "__main__":
    main()

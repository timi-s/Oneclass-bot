"""bench.py —— 测一下这台机器上「截图 + OCR」到底各花多少时间

用法：
    python bench.py                 # 默认区域尺寸 779x1066
    python bench.py --size 480 1007 --repeat 5
    python bench.py --image a.png   # 用真实截图测
"""

from __future__ import annotations

import argparse
import statistics
import time

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image, ImageDraw, ImageFont


def make_page(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    font_path = r"C:\Windows\Fonts\msyh.ttc"
    big = ImageFont.truetype(font_path, int(w * 0.075))
    mid = ImageFont.truetype(font_path, int(w * 0.055))
    small = ImageFont.truetype(font_path, int(w * 0.042))

    d.text((int(w * 0.08), int(h * 0.03)), "单词", font=big, fill="black")
    d.text((int(w * 0.08), int(h * 0.12)), "已学习 8 天", font=small, fill="black")
    d.text((int(w * 0.08), int(h * 0.22)), "abandon", font=big, fill="black")
    d.text((int(w * 0.08), int(h * 0.30)), "/əˈbændən/", font=small, fill="black")
    d.text((int(w * 0.08), int(h * 0.36)), "放弃，抛弃", font=mid, fill="black")
    d.text((int(w * 0.08), int(h * 0.45)), "例句：He abandoned the plan.", font=small, fill="black")
    d.text((int(w * 0.08), int(h * 0.55)), "请选择正确的释义", font=mid, fill="black")
    for i, t in enumerate(["增加", "放弃，抛弃", "保护", "忽略"]):
        d.text((int(w * 0.10), int(h * (0.60 + i * 0.07))), "○ " + t, font=mid, fill="black")
    d.rectangle([0, int(h * 0.93), w, h], fill="#ededed")
    d.text((int(w * 0.30), int(h * 0.955)), "下一词", font=mid, fill="black")
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", nargs=2, type=int, default=[779, 1066])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--image")
    args = ap.parse_args()

    if args.image:
        img = Image.open(args.image).convert("RGB")
        print("图片 %s  %dx%d" % (args.image, img.width, img.height))
    else:
        img = make_page(*args.size)
        img.save("bench_page.png")
        print("生成测试页 bench_page.png  %dx%d" % (img.width, img.height))

    from bot.vision import Vision

    print("\n== 截图（mss） ==")
    try:
        import mss

        with mss.mss() as sct:
            box = {"left": 0, "top": 0, "width": img.width, "height": img.height}
            times = []
            for _ in range(args.repeat + 2):
                t0 = time.perf_counter()
                shot = sct.grab(box)
                times.append((time.perf_counter() - t0) * 1000)
            times = times[2:]
            print("  平均 %.1f ms" % statistics.mean(times))
    except Exception as exc:
        print("  跳过：%s" % exc)

    print("\n== OCR（RapidOCR） ==")
    for scale in (1.0, 1.2, 1.6, 2.0):
        v = Vision(scale, 0.45)
        v.read(img)  # 预热，避免把模型加载算进去
        times = []
        for _ in range(args.repeat):
            t0 = time.perf_counter()
            items = v.read(img)
            times.append((time.perf_counter() - t0) * 1000)
        print("  scale=%.1f  平均 %6.0f ms   识别 %d 段" % (scale, statistics.mean(times), len(items)))

    print("\n== 起一次 ==")
    print("  单次循环 ≈ 截图 + OCR + 判断 + 点击")


if __name__ == "__main__":
    main()

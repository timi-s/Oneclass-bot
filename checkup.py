"""checkup.py —— 运行前自检：区域、截图、OCR、页面状态一次看完

用法：
    python checkup.py                # 实时截一张小程序区域，跑 OCR，判断当前是什么页面
    python checkup.py --image a.png  # 用已有截图检查（不截屏）

它不会点击任何东西，纯只读，随时可以跑。
"""

from __future__ import annotations

# DPI 必须在导入 pyautogui / mss 之前处理
from bot.windows_dpi import enable_dpi_awareness, system_scale_percent

DPI_MODE = enable_dpi_awareness()

import argparse
import sys
from pathlib import Path

from PIL import Image

from bot.config import ROOT, load_config

ADVICE = {
    "word_home": "单词模块首页，可以开始跑（脚本会点「开始背诵」）",
    "exam_start": "任务说明页，可以开始跑（脚本会点「开始测验」）",
    "word_home_extra": "单词首页（已有「再来一组」），可以开始跑",
    "home": "还在 App 首页，请先点进「单词」模块",
    "learn_hidden": "背单词：隐藏释义页，脚本会点空白显示答案",
    "learn_revealed": "背单词：答案页，脚本会记录词义并点「认识」",
    "learn_too_easy": "背单词：重复词页，脚本会点「标记为太简单」",
    "learn_detail": "背单词：详情页，脚本会点「下一词」",
    "section_complete": "小节结束页，脚本会点「继续背单词」",
    "learn_complete": "学习完成弹窗，脚本会点「确认」",
    "task_timeout": "任务超时弹窗，脚本会点绿色「再来一组」",
    "test_choice": "选择题页，脚本会按词库匹配选项",
    "test_dictation": "听写页（当前 dictation_mode 决定行为）",
    "test_result": "测验结果页",
    "unknown": "没认出来 —— 九成是区域没框对，或窗口被遮挡，请重新校准",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="用这张图片代替实时截图")
    args = ap.parse_args()

    cfg = load_config()
    region = cfg["region"]
    scale = system_scale_percent()
    print("DPI 模式：%s%s" % (DPI_MODE, "，检测缩放约 %d%%" % scale if scale else ""))
    print("截图区域：left=%d top=%d width=%d height=%d" % tuple(region))

    try:
        import mss  # noqa: F401
    except Exception as exc:
        print("缺少依赖 mss：%s" % exc)
        return 2

    if args.image:
        img = Image.open(args.image).convert("RGB")
        print("图片：%s  (%dx%d)" % (args.image, img.width, img.height))
    else:
        from bot.screen import Screen
        screen = Screen(
            region,
            cfg.get("after_click_delay", 0.85),
            cfg.get("input_backend", "win32"),
            cfg.get("win32_fallback_to_pyautogui", True),
        )
        # 截图前把小程序窗口置前，否则截到的是压在上面的浏览器/命令行
        try:
            from bot.controller import WordBot

            _probe = WordBot(cfg, ROOT)
            _probe.ensure_target_foreground()
        except Exception as exc:  # noqa: BLE001
            print("（置前窗口失败，忽略：%s）" % exc)
        img = screen.capture()
        out = ROOT / "checkup.png"
        img.save(out)
        print("已截图：%s  (%dx%d)" % (out, img.width, img.height))

    try:
        from bot.vision import Vision
        vision = Vision(cfg.get("ocr_scale", 1.6), cfg.get("ocr_min_score", 0.45))
        items = vision.read(img)
    except Exception as exc:
        print("OCR 初始化失败：%s" % exc)
        return 2

    print("\nOCR 识别到 %d 段文字：" % len(items))
    for it in items[:12]:
        print("  - %s  (%.0f, %.0f)" % (it.text, it.cx, it.cy))

    from bot.controller import WordBot
    bot = WordBot(cfg, ROOT)

    from PIL import ImageStat
    stat = ImageStat.Stat(img.convert("L"))
    if stat.stddev[0] < 2.5:
        print("\n⚠️ 这张图几乎是纯色（均值 %.0f，方差 %.1f）：" % (stat.mean[0], stat.stddev[0]))
        print("   要么小程序窗口被最小化/遮挡，要么屏幕已经休眠。")
        print("   先还原窗口、关掉屏幕休眠，再重新跑 checkup。")
        return 2

    if img.width > img.height:
        print("\n⚠️ 校准区域是横的（%d×%d）。小程序通常是竖屏，可能框错了位置。" % (img.width, img.height))

    state = bot.detect_state(items)
    print("\n页面状态：%s" % state)
    print("说明：%s" % ADVICE.get(state, "未知状态，看日志 log 里的 detect_state"))

    if state == "unknown":
        print("\n排查顺序：")
        print("  1) 打开 checkup.png，看它截的是不是小程序内容区；")
        print("  2) 如果是桌面/其他窗口 → 小程序没置前，或窗口被遮挡；")
        print("  3) 如果只截到一半 → 重新跑 calibrate.cmd；")
        print("  4) 如果截图正确但文字为空 → 调大 ocr_scale，或调低 ocr_min_score。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

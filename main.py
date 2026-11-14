from __future__ import annotations

import sys as _sys

_FRIENDLY = None

try:
    # DPI awareness must be enabled before importing PyAutoGUI/MSS through the bot.
    from bot.windows_dpi import enable_dpi_awareness, system_scale_percent

    DPI_MODE = enable_dpi_awareness()

    import logging
    import sys
    from pathlib import Path

    from bot.config import ROOT, load_config
    from bot.purchase import ensure_license_or_exit, exit_if_purchase_command
except Exception as _exc:  # noqa: BLE001
    import traceback as _tb

    _FRIENDLY = "启动失败：%s: %s\n" % (type(_exc).__name__, _exc)
    if _sys.version_info[:2] != (3, 13):
        _FRIENDLY += ("当前 Python 是 %d.%d，本程序依赖按 3.13 编译。\n"
                      "请安装 Python 3.13 后重新双击 安装.cmd。\n" % _sys.version_info[:2])
    elif "No module named" in str(_exc):
        _FRIENDLY += "依赖没装好（%s），请双击 安装.cmd 重新安装依赖。\n" % _exc
    else:
        _FRIENDLY += "请双击 安装.cmd 检查环境，或把下面的信息发给卖家。\n"
    _FRIENDLY += "\n完整错误：\n" + _tb.format_exc()
    print(_FRIENDLY)
    try:
        from pathlib import Path as _Path

        _log = _Path(__file__).resolve().parent / "logs" / "bot_console.log"
        _log.parent.mkdir(parents=True, exist_ok=True)
        _log.write_text(_FRIENDLY, encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(2)


def main() -> None:
    exit_if_purchase_command(sys.argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(ROOT / "wordbot.log", encoding="utf-8"),
        ],
    )
    scale = system_scale_percent()
    logging.getLogger("wordbot").info(
        "Windows DPI 模式：%s%s",
        DPI_MODE,
        f"，检测缩放约 {scale}%" if scale else "",
    )
    cfg = load_config()
    if not ensure_license_or_exit(cfg):
        raise SystemExit(1)
    from bot.controller import WordBot

    bot = WordBot(cfg, Path(ROOT))
    bot.run()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("已手动停止。")
    except Exception:  # noqa: BLE001
        # 崩溃也要落盘，方便事后看 wordbot.log 里的 traceback
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(ROOT / "wordbot.log", encoding="utf-8"),
            ],
        )
        logging.getLogger("wordbot").exception("机器人异常退出")
        raise

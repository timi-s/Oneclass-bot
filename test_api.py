"""test_api.py —— 用本地假服务器验证「API 视觉后端」能跑通（不消耗真实额度）"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bot.windows_dpi import enable_dpi_awareness

enable_dpi_awareness()

from PIL import Image

from bot.controller import WordBot
from bot.vision_api import ApiVision

REPLY = [
    {"text": "单词", "bbox": [60, 30, 200, 90]},
    {"text": "开始背诵", "bbox": [150, 280, 420, 350]},
]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps(REPLY, ensure_ascii=False)}}]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    cfg = {
        "ocr_engine": "api",
        "ocr_api": {
            "base_url": "http://127.0.0.1:%d/v1" % port,
            "api_key": "test-key",
            "model": "fake-vl",
            "timeout": 5,
        },
        "region": [0, 0, 460, 1000],
        "loop_interval": 0.1,
        "after_click_delay": 0.1,
        "input_backend": "win32",
    }

    img = Image.new("RGB", (460, 1000), "white")
    v = ApiVision(cfg)
    items = v.read(img)
    txts = [i.text for i in items]

    checks = []
    checks.append(("解析出两段文字", txts == ["单词", "开始背诵"], txts))
    checks.append(("坐标换算到像素", abs(items[1].cx - 131.1) < 3 and abs(items[1].cy - 315) < 3,
                   (items[1].cx, items[1].cy)))
    bot = WordBot(cfg, __import__("pathlib").Path(".").resolve())
    checks.append(("页面状态识别为 word_home", bot.detect_state(items) == "word_home",
                   bot.detect_state(items)))
    checks.append(("控制器确实用了 API 后端", type(bot.vision).__name__ == "ApiVision",
                   type(bot.vision).__name__))

    ok = 0
    for name, cond, extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else "  <> %s" % (extra,)))
        ok += 1 if cond else 0
    print("\nAPI: %d/%d passed" % (ok, len(checks)))
    srv.shutdown()
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

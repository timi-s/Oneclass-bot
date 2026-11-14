"""test_template_origin.py —— 不是本机录的发音模板要自动停用

现场：别人装好后听写一直不灵，换成自己积累的模板就好了 ——
说明 audio_templates.json 带着「别的机器」的录音特征。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "site-packages"))

from bot.audio_match import AudioIndex  # noqa: E402
from bot.windows_dpi import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from bot.controller import WordBot  # noqa: E402
from bot.machine import machine_id  # noqa: E402


class FakeRegion:
    width, height = 300, 600


class FakeScreen:
    def __init__(self):
        self.region = FakeRegion()

    def capture(self):
        from PIL import Image

        return Image.new("RGB", (300, 600), "white")

    def click_rel(self, *a, **k):
        pass

    def click_abs(self, *a, **k):
        pass

    def foreground_click_rel(self, *a, **k):
        pass

    def save_debug(self, *a, **k):
        return Path(".")


def make_cfg(region):
    return {
        "region": region,
        "loop_interval": 0.3,
        "input_backend": "win32",
        "verify_clicks": False,
        "audio_templates": True,
        "audio_templates_strict": True,
        "dictation_mode": "whisper",
        "ocr_max_side": 512,
        "ocr_threads": 3,
        "fallback_points": {"know": [0.5, 0.8]},
    }


def main() -> int:
    checks = []
    tmp = ROOT / "_test_tmp" / "tpl"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copy(ROOT / "vocab.json", tmp / "vocab.json")
    (tmp / "config.yaml").write_text("region: [0, 0, 300, 600]\n", encoding="utf-8")

    # 1) 保存后会写入 _meta.machine
    idx = AudioIndex(tmp / "audio_templates.json")
    idx.meta["machine"] = machine_id()
    idx.templates["salary"] = np.zeros((10, 32), dtype=np.float32)
    idx.save()
    raw = json.loads((tmp / "audio_templates.json").read_text(encoding="utf-8"))
    checks.append(("保存写入 _meta.machine", raw.get("_meta", {}).get("machine") == machine_id(),
                   raw.get("_meta")))
    checks.append(("模板内容在 templates 下", "salary" in (raw.get("templates") or {}),
                   list((raw.get("templates") or {}).keys())))

    # 2) 本机模板：读取后 machine_ok = True
    idx2 = AudioIndex(tmp / "audio_templates.json")
    checks.append(("本机模板判定为匹配", idx2.machine_ok(machine_id()) is True,
                   idx2.machine_ok(machine_id())))

    # 3) 别的机器的模板：machine_ok = False，控制器应禁用模板
    other = dict(raw)
    other["_meta"] = {"machine": "ZZ-ZZZZ-ZZZZ-ZZZZ", "saved": "2026-11-01 10:00:00"}
    (tmp / "audio_templates.json").write_text(json.dumps(other), encoding="utf-8")
    idx3 = AudioIndex(tmp / "audio_templates.json")
    checks.append(("别机模板判定为不匹配", idx3.machine_ok(machine_id()) is False,
                   idx3.machine_ok(machine_id())))

    cfg = make_cfg([0, 0, 300, 600])
    bot = WordBot(cfg, tmp)
    bot.vision = type("V", (), {"read": staticmethod(lambda img: [])})()
    bot.screen = FakeScreen()
    checks.append(("控制器自动停用别机模板",
                   getattr(bot, "audio_index", None) is None, bot.audio_index))

    # 4) 本机模板：控制器保留模板
    idx4 = AudioIndex(tmp / "audio_templates.json")
    idx4.meta["machine"] = machine_id()
    idx4.templates["salary"] = np.zeros((10, 32), dtype=np.float32)
    idx4.save()
    bot2 = WordBot(make_cfg([0, 0, 300, 600]), tmp)
    bot2.screen = FakeScreen()
    checks.append(("控制器保留本机模板",
                   getattr(bot2, "audio_index", None) is not None, bot2.audio_index))

    ok = 0
    for name, cond, *extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if not extra else "  <> %s" % (extra[0],)))
        ok += 1 if cond else 0
    print("\nTEMPLATE_ORIGIN: %d/%d passed" % (ok, len(checks)))
    shutil.rmtree(ROOT / "_test_tmp", ignore_errors=True)
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

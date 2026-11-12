"""下载 faster-whisper small.en 语音模型到 models/small.en

用法：
    python 下载模型.py
联网下载约 460 MB；已经存在就跳过。
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO = "Systran/faster-whisper-small.en"
TARGET = Path(__file__).resolve().parent / "models" / "small.en"
FILES = [
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
]


def human(n: int) -> str:
    return "%.1f MB" % (n / 1024 / 1024)


def via_hub() -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        print("  没有 huggingface_hub，改用直链下载")
        return False
    print("  使用 huggingface_hub 下载 …")
    snapshot_download(
        repo_id=REPO,
        local_dir=str(TARGET),
        allow_patterns=FILES,
    )
    return True


def via_http() -> None:
    base = "https://huggingface.co/%s/resolve/main/" % REPO
    for name in FILES:
        dst = TARGET / name
        if dst.exists() and dst.stat().st_size > 0:
            print("  已存在，跳过 %s" % name)
            continue
        url = base + name
        print("  下载 %s …" % name)
        tmp = dst.with_suffix(dst.suffix + ".part")
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print("\r    %s / %s" % (human(done), human(total)), end="")
        print()
        tmp.replace(dst)


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    model = TARGET / "model.bin"
    if model.exists() and model.stat().st_size > 100 * 1024 * 1024:
        print("模型已存在：%s（%s）" % (model, human(model.stat().st_size)))
        return 0

    print("开始下载语音模型 %s 到 %s" % (REPO, TARGET))
    ok = False
    try:
        ok = via_hub()
    except Exception as exc:  # noqa: BLE001
        print("  huggingface_hub 下载失败：%s" % exc)
    if not ok:
        try:
            via_http()
        except Exception as exc:  # noqa: BLE001
            print("\n[失败] 下载没完成：%s" % exc)
            print("请检查网络，或手动下载下面 4 个文件放进 %s：" % TARGET)
            print("  https://huggingface.co/%s/tree/main" % REPO)
            for name in FILES:
                print("   - %s" % name)
            return 1

    if not model.exists() or model.stat().st_size < 100 * 1024 * 1024:
        print("[失败] model.bin 不完整，请重跑本脚本或手动下载。")
        return 1
    print("完成：%s（%s）" % (model, human(model.stat().st_size)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

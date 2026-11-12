"""test_audio_match.py —— 验证「从识别文本里挑对的词」

whisper 常把一个词听成多个词；旧逻辑取最长词容易取错，改为按词库相似度挑。
"""

import json
import shutil
from pathlib import Path

from bot.audio_solver import AudioSolver
from bot.vocab import VocabStore

VOCAB = {
    "abandon": "v. 放弃，抛弃",
    "culture": "n. 文化",
    "invade": "v. 入侵",
    "scrape": "v. 刮，擦",
    "liberal": "adj. 自由的",
    "recovery": "n. 恢复",
    "elect": "v. 选举",
    "herd": "n. 兽群",
}

# (识别原文, 期望选出的词)
CASES = [
    ("abandon", "abandon"),
    ("abandon and culture", "abandon"),
    ("culture", "culture"),
    ("elect", "elect"),
    ("the bond", "bond"),
    ("", ""),
    ("???", ""),
    ("a abandonment story", "abandonment"),
]


def main() -> int:
    tmp = Path("_test_vocab")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    (tmp / "vocab.json").write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    words = VocabStore(tmp / "vocab.json").words()

    ok = 0
    for raw, expect in CASES:
        got = AudioSolver.best_token(raw, words)
        cond = got == expect
        print(("  OK   " if cond else "  FAIL ") + "%-24r → %-14r（期望 %r）" % (raw, got, expect))
        ok += 1 if cond else 0

    print("\nAUDIO_MATCH: %d/%d passed" % (ok, len(CASES)))
    shutil.rmtree(tmp)
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())

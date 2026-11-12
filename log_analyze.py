import re
from datetime import datetime

lines = open("wordbot.log", encoding="utf-8").read().splitlines()
rows = []
for ln in lines:
    m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", ln)
    if m:
        rows.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), ln))

print("日志行数:", len(rows))
print("时间范围:", rows[0][0], "→", rows[-1][0])

gaps = []
for (t1, _), (t2, l2) in zip(rows, rows[1:]):
    d = (t2 - t1).total_seconds()
    if d >= 60:
        gaps.append((d, t1, l2))

print("\n超过 60 秒的空档：%d 处" % len(gaps))
for d, t, l in gaps:
    print("  %5.0fs  %s → 下一条：%s" % (d, t.time(), l[:110]))

print("\n关键状态出现次数：")
for key in ["learn_complete", "section_complete", "再来一组", "task_timeout",
            "test_result", "test_choice", "test_dictation", "unknown", "已记录词义"]:
    n = sum(1 for _, ln in rows if key in ln)
    print("  %-16s %d" % (key, n))

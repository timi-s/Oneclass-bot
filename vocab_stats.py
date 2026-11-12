import json
import re

d = json.load(open("vocab.json", encoding="utf-8"))
apos = [k for k in d if "'" in k]
short = [k for k in d if len(k) < 3]
pos = [v for v in d.values() if re.match(r"^(n|v|adj|adv|prep|conj|pron|num|art)\.", v)]
weird = [v for v in d.values() if "...." in v or "。。" in v or "||" in v]
onechar = [k for k in d if not re.fullmatch(r"[a-z]+", k)]

print("总词条:", len(d))
print("含撇号（多为 OCR 误识）:", len(apos), apos[:6])
print("长度<3:", len(short), short[:6])
print("含非 a-z 字符:", len(onechar), onechar[:8])
print("释义带词性:", len(pos))
print("释义异常:", len(weird), weird[:3])
print("可疑键合计:", len(set(apos) | set(short) | set(onechar)))

"""machine.py —— 机器码（两个版本共用；付费版 license.py 也用它）

免费版没有 bot/license.py，所以机器码放在这里，避免 controller / audio_match
在免费版里 import 失败。
"""

from __future__ import annotations

import hashlib
import subprocess
import uuid


def _machine_guid() -> str:
    try:
        out = subprocess.run(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            if "MachineGuid" in line:
                return line.split()[-1].strip()
    except Exception:
        pass
    return ""


def _volume_serial() -> str:
    try:
        import ctypes

        serial = ctypes.c_uint32(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            "C:\\", None, 0, ctypes.byref(serial), None, None, None, 0,
        )
        return "%08X" % serial.value if ok else ""
    except Exception:
        return ""


def machine_id() -> str:
    """形如 A1-EFD8-115C-4432；换电脑/重装系统才变。"""
    raw = "%s|%s|%s" % (_machine_guid(), _volume_serial(), uuid.getnode())
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return "%s-%s-%s-%s" % (digest[0:2], digest[2:6], digest[6:10], digest[10:14])

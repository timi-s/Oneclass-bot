"""gui.py —— OneClass 学习助手（v2，重建版）

设计目标（按用户要求）：
1. 界面清爽：左边定位/速度/引擎，右边按钮 + 日志 + 教程，底部状态栏。
2. 绝不“卡死不动”：界面层自带看门狗，机器人 45 秒没有新日志就自动杀掉并提示。
3. 日志直接跟随 wordbot.log（不依赖 stdout 管道，pythonw 下也不会空白）。

只依赖标准库 tkinter。
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yaml"
SITE = ROOT / "site-packages"
LOG_FILE = ROOT / "wordbot.log"
LOGS = ROOT / "logs"
CRASH_LOG = ROOT / "gui_crash.log"

APP_TITLE = "OneClass 背单词 · 设置与运行"
SILENCE_LIMIT = 45.0        # 机器人多久没日志就判定卡死（秒）
POLL_MS = 300

TUTORIAL = """使用步骤
────────────────────────────
1. 打开电脑版微信 →「一课英语」小程序，拖到固定位置，
   白色内容区完整露出，别最小化、别被别的窗口压住。

2. 点「1. 扫描窗口」→ 选中 OneClass 窗口 → 点「2. 预览并确认定位」。
   预览里应只有小程序内容；框歪了就重新扫描或跑 calibrate.cmd。

3. 选答题速度（新手「均衡档」）与听写引擎（本地 Whisper，离线免费）。

4. 点「保存配置」→「预检」→「▶ 启动机器人」。

5. 停止：点「■ 停止」，或直接关窗口。

按钮说明
────────────────────────────
· 保存配置    把速度/模型写进 config.yaml（只改相关几行）
· 预检        检查区域、模型、依赖、Python 版本，不启动
· 自检        跑 checkup.py：只截图 + 识别，不点击
· ▶ 启动机器人 以子进程方式运行 main.py
· ■ 停止      结束机器人（含子进程）

防卡死机制
────────────────────────────
· 页面卡住 20 秒：日志提示「请手动点一下页面」
· 主循环卡 20 秒：机器人自己打印调用栈
· 录音卡 8 秒   ：跳过该词的发音模板，继续往下
· 45 秒没有任何日志：界面自动杀掉机器人并报错（不会无限挂着）

注意
────────────────────────────
· 运行时别在同一块屏幕上用别的程序（脚本靠截屏工作）。
· 小程序规定「背诵/考试中途退出不保存记录」，别中途关掉。
· 听写没声音：改 config.yaml 的 audio_loopback_name
  （用 python list_audio_devices.py 查设备名）。
· 状态一直 unknown：先点「自检」，再重新定位窗口。
"""

SPEED_PRESETS = {
    "fast": {"label": "快档 · 录音 2.0s，尝试 1 次", "hint": "最快，识别失败直接跳过",
             "audio_record_seconds": 2.0, "dictation_max_attempts": 1},
    "balanced": {"label": "均衡档 · 录音 2.4s，重听 1 次", "hint": "推荐：速度与准确率兼顾",
                 "audio_record_seconds": 2.4, "dictation_max_attempts": 2},
    "accurate": {"label": "准档 · 录音 3.2s，重听 2 次", "hint": "最慢，听写最准",
                 "audio_record_seconds": 3.2, "dictation_max_attempts": 3},
}

MODEL_CHOICES = ["models/small.en", "models/distil-large-v3", "models/medium.en"]


# ------------------------------------------------------------------ 配置
def read_config_text() -> str:
    return CONFIG.read_text(encoding="utf-8")


def get_value(text: str, key: str) -> str | None:
    m = re.search(r"^%s:[ \t]*(.*)$" % re.escape(key), text, re.MULTILINE)
    return m.group(1).strip() if m else None


def set_value(text: str, key: str, value) -> str:
    line = "%s: %s" % (key, value)
    pattern = re.compile(r"^%s:[ \t]*.*$" % re.escape(key), re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text.rstrip() + "\n" + line + "\n"


def speed_of(text: str) -> str:
    try:
        n = int(get_value(text, "dictation_max_attempts") or "2")
    except ValueError:
        n = 2
    return {1: "fast", 2: "balanced"}.get(n, "accurate")


def apply_speed(text: str, key: str) -> str:
    preset = SPEED_PRESETS[key]
    text = set_value(text, "audio_record_seconds", preset["audio_record_seconds"])
    text = set_value(text, "dictation_max_attempts", preset["dictation_max_attempts"])
    return text


def set_region(text: str, region: tuple[int, int, int, int]) -> str:
    x, y, w, h = region
    block = "region:\n  - %d\n  - %d\n  - %d\n  - %d\n" % (x, y, w, h)
    pattern = re.compile(
        r"^region:[ \t]*\r?\n(?:(?:[ \t]*-[ \t]*\d+[ \t]*)\r?\n)+", re.MULTILINE)
    return pattern.sub(block, text, count=1) if pattern.search(text) else block + text


def parse_region(text: str) -> list[int] | None:
    try:
        sys.path.insert(0, str(SITE))
        import yaml

        region = (yaml.safe_load(text) or {}).get("region")
        if isinstance(region, list) and len(region) == 4:
            return [int(v) for v in region]
    except Exception:
        pass
    return None


def _yaml_ok(text: str) -> bool:
    try:
        sys.path.insert(0, str(SITE))
        import yaml

        cfg = yaml.safe_load(text)
        return isinstance(cfg.get("region"), list) and len(cfg["region"]) == 4
    except Exception:
        return False


# ------------------------------------------------------------------ 窗口
def enable_dpi_awareness():
    from bot.windows_dpi import enable_dpi_awareness as _enable

    return _enable()


def scan_windows() -> list[dict]:
    """列出一课英语小程序窗口（标题、句柄、客户区物理像素、是否最小化）。"""
    keywords = ["一课英语", "OneClass", "Oneclass", "one class", "微信", "WeChat"]
    skip_titles = ("设置与运行", "学习助手", "预览", "DeepSeek Harness", "刷单词脚本")
    out: list[dict] = []
    try:
        enable_dpi_awareness()
        import ctypes
        from ctypes import wintypes
    except Exception:
        return out

    u = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def client_rect(hwnd):
        rc, origin = RECT(), POINT(0, 0)
        if not u.GetClientRect(hwnd, ctypes.byref(rc)):
            return None
        if not u.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
        return (origin.x, origin.y, rc.right - rc.left, rc.bottom - rc.top)

    def cb(hwnd, _):
        try:
            if not u.IsWindowVisible(hwnd):
                return True
            n = u.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title or any(s in title for s in skip_titles):
                return True
            if not any(k in title for k in keywords):
                return True
            rect = client_rect(hwnd)
            if rect is None:
                return True
            out.append({"title": title, "hwnd": int(hwnd), "rect": rect,
                        "minimized": bool(u.IsIconic(hwnd))})
        except Exception:
            pass
        return True

    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    try:
        u.EnumWindows(PROC(cb), 0)
    except Exception:
        return out

    seen, result = set(), []
    for row in out:
        key = (row["title"], row["rect"])
        if key in seen:
            continue
        seen.add(key)
        if not row["minimized"] and (row["rect"][2] < 120 or row["rect"][3] < 120):
            continue
        result.append(row)
    return result


def bring_foreground(hwnd: int) -> bool:
    """把窗口置前（含 Windows 前台锁的几种绕法），返回是否成功。"""
    try:
        enable_dpi_awareness()
        import ctypes

        u = ctypes.windll.user32
        u.ShowWindow(hwnd, 9)                      # SW_RESTORE
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 5)
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(hwnd)
        u.BringWindowToTop(hwnd)
        time.sleep(0.2)
        if int(u.GetForegroundWindow()) != hwnd:
            try:
                u.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass
        return int(u.GetForegroundWindow()) == hwnd
    except Exception:
        return False


# ------------------------------------------------------------------ 截图 / 识别
def grab_region(region: list[int]):
    sys.path.insert(0, str(SITE))
    import mss
    from PIL import Image

    x, y, w, h = [int(v) for v in region]
    with mss.mss() as sct:
        shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


PAGE_HINTS = [
    ("学习/背单词页", ("请跟读并默念", "显示答案", "标记为太简单", "无需复习")),
    ("单词主页", ("开始背诵", "词库预览", "今日任务", "学习天数")),
    ("选择题", ("请选择正确的释义", "请选择正确的意思", "单词测试")),
    ("听写题", ("填写你听到的单词", "听到的单词")),
    ("测验总结", ("完成了今日单词测试", "正确率", "完成测验", "错题巩固")),
    ("超时弹窗", ("任务超时", "词语未背诵")),
]


def guess_page(text: str) -> str | None:
    for name, keys in PAGE_HINTS:
        if any(k in text for k in keys):
            return name
    return None


def probe_region(region: list[int]) -> tuple[str | None, str]:
    try:
        sys.path.insert(0, str(SITE))
        from bot.vision import Vision

        v = Vision(1.0, 0.45, 512, 3, False, False)
        text = v.joined(v.read(grab_region(region)))
        return guess_page(text), text
    except Exception as exc:  # noqa: BLE001
        return None, "OCR 失败：%s" % exc


def preflight() -> list[str]:
    problems: list[str] = []
    text = read_config_text()

    region = parse_region(text)
    if not region:
        problems.append("config.yaml 里没有有效的 region（识别区域）")
    else:
        x, y, w, h = region
        if w < 120 or h < 120:
            problems.append("region 太小（%dx%d），请重新定位窗口" % (w, h))
        if w > h:
            problems.append("region 是横向的（%dx%d），小程序窗口一般是竖向" % (w, h))
        try:
            import ctypes

            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            if sw and sh and (x + w > sw or y + h > sh or x < 0 or y < 0):
                problems.append(
                    "识别区域超出屏幕（屏幕 %dx%d，区域 %d,%d %dx%d）："
                    "请点「扫描窗口 → 预览并确认定位」重新定位"
                    % (sw, sh, x, y, w, h))
        except Exception:
            pass
        page, ocr = probe_region(region)
        if page is None:
            problems.append("这块区域截图后认不出小程序内容（多半被别的窗口挡住了）：%s"
                            % (ocr[:60] or "OCR 为空"))

    model = get_value(text, "whisper_model") or ""
    if (get_value(text, "dictation_mode") or "").lower() == "whisper":
        bin_file = ROOT / model / "model.bin"
        if not bin_file.exists():
            problems.append("语音模型缺失：%s（听写会失败，可跑 下载模型.py）" % model)

    if sys.version_info[:2] != (3, 13):
        problems.append("当前 Python 是 %d.%d，依赖是按 3.13 装的" % sys.version_info[:2])

    # 回环录音自检（子进程，崩了也不影响界面）
    try:
        env_a = dict(os.environ, PYTHONPATH=str(SITE), PYTHONIOENCODING="utf-8")
        ra = subprocess.run([sys.executable, "-m", "bot.audio_probe"],
                            cwd=str(ROOT), env=env_a, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=25)
        out_a = (ra.stdout or "").strip().splitlines()
        line_a = out_a[-1] if out_a else ""
        if ra.returncode != 0:
            problems.append(
                "回环录音不可用（%s）：听写题会失败。可先把 config.yaml 的 "
                "audio_capture 改成 false（只背单词），或换 audio_loopback_name"
                % (line_a[:60] or "soundcard 报错"))
    except Exception:
        pass

    env = dict(os.environ, PYTHONPATH=str(SITE))
    try:
        r = subprocess.run([sys.executable, "-c",
                            "import yaml, cv2, mss, pyautogui, rapidocr, onnxruntime"],
                           env=env, capture_output=True, timeout=90)
        if r.returncode != 0:
            problems.append("依赖不全，请先双击 安装.cmd")
    except Exception as exc:  # noqa: BLE001
        problems.append("依赖检查失败：%s" % exc)
    return problems


# ------------------------------------------------------------------ 日志跟随
class LogTail:
    """按增量读 wordbot.log（比管道可靠）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.pos = self.path.stat().st_size if self.path.exists() else 0

    def reset(self) -> None:
        self.pos = self.path.stat().st_size if self.path.exists() else 0

    def read_new(self) -> list[str]:
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:
            self.pos = 0
        if size == self.pos:
            return []
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(self.pos)
            chunk = fh.read()
            self.pos = fh.tell()
        return chunk.splitlines()


class BotRunner:
    """机器人子进程 + 看门狗（45 秒无日志自动杀掉）。"""

    def __init__(self, tail: LogTail, cmd: list[str] | None = None):
        self.tail = tail
        self.cmd = cmd                      # 测试时可注入命令
        self.proc: subprocess.Popen | None = None
        self.last_log_at = time.monotonic()
        self.killed_by_watchdog = False
        self.exit_reported = False
        self.console_log = ROOT / "logs" / "bot_console.log"

    def console_tail(self, n: int = 8) -> list[str]:
        """机器人控制台输出（python 的错误都在这里）。"""
        try:
            if not self.console_log.exists():
                return []
            text = self.console_log.read_text(encoding="utf-8", errors="replace")
            return [ln for ln in text.splitlines() if ln.strip()][-n:]
        except Exception:
            return []

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        if self.running:
            return True
        env = dict(os.environ, PYTHONPATH=str(SITE), PYTHONIOENCODING="utf-8")
        cmd = self.cmd or [sys.executable, "-u", str(ROOT / "main.py")]
        try:
            self.console_log.parent.mkdir(parents=True, exist_ok=True)
            self._console = open(self.console_log, "w", encoding="utf-8", errors="replace")
            self.proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                                         stdout=self._console,
                                         stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            try:
                self._console.write("启动失败：%s\n" % exc)
                self._console.close()
            except Exception:
                pass
            return False
        self.tail.reset()
        self.last_log_at = time.monotonic()
        self.killed_by_watchdog = False
        return True

    def stop(self) -> None:
        if not self.running:
            return
        try:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, text=True)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def tick(self) -> tuple[list[str], str | None]:
        """返回 (新日志, 需要提示的消息)。停滞超时会被自动杀掉。"""
        lines = self.tail.read_new()
        if lines:
            self.last_log_at = time.monotonic()
        note = None
        if (not self.running) and self.proc is not None and not self.exit_reported \
                and not self.killed_by_watchdog:
            self.exit_reported = True
            code = self.proc.returncode
            tail_lines = self.console_tail(10)
            detail = "\n".join(tail_lines) if tail_lines else "（没有输出）"
            note = ("机器人启动后自己退出了（退出码 %s）。\n\n最后输出：\n%s\n\n"
                    "常见原因：依赖没装好 / Python 版本不对 / 配置写坏。\n"
                    "完整记录见 logs\\bot_console.log" % (code, detail[-800:]))
            try:
                if hasattr(self, "_console") and self._console:
                    self._console.close()
            except Exception:
                pass
        if self.running:
            quiet = time.monotonic() - self.last_log_at
            if quiet > SILENCE_LIMIT:
                self.killed_by_watchdog = True
                self.stop()
                note = ("机器人已经 %.0f 秒没有任何日志，判定为卡死，已自动停止。"
                        "请查看小程序是否卡住/被遮挡，然后重新启动。" % quiet)
                # 把这次强制停止写进机器人日志，事后能对上时间
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write("%s | ERROR | [界面看门狗] 机器人 %.0f 秒没有日志，已强制停止\n"
                                 % (time.strftime("%Y-%m-%d %H:%M:%S"), quiet))
                except Exception:
                    pass
        return lines, note


def _report_crash(exc_type, exc, tb) -> None:
    import traceback

    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        CRASH_LOG.write_text(text, encoding="utf-8")
    except Exception:
        pass
    if os.environ.get("ONECLASS_GUI_DIALOG", "1") == "0":
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("OneClass 助手启动失败",
                             "错误已写到：\n%s\n\n%s" % (CRASH_LOG, text[-1200:]))
        r.destroy()
    except Exception:
        pass


# ------------------------------------------------------------------ 界面
def build_app():
    import tkinter as tk
    from tkinter import ttk, messagebox

    try:
        enable_dpi_awareness()
    except Exception:
        pass

    root = tk.Tk()
    root.title(APP_TITLE)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w = min(1240, max(1000, sw - 120))
    h = min(860, max(640, sh - 120))
    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
    root.minsize(980, 620)
    root.configure(bg="#f4f6f9")

    text = read_config_text()
    tail = LogTail(LOG_FILE)
    runner = BotRunner(tail)
    ui_queue: queue.Queue = queue.Queue()
    state = {"windows": [], "selfcheck": None, "warned": False}

    font = ("Microsoft YaHei UI", 10)

    # 顶部
    head = tk.Frame(root, bg="#ffffff")
    head.pack(fill="x")
    tk.Frame(head, bg="#4c8bf5", height=4).pack(fill="x")
    head_in = tk.Frame(head, bg="#ffffff")
    head_in.pack(fill="x", padx=16, pady=9)
    tk.Label(head_in, text="OneClass · 学习助手", bg="#ffffff",
             font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    tk.Label(head_in, text="定位窗口 → 预览确认 → 配置听写 → 开始学习",
             bg="#ffffff", fg="#8a8f98").pack(anchor="w")

    # 底部状态栏（先占位）
    status = tk.Label(root, anchor="w", bg="#e9edf2", fg="#2b2f36", font=font,
                      padx=12, pady=7, text="状态：未运行")
    status.pack(side="bottom", fill="x")

    body = tk.Frame(root, bg="#f4f6f9")
    body.pack(fill="both", expand=True, padx=12, pady=10)

    left_wrap = tk.Frame(body, bg="#f4f6f9", width=500)
    left_wrap.pack(side="left", fill="y")
    left_wrap.pack_propagate(False)
    right = tk.Frame(body, bg="#f4f6f9")
    right.pack(side="left", fill="both", expand=True, padx=(12, 0))

    canvas = tk.Canvas(left_wrap, bg="#f4f6f9", highlightthickness=0)
    vbar = ttk.Scrollbar(left_wrap, orient="vertical", command=canvas.yview)
    left = tk.Frame(canvas, bg="#f4f6f9")
    left.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win_id = canvas.create_window((0, 0), window=left, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    def card(parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg="#ffffff", highlightbackground="#dfe3e8",
                         highlightthickness=1)
        outer.pack(fill="x", pady=(0, 10))
        tk.Label(outer, text=title, bg="#ffffff", fg="#1f2328",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=12, pady=(9, 4))
        inner = tk.Frame(outer, bg="#ffffff")
        inner.pack(fill="x", padx=12, pady=(0, 10))
        return inner

    # 定位
    c1 = card(left, "第一步 · 定位小程序窗口（启动前必须确认）")
    tk.Label(c1, text="目标窗口", bg="#ffffff", font=font).pack(anchor="w")
    win_box = ttk.Combobox(c1, state="readonly", font=font)
    win_box.pack(fill="x", pady=(2, 6))
    row1 = tk.Frame(c1, bg="#ffffff")
    row1.pack(fill="x")
    scan_btn = tk.Button(row1, text="1. 扫描窗口", font=font)
    scan_btn.pack(side="left", fill="x", expand=True)
    preview_btn = tk.Button(row1, text="2. 预览并确认定位", font=font)
    preview_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))
    raise_btn = tk.Button(row1, text="置前小程序", font=font)
    raise_btn.pack(side="left", padx=(6, 0))
    hint = tk.Label(c1, text="点「扫描窗口」查找一课英语窗口", bg="#ffffff", fg="#9aa0a6")
    hint.pack(anchor="w", pady=(4, 0))

    # 速度
    c2 = card(left, "1 · 答题速度")
    speed_var = tk.StringVar(value=speed_of(text))
    for key, preset in SPEED_PRESETS.items():
        tk.Radiobutton(c2, text=preset["label"], value=key, variable=speed_var,
                       bg="#ffffff", anchor="w", font=font).pack(fill="x")
        tk.Label(c2, text="     " + preset["hint"], bg="#ffffff",
                 fg="#9aa0a6").pack(anchor="w")

    # 引擎
    c3 = card(left, "2 · 听写引擎（本地离线免费）")
    engine_var = tk.StringVar(value="local")
    tk.Radiobutton(c3, text="本地 Whisper（有 GPU 自动加速）", value="local",
                   variable=engine_var, bg="#ffffff", anchor="w",
                   font=font).pack(fill="x")
    tk.Radiobutton(c3, text="语音识别 API（需自行配置接口）", value="api",
                   variable=engine_var, bg="#ffffff", anchor="w",
                   font=font).pack(fill="x")
    mrow = tk.Frame(c3, bg="#ffffff")
    mrow.pack(fill="x", pady=(6, 0))
    tk.Label(mrow, text="本地模型", bg="#ffffff").pack(side="left")
    model_box = ttk.Combobox(mrow, values=MODEL_CHOICES, font=font)
    model_box.set(get_value(text, "whisper_model") or "models/small.en")
    model_box.pack(side="left", fill="x", expand=True, padx=(6, 0))
    tk.Label(c3, text="small.en ≈ 460 MB；换模型需先把文件放进 models 目录",
             bg="#ffffff", fg="#9aa0a6").pack(anchor="w", pady=(4, 0))

    # 右侧按钮
    bar = tk.Frame(right, bg="#f4f6f9")
    bar.pack(fill="x")
    save_btn = tk.Button(bar, text="保存配置", font=font, width=11)
    save_btn.pack(side="left")
    check_btn = tk.Button(bar, text="预检", font=font, width=8)
    check_btn.pack(side="left", padx=(6, 0))
    self_btn = tk.Button(bar, text="自检（不点击）", font=font)
    self_btn.pack(side="left", padx=(6, 0))
    start_btn = tk.Button(bar, text="▶ 启动机器人", font=font, width=13)
    start_btn.pack(side="left", padx=(14, 0))
    stop_btn = tk.Button(bar, text="■ 停止", font=font, width=9, state="disabled")
    stop_btn.pack(side="left", padx=(6, 0))
    run_state = tk.Label(bar, text="未运行", bg="#f4f6f9", fg="#8a8f98", font=font)
    run_state.pack(side="left", padx=12)

    nb = ttk.Notebook(right)
    nb.pack(fill="both", expand=True, pady=(8, 0))
    log_tab = tk.Frame(nb, bg="#ffffff")
    tut_tab = tk.Frame(nb, bg="#ffffff")
    nb.add(log_tab, text="  运行日志  ")
    nb.add(tut_tab, text="  使用教程  ")

    opts = tk.Frame(log_tab, bg="#ffffff")
    opts.pack(fill="x", pady=(6, 2), padx=6)
    autoscroll = tk.BooleanVar(value=True)
    tk.Checkbutton(opts, text="自动滚动", variable=autoscroll,
                   bg="#ffffff").pack(side="left")
    tk.Button(opts, text="打开日志目录",
              command=lambda: subprocess.Popen(["explorer", str(LOGS)])).pack(side="right")
    tk.Button(opts, text="清空",
              command=lambda: log_text.delete("1.0", "end")).pack(side="right", padx=6)

    log_text = tk.Text(log_tab, wrap="word", bg="#14161a", fg="#d7e0e8",
                       font=("Consolas", 10), borderwidth=0)
    log_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))
    log_text.tag_config("warn", foreground="#ffd166")
    log_text.tag_config("err", foreground="#ff7b72")
    log_text.tag_config("ok", foreground="#7ee787")
    log_text.tag_config("sys", foreground="#79c0ff")

    tut = tk.Text(tut_tab, wrap="word", font=("Microsoft YaHei UI", 10),
                  borderwidth=0, padx=12, pady=10)
    tut.insert("1.0", TUTORIAL)
    tut.config(state="disabled")
    tut.pack(fill="both", expand=True)

    # ---------------- 行为
    def log(line: str, tag: str | None = None) -> None:
        if line.strip():
            log_text.insert("end", line.rstrip() + "\n", tag or ())
        if autoscroll.get():
            log_text.see("end")

    def set_status(msg: str) -> None:
        status.config(text="状态：" + msg)

    def set_running(running: bool) -> None:
        run_state.config(text="运行中" if running else "未运行",
                         fg="#1a7f37" if running else "#8a8f98")
        start_btn.config(state="disabled" if running else "normal")
        stop_btn.config(state="normal" if running else "disabled")

    def refresh_logs() -> None:
        """主定时器：读日志 + 处理队列 + 看门狗。"""
        lines, note = runner.tick()
        for line in lines:
            low = line.lower()
            tag = None
            if "error" in low or "错误" in line or "失败" in line:
                tag = "err"
            elif "warn" in low or "警告" in line or "没反应" in line:
                tag = "warn"
            log(line, tag)
            m = re.search(r"页面状态：(\w+)", line)
            if m:
                set_status("运行中 · 当前页面 %s" % m.group(1))
            m2 = re.search(r"正确率[^\d]{0,6}(\d+(?:\.\d+)?)\s*%", line)
            if m2:
                set_status("运行中 · 本次正确率 %s%%" % m2.group(1))
        if note:
            log("[看门狗] " + note, "err")
            set_status("机器人卡死，已自动停止")
            set_running(False)
            messagebox.showerror("机器人卡死", note)

        while True:
            try:
                item = ui_queue.get_nowait()
            except queue.Empty:
                break
            if item == "selfcheck_done":
                log("[自检] 结束", "sys")
            else:
                log(item, "sys")

        if not runner.running and start_btn["state"] == "disabled":
            set_running(False)
            if not runner.killed_by_watchdog:
                set_status("机器人已停止")
        root.after(POLL_MS, refresh_logs)

    def do_scan():
        wins = scan_windows()
        state["windows"] = wins
        labels = []
        for item in wins:
            x, y, ww, hh = item["rect"]
            tag = "（已最小化）" if item["minimized"] else ""
            labels.append("%s  [%d,%d %dx%d]%s" % (item["title"], x, y, ww, hh, tag))
        win_box["values"] = labels
        if wins:
            win_box.current(0)
            hint.config(text="找到 %d 个候选窗口" % len(wins), fg="#1a7f37")
            log("[定位] 找到 %d 个候选窗口" % len(wins), "sys")
        else:
            win_box.set("")
            hint.config(text="没找到：请打开小程序并取消最小化", fg="#c0392b")
            log("[定位] 没找到候选窗口", "warn")

    def do_raise():
        wins = scan_windows()
        if not wins:
            log("[置前] 没找到小程序窗口", "warn")
            return
        ok = bring_foreground(wins[0]["hwnd"])
        log("[置前] %s → %s" % (wins[0]["title"][:20], "成功" if ok else "失败（系统前台锁）"),
            "ok" if ok else "warn")

    def do_preview():
        idx = win_box.current()
        if idx < 0 or idx >= len(state["windows"]):
            messagebox.showwarning("提示", "先点「1. 扫描窗口」并选中一个窗口。")
            return
        win = state["windows"][idx]
        bring_foreground(win["hwnd"])
        x, y, ww, hh = win["rect"]
        if ww < 120 or hh < 120:
            messagebox.showwarning("窗口太小", "窗口只有 %dx%d，先拖大一点。" % (ww, hh))
            return
        CONFIG.write_text(set_region(read_config_text(), (x, y, ww, hh)), encoding="utf-8")
        log("[定位] region=(%d, %d, %d, %d)" % (x, y, ww, hh), "ok")
        page, ocr = probe_region([x, y, ww, hh])
        if page:
            log("[定位] 识别校验：%s" % page, "ok")
            set_status("定位已保存（%s），可保存配置并启动" % page)
        else:
            log("[定位] 识别校验失败：%s" % ocr[:70], "warn")
            messagebox.showwarning(
                "这块区域不像小程序",
                "OCR 读到的是：\n\n%s\n\n先把挡住它的窗口移开，再重新定位。" % ocr[:200])

    def show_preview_image(region: list[int]) -> None:
        try:
            from PIL import ImageTk

            img = grab_region(region)
            img.thumbnail((360, 600))
            top = tk.Toplevel(root)
            top.title("预览")
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(top, image=photo)
            lbl.image = photo
            lbl.pack(padx=8, pady=8)
            top.after(5000, top.destroy)     # 挡住小程序就麻烦了，自动关
        except Exception as exc:  # noqa: BLE001
            log("[预览] 失败：%s" % exc, "warn")

    def do_save():
        try:
            t = apply_speed(read_config_text(), speed_var.get())
            t = set_value(t, "dictation_mode", "whisper")
            t = set_value(t, "whisper_model", model_box.get().strip() or "models/small.en")
            t = set_value(t, "whisper_device", "cpu")
            CONFIG.write_text(t, encoding="utf-8")
            preset = SPEED_PRESETS[speed_var.get()]
            log("[配置] 已保存：%s；模型 %s" % (preset["label"], model_box.get()), "ok")
            set_status("配置已保存（录音 %ss）" % preset["audio_record_seconds"])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))

    def do_preflight(show: bool = True) -> bool:
        problems = preflight()
        for p in problems:
            log("[预检] " + p, "warn")
        if not problems:
            log("[预检] 通过，可以启动", "ok")
            set_status("预检通过")
            if show:
                messagebox.showinfo("预检", "一切正常，可以启动机器人。")
            return True
        set_status("预检发现 %d 个问题" % len(problems))
        if show:
            messagebox.showwarning("预检", "发现 %d 个问题：\n\n· %s"
                                   % (len(problems), "\n· ".join(problems)))
        return False

    def do_selfcheck():
        if state["selfcheck"] and state["selfcheck"].poll() is None:
            return
        env = dict(os.environ, PYTHONPATH=str(SITE), PYTHONIOENCODING="utf-8")
        log("[自检] 运行 checkup.py（只截图 + 识别，不点击）", "sys")

        def work():
            try:
                r = subprocess.run([sys.executable, "-u", str(ROOT / "checkup.py")],
                                   cwd=str(ROOT), env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=120)
                for line in (r.stdout or "").splitlines():
                    ui_queue.put("  " + line)
            except Exception as exc:  # noqa: BLE001
                ui_queue.put("  [自检] 失败：%s" % exc)
            ui_queue.put("selfcheck_done")

        state["selfcheck"] = threading.Thread(target=work, daemon=True)
        state["selfcheck"].start()

    def do_start():
        if runner.running:
            return
        problems = preflight()
        fatal = [p for p in problems
                 if p.startswith("当前 Python") or p.startswith("依赖不全")]
        if fatal:
            log("[预检] 致命问题，无法启动：", "err")
            for item in fatal:
                log("    " + item, "err")
            messagebox.showerror(
                "无法启动",
                "环境不满足，直接启动会秒退：\n\n· %s\n\n"
                "请先双击 安装.cmd，或安装 Python 3.13。" % "\n· ".join(fatal),
            )
            return
        if not do_preflight(show=False):
            if not messagebox.askyesno("预检未通过", "有上面的问题，仍然要启动吗？"):
                return
        if not runner.start():
            messagebox.showerror("启动失败", "无法启动 main.py，看日志。")
            return
        set_running(True)
        log("[系统] 已启动机器人（PID %d）" % runner.proc.pid, "sys")
        set_status("机器人运行中")

    def do_stop():
        was = runner.running
        runner.stop()
        set_running(False)
        if was:
            log("[系统] 已停止", "sys")
            set_status("机器人已停止")

    scan_btn.config(command=do_scan)
    preview_btn.config(command=lambda: (do_preview(), show_preview_image(
        parse_region(read_config_text()) or [0, 0, 10, 10])))
    raise_btn.config(command=do_raise)
    save_btn.config(command=do_save)
    check_btn.config(command=lambda: do_preflight(True))
    self_btn.config(command=do_selfcheck)
    start_btn.config(command=do_start)
    stop_btn.config(command=do_stop)
    root.bind("<Control-s>", lambda _e: do_save())
    root.bind("<F5>", lambda _e: do_start())
    root.protocol("WM_DELETE_WINDOW", lambda: (do_stop(), root.destroy()))

    try:
        root.lift()
        root.attributes("-topmost", True)
        root.after(1200, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    log("[系统] 界面已就绪：先定位窗口，再点「▶ 启动机器人」", "sys")
    set_status("未运行。步骤：扫描窗口 → 预览定位 → 保存配置 → 启动")
    root.after(POLL_MS, refresh_logs)
    root.mainloop()


# ------------------------------------------------------------------ 自检
def selftest() -> int:
    t = read_config_text()
    checks = []

    fast = apply_speed(t, "fast")
    checks.append(("快档 2.0s/1次",
                   get_value(fast, "audio_record_seconds") == "2.0"
                   and get_value(fast, "dictation_max_attempts") == "1", None))
    checks.append(("读回 fast", speed_of(fast) == "fast", speed_of(fast)))
    acc = apply_speed(t, "accurate")
    checks.append(("准档 3.2s/3次",
                   get_value(acc, "audio_record_seconds") == "3.2"
                   and get_value(acc, "dictation_max_attempts") == "3", None))
    checks.append(("读回 accurate", speed_of(acc) == "accurate", speed_of(acc)))

    r = set_region(t, (100, 200, 600, 900))
    checks.append(("region 只出现一次", r.count("region:") == 1, r.count("region:")))
    checks.append(("region 可解析", parse_region(r) == [100, 200, 600, 900], parse_region(r)))
    checks.append(("YAML 仍合法", _yaml_ok(r), None))
    checks.append(("不缩进列表也能替换",
                   "region:\n  - 100\n  - 200\n  - 600\n  - 900\n"
                   in set_region("region:\n- 1\n- 2\n- 3\n- 4\nloop_interval: 0.3\n",
                                 (100, 200, 600, 900)), None))

    wins = scan_windows()
    checks.append(("扫描窗口可用（%d 个）" % len(wins), isinstance(wins, list), len(wins)))
    problems = preflight()
    checks.append(("预检可运行（问题 %d 条）" % len(problems), isinstance(problems, list), None))

    ok = 0
    for name, cond, extra in checks:
        print(("  OK   " if cond else "  FAIL ") + name
              + ("" if extra is None else "  <> %s" % (extra,)))
        ok += 1 if cond else 0
    print("\nGUI_SELFTEST: %d/%d passed" % (ok, len(checks)))
    for w in wins[:5]:
        print("  候选窗口: %s %r minimized=%s" % (w["title"][:20], w["rect"], w["minimized"]))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.excepthook = _report_crash
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--crashtest" in sys.argv:
        raise RuntimeError("这是一次崩溃测试")
    try:
        build_app()
    except Exception:
        _report_crash(*sys.exc_info())
        raise SystemExit(1)

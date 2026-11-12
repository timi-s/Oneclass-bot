from __future__ import annotations

import atexit
import csv
import logging
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageStat

from .audio_match import AudioIndex
from .audio_solver import AudioSolver
from .screen import Screen
from .vision import OCRItem, Vision, chinese_similarity, norm_text
from .vocab import VocabStore


LOG = logging.getLogger("wordbot")


class WordBot:
    def __init__(self, cfg: dict, root: Path):
        self.cfg = cfg
        self.root = root
        self.screen = Screen(
            cfg["region"],
            cfg.get("after_click_delay", 0.85),
            cfg.get("input_backend", "win32"),
            cfg.get("win32_fallback_to_pyautogui", True),
        )
        if str(cfg.get("ocr_engine", "local")).lower() == "api":
            from .vision_api import ApiVision

            self.vision = ApiVision(cfg)
        else:
            self.vision = Vision(
                cfg.get("ocr_scale", 1.0),
                cfg.get("ocr_min_score", 0.45),
                cfg.get("ocr_max_side", 512),
                cfg.get("ocr_threads", 3),
                cfg.get("ocr_use_cls", False),
                cfg.get("ocr_use_dml", False),
            )
        self.vocab = VocabStore(root / "vocab.json")
        self.audio = AudioSolver(cfg, root / "logs")
        # 需要听写或录发音模板时，开常驻录音（页面往往一进新词就自动读音，
        # 等脚本发现新词再开始录，声音早放完了）
        self.use_audio = bool(cfg.get("audio_capture", True)) and (
            bool(cfg.get("audio_templates", False))
            or str(cfg.get("dictation_mode", "")).lower() == "whisper"
        )
        if self.use_audio:
            try:
                self.audio.start_capture()
                atexit.register(self.audio.stop_capture)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("常驻录音启动失败：%s", exc)
        # 音频指纹：把背单词阶段的读音存起来，测试时比对
        self.audio_enabled = bool(cfg.get("audio_templates", False))
        self.audio_index = AudioIndex(root / "audio_templates.json") if self.audio_enabled else None
        self._last_template_word = ""
        self._template_silent = 0
        # 同一道听写题只录一次：记住当前页和识别出的词
        self._dictation_sig = ""
        self._dictation_word = ""
        # 选择题：记录「这页刚答过」，避免同一页反复作答
        self._choice_sig = ""
        self._choice_at = 0.0
        if self.audio_index is not None:
            atexit.register(self._save_audio_index)
        self.points = cfg.get("fallback_points", {})
        self.debug = bool(cfg.get("debug", True))
        self.unknown_count = 0
        self.last_state = ""
        self.extra_group_mode = False
        self.extra_groups_started = 0
        # 画面指纹：用来判断「这一帧和上一帧是不是一样」，一样就不再跑 OCR
        self._last_sig: bytes | None = None
        self._same_frames = 0
        # 黑屏 / 卡死监控
        self._blank_since: float | None = None
        self._blank_last_log = 0.0
        self._blank_last_save = 0.0
        self._blank_last_fg = 0.0
        self._stall_since: float | None = None
        self._stall_last_log = 0.0
        # 同一页面停留计时（心跳日志）
        self._state_since: float | None = None
        self._heartbeat_at = 0.0
        self._state_repeat = 0
        self._last_fg_at = 0.0
        self._fg_ok = 0
        self._stuck_warned = False
        self._last_tick = time.monotonic()
        self._watchdog_last = 0.0
        self._fg_backoff_until = 0.0

    def point(self, name: str) -> tuple[float, float]:
        value = self.points.get(name)
        if not isinstance(value, list) or len(value) != 2:
            raise KeyError(f"config.yaml 缺少 fallback_points.{name}")
        return float(value[0]), float(value[1])

    def click_text(self, items: list[OCRItem], *texts: str, fallback: str | None = None) -> bool:
        item = self.vision.find(items, *texts)
        if item:
            LOG.info("点击文字 %s at (%.0f, %.0f)", item.text, item.cx, item.cy)
            before = self._signature(self.screen.capture())
            self.screen.click_abs(item.cx, item.cy)
            if bool(self.cfg.get("verify_clicks", True)):
                time.sleep(0.45)
                if self._signature(self.screen.capture()) == before:
                    # 后台点击对按钮常常无效 → 换成真实鼠标点两下（先激活窗口）
                    LOG.info("后台点击「%s」没生效，改用真实鼠标再点一次", item.text)
                    self.ensure_foreground()
                    w = float(self.screen.region.width) or 1.0
                    h = float(self.screen.region.height) or 1.0
                    try:
                        self.screen.foreground_click_rel(item.cx / w, item.cy / h,
                                                         delay=0.3, clicks=2)
                    except TypeError:
                        self.screen.foreground_click_rel(item.cx / w, item.cy / h, delay=0.3)
            return True
        if fallback:
            x, y = self.point(fallback)
            LOG.warning("OCR 未找到 %s，使用兜底坐标 %s", texts, fallback)
            self.screen.click_rel(x, y)
            return True
        return False

    def click_label_exact(self, items: list[OCRItem], *labels: str, fallback: str | None = None) -> bool:
        """按「完全相同」的文字点按钮，避免「认识」误命中「不认识」。"""
        wanted = [norm_text(l) for l in labels]
        for target in wanted:
            for it in items:
                if norm_text(it.text) == target:
                    LOG.info("点击按钮 %s at (%.0f, %.0f)", it.text, it.cx, it.cy)
                    before = self._signature(self.screen.capture())
                    self.screen.click_abs(it.cx, it.cy)
                    if bool(self.cfg.get("verify_clicks", True)):
                        time.sleep(0.45)
                        if self._signature(self.screen.capture()) == before:
                            LOG.info("后台点击「%s」没生效，改用真实鼠标再点一次", it.text)
                            self.ensure_foreground()
                            w = float(self.screen.region.width) or 1.0
                            h = float(self.screen.region.height) or 1.0
                            try:
                                self.screen.foreground_click_rel(it.cx / w, it.cy / h,
                                                                 delay=0.3, clicks=2)
                            except TypeError:
                                self.screen.foreground_click_rel(it.cx / w, it.cy / h, delay=0.3)
                    return True
        if fallback:
            x, y = self.point(fallback)
            LOG.warning("OCR 未找到 %s，使用兜底坐标 %s", labels, fallback)
            self.screen.click_rel(x, y)
            return True
        return False

    def detect_state(self, items: list[OCRItem]) -> str:
        text = norm_text(self.vision.joined(items))
        height = float(self.screen.region.height)

        def bottom_exact(label: str, min_ratio: float = 0.84) -> bool:
            wanted = norm_text(label)
            return any(
                norm_text(item.text) == wanted
                and item.cy >= height * min_ratio
                for item in items
            )

        # 弹窗中和页面底部可能同时出现“再来一组”，优先识别弹窗。
        if (
            "再来一组" in text
            and (
                "任务超时" in text
                or ("词语未背诵" in text and "我再想想" in text)
            )
        ):
            return "task_timeout"

        if "学习完成" in text:
            return "learn_complete"
        if "继续背单词" in text:
            return "section_complete"

        # 测试阶段听写题和选择题交替出现，两种页面都带「单词测试 N/100」。
        # 用题干文案区分；文案没认全时再靠「我不会 + 确定」这类听写特征兜底。
        has_choice_prompt = ("选择正确的释义" in text) or ("选择正确的意思" in text)
        has_dict_prompt = ("填写你听到的单词" in text) or ("听到的单词" in text)

        # 最后一题答完后底部是「完成」而不是「下一词」。
        if has_choice_prompt and bottom_exact("完成"):
            return "choice_feedback_final"
        if has_dict_prompt and bottom_exact("完成"):
            return "dictation_feedback_final"

        # 普通题目反馈页。
        if has_choice_prompt and bottom_exact("下一词"):
            return "choice_feedback"
        if has_dict_prompt and bottom_exact("下一词"):
            return "dictation_feedback"

        if has_dict_prompt:
            return "test_dictation"
        if has_choice_prompt:
            return "test_choice"
        if "我不会" in text and "确定" in text and "选择" not in text:
            return "test_dictation"

        # 测验总结页（恭喜你，完成了今日单词测试 / 正确率 84.0% / 错题巩固 /
        # 底部「重新测验」「完成测验」）。必须排在「单词测试 N/100」前面，
        # 否则总结页会被当成一道选择题，反复作答。
        if (
            "完成了今日单词测试" in text
            or "错题巩固" in text
            or "完成测验" in text
            or ("正确率" in text and ("重新测验" in text or "错题" in text))
        ):
            return "test_result"

        if "词测试" in text or "单词测试" in text:
            return "test_choice"

        # 兼容其他可能的完成提示。
        if any(
            value in text
            for value in ("测验完成", "测试完成", "本次成绩")
        ):
            return "test_complete"

        # 「标记为太简单（无需复习）」在答案页右上角只是一个状态标签，点不动；
        # 真正的按钮是下面的「认识/模糊/不认识」。所以有这三个按钮时按答案页处理。
        has_reveal_buttons = "认识" in text and ("模糊" in text or "不认识" in text)
        if "标记为太简单" in text and not has_reveal_buttons:
            return "learn_too_easy"
        if has_reveal_buttons:
            return "learn_revealed"
        # 单词详情页：有「释义/例句」，通常还带音标；底部橙色「下一词」经常 OCR 不到，
        # 所以不能只靠「下一词」判断（否则会被当成隐藏释义页，一直点空白卡死）。
        # 注意隐藏释义页的提示语里也有「释义」两个字（默念单词释义），要排除。
        hint_page = ("请跟读并默念" in text) or ("显示答案" in text)
        has_detail_words = ("例句" in text) or (("释义" in text) and not hint_page)
        has_phonetic = ("英" in text) and ("美" in text)
        if has_detail_words and (has_phonetic or "下一词" in text):
            return "learn_detail"
        if "下一词" in text and ("释义" in text or "例句" in text):
            return "learn_detail"
        if "显示答案" in text or "请跟读并默念" in text:
            return "learn_hidden"
        # 兜底：学习页底部提示行偶尔会被 OCR 漏掉，只剩音标行，同样按背单词页处理。
        if "跟读" in text or ("英" in text and "美" in text):
            return "learn_hidden"
        # 任务说明页：「单词背诵/考试后开始不可以中途退出」+ 底部「开始测验」。
        if "开始测验" in text or "开始测试" in text:
            return "exam_start"
        if "开始背诵" in text:
            return "word_home"

        # 没有弹窗时，单词主页底部可能直接显示橙色“再来一组”。
        if (
            "再来一组" in text
            and any(
                value in text
                for value in ("截止日期", "词库预览", "已学习")
            )
        ):
            return "word_home_extra"
        if "今日任务" in text and "学习天数" in text:
            return "home"
        return "unknown"

    def learn_speaker_point(self, items: list[OCRItem], image: Image.Image) -> tuple[float, float]:
        """背单词页的喇叭是「英/美」音标行右边的小喇叭（不是听写页的大橙圆）。

        做法：先 OCR 找到音标行，再在它右侧一条带子里找橙黄色像素。
        """
        try:
            import cv2
            import numpy as np

            arr = np.asarray(image.convert("RGB"))
            hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
            mask = cv2.inRange(hsv, np.array([10, 80, 120]), np.array([45, 255, 255]))
            for key in ("英", "美"):
                it = next((i for i in items if key in i.text), None)
                if it is None:
                    continue
                y0, y1 = int(it.cy - 40), int(it.cy + 40)
                x0 = int(it.x2)
                x1 = int(min(image.width - 1, it.x2 + 0.22 * image.width))
                y0, x0 = max(0, y0), max(0, x0)
                if y1 <= y0 or x1 <= x0:
                    continue
                sub = mask[y0:y1, x0:x1]
                if int(sub.sum() // 255) < 20:
                    continue
                ys, xs = np.where(sub > 0)
                cx = x0 + float(xs.mean())
                cy = y0 + float(ys.mean())
                LOG.info("学习页喇叭定位：%s 行右侧 (%.0f, %.0f)", key, cx, cy)
                return cx / image.width, cy / image.height
        except Exception as exc:  # noqa: BLE001
            LOG.warning("学习页喇叭颜色定位失败：%s", exc)

        it = next((i for i in items if "英" in i.text), None)
        if it is not None:
            return (
                min(0.95, (it.x2 + 0.05 * image.width) / image.width),
                it.cy / image.height,
            )
        return self.point("speaker")

    def _save_audio_index(self) -> None:
        try:
            if self.audio_index is not None and len(self.audio_index):
                self.audio_index.save()
        except Exception:  # noqa: BLE001
            pass

    def _voiced(self, samples) -> bool:
        try:
            import numpy as np

            if samples is None or len(samples) == 0:
                return False
            rms = float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=float)))))
            return rms >= float(self.cfg.get("audio_silence_rms", 0.002))
        except Exception:  # noqa: BLE001
            return False

    def collect_audio_template(self, items: list[OCRItem], image: Image.Image) -> None:
        """背单词阶段：把当前词的读音存成指纹模板（每个词只录一次）。

        录音偶尔会卡住（声卡设备异常/驱动占住），所以放到子线程里做，
        超过 8 秒就放弃这个词，绝不能把主循环拖死。
        """

        def _work() -> None:
            self._collect_audio_template_inner(items, image)

        th = threading.Thread(target=_work, daemon=True)
        th.start()
        th.join(timeout=8.0)
        if th.is_alive():
            LOG.warning("录发音模板超过 8 秒没结束，跳过这个词（不阻塞继续背单词）")

    def _collect_audio_template_inner(self, items: list[OCRItem], image: Image.Image) -> None:
        if not self.audio_enabled or self.audio_index is None:
            return
        found = self.vision.main_word(items, image.height, (0.10, 0.64))
        if not found:
            return
        word, word_item = found
        if not word or word == self._last_template_word or word in self.audio_index.templates:
            return
        self._last_template_word = word

        seconds = float(self.cfg.get("audio_template_seconds", 2.0))
        speaker_nx, speaker_ny = self.learn_speaker_point(items, image)

        attempts: list[tuple[str, tuple[float, float] | None]] = []
        if self.audio.capturing:
            attempts.append(("缓冲", None))
        attempts.append(("喇叭", (speaker_nx, speaker_ny)))

        for tag, point in attempts:
            try:
                if point is None:
                    samples = self.audio.snapshot(max(1.5, seconds))
                    if not self._voiced(samples):
                        continue
                else:
                    samples = self.audio.record_samples(
                        lambda p=point: self.screen.foreground_click_rel(p[0], p[1], delay=0.2),
                        seconds=seconds,
                    )
            except Exception as exc:  # noqa: BLE001
                if "静音" in str(exc):
                    continue
                LOG.warning("录发音模板失败（%s）：%s", tag, exc)
                continue

            if self.audio_index.add(word, samples):
                count = len(self.audio_index)
                if count <= 3 or count % 10 == 0:
                    self.audio_index.save()
                    LOG.info("已存发音模板：%s（共 %d 个，已保存，方式=%s）", word, count, tag)
                else:
                    LOG.info("已存发音模板：%s（共 %d 个，方式=%s）", word, count, tag)
                return

        self._template_silent += 1
        if self._template_silent <= 2 or self._template_silent % 10 == 0:
            LOG.warning(
                "这几个词都没录到发音（第 %d 次）：页面可能根本不放音，或输出设备不对；模板先跳过。",
                self._template_silent,
            )

    def learn_from_page(self, items: list[OCRItem], image: Image.Image) -> None:
        found = self.vision.main_word(items, image.height, (0.10, 0.64))
        if not found:
            return
        word, word_item = found
        definition = self.vision.definition(items, image.height, word_item)
        if self.vocab.add(word, definition):
            LOG.info("已记录词义：%s -> %s", word, definition)

    def handle_choice(self, items: list[OCRItem], image: Image.Image) -> None:
        rows = self.vision.choice_rows(items, image.height)
        if len(rows) < 2:
            # 小程序刚跳过来时会先显示「资源玩命加载中…」，选项还没渲染出来。
            # 这时候点任何坐标都是错的，等下一轮再说。
            LOG.info("选择题选项还没加载出来（%d 个），等下一轮", len(rows))
            return

        # 选项文字没认全（例如只认出「小」「√」这种），不能拿来选，等下一轮重认
        usable = [
            r for r in rows
            if len(r[0].strip()) >= 2 and r[0].strip() not in {"小", "√", "×", "口"}
        ]
        if len(usable) < 2:
            LOG.info("选项文字没认全（%s），等下一轮重认", [r[0] for r in rows])
            return
        rows = usable

        target = self.vision.main_word(items, image.height, (0.24, 0.48))
        if not target:
            self._choice_unknown(items, "未识别到题目单词")
            return
        word, _ = target
        definition = self.vocab.definition(word)
        LOG.info("选择题：word=%s, definition=%s, rows=%s", word, definition, [r[0] for r in rows])
        if definition:
            scored = [(chinese_similarity(definition, text), text, x, y) for text, x, y in rows]
            score, text, x, y = max(scored, key=lambda z: z[0])
            LOG.info("最佳选项：%s，匹配分 %.1f", text, score)
            if score >= float(self.cfg.get("choice_match_threshold", 42)):
                self.screen.click_abs(x, y)
                # 记下「这页已经答过」，避免同一页被反复作答
                self._choice_sig = self._page_sig(items)
                self._choice_at = time.monotonic()
                return
        self._choice_unknown(items, f"词义库缺失或匹配度不足：{word}")

    def _wait_enter(self, seconds: float) -> bool:
        """等回车，最多等 seconds 秒；超时返回 False（键盘输入不阻塞主循环）。"""
        try:
            import msvcrt
            import time as _time
        except Exception:  # noqa: BLE001
            return False
        end = _time.time() + max(0.5, seconds)
        while _time.time() < end:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\r", b"\n"):
                    return True
                if ch == b"\x03":
                    raise KeyboardInterrupt
            _time.sleep(0.1)
        return False

    def _choice_unknown(self, items: list[OCRItem], reason: str) -> None:
        strategy = str(self.cfg.get("unknown_choice_strategy", "pause"))
        LOG.warning("%s；unknown_choice_strategy=%s", reason, strategy)
        if strategy == "first":
            self.screen.click_rel(0.50, 0.48)
        elif strategy == "unknown":
            self.click_text(items, "我不会", fallback="unknown")
        else:
            # 暂停但**不能卡住整场**：小程序明确写着「中途退出不保存学习记录」，
            # 停太久会被判定中断，之前背过的记录就白做了。
            timeout = float(self.cfg.get("pause_timeout_seconds", 12))
            LOG.error(
                "词库缺词，暂停 %d 秒：按 Enter 手动继续，或等它自动跳过（避免整场记录作废）。",
                int(timeout),
            )
            if not self._wait_enter(timeout):
                LOG.warning("超时未操作，自动跳过这题（点「我不会」）。")
                self.click_text(items, "我不会", fallback="unknown")

    def type_word(self, word: str) -> None:
        x, y = self.point("dictation_input")
        self.screen.replace_text_rel(x, y, word, delay=0.15)

    def _find_orange_circle(self, image: Image.Image) -> tuple[float, float] | None:
        """找页面上的橙色喇叭圆钮（它没有文字，OCR 认不到，用颜色找）。"""
        try:
            import cv2
            import numpy as np

            arr = np.asarray(image.convert("RGB"))
            hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
            mask = cv2.inRange(hsv, np.array([8, 110, 140]), np.array([38, 255, 255]))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # 页面上还有橙色「确定」按钮，按形状挑：喇叭是圆，按钮是长条。
            for c in sorted(contours, key=cv2.contourArea, reverse=True):
                if cv2.contourArea(c) < 1200:
                    break
                x, y, w, h = cv2.boundingRect(c)
                if not 0.55 <= w / max(1, h) <= 1.8:
                    continue
                if w < 30:
                    continue
                return (x + w / 2.0, y + h / 2.0)
            return None
        except Exception:
            return None

    def speaker_point(self, items: list[OCRItem], image: Image.Image) -> tuple[float, float]:
        """喇叭位置：优先颜色识别，其次用手工校准的兜底坐标。"""
        found = self._find_orange_circle(image)
        if found:
            nx = found[0] / image.width
            ny = found[1] / image.height
            LOG.info("颜色定位到喇叭 (%.0f, %.0f) → 相对 (%.3f, %.3f)", found[0], found[1], nx, ny)
            return nx, ny
        return self.point("speaker")

    def input_point(self, items: list[OCRItem], image: Image.Image) -> tuple[float, float]:
        """听写输入框的位置。

        实际界面里输入区在「橙色喇叭」和「确定」按钮之间（页面顶部那句
        「请填写你听到的单词」只是提示文字，不是输入框），所以取两者的中点。
        """
        speaker = self._find_orange_circle(image)
        confirm = self.vision.find(items, "确定")
        if speaker is not None and confirm is not None:
            x = (speaker[0] + confirm.cx) / 2.0
            y = (speaker[1] + confirm.cy) / 2.0
            return x / image.width, y / image.height
        if confirm is not None:
            return confirm.cx / image.width, max(0.05, confirm.cy / image.height - 0.10)
        return self.point("dictation_input")

    def submit_dummy_dictation(
        self,
        items: list[OCRItem],
        image: Image.Image,
        reason: str = "",
    ) -> None:
        word = str(
            self.cfg.get("dictation_fallback_word", "zzzz")
        ).strip() or "zzzz"
        if reason:
            LOG.warning(
                "听写改用占位词：%s；reason=%s",
                word,
                reason,
            )
        else:
            LOG.info("听写占位模式：输入 %s", word)
        self.submit_word(items, image, word)

    def _page_sig(self, items: list[OCRItem]) -> str:
        return "|".join(i.text for i in items)

    def _input_band(self, image: Image.Image, nx: float, ny: float):
        """输入区附近的一条横带，用来比较「打字前后有没有变化」。"""
        try:
            import numpy as np

            w, h = image.size
            x0 = int(max(0, (nx - 0.42) * w))
            x1 = int(min(w, (nx + 0.42) * w))
            y0 = int(max(0, (ny - 0.10) * h))
            y1 = int(min(h, (ny + 0.10) * h))
            if x1 - x0 < 4 or y1 - y0 < 4:
                return None
            return np.asarray(image.convert("L"))[y0:y1, x0:x1].astype("int16")
        except Exception:  # noqa: BLE001
            return None

    def submit_word(self, items: list[OCRItem], image: Image.Image, word: str) -> None:
        """敲字 → 空格上屏（把输入法里的字母落到输入框） → 点「确定」。"""
        input_nx, input_ny = self.input_point(items, image)

        confirm = self.vision.find(items, "确定")
        if confirm:
            confirm_nx, confirm_ny = confirm.cx / image.width, confirm.cy / image.height
        else:
            confirm_nx, confirm_ny = self.point("dictation_confirm")
            LOG.warning("OCR 未找到确定按钮，使用 dictation_confirm 兜底坐标")

        key = str(self.cfg.get("dictation_submit_key", "space")).strip() or "space"
        LOG.info("提交听写：输入框(%.3f, %.3f) 确定(%.3f, %.3f) 词=%s 上屏键=%s",
                 input_nx, input_ny, confirm_nx, confirm_ny, word, key)

        try:
            # 敲字母后按空格：把输入法/输入框里的内容“上屏”，否则框里可能是空的
            self.screen.foreground_type_rel(input_nx, input_ny, word, submit_key=key)
        except TypeError:
            self.screen.foreground_type_rel(input_nx, input_ny, word)
            self.screen.press_key(key)

        time.sleep(0.35)
        self.screen.foreground_click_rel(confirm_nx, confirm_ny, delay=0.25)

    def handle_dictation(self, items: list[OCRItem], image: Image.Image) -> None:
        mode = str(self.cfg.get("dictation_mode", "whisper")).lower().strip()
        if mode == "reveal":
            self.click_text(items, "我不会", fallback="unknown")
            return
        if mode == "dummy":
            self.submit_dummy_dictation(items, image)
            return
        if mode != "whisper":
            raise ValueError("dictation_mode 只能是 reveal、dummy 或 whisper")

        # 同一道听写题只录一次：识别结果缓存在内存里，下次循环直接复用
        sig = self._page_sig(items)
        if self._dictation_word and sig == self._dictation_sig:
            LOG.info("这题已经听过一次，直接复用识别结果：%s", self._dictation_word)
            self.submit_word(items, image, self._dictation_word)
            return

        # 默认共听两次：第一次识别置信度不足或录音异常时，
        # 再点击一次喇叭重新录音和识别。次数可在 config.yaml 中修改。
        max_attempts = max(1, int(self.cfg.get("dictation_max_attempts", 2)))
        retry_delay = max(0.0, float(self.cfg.get("dictation_retry_delay", 0.65)))
        threshold = float(self.cfg.get("speech_match_threshold", 52))
        base_seconds = float(self.cfg.get("audio_record_seconds", 3.2))
        speaker = self.speaker_point(items, image)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                LOG.info(
                    "听写识别第 %d/%d 次：点击喇叭并重新录音",
                    attempt,
                    max_attempts,
                )
                # 重听时多录 1.5 秒，避免声音来得晚只录到半截。
                seconds = base_seconds if attempt == 1 else base_seconds + 1.5
                audio_path = self.audio.record_after_click(
                    lambda: self.screen.foreground_click_rel(*speaker, delay=0.25),
                    seconds=seconds,
                )
                raw, heard = self.audio.transcribe(audio_path, self.vocab.words())
                word, score = self.vocab.closest_word(heard)
                LOG.info(
                    "听写识别第 %d/%d 次：raw=%r, heard=%r, match=%r, score=%.1f",
                    attempt,
                    max_attempts,
                    raw,
                    heard,
                    word,
                    score,
                )

                if word and score >= threshold:
                    self._dictation_sig = sig
                    self._dictation_word = word
                    self.submit_word(items, image, word)
                    return

                # 语音识别不够自信时，用「背单词阶段录下的发音」比对一次。
                if self.audio_enabled and self.audio_index is not None and len(self.audio_index):
                    try:
                        from rapidfuzz import fuzz, process

                        candidates = None
                        if heard:
                            top = process.extract(heard, list(self.audio_index.templates), scorer=fuzz.WRatio, limit=8)
                            candidates = [w for w, _s, _i in top]
                        samples = AudioSolver._read_wav(audio_path)
                        tpl_word, dist, margin = self.audio_index.match(samples, candidates=candidates)
                        LOG.info(
                            "音频指纹：%s（dist=%.2f, margin=%.2f, 模板 %d 个）",
                            tpl_word, dist, margin, len(self.audio_index),
                        )
                        if (
                            tpl_word
                            and dist <= float(self.cfg.get("audio_match_max_distance", 6.0))
                            and margin >= float(self.cfg.get("audio_match_min_margin", 0.4))
                        ):
                            LOG.info("音频指纹命中，采用：%s", tpl_word)
                            self._dictation_sig = sig
                            self._dictation_word = tpl_word
                            self.submit_word(items, image, tpl_word)
                            return
                    except Exception as exc:  # noqa: BLE001
                        LOG.warning("音频指纹比对失败：%s", exc)

                last_error = RuntimeError(
                    f"语音识别置信度不足：{heard!r} -> {word!r} ({score:.1f})"
                )
                if attempt < max_attempts:
                    LOG.warning(
                        "%s；%.2f 秒后再次点击喇叭重听",
                        last_error,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    continue
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < max_attempts:
                    LOG.exception(
                        "第 %d/%d 次听写失败：%s；%.2f 秒后再次点击喇叭重听",
                        attempt,
                        max_attempts,
                        exc,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    continue
                LOG.exception(
                    "第 %d/%d 次听写仍失败：%s",
                    attempt,
                    max_attempts,
                    exc,
                )

        # 重听次数全部用完后才执行兜底；默认输入 zzzz，
        # 不会一识别失败就直接点击“我不会”。
        reason = str(last_error or "多次重听后仍未识别到可靠单词")
        self._dictation_sig = sig
        self._dictation_word = ""
        strategy = str(
            self.cfg.get("dictation_failure_strategy", "dummy")
        ).lower().strip()
        if strategy == "dummy":
            self.submit_dummy_dictation(items, image, reason)
        elif strategy == "reveal":
            self.click_text(items, "我不会", fallback="unknown")
        elif strategy == "pause":
            LOG.error("多次重听仍失败，已暂停；按 Enter 重试当前题，或 Ctrl+C 退出。")
            input()
        else:
            raise ValueError(
                "dictation_failure_strategy 只能是 dummy、reveal 或 pause"
            )

    def start_extra_group(
        self,
        modal: bool,
        items: list[OCRItem] | None = None,
    ) -> None:
        if not bool(self.cfg.get("auto_next_group", True)):
            LOG.info("检测到‘再来一组’，但 auto_next_group=false，停止运行。")
            raise SystemExit(0)

        maximum = int(self.cfg.get("max_extra_groups", 0))
        if maximum > 0 and self.extra_groups_started >= maximum:
            LOG.info("已达到 max_extra_groups=%d，停止运行。", maximum)
            raise SystemExit(0)

        now = time.monotonic()
        retry_seconds = max(
            1.0,
            float(self.cfg.get("extra_group_retry_seconds", 3.0)),
        )
        pending = bool(
            getattr(self, "_extra_group_transition_pending", False)
        )
        last_click = float(
            getattr(self, "_extra_group_last_click_at", 0.0)
        )

        if pending and now - last_click < retry_seconds:
            LOG.info(
                "已前台点击‘再来一组’，等待页面切换（%.1f/%.1f 秒）。",
                now - last_click,
                retry_seconds,
            )
            return

        width = float(self.screen.region.width)
        height = float(self.screen.region.height)

        if modal:
            # 弹窗里的绿色「再来一组」在页面中部，优先用 OCR 定位；
            # 认不到再用校准坐标兜底（区域换过之后校准坐标常常是偏的）。
            target_nx, target_ny = None, None
            if items:
                middle = [
                    item
                    for item in items
                    if norm_text(item.text) == "再来一组"
                    and height * 0.40 <= item.cy <= height * 0.80
                ]
                if middle:
                    button = max(middle, key=lambda item: (item.score, item.width * item.height))
                    target_nx = float(button.cx) / width
                    target_ny = float(button.cy) / height
                    LOG.info(
                        "OCR 定位到弹窗绿色‘再来一组’ at (%.0f, %.0f)。",
                        button.cx,
                        button.cy,
                    )
            if target_nx is None or target_ny is None:
                target_nx, target_ny = self.point("timeout_next_group")
                LOG.info(
                    "弹窗‘再来一组’使用专用校准坐标："
                    "normalized=(%.4f, %.4f)，absolute≈(%.0f, %.0f)。",
                    target_nx,
                    target_ny,
                    target_nx * width,
                    target_ny * height,
                )
        else:
            target_nx = None
            target_ny = None
            if items:
                candidates = [
                    item
                    for item in items
                    if "再来一组" in norm_text(item.text)
                    and item.cy >= height * 0.80
                ]
                if candidates:
                    button = max(
                        candidates,
                        key=lambda item: (
                            item.score,
                            item.width * item.height,
                        ),
                    )
                    target_nx = float(button.cx) / width
                    target_ny = float(button.cy) / height
                    LOG.info(
                        "定位到底部‘再来一组’ at (%.0f, %.0f)。",
                        button.cx,
                        button.cy,
                    )

            if target_nx is None or target_ny is None:
                target_nx, target_ny = self.point("start_next_group")
                LOG.warning(
                    "OCR 未定位到底部‘再来一组’，使用兜底坐标。"
                )

        self.screen.foreground_click_rel(
            target_nx,
            target_ny,
            delay=0.85,
        )
        self._extra_group_last_click_at = time.monotonic()
        self._extra_group_transition_pending = True
        self.extra_group_mode = True

        if pending:
            LOG.warning(
                "上次点击后弹窗仍存在，已按专用坐标重新点击绿色‘再来一组’。"
            )
        else:
            LOG.info(
                "已点击‘再来一组’，将在识别到新词页面后确认额外组开始。"
            )

    def route_test(self, items: list[OCRItem], image: Image.Image) -> str:
        """测试阶段：到底是听写题还是选择题？

        听写页的几个字（「我不会」「确定」「请填写你听到的单词」）也会被
        choice_rows 当成“选项行”，所以必须先看文案、再看选项像不像真选项。
        """
        text = norm_text(self.vision.joined(items))
        if ("填写你听到的单词" in text) or ("听到的单词" in text):
            return "dictation"
        if "我不会" in text and "选择" not in text:
            return "dictation"

        rows = [r for r in self.vision.choice_rows(items, image.height) if len(r[0].strip()) >= 4]
        if len(rows) >= 3:
            return "choice"
        if self._find_orange_circle(image) is not None:
            return "dictation"
        return "choice"

    def record_accuracy(self, text: str) -> str | None:
        """从测验结果页抓「正确率 xx%」，记到 accuracy.csv，用来算真实正确率。"""
        m = re.search(r"正确率[^\d%]{0,6}(\d+(?:\.\d+)?)\s*%", text or "")
        if not m:
            return None
        value = m.group(1)
        LOG.info("本次测验正确率：%s%%", value)
        path = self.root / "accuracy.csv"
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "accuracy", "raw_ocr"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), value, text[:240]])
        return value

    def act(self, state: str, items: list[OCRItem], image: Image.Image) -> None:
        if (
            bool(getattr(self, "_extra_group_transition_pending", False))
            and state
            in {
                "learn_hidden",
                "learn_too_easy",
                "learn_revealed",
                "learn_detail",
                "section_complete",
                "learn_complete",
                "test_choice",
                "test_dictation",
            }
        ):
            self._extra_group_transition_pending = False
            self.extra_groups_started += 1
            LOG.info(
                "已确认进入额外第 %d 组；继续识别今日新词和后续测试。",
                self.extra_groups_started,
            )

        if state == "home":
            # 首页中“单词”卡片文字通常可直接 OCR 到。
            if not self.click_text(items, "单词"):
                self.screen.click_rel(0.50, 0.78)
        elif state == "word_home":
            self.click_text(items, "开始背诵", fallback="start_memorize")
        elif state == "exam_start":
            # 任务说明页（提示中途不能退出），底部按钮是「开始测验」。
            self.click_text(items, "开始测验", "开始测试", fallback="start_memorize")
        elif state == "task_timeout":
            self.start_extra_group(modal=True, items=items)
        elif state == "word_home_extra":
            self.start_extra_group(modal=False, items=items)
        elif state == "learn_hidden":
            # 页面还在加载（「资源玩命加载中…」）时点击无效，先等它画完
            joined = self.vision.joined(items)
            if "加载中" in joined:
                LOG.info("页面还在加载，先等一等再点")
                time.sleep(0.8)
                return

            # 隐藏释义页先在空白区域点一次，显示答案和操作按钮。
            before = self._signature(image)
            candidates = [self.point("reveal_answer"), (0.50, 0.58)]
            found = self.vision.main_word(items, image.height, (0.10, 0.64))
            if found:
                candidates.append((found[1].cx / image.width, found[1].cy / image.height))

            # 同一页连续多轮没推进：不靠画面变化判断，直接强制重试
            if self._state_repeat >= 2:
                # 先确认「其实已经显示答案了」——认识按钮是浅灰字，低阈值再认一次
                if "认识" not in joined:
                    old = self.vision.min_score
                    try:
                        self.vision.min_score = 0.30
                        low_items = self.vision.read(image)
                        low = self.vision.joined(low_items)
                    finally:
                        self.vision.min_score = old
                    if "认识" in low:
                        LOG.info("低阈值识别到「认识」，说明答案已显示，直接点它")
                        if self.click_text(low_items, "认识", "模糊", fallback="know"):
                            return
                    # 也可能是单词详情页（有释义/例句），底部橙色「下一词」没被主阈值认出
                    if ("释义" in low or "例句" in low or "下一词" in low):
                        LOG.info("低阈值看到「释义/例句」→ 其实是详情页，点「下一词」")
                        if self.click_label_exact(low_items, "下一词", fallback="next_word"):
                            return

                LOG.warning(
                    "这页已连续 %d 轮没推进（learn_hidden），强制用真实鼠标重点",
                    self._state_repeat,
                )
                self.ensure_foreground()
                for cx, cy in candidates:
                    self.screen.foreground_click_rel(cx, cy, delay=0.3, clicks=2)
                    time.sleep(0.5)
                return

            self.screen.click_rel(*candidates[0])
            time.sleep(0.8)
            if self._signature(self.screen.capture()) != before:
                return

            # 后台点击没生效：先把窗口置前，再用真实鼠标依次试几个位置。
            LOG.warning("点空白后页面没反应，先把窗口置前再重试点击")
            self.ensure_foreground()
            for cx, cy in candidates:
                self.screen.foreground_click_rel(cx, cy, delay=0.3, clicks=2)
                time.sleep(0.5)
                if self._signature(self.screen.capture()) != before:
                    LOG.info("换点 (%.2f, %.2f) 后页面动了", cx, cy)
                    return
        elif state == "learn_too_easy":
            # 这一页确实只有「标记为太简单」可点（没有认识/模糊/不认识）。
            self.learn_from_page(items, image)
            self.collect_audio_template(items, image)
            if self._state_repeat >= 2:
                # 连续点不动：多半那是状态标签而不是按钮，改点「认识」
                LOG.warning("「标记为太简单」点了 %d 轮没反应，改点「认识」", self._state_repeat)
                if self.click_label_exact(items, "认识", "模糊", fallback="know"):
                    return
            if bool(self.cfg.get("mark_too_easy", True)):
                if self.click_text(items, "标记为太简单"):
                    return
            # 用户关闭该功能或 OCR 瞬时未找到按钮时，按普通流程处理。
            self.click_label_exact(items, "认识", "模糊", fallback="know")
        elif state == "learn_revealed":
            self.learn_from_page(items, image)
            self.collect_audio_template(items, image)
            self.click_label_exact(items, "认识", "模糊", fallback="know")
        elif state == "learn_detail":
            self.learn_from_page(items, image)
            self.click_text(items, "下一词", fallback="next_word")
        elif state == "section_complete":
            self.click_text(items, "继续背单词", fallback="continue_words")
        elif state == "learn_complete":
            self.click_text(items, "确认", fallback="complete_confirm")
        elif state == "choice_feedback_final":
            LOG.info("第 60 题已显示答案，点击底部‘完成’进入测验总结。")
            self.click_text(
                items,
                "完成",
                fallback="test_question_finish",
            )
        elif state == "dictation_feedback_final":
            LOG.info("第 60 题听写已显示答案，点击底部‘完成’进入测验总结。")
            self.click_text(
                items,
                "完成",
                fallback="test_question_finish",
            )
        elif state == "choice_feedback":
            # 正确/错误反馈页无需再次答题，直接进入下一题。
            self.click_text(items, "下一词", fallback="next_word")
        elif state == "test_choice":
            if self.route_test(items, image) == "dictation":
                LOG.info("没有选项但有橙色喇叭 → 按听写处理")
                self.handle_dictation(items, image)
            elif (
                self._choice_sig
                and self._page_sig(items) == self._choice_sig
                and time.monotonic() - self._choice_at < 25
            ):
                # 这页刚答过，页面可能还没跳到反馈态（或反馈页没识别出来）；
                # 不要再作答一次，直接点「下一词」翻页。
                LOG.info("这题已经答过，直接点「下一词」")
                self.click_text(items, "下一词", fallback="next_word")
            else:
                self.handle_choice(items, image)
        elif state == "test_dictation":
            if self.route_test(items, image) == "choice":
                LOG.info("页面有选项 → 按选择题处理")
                self.handle_choice(items, image)
            else:
                self.handle_dictation(items, image)
        elif state == "dictation_feedback":
            # “我不会”或提交后会出现正确答案，顺便补录进词库。
            found = self.vision.main_word(items, image.height, (0.48, 0.78))
            if found:
                word, word_item = found
                definition = self.vision.definition(items, image.height, word_item)
                self.vocab.add(word, definition)
            self.click_text(items, "下一词", fallback="next_word")
        elif state == "test_result":
            LOG.info("检测到测验总结页，点击橙色‘完成测验’。")
            self.record_accuracy(self.vision.joined(items))
            self.click_text(
                items,
                "完成测验",
                fallback="test_result_finish",
            )
        elif state == "test_complete":
            self.record_accuracy(self.vision.joined(items))
            if not self.click_text(
                items,
                "完成测验",
                "确认",
                "完成",
                "返回首页",
                fallback="test_result_finish",
            ):
                LOG.info("检测到测试完成，但没有找到结束按钮，停止运行。")
                raise SystemExit(0)
        else:
            self.handle_unknown(image, items)

    def handle_unknown(self, image: Image.Image, items: list[OCRItem]) -> None:
        self.unknown_count += 1
        # 认不出来的最常见原因：小程序窗口被别的窗口挡住了 → 主动把它置前
        if self.unknown_count >= 2:
            LOG.warning(
                "认不出页面（第 %d 次），把小程序窗口置前再说（可能被浏览器/命令行挡住了）",
                self.unknown_count,
            )
            self.ensure_foreground()
        if self.unknown_count % 8 == 0:
            LOG.warning("连续未识别页面，OCR=%s", self.vision.joined(items))
            if self.debug:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = self.screen.save_debug(image, self.root / "logs", f"unknown_{stamp}.png")
                LOG.warning("已保存未知页面：%s", path)
        time.sleep(0.5)

    # ---------------- 黑屏 / 卡死保护 ----------------
    def is_blank(self, image: Image.Image) -> bool:
        """截图区域是不是「什么都没有」：全黑（窗口最小化/屏幕休眠）或纯白（遮挡）。"""
        g = image.convert("L")
        stat = ImageStat.Stat(g)
        return stat.mean[0] < 8 or stat.stddev[0] < 2.5

    # 自己的窗口 / 预览窗 / 本对话窗口，绝不能被当成小程序置前
    OWN_TITLE_HINTS = ("设置与运行", "学习助手", "DeepSeek Harness", "刷单词脚本", "预览")

    def _target_windows(self) -> list[tuple[int, str, bool]]:
        """按标题关键字找小程序窗口，返回 [(hwnd, 标题, 是否最小化)]。

        不用 pygetwindow 的 getWindowsWithTitle：它是“包含匹配”，
        会把「OneClass 背单词 · 设置与运行」也返回，导致把助手自己置前。
        """
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:  # noqa: BLE001
            return []

        u = ctypes.windll.user32
        kws = self.cfg.get("foreground_keywords") or ["一课英语", "OneClass", "微信"]
        out: list[tuple[int, str, bool]] = []
        PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _l):
            try:
                if not u.IsWindowVisible(h):
                    return True
                n = u.GetWindowTextLengthW(h)
                if n <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, buf, n + 1)
                t = buf.value.strip()
                if not t:
                    return True
                if any(x in t for x in self.OWN_TITLE_HINTS):
                    return True
                if not any(k in t for k in kws):
                    return True
                out.append((int(h), t, bool(u.IsIconic(h))))
            except Exception:  # noqa: BLE001
                pass
            return True

        try:
            u.EnumWindows(PROC(cb), 0)
        except Exception:  # noqa: BLE001
            return []
        return out

    def ensure_foreground(self, reason: str = "", quiet: bool = True) -> bool:
        """把小程序窗口恢复并置前。真实鼠标点击前必须先做，否则点击只会激活窗口。"""
        wins = self._target_windows()
        if not wins:
            return False
        try:
            import ctypes

            u = ctypes.windll.user32
        except Exception:  # noqa: BLE001
            return False
        for hwnd, title, minimized in wins:
            try:
                u.ShowWindow(hwnd, 9)                       # SW_RESTORE
                if u.IsIconic(hwnd):
                    u.ShowWindow(hwnd, 5)
                # 绕过 Windows 的前台锁：先敲一下 Alt 再置前，必要时用 AttachThreadInput
                u.keybd_event(0x12, 0, 0, 0)
                u.keybd_event(0x12, 0, 2, 0)
                u.SetForegroundWindow(hwnd)
                u.BringWindowToTop(hwnd)
                if int(u.GetForegroundWindow()) != hwnd:
                    try:
                        u.SwitchToThisWindow(hwnd, True)
                    except Exception:  # noqa: BLE001
                        pass
                if int(u.GetForegroundWindow()) != hwnd:
                    try:
                        k32 = ctypes.windll.kernel32
                        fg = int(u.GetForegroundWindow())
                        tid_fg = u.GetWindowThreadProcessId(fg, None)
                        tid_me = k32.GetCurrentThreadId()
                        u.AttachThreadInput(tid_me, tid_fg, True)
                        u.SetForegroundWindow(hwnd)
                        u.AttachThreadInput(tid_me, tid_fg, False)
                    except Exception:  # noqa: BLE001
                        pass
                time.sleep(0.2)
                ok = int(u.GetForegroundWindow()) == hwnd
                if not ok:
                    # 系统前台锁挡着时，用真实鼠标点一下它的标题栏（模拟输入会被系统当成用户操作）
                    try:
                        import pyautogui

                        class RECT(ctypes.Structure):
                            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

                        rc = RECT()
                        u.GetWindowRect(hwnd, ctypes.byref(rc))
                        cx = (rc.left + rc.right) // 2
                        cy = rc.top + 10
                        pos = pyautogui.position()
                        pyautogui.click(cx, cy)
                        time.sleep(0.35)
                        pyautogui.moveTo(pos.x, pos.y, duration=0.1)
                        ok = int(u.GetForegroundWindow()) == hwnd
                    except Exception:  # noqa: BLE001
                        pass
                self._fg_ok += 1
                if not quiet or not ok or self._fg_ok <= 3 or self._fg_ok % 25 == 0:
                    LOG.info("%s已把窗口置前 → %s（%s）", reason, title[:30],
                             "成功" if ok else "未成功：窗口可能被最小化、被系统锁屏，或别的程序一直抢前台")
                return ok
            except Exception:  # noqa: BLE001
                continue
        return False

    def try_activate_window(self) -> None:
        """黑屏时尝试把小程序窗口恢复并置前（尽力而为，失败不影响主循环）。"""
        self.ensure_foreground("黑屏：")

    def _handle_blank(self, image: Image.Image) -> None:
        now = time.monotonic()
        if self._blank_since is None:
            self._blank_since = now
        lasted = now - self._blank_since
        if now - self._blank_last_log >= 10:
            self._blank_last_log = now
            LOG.warning(
                "截图区域是黑屏/空白（已持续 %d 秒）：小程序窗口可能被最小化、被其它窗口遮挡，或屏幕已休眠。",
                int(lasted),
            )
            if self.debug and now - self._blank_last_save >= 60:
                self._blank_last_save = now
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = self.screen.save_debug(image, self.root / "logs", f"blank_{stamp}.png")
                LOG.warning("已保存黑屏截图：%s", path)
        if bool(self.cfg.get("auto_foreground", True)) and now - self._blank_last_fg >= 15:
            self._blank_last_fg = now
            self.try_activate_window()

    def _signature(self, image: Image.Image) -> bytes:
        """把整帧压成 48x64 灰度指纹，几毫秒就够。"""
        return image.convert("L").resize((48, 64), Image.BILINEAR).tobytes()

    def should_ocr(self, image: Image.Image) -> bool:
        """画面没变化就不重复 OCR；长时间静止则每 recheck 秒强制认一次（防止点击没生效）。"""
        if not bool(self.cfg.get("ocr_skip_static", True)):
            return True
        sig = self._signature(image)
        if sig != self._last_sig:
            self._last_sig = sig
            self._same_frames = 0
            self._stall_since = time.monotonic()
            return True
        self._same_frames += 1
        interval = max(0.05, float(self.cfg.get("loop_interval", 0.3)))
        recheck = max(0.5, float(self.cfg.get("ocr_recheck_seconds", 3.0)))
        if self._same_frames * interval >= recheck:
            self._same_frames = 0
            return True
        return False

    def _log_heartbeat(self, state: str) -> None:
        """同一页面停留太久时每 4 秒打一行，卡顿时能看出卡在哪一步。"""
        now = time.monotonic()
        if self._state_since is None:
            self._state_since = now
        lasted = now - self._state_since
        if lasted < 4.0 or now - self._heartbeat_at < 4.0:
            return
        self._heartbeat_at = now
        LOG.info("页面仍是 %s，已停留 %d 秒（正在尝试推进）", state, int(lasted))
        if lasted >= 20.0 and not self._stuck_warned:
            self._stuck_warned = True
            LOG.error(
                "这一页点了 20 秒都没动，大概率是小程序自己卡住了："
                "请手动点一下页面（或关掉小程序重开），机器人会继续。"
            )

    def _check_stall(self) -> None:
        """画面长时间不动就周期性提醒，避免「看起来卡死但日志一声不吭」。"""
        if self._stall_since is None:
            return
        now = time.monotonic()
        lasted = now - self._stall_since
        warn_after = float(self.cfg.get("stall_warn_seconds", 30))
        if lasted >= warn_after and now - self._stall_last_log >= 15:
            self._stall_last_log = now
            LOG.warning(
                "画面已经 %d 秒没有变化（当前状态 %s）：如果在等加载可以忽略；否则检查窗口是否被挡住、点击是否点空。",
                int(lasted),
                self.last_state or "?",
            )

    def should_pause_clicking(self) -> bool:
        """静止太久（多半是弹窗/遮挡/加载卡住）就暂停点击，避免在弹窗上乱点。"""
        if self._stall_since is None:
            return False
        limit = float(self.cfg.get("stall_pause_seconds", 90))
        return (time.monotonic() - self._stall_since) >= limit

    def _start_watchdog(self) -> None:
        """看门狗：主循环卡住超过 20 秒就把卡住的调用栈写进日志。"""

        def loop() -> None:
            while True:
                time.sleep(5)
                stale = time.monotonic() - self._last_tick
                if stale <= 20:
                    continue
                if time.monotonic() - self._watchdog_last < 20:
                    continue
                self._watchdog_last = time.monotonic()
                LOG.error("主循环已经 %.0f 秒没有动静，卡在这里：", stale)
                try:
                    for tid, frame in sys._current_frames().items():
                        if tid != threading.main_thread().ident:
                            continue
                        LOG.error("".join(traceback.format_stack(frame)[-6:]))
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=loop, daemon=True).start()

    def _should_keep_foreground(self) -> bool:
        """每隔 keep_foreground_seconds 把小程序窗口置前一次（防止被别的窗口盖住）。"""
        secs = float(self.cfg.get("keep_foreground_seconds", 1) or 0)
        if secs <= 0 or not bool(self.cfg.get("auto_foreground", True)):
            return False
        now = time.monotonic()
        if now - self._last_fg_at < secs:
            return False
        self._last_fg_at = now
        return True

    def ensure_target_foreground(self) -> None:
        """当前前台不是小程序就把它提到最前（每轮截图前调用，保证截到的是小程序）。"""
        now = time.monotonic()
        if now < self._fg_backoff_until:
            return
        try:
            import ctypes

            fg = int(ctypes.windll.user32.GetForegroundWindow())
        except Exception:  # noqa: BLE001
            return
        wins = self._target_windows()
        if not wins:
            return
        if any(fg == hwnd for hwnd, _t, _m in wins):
            return
        if not self.ensure_foreground("截图前置前：", quiet=True):
            # 抢不到前台（可能窗口最小化/屏幕锁定）→ 退避 5 秒，别每轮都刷屏
            self._fg_backoff_until = now + 5.0


    def run(self) -> None:
        LOG.info("机器人启动。win32 模式不会移动鼠标；按 Ctrl+C 可退出。PyAutoGUI 模式仍可用左上角紧急停止。")
        self._start_watchdog()
        while True:
            self._last_tick = time.monotonic()
            # 截图前确认前台是小程序，否则截到的是压在上面的浏览器/命令行
            if bool(self.cfg.get("force_foreground_each_loop", True)):
                self.ensure_target_foreground()
            image = self.screen.capture()
            if self.is_blank(image):
                self._handle_blank(image)
                time.sleep(0.5)
                continue
            self._blank_since = None
            if not self.should_ocr(image):
                self._check_stall()
                time.sleep(float(self.cfg.get("loop_interval", 0.65)))
                continue
            items = self.vision.read(image)
            state = self.detect_state(items)
            if state != self.last_state:
                LOG.info("页面状态：%s | OCR=%s", state, self.vision.joined(items))
                self.last_state = state
                self._state_since = time.monotonic()
                self._heartbeat_at = time.monotonic()
                self._state_repeat = 0
            else:
                self._state_repeat += 1
            self._log_heartbeat(state)
            # 定时把小程序窗口置前，避免被别的窗口盖住导致截图截错
            if self._should_keep_foreground():
                self.ensure_foreground("定期置前：")
            if state != "unknown":
                self.unknown_count = 0
            if self.should_pause_clicking():
                now = time.monotonic()
                if now - self._stall_pause_log >= 30:
                    self._stall_pause_log = now
                    LOG.warning(
                        "画面静止超过 %.0f 秒，已暂停点击（疑似弹窗/遮挡/加载卡住）。关掉挡住小程序的窗口后，页面一动就会自动继续。",
                        float(self.cfg.get("stall_pause_seconds", 90)),
                    )
                time.sleep(0.5)
                continue
            self.act(state, items, image)
            time.sleep(float(self.cfg.get("loop_interval", 0.65)))

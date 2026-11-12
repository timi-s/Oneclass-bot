from __future__ import annotations

import ctypes
import re
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .vision import clean_word


class AudioRing:
    """持续录音的环形缓冲：随时可以取「最近 N 秒」。

    背单词页往往一进来就自动读音，等脚本发现新词再开始录，声音早放完了。
    所以常驻录音、需要时往回取一段，才录得到那句话。
    """

    def __init__(self, rate: int, seconds: float = 6.0):
        self.rate = int(rate)
        self.max_samples = int(self.rate * seconds)
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()

    def push(self, chunk: np.ndarray) -> None:
        chunk = np.asarray(chunk, dtype=np.float32).flatten()
        if chunk.size == 0:
            return
        with self._lock:
            self._buf = np.concatenate([self._buf, chunk])[-self.max_samples:]

    def snapshot(self, seconds: float) -> np.ndarray:
        n = int(self.rate * max(0.1, seconds))
        with self._lock:
            if self._buf.size == 0:
                return np.zeros(0, dtype=np.float32)
            return self._buf[-n:].copy()

    def clear(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)


class AudioSolver:
    def __init__(self, cfg: dict, work_dir: Path):
        self.cfg = cfg
        self.work_dir = work_dir
        self._model = None
        self.rate = int(cfg.get("audio_sample_rate", 48000))
        self.ring = AudioRing(self.rate, float(cfg.get("audio_buffer_seconds", 6.0)))
        self._cap_thread: threading.Thread | None = None
        self._cap_stop: threading.Event | None = None

    def _get_loopback(self):
        import soundcard as sc

        explicit = str(self.cfg.get("audio_loopback_name", "")).strip()
        if explicit:
            return sc.get_microphone(explicit, include_loopback=True)
        speaker = sc.default_speaker()
        # SoundCard 官方接口支持把扬声器作为 loopback microphone 获取。
        return sc.get_microphone(str(speaker.name), include_loopback=True)

    def list_devices(self) -> list[str]:
        import soundcard as sc

        return [f"{m.name} | loopback={getattr(m, 'isloopback', False)}" for m in sc.all_microphones(include_loopback=True)]

    # ---------------- 常驻录音 ----------------
    def start_capture(self) -> bool:
        """开一个后台线程持续录回环音频，环形缓冲保留最近几秒。"""
        if self._cap_thread is not None and self._cap_thread.is_alive():
            return True
        rate = self.rate
        self._cap_stop = threading.Event()
        stop = self._cap_stop
        chunk_frames = max(1, int(rate * 0.2))

        def worker() -> None:
            com_ready = False
            try:
                if hasattr(ctypes, "windll"):
                    ctypes.windll.ole32.CoInitialize(None)
                    com_ready = True
                mic = self._get_loopback()
                with mic.recorder(samplerate=rate) as rec:
                    while not stop.is_set():
                        chunk = np.asarray(rec.record(numframes=chunk_frames))
                        if chunk.ndim == 2:
                            chunk = chunk.mean(axis=1)
                        self.ring.push(chunk)
            except Exception as exc:  # noqa: BLE001
                print("常驻录音启动失败：%s" % exc)
            finally:
                if com_ready:
                    try:
                        ctypes.windll.ole32.CoUninitialize()
                    except Exception:  # noqa: BLE001
                        pass

        self._cap_thread = threading.Thread(target=worker, daemon=True)
        self._cap_thread.start()
        time.sleep(0.4)
        return True

    def stop_capture(self) -> None:
        if self._cap_stop is not None:
            self._cap_stop.set()

    @property
    def capturing(self) -> bool:
        return self._cap_thread is not None and self._cap_thread.is_alive()

    def snapshot(self, seconds: float) -> np.ndarray:
        return self.ring.snapshot(seconds)

    def _check_silence(self, data: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0
        limit = float(self.cfg.get("audio_silence_rms", 0.002))
        if rms < limit:
            raise RuntimeError(
                "录到的音频是静音（RMS=%.4f，门槛 %.4f）：系统可能被静音、音量接近 0，"
                "或当前输出设备与 audio_loopback_name 不一致" % (rms, limit)
            )
        return rms

    def record_after_click(self, click_speaker: Callable[[], None], seconds: float | None = None) -> Path:
        seconds = float(seconds if seconds is not None else self.cfg.get("audio_record_seconds", 2.8))
        output = self.work_dir / "last_dictation.wav"

        # 常驻录音开着时，点一下喇叭、等一会儿、从缓冲里取最近这段，
        # 比「临时开一个录音流」更稳（不用抢设备、也不必提前启动）。
        if self.capturing:
            self.ring.clear()
            click_speaker()
            time.sleep(seconds)
            data = self.ring.snapshot(seconds + 0.3)
            if data.size == 0:
                raise RuntimeError("录到的音频为空")
            self._check_silence(data)
            self.write_wav(output, data, self.rate)
            return output

        rate = int(self.cfg.get("audio_sample_rate", 48000))

    @staticmethod
    def write_wav(path: Path, data: np.ndarray, rate: int) -> None:
        """用标准库写 16 位单声道 wav，避开 soundfile 的 libsndfile 依赖。"""
        pcm = np.clip(np.asarray(data, dtype=float), -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(rate))
            w.writeframes(pcm.tobytes())

    def record_after_click(self, click_speaker: Callable[[], None], seconds: float | None = None) -> Path:
        rate = int(self.cfg.get("audio_sample_rate", 48000))
        seconds = float(seconds if seconds is not None else self.cfg.get("audio_record_seconds", 2.8))
        output = self.work_dir / "last_dictation.wav"
        ready = threading.Event()
        result: dict[str, np.ndarray | Exception] = {}

        def worker() -> None:
            # WASAPI(soundcard) 走 COM，工作线程必须先 CoInitialize，
            # 否则会报 0x800401f0（COM not initialized），录音直接失败。
            com_ready = False
            try:
                if hasattr(ctypes, "windll"):
                    ctypes.windll.ole32.CoInitialize(None)
                    com_ready = True
                mic = self._get_loopback()
                with mic.recorder(samplerate=rate) as rec:
                    ready.set()
                    data = rec.record(numframes=max(1, int(rate * seconds)))
                result["data"] = np.asarray(data)
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc
                ready.set()
            finally:
                if com_ready:
                    try:
                        ctypes.windll.ole32.CoUninitialize()
                    except Exception:  # noqa: BLE001
                        pass

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        ready.wait(timeout=5)
        if "error" in result:
            raise RuntimeError(f"回环录音启动失败：{result['error']}")
        time.sleep(0.18)
        click_speaker()
        thread.join(timeout=seconds + 8)
        if thread.is_alive():
            raise TimeoutError("回环录音超时")
        if "error" in result:
            raise RuntimeError(f"回环录音失败：{result['error']}")
        data = np.asarray(result.get("data"))
        if data.size == 0:
            raise RuntimeError("录到的音频为空")
        if data.ndim == 2:
            data = data.mean(axis=1)
        rms = self._check_silence(data)
        try:
            import logging

            logging.getLogger("wordbot").info("录音 RMS=%.4f", rms)
        except Exception:
            pass
        self.write_wav(output, data, rate)
        return output

    @staticmethod
    def _read_wav(path: Path) -> np.ndarray:
        """把 16 位单声道 wav 读成 16kHz 的 [-1,1] float32（whisper 只认 16k）。"""
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                raise RuntimeError("只支持 16 位单声道 wav")
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if rate != 16000:
            n_out = max(1, int(len(data) * 16000 / rate))
            t_in = np.linspace(0.0, 1.0, len(data), endpoint=False)
            t_out = np.linspace(0.0, 1.0, n_out, endpoint=False)
            data = np.interp(t_out, t_in, data).astype(np.float32)
        return data

    def record_samples(self, click_speaker: Callable[[], None], seconds: float | None = None) -> np.ndarray:
        """录一段回环音频并返回 16k 单声道样本（听写与音频模板都用它）。"""
        path = self.record_after_click(click_speaker, seconds=seconds)
        return self._read_wav(path)

    def transcribe(self, audio_path: Path, vocabulary: list[str]) -> tuple[str, str]:
        from faster_whisper import WhisperModel

        if self._model is None:
            self._model = WhisperModel(
                str(self.cfg.get("whisper_model", "small.en")),
                device=str(self.cfg.get("whisper_device", "cpu")),
                compute_type=str(self.cfg.get("whisper_compute_type", "int8")),
            )
        prompt = "Possible vocabulary: " + ", ".join(vocabulary[:250]) if vocabulary else None
        # 直接把音频样本交给模型，不让 faster-whisper 走 PyAV 解码：
        # 新版 PyAV 去掉了 av.open(metadata_errors=...) 参数，走文件路径会直接报
        # TypeError: open() got an unexpected keyword argument 'metadata_errors'。
        segments, _ = self._model.transcribe(
            self._read_wav(audio_path),
            language="en",
            beam_size=int(self.cfg.get("whisper_beam_size", 1)),
            condition_on_previous_text=False,
            initial_prompt=prompt,
            vad_filter=False,
        )
        raw = " ".join(seg.text for seg in segments).strip()
        return raw, self.best_token(raw, vocabulary)

    @staticmethod
    def best_token(raw: str, vocabulary: list[str]) -> str:
        """从识别文本里挑「最像词库里某个词」的那一段，而不是挑最长的。

        whisper 有时会把一个单词听成好几个词（"the bond" / "a band"），
        取最长词经常取错；按词库相似度挑才稳。
        """
        pieces = [clean_word(p) for p in re.findall(r"[A-Za-z][A-Za-z'-]+", raw or "")]
        pieces = [p for p in pieces if p]
        if not pieces:
            return clean_word(raw or "")
        if not vocabulary:
            return max(pieces, key=len)

        from rapidfuzz import fuzz, process

        best, best_score = pieces[0], -1.0
        for token in pieces:
            match = process.extractOne(token, vocabulary, scorer=fuzz.WRatio)
            if match and match[1] > best_score:
                best, best_score = token, float(match[1])
        return best

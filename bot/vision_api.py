"""vision_api.py —— 用「视觉大模型 API」替代本地 OCR（可选，默认关闭）

为什么默认关闭：API 单次通常 0.8–3 秒，比本地 OCR（这台机器约 0.45 秒）慢；
它的价值是**认字更准**（生僻词、花体字、错位排版），不是更快。
所以建议只在本地 OCR 连续认不出时才切过来。

支持任何 OpenAI 兼容的 chat/completions 接口（通义 qwen-vl、GLM-4V、gpt-4o 等）。

config.yaml:
```yaml
ocr_engine: api            # local（默认）| api
ocr_api:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "sk-..."
  model: "qwen-vl-plus"
  timeout: 20
  coord_scale: 1000        # 让模型用 0-1000 归一化坐标
```
"""

from __future__ import annotations

import base64
import io
import json
import re

from PIL import Image

from .vision import OCRItem, Vision

PROMPT = (
    "你是 OCR 引擎。识别图片里的所有文字，按从上到下、从左到右输出 JSON 数组，"
    "每项格式：{\"text\": \"原文\", \"bbox\": [x1, y1, x2, y2]}。"
    "bbox 用 0-1000 的归一化坐标。只输出 JSON，不要任何解释。"
)


class ApiVision(Vision):
    def __init__(self, cfg: dict):
        # 不调用父类 __init__，避免加载本地模型
        self.scale = 1.0
        self.min_score = 0.0
        self.engine = None
        api = cfg.get("ocr_api") or {}
        self.base_url = str(api.get("base_url") or "").rstrip("/")
        self.api_key = str(api.get("api_key") or "")
        self.model = str(api.get("model") or "")
        self.timeout = float(api.get("timeout", 20))
        self.min_score = float(cfg.get("ocr_min_score", 0.45))

    def _encode(self, image: Image.Image) -> str:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _post(self, image: Image.Image) -> str:
        import requests

        if not (self.base_url and self.model and self.api_key):
            raise RuntimeError("ocr_api 配置不完整：需要 base_url / api_key / model")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + self._encode(image)}},
                ],
            }],
        }
        resp = requests.post(
            self.base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _extract_json(text: str) -> list:
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < 0:
            return []
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return []

    def read(self, image: Image.Image) -> list[OCRItem]:
        raw = self._post(image)
        rows = self._extract_json(raw)
        w, h = image.width, image.height
        items: list[OCRItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            txt = str(row.get("text") or "").strip()
            bbox = row.get("bbox") or row.get("box") or []
            if not txt or len(bbox) != 4:
                continue
            try:
                x1, y1, x2, y2 = [float(v) for v in bbox]
            except Exception:
                continue
            if max(x1, y1, x2, y2) <= 1.0:      # 模型给了 0-1
                x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h
            elif max(x1, y1, x2, y2) <= 1000:   # 0-1000 归一化
                x1, y1, x2, y2 = x1 * w / 1000, y1 * h / 1000, x2 * w / 1000, y2 * h / 1000
            elif max(x1, y1, x2, y2) <= 10000 and min(x1, y1) > 0 and max(x1, y1, x2, y2) / max(w, h) > 2:
                x1, y1, x2, y2 = x1 / 1000 * w, y1 / 1000 * h, x2 / 1000 * w, y2 / 1000 * h
            items.append(OCRItem(txt, 1.0, x1, y1, x2, y2))
        return sorted(items, key=lambda i: (i.cy, i.cx))

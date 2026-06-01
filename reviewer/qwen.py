"""Qwen3.5-Omni 专业级逐帧情感分析 — 阿里云百炼 API

本模块提供专业审片人级别的 16 帧逐帧情感分析：
- 每帧 8 个维度深度解析（情绪/强度/面部/肢体/视觉/角色/微表情/置信度）
- 输出包含精确时间戳，覆盖全片情感曲线
- 向后兼容旧版 issues/summary 结构

API: Qwen Omni (qwen-omni-turbo) via DashScope
"""

from __future__ import annotations

import os
import json
import base64
import subprocess
import tempfile
import uuid
import re
from pathlib import Path

import requests

QWEN_API_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")

# ── 每帧 16 向情感标签字典 ──────────────────────────────────────────────
EMOTION_LABELS = [
    "愤怒", "悲伤", "喜悦", "恐惧", "惊讶", "厌恶",
    "中性", "紧张", "期待", "释然", "轻蔑", "困惑",
    "满足", "内疚", "羞耻", "兴奋",
]

# ── 分析 prompt 模板 ────────────────────────────────────────────────────
ANALYSIS_PROMPT = """你是一位拥有 30 年经验的影视审片导演，专精于表演和情感传达分析。

我将向你展示从一段视频中按时间顺序抽取的 {frame_count} 个关键帧。
请逐帧进行专业级情感分析，输出严格的 JSON。

{shot_context}

【分析维度 — 每一帧必须逐项分析】

1. primary_emotion: 从以下标签中挑选最匹配的主要情绪：
   {emotion_labels}
2. intensity: 情绪强度 1-10（1=完全抑制，5=适中流露，10=极度爆发）
3. facial_expression: 面部表情细节（眉眼形态、嘴角弧度、肌肉紧张度、眼神注视方向）
4. body_language: 肢体语言（手势含义、躯干姿态、身体朝向、与镜头距离感）
5. visual_mood: 画面情绪氛围（色调冷暖、光线明暗与方向、构图张力）
6. character: 角色身份（如果可以判断，否则填"未知"）
7. micro_expressions: 微表情观察（是否有转瞬即逝的不自然微表情，或与主情绪矛盾的细微信号）
8. confidence: 你对本帧分析的置信度 0.0-1.0

【额外要求】
- 在分析完所有帧后，给出 overall_observation（200 字以内的整体情感观察）
- 给出 dominant_emotion（整个片段中最突出的情绪，从标签中选择一个）
- 给出 emotional_range（片段中出现的所有情绪标签列表）
- 保持 issues 字段为空数组

输出 JSON 格式（严格遵循，不要包含任何注释或多余文字）：
{{
  "frames": [
    {{
      "index": 0,
      "timestamp_sec": 0.0,
      "primary_emotion": "中性",
      "intensity": 5,
      "facial_expression": "眉眼舒展...",
      "body_language": "双手自然下垂...",
      "visual_mood": "暖色调...",
      "character": "未知",
      "micro_expressions": "无明显异常微表情",
      "confidence": 0.90
    }}
  ],
  "overall_observation": "整体情感观察...",
  "dominant_emotion": "愤怒",
  "emotional_range": ["愤怒", "悲伤", "释然"],
  "issues": []
}}"""


class QwenAnalyzer:
    """使用 Qwen Omni 模型做专业级短剧情感分析。

    提取 16 帧并对每帧进行 8 维度深度情感解析，
    同时保持与旧版接口的向后兼容。
    """

    def __init__(self) -> None:
        """初始化分析器，从环境变量读取 API Key。"""
        self.api_key: str = os.getenv("QWEN_API_KEY", "")
        self.api_url: str = QWEN_API_URL

    # ── 关键帧提取 ──────────────────────────────────────────────────────

    def _extract_keyframes(
        self,
        video_path: str,
        count: int = 16,
    ) -> list[tuple[float, str]]:
        """从视频均匀提取 N 个关键帧。

        Args:
            video_path: 视频文件路径
            count: 提取帧数（默认 16）

        Returns:
            [(timestamp_sec, data_uri), ...] 或空列表
            其中 data_uri 为 "data:image/jpeg;base64,..."
        """
        tmp_dir = (
            Path(tempfile.gettempdir())
            / "ai_review_qwen"
            / uuid.uuid4().hex
        )
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # 获取视频时长
        try:
            result = subprocess.run(
                [FFMPEG, "-i", video_path],
                capture_output=True, text=True, timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        duration: float = 0.0
        for line in (result.stderr or "").split("\n"):
            if "Duration:" in line:
                parts = line.strip().split("Duration: ")[1].split(",")[0]
                h, m, s = parts.split(":")
                duration = float(h) * 3600 + float(m) * 60 + float(s)
                break

        if duration <= 0:
            return []

        # 均匀分布取帧
        frames: list[tuple[float, str]] = []
        step = duration / (count + 1)
        for i in range(1, count + 1):
            t = step * i
            out_path = tmp_dir / f"kf_{i:03d}.jpg"
            try:
                subprocess.run(
                    [
                        FFMPEG, "-ss", str(t), "-i", video_path,
                        "-frames:v", "1", "-q:v", "2", "-y",
                        str(out_path), "-loglevel", "quiet",
                    ],
                    capture_output=True, timeout=30,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

            if out_path.exists() and out_path.stat().st_size > 0:
                with open(out_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                    frames.append((
                        round(t, 2),
                        f"data:image/jpeg;base64,{b64}",
                    ))

        return frames

    # ── JSON 解析辅助 ───────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> str:
        """从模型原始输出中提取纯 JSON 文本。

        处理 ```json...``` 包裹、尾部逗号、多余内容等情况。
        """
        text = text.strip()
        # 去掉 markdown 代码块包裹
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # 尝试定位第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        # 移除尾部逗号（JSON 不允许）
        text = re.sub(r",\s*([}\]])", r"\1", text)

        return text

    @staticmethod
    def _normalize_emotion(value: str) -> str:
        """将模型返回的情绪标签归一化到标准标签集。"""
        if not value:
            return "中性"
        value = value.strip()
        for label in EMOTION_LABELS:
            if label in value or value in label:
                return label
        return value  # 保留模型判断但不在标签集中时也返回

    # ── 主分析方法 ──────────────────────────────────────────────────────

    def analyze_emotion(
        self,
        video_path: str,
        shot_emotions: list | None = None,
    ) -> dict:
        """对视频进行专业级 16 帧逐帧情感分析。

        Args:
            video_path: 视频文件路径
            shot_emotions: 可选的预期分镜情绪列表，
               如 [{"time": 0, "emotion": "悲伤"}, ...]
               会作为参考提供给模型，但不强制匹配。

        Returns:
            {
                frames: [{index, timestamp_sec, primary_emotion, intensity,
                          facial_expression, body_language, visual_mood,
                          character, micro_expressions, confidence}, ...],
                overall_observation: str,
                dominant_emotion: str,
                emotional_range: [str, ...],
                issues: [],           # 向后兼容
                summary: str,         # 向后兼容（等同 overall_observation）
                _fallback: bool,      # 仅在降级时存在
            }
        """
        # ── 检查 API Key ────────────────────────────────────────
        if not self.api_key:
            return {
                "frames": [],
                "overall_observation": "Qwen API Key 未配置，跳过情感分析",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": "Qwen API Key 未配置，跳过情感分析",
                "_fallback": True,
            }

        # ── 提取 16 帧 ─────────────────────────────────────────
        frame_data = self._extract_keyframes(video_path, count=16)
        if not frame_data:
            return {
                "frames": [],
                "overall_observation": "无法提取视频关键帧",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": "无法提取视频关键帧",
                "_fallback": True,
            }

        timestamps = [ts for ts, _ in frame_data]
        images = [uri for _, uri in frame_data]

        # ── 构建 shot_emotions 参考上下文 ───────────────────────
        shot_context = ""
        if shot_emotions:
            items = [
                f"  {s.get('time', '?')}s: {s.get('emotion', '?')}"
                for s in shot_emotions[:20]
            ]
            shot_context = (
                "【参考信息 — 预期分镜情绪（仅供参考，不强制匹配）】\n"
                + "\n".join(items)
                + "\n\n"
            )

        # ── 构建 prompt ─────────────────────────────────────────
        prompt = ANALYSIS_PROMPT.format(
            frame_count=len(frame_data),
            shot_context=shot_context,
            emotion_labels=", ".join(EMOTION_LABELS),
        )

        # 在每帧图片后附加时间戳信息
        time_hints = (
            "\n\n【时间戳参考 — 每帧对应视频时间】\n"
            + "\n".join(
                f"  帧 {i}: {ts:.1f}s"
                for i, ts in enumerate(timestamps)
            )
        )
        prompt += time_hints

        # ── 构建多模态请求 ─────────────────────────────────────
        content: list[dict] = []
        for img_data_uri in images:
            content.append({"image": img_data_uri})
        content.append({"text": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "qwen-omni-turbo",
            "input": {
                "messages": [{"role": "user", "content": content}],
            },
        }

        # ── 调用 API ───────────────────────────────────────────
        try:
            resp = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=180,  # 16 帧 + 详细 prompt 需要更多时间
            )
        except requests.RequestException as e:
            return {
                "frames": [],
                "overall_observation": f"Qwen API 网络请求失败: {e}",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": f"Qwen API 网络请求失败: {e}",
                "_fallback": True,
            }

        if resp.status_code != 200:
            return {
                "frames": [],
                "overall_observation": f"Qwen API 返回 {resp.status_code}",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": f"Qwen API 返回 {resp.status_code}",
                "_error": resp.text[:500],
                "_fallback": True,
            }

        # ── 解析响应 ───────────────────────────────────────────
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {
                "frames": [],
                "overall_observation": "Qwen API 返回非 JSON 响应",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": "Qwen API 返回非 JSON 响应",
                "_error": resp.text[:500],
                "_fallback": True,
            }

        # 提取 message content
        output = data.get("output", {})
        choices = output.get("choices", [])
        if not choices:
            return {
                "frames": [],
                "overall_observation": "Qwen API 返回空 choices",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": "Qwen API 返回空 choices",
                "_fallback": True,
            }

        try:
            content_raw = choices[0].get("message", {}).get("content", "")
        except (AttributeError, TypeError, IndexError):
            content_raw = ""

        # Qwen Omni 可能返回 list[dict] 或纯字符串
        text = ""
        if isinstance(content_raw, list):
            for block in content_raw:
                if isinstance(block, dict) and "text" in block:
                    text += block["text"]
                elif isinstance(block, str):
                    text += block
        else:
            text = str(content_raw)

        if not text.strip():
            return {
                "frames": [],
                "overall_observation": "Qwen API 返回空内容",
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": "Qwen API 返回空内容",
                "_fallback": True,
            }

        # ── 解析 JSON ──────────────────────────────────────────
        try:
            clean = self._extract_json(text)
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            return {
                "frames": [],
                "overall_observation": text[:500],
                "dominant_emotion": "未知",
                "emotional_range": [],
                "issues": [],
                "summary": text[:500],
                "_fallback": True,
                "_note": "Qwen 返回格式无法解析为 JSON",
            }

        # ── 规范化并注入时间戳 ─────────────────────────────────
        raw_frames: list[dict] = parsed.get("frames", [])

        normalized_frames: list[dict] = []
        for i, rf in enumerate(raw_frames):
            frame = {
                "index": rf.get("index", i),
                "timestamp_sec": round(
                    rf.get("timestamp_sec", 0.0)
                    if rf.get("timestamp_sec", 0) > 0
                    else (timestamps[i] if i < len(timestamps) else 0.0),
                    2,
                ),
                "primary_emotion": self._normalize_emotion(
                    rf.get("primary_emotion", "中性")
                ),
                "intensity": max(1, min(10, int(rf.get("intensity", 5)))),
                "facial_expression": str(
                    rf.get("facial_expression", "未提供")
                ),
                "body_language": str(rf.get("body_language", "未提供")),
                "visual_mood": str(rf.get("visual_mood", "未提供")),
                "character": str(rf.get("character", "未知")),
                "micro_expressions": str(
                    rf.get("micro_expressions", "未观察到")
                ),
                "confidence": max(
                    0.0, min(1.0, float(rf.get("confidence", 0.5)))
                ),
            }
            normalized_frames.append(frame)

        # 如果模型没有返回 frames，使用帧数 + 时间戳构建基础结构
        if not normalized_frames and len(timestamps) > 0:
            for i, ts in enumerate(timestamps):
                normalized_frames.append({
                    "index": i,
                    "timestamp_sec": ts,
                    "primary_emotion": "未知",
                    "intensity": 5,
                    "facial_expression": "模型未返回逐帧分析",
                    "body_language": "模型未返回逐帧分析",
                    "visual_mood": "模型未返回逐帧分析",
                    "character": "未知",
                    "micro_expressions": "模型未返回",
                    "confidence": 0.0,
                })

        # ── 构建结果 ───────────────────────────────────────────
        overall = str(parsed.get("overall_observation", "无"))
        dominant = self._normalize_emotion(
            parsed.get("dominant_emotion", "中性")
        )
        e_range = parsed.get("emotional_range", [])
        if not isinstance(e_range, list):
            e_range = []
        e_range = [
            self._normalize_emotion(e) for e in e_range
            if isinstance(e, str) and e.strip()
        ]

        issues = parsed.get("issues", [])
        if not isinstance(issues, list):
            issues = []

        return {
            "frames": normalized_frames,
            "overall_observation": overall,
            "dominant_emotion": dominant,
            "emotional_range": e_range,
            "issues": issues,
            "summary": overall,  # 向后兼容
        }

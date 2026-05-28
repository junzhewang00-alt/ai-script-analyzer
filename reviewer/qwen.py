"""Qwen3.5-Omni 情感分析 — 阿里云百炼 API"""

from __future__ import annotations

import os
import json
import base64
import subprocess
import tempfile
import uuid
from pathlib import Path

import requests

QWEN_API_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")


class QwenAnalyzer:
    """使用 Qwen Omni 模型做短剧情感一致性分析"""

    def __init__(self):
        self.api_key = os.getenv("QWEN_API_KEY", "")
        self.api_url = QWEN_API_URL

    def _extract_keyframes(self, video_path: str, count: int = 10) -> list[str]:
        """从视频提取 N 个关键帧，返回 base64 列表"""
        tmp_dir = Path(tempfile.gettempdir()) / "ai_review_qwen" / uuid.uuid4().hex
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # 先获取时长
        result = subprocess.run(
            [FFMPEG, "-i", video_path],
            capture_output=True, text=True,
        )
        duration = 0.0
        for line in (result.stderr or "").split("\n"):
            if "Duration:" in line:
                parts = line.strip().split("Duration: ")[1].split(",")[0]
                h, m, s = parts.split(":")
                duration = float(h) * 3600 + float(m) * 60 + float(s)
                break

        if duration <= 0:
            return []

        frames = []
        step = duration / (count + 1)
        for i in range(1, count + 1):
            t = step * i
            out_path = tmp_dir / f"kf_{i:03d}.jpg"
            subprocess.run(
                [FFMPEG, "-ss", str(t), "-i", video_path,
                 "-frames:v", "1", "-q:v", "2", "-y",
                 str(out_path), "-loglevel", "quiet"],
                capture_output=True,
            )
            if out_path.exists() and out_path.stat().st_size > 0:
                with open(out_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                    frames.append(f"data:image/jpeg;base64,{b64}")

        return frames

    def analyze_emotion(self, video_path: str,
                        shot_emotions: list | None = None) -> dict:
        """
        分析视频情感一致性。

        Args:
            video_path: 视频文件路径
            shot_emotions: 预期的分镜情绪列表，如 [{"time": 0, "emotion": "悲伤"}, ...]

        Returns:
            {issues: [{timestamp, expected, actual, confidence}], summary}
        """
        if not self.api_key:
            return {
                "issues": [],
                "summary": "Qwen API Key 未配置，跳过情感分析",
                "_fallback": True,
            }

        # 提取关键帧
        frames = self._extract_keyframes(video_path, count=8)
        if not frames:
            return {
                "issues": [],
                "summary": "无法提取视频关键帧",
                "_fallback": True,
            }

        # 构建情绪上下文
        emotion_ctx = ""
        if shot_emotions:
            items = [f"{s.get('time', '?')}s: {s.get('emotion', '?')}"
                     for s in shot_emotions[:10]]
            emotion_ctx = "预期分镜情绪: " + "; ".join(items)

        prompt = (
            f"你是一个专业的短剧审核员。请逐帧分析以下视频片段的情感表达。\n"
            f"{emotion_ctx}\n\n"
            f"请对每一帧判断：人物表情/肢体语言传达的情感是否与预期一致。\n"
            f"输出 JSON 格式：\n"
            f'{{"issues": [{{"timestamp": 秒数, "expected": "预期的情绪", '
            f'"actual": "实际观察到的情绪", "confidence": 0.0-1.0}}], '
            f'"summary": "总体情感一致性评价"}}'
        )

        # 构建多模态请求
        content = [{"image": frame} for frame in frames[:6]]
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

        try:
            resp = requests.post(
                self.api_url, headers=headers,
                json=payload, timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                # 提取输出中的 JSON
                output = data.get("output", {})
                choices = output.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", "")
                    # 尝试解析 JSON
                    try:
                        parsed = json.loads(
                            text.strip().removeprefix("```json").removesuffix("```").strip()
                        )
                        return {
                            "issues": parsed.get("issues", []),
                            "summary": parsed.get("summary", text[:500]),
                        }
                    except json.JSONDecodeError:
                        return {
                            "issues": [],
                            "summary": text[:500],
                        }
            else:
                return {
                    "issues": [],
                    "summary": f"Qwen API 返回 {resp.status_code}",
                    "_error": resp.text[:300],
                }
        except Exception as e:
            return {
                "issues": [],
                "summary": f"Qwen API 调用失败: {e}",
                "_error": str(e),
            }

"""视频处理管道 — FFmpeg 技术质量检测"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")


class VideoAnalyzer:
    """视频技术质量分析器 — 模糊 / 卡顿 / 音画同步"""

    UPLOAD_FOLDER = BASE_DIR / "uploads" / "videos"
    AUDIO_FOLDER = BASE_DIR / "uploads" / "audio"
    TEMP_FOLDER = Path(tempfile.gettempdir()) / "ai_review_tmp"

    def __init__(self):
        self.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        self.AUDIO_FOLDER.mkdir(parents=True, exist_ok=True)
        self.TEMP_FOLDER.mkdir(parents=True, exist_ok=True)

    def upload_video(self, file_storage) -> str:
        """保存上传视频，返回路径"""
        import uuid
        ext = os.path.splitext(file_storage.filename)[1] or ".mp4"
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = self.UPLOAD_FOLDER / filename
        file_storage.save(str(dest))
        return str(dest)

    # ── FFmpeg 命令构建 ──────────────────────────

    def _run_ffmpeg(self, args: list, timeout: int = 120) -> tuple[str, str]:
        """运行 ffmpeg，返回 (stdout, stderr)。不抛异常，遇错返回空字符串。"""
        try:
            result = subprocess.run(
                [FFMPEG, "-hide_banner"] + args,
                capture_output=True, text=True, timeout=timeout,
            )
            return result.stdout, result.stderr
        except Exception:
            return "", ""

    def _get_duration(self, video_path: str) -> float:
        """获取视频时长（秒）"""
        _, stderr = self._run_ffmpeg(["-i", video_path])
        for line in (stderr or "").split("\n"):
            if "Duration:" in line:
                parts = line.strip().split("Duration: ")[1].split(",")[0]
                h, m, s = parts.split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)
        return 0.0

    def extract_audio(self, video_path: str) -> str | None:
        """提取音频为 WAV，返回路径"""
        audio_name = Path(video_path).stem + ".wav"
        dest = self.AUDIO_FOLDER / audio_name
        self._run_ffmpeg([
            "-i", video_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-y", str(dest),
        ])
        return str(dest) if dest.exists() else None

    # ── 模糊检测 ──────────────────────────────────

    def check_blur(self, video_path: str) -> dict:
        """抽取 5 个等间距关键帧，用 Laplacian 方差判定模糊程度"""
        duration = self._get_duration(video_path)
        if duration <= 0:
            return {"blur_score": 0.0, "blurry_frames": [], "is_acceptable": True}

        try:
            import cv2
            import numpy as np
        except ImportError:
            return {"blur_score": 0.0, "blurry_frames": [],
                    "is_acceptable": True, "_error": "opencv-python not installed"}

        frame_times = [duration * i / 6 for i in range(1, 6)]  # 5 个时间点
        blurry_frames = []
        scores = []

        tmp_dir = self.TEMP_FOLDER / Path(video_path).stem
        tmp_dir.mkdir(parents=True, exist_ok=True)

        for i, t in enumerate(frame_times):
            out_path = tmp_dir / f"frame_{i}.png"
            self._run_ffmpeg([
                "-ss", str(t), "-i", video_path,
                "-frames:v", "1", "-q:v", "2",
                "-y", str(out_path), "-loglevel", "quiet",
            ])
            if not out_path.exists():
                continue

            img = cv2.imread(str(out_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue

            laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
            scores.append(laplacian_var)
            if laplacian_var < 100:  # 经验阈值
                blurry_frames.append({
                    "time": round(t, 1),
                    "variance": round(laplacian_var, 1),
                })

        # 归一化：(0=极模糊, 1=极清晰) → blur_score (0=清晰, 1=模糊)
        if scores:
            avg_var = sum(scores) / len(scores)
            # 用 sigmoid 映射到 0-1；500 约为"清晰"的 Laplacian 方差
            blur_score = round(1.0 / (1.0 + avg_var / 100.0), 2)
        else:
            blur_score = 0.0

        return {
            "blur_score": blur_score,
            "blurry_frames": blurry_frames,
            "is_acceptable": blur_score < 0.5 and len(blurry_frames) <= 2,
        }

    # ── 卡顿检测 ──────────────────────────────────

    def check_stutter(self, video_path: str) -> dict:
        """用 mpdecimate 检测重复帧 / 卡顿（限制前 60 秒）"""
        _, stderr = self._run_ffmpeg([
            "-i", video_path,
            "-t", "60",
            "-vf", "mpdecimate",
            "-f", "null", "-",
        ])
        # 解析 mpdecimate 输出行: "mpdecimate: lo:xxx hi:xxx drops:xxx dups:xxx ..."
        stutter_timestamps = []
        for line in (stderr or "").split("\n"):
            if "mpdecimate" in line and "pts_time:" in line:
                try:
                    ts = float(line.split("pts_time:")[1].split()[0])
                    stutter_timestamps.append(round(ts, 1))
                except (ValueError, IndexError):
                    pass

        return {
            "stutter_count": len(stutter_timestamps),
            "stutter_timestamps": stutter_timestamps,
            "is_acceptable": len(stutter_timestamps) <= 3,
        }

    # ── 音画同步 ──────────────────────────────────

    def check_audio_sync(self, video_path: str) -> dict:
        """检测音视频流的起始偏移"""
        _, stderr = self._run_ffmpeg(["-i", video_path])

        audio_start = video_start = None
        for line in (stderr or "").split("\n"):
            if "Stream #0" in line and "Audio:" in line and "start" in line:
                try:
                    audio_start = float(line.split("start")[1].split(",")[0].strip())
                except (ValueError, IndexError):
                    pass
            elif "Stream #0" in line and "Video:" in line and "start" in line:
                try:
                    video_start = float(line.split("start")[1].split(",")[0].strip())
                except (ValueError, IndexError):
                    pass

        offset = 0.0
        if audio_start is not None and video_start is not None:
            offset = round(abs(audio_start - video_start) * 1000, 1)  # 转毫秒

        return {
            "sync_offset_ms": offset,
            "is_acceptable": offset < 200,  # 200ms 以内可接受
        }

    # ── 综合 ──────────────────────────────────────

    def analyze_technical(self, video_path: str) -> dict:
        """一站式技术质量检测"""
        blur = self.check_blur(video_path)
        stutter = self.check_stutter(video_path)
        sync = self.check_audio_sync(video_path)
        return {
            "blur": blur,
            "stutter": stutter,
            "audio_sync": sync,
            "all_acceptable": (
                blur.get("is_acceptable", True)
                and stutter.get("is_acceptable", True)
                and sync.get("is_acceptable", True)
            ),
        }

"""审核编排器 — 串联视频处理、ASR、AI 分析、汇总

新版流程（专业审片人级别）：
1. 技术质量检测（并行）
2. 提取音频 → ASR → 台词比对
3. 16帧关键帧 → Qwen Omni 逐帧情感分析
4. DeepSeek 专业审片报告合成（综合 Qwen数据 + 剧本 + ASR）
5. 三者汇总 → DeepSeek 最终评审
6. 保存到数据库
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from reviewer.video import VideoAnalyzer
from reviewer.asr import ASRProcessor
from reviewer.qwen import QwenAnalyzer
from reviewer.synthesizer import EmotionSynthesizer
from reviewer.claude_bridge import ClaudeBridge


class ReviewOrchestrator:
    """审核流水线总调度"""

    def __init__(self):
        self.video = VideoAnalyzer()
        self.asr = ASRProcessor()
        self.qwen = QwenAnalyzer()
        self.synthesizer = EmotionSynthesizer()
        self.claude = ClaudeBridge()

    def run_review(self, job_id: int, video_path: str, script_text: str,
                   cancel_event: threading.Event | None = None,
                   flask_app=None) -> dict:
        """
        主入口：执行完整审核流水线。

        流程:
        1. 技术质量检测（可立即启动，不需要 AI）
        2. 提取音频 → ASR → 台词比对（串行依赖）
        3. 关键帧 → Qwen 16帧逐帧情感分析
        4. 合成器 → DeepSeek 专业审片报告
        5. 三者汇总 → DeepSeek 最终评审
        6. 保存到数据库

        Returns:
            {success: bool, results: {emotion, dialogue, tech}, summary: {...}}
        """
        results = {}
        errors = []

        def _cancelled():
            return cancel_event and cancel_event.is_set()

        # ── 阶段 1: 技术质量（并行） ──
        if _cancelled():
            return {"success": False, "error": "已取消", "results": {}}

        tech_result = self.video.analyze_technical(video_path)
        results["tech"] = tech_result
        tech_issues = 0
        if not tech_result.get("all_acceptable", True):
            tech_issues = sum(
                1 for k in ["blur", "stutter", "audio_sync"]
                if not tech_result.get(k, {}).get("is_acceptable", True)
            )

        # ── 阶段 2: 音频 → ASR → 台词比对 ──
        if _cancelled():
            return {"success": True, "results": results, "summary": None}

        audio_path = self.video.extract_audio(video_path)
        asr_result = {"text": "", "segments": [], "language": "unknown"}

        if audio_path:
            asr_result = self.asr.transcribe(str(audio_path))

        dialogue_result = self.claude.compare_dialogue(
            script_text, asr_result.get("text", "")
        )
        results["dialogue"] = dialogue_result

        # ── 阶段 3: Qwen 16帧逐帧情感分析 ──
        if _cancelled():
            return {"success": True, "results": results, "summary": None}

        qwen_emotion = self.qwen.analyze_emotion(video_path)

        # ── 阶段 4: DeepSeek 专业审片报告合成 ──
        if _cancelled():
            return {"success": True, "results": results, "summary": None}

        if not qwen_emotion.get("_fallback"):
            # Qwen 分析成功 → 合成专业审片报告
            emotion_result = self.synthesizer.synthesize(
                qwen_result=qwen_emotion,
                script_text=script_text,
                asr_text=asr_result.get("text", ""),
            )
            # 附带原始 Qwen 数据供前端展示逐帧分析
            emotion_result["_qwen_raw"] = qwen_emotion
        else:
            # Qwen 不可用 → 直接使用 fallback
            emotion_result = qwen_emotion
        results["emotion"] = emotion_result

        # ── 阶段 5: 汇总评审 ──
        if _cancelled():
            return {"success": True, "results": results, "summary": None}

        summary = self.claude.generate_summary(results)
        results["_summary"] = summary

        # ── 阶段 6: 持久化 ──
        if flask_app:
            try:
                from models import ReviewJob, ReviewResult, ReviewSummary
                from datetime import datetime, timezone

                with flask_app.app_context():
                    from app import db
                    job = db.session.get(ReviewJob, job_id)
                    if job:
                        job.status = "completed"
                        job.updated_at = datetime.now(timezone.utc)

                        # 保存各维度结果
                        for dim, data in [
                            ("tech", tech_result),
                            ("dialogue", dialogue_result),
                            ("emotion", emotion_result),
                        ]:
                            issue_count = len(data.get("issues", [])) if dim != "tech" else tech_issues
                            db.session.add(ReviewResult(
                                job_id=job_id,
                                dimension=dim,
                                result_json=json.dumps(data, ensure_ascii=False),
                                issues_count=issue_count,
                            ))

                        # 保存汇总
                        existing = db.session.query(ReviewSummary).filter_by(
                            job_id=job_id,
                        ).first()
                        if existing:
                            existing.overall_score = summary.get("overall_score", 50)
                            existing.ai_opinion = summary.get("opinion", "")
                            existing.passed = summary.get("passed", False)
                            existing.created_at = datetime.now(timezone.utc)
                        else:
                            db.session.add(ReviewSummary(
                                job_id=job_id,
                                overall_score=summary.get("overall_score", 50),
                                ai_opinion=summary.get("opinion", ""),
                                passed=summary.get("passed", False),
                            ))

                        db.session.commit()
            except Exception as e:
                errors.append(f"数据库保存失败: {e}")

        return {
            "success": True,
            "results": results,
            "summary": summary,
            "errors": errors if errors else None,
        }

    def _update_status(self, job, status: str, db):
        """更新 ReviewJob 状态"""
        from datetime import datetime, timezone
        job.status = status
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

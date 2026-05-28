"""ASR 语音转写 — OpenAI Whisper"""

import logging

logger = logging.getLogger(__name__)

# 延迟加载 whisper 模型（首次调用时触发）
_whisper_model = None
_model_name = "base"


def _get_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            import whisper
            _whisper_model = whisper.load_model(_model_name)
        except ImportError:
            logger.warning("openai-whisper not installed; ASR will return fallback")
            return None
        except Exception as e:
            logger.error(f"Whisper model load failed: {e}")
            return None
    return _whisper_model


class ASRProcessor:
    """语音转文本处理器"""

    def __init__(self, model: str = "base"):
        global _model_name
        _model_name = model

    def transcribe(self, audio_path: str) -> dict:
        """
        转写音频文件 → 返回 {text, segments, language}

        如果 whisper 不可用，返回 fallback dict
        """
        model = _get_model()
        if model is None:
            return {
                "text": "",
                "segments": [],
                "language": "unknown",
                "_error": "openai-whisper not installed",
            }

        try:
            result = model.transcribe(audio_path, fp16=False)
            return {
                "text": result.get("text", "").strip(),
                "segments": [
                    {
                        "start": round(seg.get("start", 0), 2),
                        "end": round(seg.get("end", 0), 2),
                        "text": seg.get("text", "").strip(),
                    }
                    for seg in result.get("segments", [])
                ],
                "language": result.get("language", "unknown"),
            }
        except Exception as e:
            logger.error(f"ASR transcription failed: {e}")
            return {
                "text": "",
                "segments": [],
                "language": "unknown",
                "_error": str(e),
            }

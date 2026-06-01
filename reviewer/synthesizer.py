"""DeepSeek 驱动的专业审片报告合成器。

将 Qwen 逐帧情感分析结果合成为结构化的专业审片报告，
包含情绪曲线、角色分析、表演质量、节奏把控、亮点/问题等维度。

使用方式:
    synth = EmotionSynthesizer()
    report = synth.synthesize(qwen_result, script_text="...", asr_text="...")
"""

from __future__ import annotations

import json
import logging
import re

from analyzer.llm import call_llm

logger = logging.getLogger(__name__)

# ── 资深短剧审片人 System Prompt ──────────────────────────────

SYSTEM_PROMPT = (
    "【角色】你是一位资深短剧审片人，拥有 15 年影视后期审片经验，"
    "阅片过万，对表演、情绪表达、节奏把控有极其敏锐的判断力。\n\n"
    "【风格】你的评价专业、犀利、一针见血，不绕弯子。"
    "该夸就夸，该骂就骂，坚决不说废话和客套话。"
    "点评要具体到秒，给出可操作的改进建议。\n\n"
    "【输出规则】\n"
    "1. 所有情绪分析必须基于给定的逐帧数据，不可以凭空编造\n"
    "2. 如果提供了剧本原文和 ASR 文本，需结合考虑台词与情绪的匹配度\n"
    "3. 评分标准（0-100）：\n"
    "   - 90+：表演精湛，情绪层次丰富，可以直接过片\n"
    "   - 75-89：整体合格，有亮点但也存在可改进之处\n"
    "   - 60-74：基本达标，但多处需要补拍或调整\n"
    "   - 60 以下：表演存在明显问题，建议重拍\n"
    "4. 情绪阶段划分要合理，每个阶段至少包含 3 秒以上的连续情绪\n"
    "5. 重拍建议必须具体，指明时间点和原因\n\n"
    "【输出格式】纯 JSON，不要 markdown 代码块，不要任何额外文字。"
    "所有字段必须填写，字符串不能为空，数组不能为空（除非真的没有）。"
)

# ── 输出 JSON Schema 定义（嵌入 prompt 中） ──────────────────

OUTPUT_SCHEMA = """
{
  "emotional_arc": {
    "trajectory": "情绪从XX到XX的变化轨迹描述（一句话概括）",
    "curve_description": "用文字描述情绪曲线形状：上升 / 下降 / 波动 / 平缓 / 先升后降 / 波浪式上升 等",
    "stages": [
      {
        "timestamp_range": "0s-15s",
        "emotion": "愤怒",
        "intensity": 8,
        "note": "对这一阶段情绪表现的简短点评"
      }
    ]
  },
  "character_analysis": [
    {
      "character": "女主",
      "emotional_journey": "角色从出场到结束的情感发展脉络描述",
      "consistency_score": 85,
      "performance_notes": "表演点评，指出亮点和不足",
      "believable": true
    }
  ],
  "performance_quality": {
    "overall_score": 78,
    "facial_score": 80,
    "body_language_score": 75,
    "strengths": ["微表情丰富自然", "愤怒戏爆发力强"],
    "weaknesses": ["第30秒处表情略显僵硬", "悲伤场景眼神不够到位"],
    "micro_expression_notes": "对微表情的整体评价，如果没有微表情数据则填'无可用的微表情数据'"
  },
  "emotional_pacing": {
    "score": 82,
    "rhythm": "紧凑 / 舒缓 / 张弛有度 / 拖沓",
    "transition_quality": "情绪转换是否自然、流畅",
    "critique": "节奏把控的详细点评"
  },
  "highlights": [
    {"timestamp_sec": 12, "description": "愤怒爆发表演极具张力，肢体语言配合完美"}
  ],
  "issues": [
    {
      "timestamp_sec": 45,
      "description": "从悲伤到平静的过渡过于突兀",
      "severity": "high",
      "suggestion": "建议增加2秒缓冲镜头"
    }
  ],
  "overall_score": 80,
  "verdict": "200字以内的总评审意见，语气专业但直接，一针见血",
  "reshoot_recommendations": ["重拍45-50秒过渡段", "补拍特写强化悲伤情绪"]
}
"""


def _strip_markdown_fence(text: str) -> str:
    """去除 markdown 代码块包裹（```json ... ```）。"""
    text = text.strip()
    # 匹配开头的 ```json 或 ```（可能带语言标识）
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    # 匹配结尾的 ```
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()


def _build_prompt(qwen_result: dict, script_text: str, asr_text: str) -> str:
    """构建发送给 DeepSeek 的分析 prompt。"""
    parts = []

    # 1. 逐帧情感数据（核心输入）
    frames = qwen_result.get("frames", [])
    if frames:
        frame_lines = []
        for f in frames:
            idx = f.get("index", "?")
            ts = f.get("timestamp_sec", 0)
            emo = f.get("primary_emotion", "未知")
            intensity = f.get("intensity", 0)
            char = f.get("character", "未知角色")
            facial = f.get("facial_expression", "")
            body = f.get("body_language", "")
            mood = f.get("visual_mood", "")
            micro = f.get("micro_expressions", "")
            conf = f.get("confidence", 0)
            frame_lines.append(
                f"  帧#{idx} @ {ts:.1f}s | {char} | {emo} (强度{intensity}) | "
                f"表情:{facial} | 肢体:{body} | 氛围:{mood} | 微表情:{micro} | 置信度:{conf:.0%}"
            )
        parts.append(f"【逐帧情感数据】({len(frames)} 帧)\n" + "\n".join(frame_lines))
    else:
        parts.append("【逐帧情感数据】（无帧数据）")

    # 2. 整体观察
    overall = qwen_result.get("overall_observation", "")
    dominant = qwen_result.get("dominant_emotion", "")
    emo_range = qwen_result.get("emotional_range", [])
    parts.append(
        f"\n【整体观察】\n"
        f"  主导情绪: {dominant}\n"
        f"  情绪范围: {', '.join(emo_range) if emo_range else '未知'}\n"
        f"  观察摘要: {overall}"
    )

    # 3. 剧本原文（可选）
    if script_text.strip():
        parts.append(f"\n【剧本原文】（供情绪对照参考）\n{script_text[:3000]}")

    # 4. ASR 语音转写（可选）
    if asr_text.strip():
        parts.append(f"\n【ASR 语音转写】（供台词-情绪匹配参考）\n{asr_text[:3000]}")

    parts.append(
        f"\n\n请根据以上数据进行专业审片分析，输出完整的 JSON 报告。\n"
        f"输出格式（严格按此 JSON 结构）：\n{OUTPUT_SCHEMA}"
    )

    return "\n".join(parts)


def _build_fallback(qwen_result: dict, error_msg: str = "") -> dict:
    """构造降级报告（API 调用失败时使用）。"""
    frames = qwen_result.get("frames", [])
    dominant = qwen_result.get("dominant_emotion", "未知")
    emo_range = qwen_result.get("emotional_range", [])
    overall = qwen_result.get("overall_observation", "")

    # 从帧数据提取简单统计
    if frames:
        chars = list(dict.fromkeys(f.get("character", "未知") for f in frames))
        intensities = [f.get("intensity", 0) for f in frames]
        avg_intensity = sum(intensities) / len(intensities) if intensities else 0
    else:
        chars = ["未知角色"]
        avg_intensity = 0

    fallback = {
        "_fallback": True,
        "_error": error_msg,
        "emotional_arc": {
            "trajectory": f"情绪整体表现为{dominant}主导{'，辅以' + '、'.join(emo_range[1:4]) if len(emo_range) > 1 else ''}" if dominant else "无法确定情绪轨迹",
            "curve_description": "无法分析（API 调用失败）",
            "stages": [
                {
                    "timestamp_range": "0s-全部",
                    "emotion": dominant or "未知",
                    "intensity": round(avg_intensity),
                    "note": "基于帧数据的粗略推断，待 API 恢复后重新分析",
                }
            ],
        },
        "character_analysis": [
            {
                "character": c,
                "emotional_journey": "无法分析（API 调用失败）",
                "consistency_score": 50,
                "performance_notes": "API 不可用，无法评估",
                "believable": True,
            }
            for c in (chars or ["未知角色"])
        ],
        "performance_quality": {
            "overall_score": 50,
            "facial_score": 50,
            "body_language_score": 50,
            "strengths": ["暂无数据"],
            "weaknesses": ["暂无数据"],
            "micro_expression_notes": "API 不可用，无法评估微表情",
        },
        "emotional_pacing": {
            "score": 50,
            "rhythm": "无法判断",
            "transition_quality": "API 不可用，无法评估",
            "critique": "API 调用失败，请检查配置后重试",
        },
        "highlights": [],
        "issues": [
            {
                "timestamp_sec": 0,
                "description": f"审片报告生成失败: {error_msg}" if error_msg else "API 调用失败",
                "severity": "high",
                "suggestion": "请检查 DeepSeek API 配置后重试",
            }
        ],
        "overall_score": 50,
        "verdict": f"审片报告无法生成。{error_msg}" if error_msg else "审片报告无法生成，API 不可用。",
        "reshoot_recommendations": [],
    }
    return fallback


class EmotionSynthesizer:
    """专业审片报告合成器。

    将 Qwen 逐帧情感分析结果、剧本原文和 ASR 语音转写文本
    输入 DeepSeek，生成结构化的专业审片报告。
    """

    def synthesize(
        self,
        qwen_result: dict,
        script_text: str = "",
        asr_text: str = "",
    ) -> dict:
        """合成完整的专业审片报告。

        Args:
            qwen_result: Qwen 情感分析输出，包含 frames、overall_observation、
                         dominant_emotion、emotional_range 等字段。
            script_text: 剧本原文（可选），用于台词-情绪匹配参考。
            asr_text: 语音转写文本（可选），用于实际台词-情绪匹配参考。

        Returns:
            结构化的审片报告 dict。如果 API 调用失败，返回带 _fallback: True
            的降级报告。

        Raises:
            不抛异常——所有错误均通过 fallback 报告返回。
        """
        prompt = _build_prompt(qwen_result, script_text, asr_text)

        try:
            raw_output = call_llm(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
            )
        except Exception as exc:
            logger.warning("DeepSeek API 调用失败: %s", exc)
            return _build_fallback(qwen_result, error_msg=str(exc))

        if not raw_output or not raw_output.strip():
            logger.warning("DeepSeek 返回空内容")
            return _build_fallback(qwen_result, error_msg="DeepSeek 返回空内容")

        # ── JSON 解析（容错处理） ──────────────────────
        cleaned = _strip_markdown_fence(raw_output)

        try:
            report = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("DeepSeek 返回 JSON 解析失败: %s\n原始输出前500字符: %s",
                           exc, raw_output[:500])
            # 第二次尝试：提取第一个 { 到最后一个 } 之间的内容
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    report = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return _build_fallback(
                        qwen_result,
                        error_msg=f"JSON 解析失败: {exc}",
                    )
            else:
                return _build_fallback(
                    qwen_result,
                    error_msg=f"JSON 解析失败: {exc}",
                )

        # ── 确保返回格式完整 ──────────────────────────
        report.setdefault("_fallback", False)
        # 向后兼容：summary = verdict
        if "verdict" in report and "summary" not in report:
            report["summary"] = report["verdict"]

        # 填充缺失的顶层字段
        defaults: dict = {
            "emotional_arc": {
                "trajectory": "",
                "curve_description": "",
                "stages": [],
            },
            "character_analysis": [],
            "performance_quality": {
                "overall_score": 50,
                "facial_score": 50,
                "body_language_score": 50,
                "strengths": [],
                "weaknesses": [],
                "micro_expression_notes": "",
            },
            "emotional_pacing": {
                "score": 50,
                "rhythm": "",
                "transition_quality": "",
                "critique": "",
            },
            "highlights": [],
            "issues": [],
            "overall_score": 50,
            "verdict": "",
            "reshoot_recommendations": [],
        }
        for key, default_val in defaults.items():
            if key not in report or report[key] is None:
                report[key] = default_val

        return report


# ── 便捷函数 ──────────────────────────────────────────────

_synthesizer: EmotionSynthesizer | None = None


def get_synthesizer() -> EmotionSynthesizer:
    """获取全局单例 EmotionSynthesizer 实例。"""
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = EmotionSynthesizer()
    return _synthesizer


def synthesize_report(
    qwen_result: dict,
    script_text: str = "",
    asr_text: str = "",
) -> dict:
    """快捷函数：生成审片报告。

    Args:
        qwen_result: Qwen 情感分析结果。
        script_text: 剧本原文（可选）。
        asr_text: ASR 语音转写文本（可选）。

    Returns:
        结构化审片报告 dict。
    """
    return get_synthesizer().synthesize(qwen_result, script_text, asr_text)

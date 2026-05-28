"""DeepSeek 分析桥接 — 台词比对 + 汇总评审（替代 Claude Code）"""

import json
import os
import re

from analyzer.llm import call_llm


class ClaudeBridge:
    """通过 DeepSeek API 进行台词比对和汇总评审（兼容原 ClaudeBridge 接口）"""

    SYSTEM_DIALOGUE = (
        "【角色】你是短剧台词比对专家，专门比对剧本原文与 ASR 实际台词。\n\n"
        "【规则】\n"
        "• ASR 可能有识别错误（同音字、漏词），请合理判断，不要把 ASR 错误标记为台词差异\n"
        "• 差异类型必须明确归类：缺失/替换/新增/顺序错误\n"
        "• 匹配度 = 完全匹配的台词行数 / 总行数 × 100%\n\n"
        "【输出格式】每行一条差异，末尾一行匹配度\n"
        "【禁止】不要输出解释性文字，不要开场白"
    )

    SYSTEM_SUMMARY = (
        "【角色】你是短剧审核总评审，综合技术质量、台词匹配、情感一致性三维度，"
        "给出最终评分和决策。\n\n"
        "【评分权重】\n"
        "• 技术质量 20%：画面清晰度、流畅度、音画同步\n"
        "• 台词匹配 40%：剧本与实际台词的一致性\n"
        "• 情感一致性 40%：表演情绪是否符合剧本要求\n\n"
        "【通过标准】综合≥70 分为通过\n\n"
        "【输出格式】纯 JSON，不要 markdown 代码块\n"
        '{"overall_score": 整数, "opinion": "一句话评审意见 + 主要问题", "passed": true/false}\n\n'
        "【禁止】输出 JSON 以外的任何内容"
    )

    # ── 台词比对 ──────────────────────────────────

    def compare_dialogue(self, script_text: str, asr_text: str) -> dict:
        """
        比对剧本原文与 ASR 实际台词。

        Returns:
            {differences: [{position, original, actual, type}], match_percentage}
        """
        if not script_text.strip() or not asr_text.strip():
            return {"differences": [], "match_percentage": 100.0,
                    "_note": "无对比内容"}

        script_short = script_text[:2000]
        asr_short = asr_text[:2000]

        prompt = (
            "请比对以下短剧剧本与实际台词，找出所有差异。\n\n"
            f"【剧本原文】\n{script_short}\n\n"
            f"【实际台词（ASR 转写）】\n{asr_short}\n\n"
            "请逐条列出差异，格式如下：\n"
            "位置 | 原文 | 实际 | 类型(缺失/替换/新增/顺序错误)\n\n"
            "最后一行单独给出匹配度百分比，格式: 匹配度: XX%"
        )

        try:
            output = call_llm(
                prompt=prompt,
                system_prompt=self.SYSTEM_DIALOGUE,
            )
        except Exception as e:
            return {"differences": [], "match_percentage": 100.0,
                    "_error": f"API 调用失败: {e}"}

        differences = []
        match_pct = 100.0

        for line in (output or "").split("\n"):
            line = line.strip()
            m = re.search(r"匹配度[：:]?\s*(\d+\.?\d*)\s*%", line)
            if m:
                match_pct = float(m.group(1))
                continue
            if " | " in line and not line.startswith("[") and not line.startswith("位置"):
                parts = line.split(" | ", 3)
                if len(parts) >= 3:
                    differences.append({
                        "position": parts[0].strip(),
                        "original": parts[1].strip(),
                        "actual": parts[2].strip(),
                        "type": parts[3].strip() if len(parts) > 3 else "未知",
                    })

        return {
            "differences": differences,
            "match_percentage": match_pct,
        }

    # ── 汇总评审 ──────────────────────────────────

    def generate_summary(self, all_results: dict) -> dict:
        """
        汇总三个维度的审核结果，生成最终评分和意见。

        Args:
            all_results: {"emotion": {...}, "dialogue": {...}, "tech": {...}}

        Returns:
            {overall_score: int, opinion: str, passed: bool}
        """
        # 提取关键信息，避免 token 过长
        summary_data = {}
        skipped_dims = []
        for dim in ("tech", "dialogue", "emotion"):
            data = all_results.get(dim, {})
            if data.get("_fallback") or data.get("_note"):
                skipped_dims.append(dim)
            if dim == "tech":
                summary_data["tech"] = {
                    "all_acceptable": data.get("all_acceptable", True),
                    "blur_score": data.get("blur", {}).get("blur_score", 0),
                    "stutter_count": data.get("stutter", {}).get("stutter_count", 0),
                    "sync_offset_ms": data.get("audio_sync", {}).get("sync_offset_ms", 0),
                }
            elif dim == "dialogue":
                summary_data["dialogue"] = {
                    "match_percentage": data.get("match_percentage", 100),
                    "difference_count": len(data.get("differences", [])),
                }
            elif dim == "emotion":
                summary_data["emotion"] = {
                    "issue_count": len(data.get("issues", [])),
                    "summary": data.get("summary", ""),
                }

        result_text = json.dumps(summary_data, ensure_ascii=False, indent=2)
        skipped_note = ""
        if skipped_dims:
            dim_cn = {"tech": "技术质量", "dialogue": "台词匹配", "emotion": "情感分析"}
            skipped_note = "\n\n⚠️ 以下维度因配置缺失已跳过，不计入评分: " + ", ".join(dim_cn.get(d, d) for d in skipped_dims)

        prompt = (
            "请根据以下审核数据给出综合评分（0-100）、审核意见和是否通过。\n\n"
            f"{result_text[:3000]}{skipped_note}\n\n"
            "输出 JSON（不要 markdown 代码块）：\n"
            '{"overall_score": 整数, "opinion": "综合评审意见", "passed": true/false}'
        )

        try:
            output = call_llm(
                prompt=prompt,
                system_prompt=self.SYSTEM_SUMMARY,
            )
        except Exception as e:
            return {
                "overall_score": 50,
                "opinion": f"评审 API 不可用: {e}",
                "passed": False,
            }

        try:
            clean = (output or "").strip()
            clean = clean.removeprefix("```json").removesuffix("```").strip()
            parsed = json.loads(clean)
            return {
                "overall_score": int(parsed.get("overall_score", 50)),
                "opinion": str(parsed.get("opinion", output[:500])),
                "passed": bool(parsed.get("passed", False)),
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "overall_score": 50,
                "opinion": (output or "评审暂不可用")[:500],
                "passed": False,
            }

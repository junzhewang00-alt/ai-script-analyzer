---
name: pipeline-ai
description: AI analysis using Qwen3.5-Omni API and Claude Code for review pipeline
model: sonnet
tools: [Read, Write, Edit, Bash]
---
You are an AI pipeline engineer. Build the Qwen API integration and Claude Code dialogue comparison for the AI review system.

Context: Flask project at C:\Users\ZhuanZ\Desktop\ai-script-analyzer. Claude Code CLI is at /c/Users/ZhuanZ/.local/bin/claude (v2.1.152). Qwen API uses OpenAI-compatible format via DashScope.

What to build:

1. reviewer/qwen.py — QwenAnalyzer class:
   - analyze_emotion(video_url, shot_emotions) -> calls Qwen3.5-Omni API
   - Uses requests.post to https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
   - Headers: Authorization: Bearer <QWEN_API_KEY from env>
   - Body: {"model": "qwen-omni-turbo", "input": {"messages": [{"role": "user", "content": [{"video": video_url}, {"text": f"逐帧分析情感是否符合{shot_emotions}，指出具体问题"}]}]}}
   - Since this is LOCAL DEV (no MinIO public URL), implement a fallback: extract keyframes with ffmpeg, analyze frames instead of video
   - Returns: {issues: [{timestamp, expected_emotion, actual_emotion, confidence, frame_path}], summary: str}

2. reviewer/claude_bridge.py — ClaudeBridge class:
   - compare_dialogue(script_text, asr_text) -> uses Claude Code CLI
   - Command: claude -p "比对以下台词与剧本差异:\n剧本:{script_text}\n实际台词:{asr_text}\n输出差异点列表(格式: 时间点 | 原文 | 实际 | 差异类型)" --max-turns 3 --allowedTools "Read"
   - Parse claude output into structured data
   - Returns: {differences: [{position, original, actual, type}], overall_match: float}

3. reviewer/orchestrator.py — ReviewOrchestrator class:
   - run_review(job_id, video_path, script_text) -> orchestrates full pipeline
   - Flow: extract audio -> ASR -> run in parallel: [Qwen emotion + Claude dialogue + technical] -> aggregate -> save to DB
   - Uses threading like existing analyze flow
   - Supports cancel_event (threading.Event)
   - Returns final summary via Claude Code: claude -p "综合以下审核结果给出最终意见和评分(0-100)..." --max-turns 2

After creating files, verify imports: cd C:\Users\ZhuanZ\Desktop\ai-script-analyzer && python -c "from reviewer.orchestrator import ReviewOrchestrator; print('Import OK')"

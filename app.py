import os
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import markdown
from flask import Flask, render_template, request, session, jsonify
from dotenv import load_dotenv

from analyzer.parser import parse_text, parse_file
from analyzer.llm import call_llm
from analyzer.prompts import build_analysis_tasks

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")

UPLOAD_FOLDER = tempfile.gettempdir()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    # 1. Get script text
    text_input = request.form.get("script_text", "").strip()
    uploaded_file = request.files.get("script_file")

    try:
        if uploaded_file and uploaded_file.filename:
            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            tmp_path = os.path.join(UPLOAD_FOLDER, f"upload_{os.urandom(8).hex()}{ext}")
            uploaded_file.save(tmp_path)
            try:
                script_text = parse_file(tmp_path)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        elif text_input:
            script_text = parse_text(text_input)
        else:
            return render_template("index.html", error="请粘贴剧本文本或上传剧本文件")
    except ValueError as e:
        return render_template("index.html", error=str(e))
    except Exception as e:
        return render_template("index.html", error=f"文件解析失败: {e}")

    # 2. Run analysis
    tasks = build_analysis_tasks(script_text)
    config_ok = bool(os.getenv("LLM_API_KEY"))

    if config_ok:
        results = _run_analysis(tasks)
    else:
        # Demo mode — show prompts without calling LLM
        results = _demo_analysis(tasks)

    # Markdown → HTML
    for r in results:
        if r["content"] and not r["error"]:
            r["content"] = _render_md(r["content"])

    return render_template("result.html", results=results, is_demo=not config_ok)


def _run_analysis(tasks: list[dict]) -> list[dict]:
    """Run all analysis tasks concurrently."""
    results = []

    def _run_one(task):
        full_prompt = f"{task['instruction']}\n\n{task['user']}"
        try:
            output = call_llm(full_prompt, system_prompt=task["system"])
            return {"label": task["label"], "content": output, "error": None}
        except Exception as e:
            return {"label": task["label"], "content": "", "error": str(e)}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_run_one, t): t for t in tasks}
        # Preserve order
        ordered = [None] * len(tasks)
        for future in as_completed(futures):
            task = futures[future]
            idx = tasks.index(task)
            ordered[idx] = future.result()

        results = [r for r in ordered if r is not None]

    return results


def _demo_analysis(tasks: list[dict]) -> list[dict]:
    """Return prompt preview when no LLM configured."""
    results = []
    for t in tasks:
        content = f"**[演示模式 — 请配置 .env 中的 LLM_API_KEY 以获取真实分析]**\n\n"
        content += f"**System Prompt:** {t['system'][:100]}...\n\n"
        content += f"**指令:** {t['instruction'][:200]}...\n\n"
        content += f"**剧本长度:** {len(t['user'])} 字符"
        results.append({"label": t["label"], "content": content, "error": None})
    return results


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    if not data or "script_text" not in data:
        return jsonify({"error": "缺少 script_text 字段"}), 400

    try:
        script_text = parse_text(data["script_text"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not os.getenv("LLM_API_KEY"):
        return jsonify({"error": "请先配置 LLM_API_KEY"}), 500

    tasks = build_analysis_tasks(script_text)
    results = _run_analysis(tasks)
    for r in results:
        if r["content"] and not r["error"]:
            r["content"] = _render_md(r["content"])
    return jsonify({"results": results})


def _render_md(text: str) -> str:
    """Convert Markdown to HTML for display."""
    return markdown.markdown(
        text,
        extensions=["extra", "codehilite", "nl2br"],
        extension_configs={
            "codehilite": {"guess_lang": False},
        },
    )


if __name__ == "__main__":
    import sys

    print("=" * 50)
    print("  AI 短剧剧本分析器")
    print("  http://localhost:5000")
    print("=" * 50)

    # 生产模式用 waitress，开发模式用 Flask dev server
    if "--prod" in sys.argv:
        from waitress import serve
        port = int(os.getenv("PORT", 5000))
        print(f"  生产模式 (waitress) → http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port)
    else:
        app.run(debug=True)

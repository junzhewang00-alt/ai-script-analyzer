import os
import json
import tempfile
import threading
import uuid
from pathlib import Path

import markdown
from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from dotenv import load_dotenv

from analyzer.parser import parse_text, parse_file
from analyzer.llm import call_llm
from analyzer.prompts import build_analysis_tasks

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")

UPLOAD_FOLDER = tempfile.gettempdir()

# 内存任务存储
_jobs: dict = {}
_lock = threading.Lock()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
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

    config_ok = bool(os.getenv("LLM_API_KEY"))
    tasks = build_analysis_tasks(script_text)

    job_id = uuid.uuid4().hex[:12]

    with _lock:
        _jobs[job_id] = {
            "script_text": script_text,
            "tasks": tasks,
            "results": [
                {"label": t["label"], "content": "", "error": None, "status": "idle"}
                for t in tasks
            ],
            "is_demo": not config_ok,
            "total": len(tasks),
            "script_preview": script_text[:200].replace("\n", " ") + ("..." if len(script_text) > 200 else ""),
            "char_count": len(script_text),
        }

    return redirect(url_for("manual_analyze", job_id=job_id), code=303)


@app.route("/analyze/<job_id>")
def manual_analyze(job_id):
    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        return render_template("index.html", error="任务不存在或已过期，请重新提交剧本")

    return render_template("manual.html",
        job_id=job_id,
        is_demo=job["is_demo"],
        results=job["results"],
        script_preview=job.get("script_preview", ""),
        char_count=job.get("char_count", 0),
    )


@app.route("/api/job/<job_id>")
def job_status(job_id):
    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        return jsonify({"error": "任务不存在或已过期"}), 404

    return jsonify({
        "results": job["results"],
        "is_demo": job["is_demo"],
        "total": job["total"],
        "script_preview": job.get("script_preview", ""),
        "char_count": job.get("char_count", 0),
    })


@app.route("/api/job/<job_id>/run/<int:index>", methods=["POST"])
def run_single_dimension(job_id, index):
    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        return jsonify({"error": "任务不存在"}), 404

    if index < 0 or index >= len(job["tasks"]):
        return jsonify({"error": "无效的分析维度"}), 400

    with _lock:
        if job["results"][index]["status"] == "running":
            return jsonify({"error": "该维度正在分析中"}), 409
        if job["results"][index]["status"] == "done":
            return jsonify({"error": "该维度已完成"}), 409
        job["results"][index]["status"] = "running"

    task = job["tasks"][index]

    def _run_one():
        if job["is_demo"]:
            import time
            time.sleep(0.5)
            demo = (
                f"**[演示模式]**\n\n"
                f"**System Prompt:** {task['system'][:100]}...\n\n"
                f"**指令:** {task['instruction'][:200]}...\n\n"
                f"**剧本长度:** {len(task['user'])} 字符"
            )
            with _lock:
                job["results"][index] = {
                    "label": task["label"],
                    "content": _render_md(demo),
                    "error": None,
                    "status": "done",
                }
        else:
            full_prompt = f"{task['instruction']}\n\n{task['user']}"
            try:
                output = call_llm(full_prompt, system_prompt=task["system"])
                with _lock:
                    job["results"][index] = {
                        "label": task["label"],
                        "content": _render_md(output),
                        "error": None,
                        "status": "done",
                    }
            except Exception as e:
                with _lock:
                    job["results"][index] = {
                        "label": task["label"],
                        "content": "",
                        "error": str(e),
                        "status": "error",
                    }

    threading.Thread(target=_run_one, daemon=True).start()

    return jsonify({"ok": True})


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
    results = []
    for task in tasks:
        full_prompt = f"{task['instruction']}\n\n{task['user']}"
        try:
            output = call_llm(full_prompt, system_prompt=task["system"])
            results.append({"label": task["label"], "content": _render_md(output), "error": None})
        except Exception as e:
            results.append({"label": task["label"], "content": "", "error": str(e)})
    return jsonify({"results": results})


def _render_md(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=["extra", "codehilite", "nl2br"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )


if __name__ == "__main__":
    import sys

    print("=" * 50)
    print("  AI 短剧剧本分析器")
    print("  http://localhost:5000")
    print("=" * 50)

    if "--prod" in sys.argv:
        from waitress import serve
        port = int(os.getenv("PORT", 5000))
        print(f"  生产模式 (waitress) → http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port)
    else:
        app.run(debug=True, threaded=True)

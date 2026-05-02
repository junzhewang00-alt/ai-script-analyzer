import os
import json
import tempfile
import threading
import uuid
import time
from pathlib import Path

import markdown
from flask import Flask, render_template, request, session, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_required, current_user
from dotenv import load_dotenv

from analyzer.parser import parse_text, parse_file
from analyzer.llm import call_llm, get_config
from analyzer.prompts import build_analysis_tasks, SYSTEM_ROLE

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'instance' / 'app.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
(BASE_DIR / "instance").mkdir(exist_ok=True)

from models import db, User, CreditLog, get_analysis_cost, CREDIT_COST
from auth import auth_bp
from pay_bp import pay_bp

db.init_app(app)
app.register_blueprint(auth_bp)
app.register_blueprint(pay_bp)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "请先登录后再使用此功能"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

UPLOAD_FOLDER = tempfile.gettempdir()
JOBS_DIR = BASE_DIR / ".jobs"
JOBS_DIR.mkdir(exist_ok=True)

# 服务端 API 配置存储 (key=sid, 不在 cookie 中传密钥)
_api_configs: dict = {}
# 内存任务存储
_jobs: dict = {}
# 取消事件 — (job_id, index) → threading.Event
_cancel_events: dict = {}
_lock = threading.Lock()

JOB_TTL_SECONDS = 24 * 3600  # 24 小时后自动清理
LOG_FILE = BASE_DIR / "server.log"

def _log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _get_sid() -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["sid"] = sid
    return sid


# ---- 持久化 ----

def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _save_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        return
    data = {
        "script_text": job.get("script_text", ""),
        "tasks": job.get("tasks", []),
        "results": job.get("results", []),
        "is_demo": job.get("is_demo", False),
        "total": job.get("total", 0),
        "script_preview": job.get("script_preview", ""),
        "char_count": job.get("char_count", 0),
        "overview": job.get("overview"),
        "created_at": job.get("created_at", time.time()),
    }
    tmp = _job_path(job_id).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_job_path(job_id))


def _load_jobs():
    count = 0
    now = time.time()
    for fp in sorted(JOBS_DIR.glob("*.json")):
        job_id = fp.stem
        if job_id in _jobs:
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if now - data.get("created_at", 0) > JOB_TTL_SECONDS:
                fp.unlink(missing_ok=True)
                continue
            _jobs[job_id] = {
                "script_text": data.get("script_text", ""),
                "tasks": data.get("tasks", []),
                "results": data.get("results", []),
                "is_demo": data.get("is_demo", False),
                "total": data.get("total", 0),
                "script_preview": data.get("script_preview", ""),
                "char_count": data.get("char_count", 0),
                "overview": data.get("overview"),
                "created_at": data.get("created_at", time.time()),
            }
            count += 1
        except Exception:
            fp.unlink(missing_ok=True)
    if count:
        print(f"  已加载 {count} 个历史分析任务")


def _cleanup_stale_jobs():
    now = time.time()
    with _lock:
        stale = [
            jid for jid, j in _jobs.items()
            if now - j.get("created_at", 0) > JOB_TTL_SECONDS
        ]
        for jid in stale:
            del _jobs[jid]
            _job_path(jid).unlink(missing_ok=True)


# 启动时加载历史任务
_load_jobs()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/prompts")
def prompts_studio():
    return render_template("prompts.html")


@app.route("/analyze", methods=["POST"])
@login_required
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

    # 积分检查
    cost = get_analysis_cost(len(script_text))
    if current_user.credits < cost:
        return render_template("index.html",
            error=f"积分不足！本次分析需要 {cost} 积分，当前余额 {current_user.credits} 积分。"
                  f'<a href="/dashboard">去充值</a>')

    _deduct_credits(cost, f"剧本分析 ({len(script_text)}字)")

    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    config_ok = bool(os.getenv("LLM_API_KEY") or sc.get("api_key"))
    tasks = build_analysis_tasks(script_text)

    job_id = uuid.uuid4().hex[:12]

    with _lock:
        _jobs[job_id] = {
            "script_text": script_text,
            "tasks": tasks,
            "results": [
                {"label": t["label"], "content": "", "error": None, "status": "idle", "cancel": False}
                for t in tasks
            ],
            "is_demo": not config_ok,
            "total": len(tasks),
            "script_preview": script_text[:200].replace("\n", " ") + ("..." if len(script_text) > 200 else ""),
            "char_count": len(script_text),
            "created_at": time.time(),
        }
        _save_job(job_id)

    return redirect(url_for("manual_analyze", job_id=job_id), code=303)


@app.route("/analyze/<job_id>")
@login_required
def manual_analyze(job_id):
    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        return render_template("index.html", error="任务不存在或已过期，请重新提交剧本")

    return render_template("manual.html",
        job_id=job_id,
        is_demo=job["is_demo"],
        results=job["results"],
        total=job["total"],
        script_preview=job.get("script_preview", ""),
        char_count=job.get("char_count", 0),
    )


@app.route("/api/job/<job_id>")
@login_required
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
        "overview": job.get("overview"),
    })


@app.route("/api/config", methods=["GET"])
def api_config_get():
    is_local = request.remote_addr in ("127.0.0.1", "localhost", "::1")
    sid = _get_sid()
    server_config = _api_configs.get(sid, {})
    env_config = get_config() if is_local else {"api_base": "", "api_key": "", "model": ""}

    if server_config:
        merged = {
            "api_base": server_config.get("api_base", ""),
            "api_key": server_config.get("api_key", ""),
            "model": server_config.get("model", ""),
            "has_env_key": bool(env_config["api_key"]),
        }
    else:
        merged = {
            "api_base": env_config["api_base"],
            "api_key": env_config["api_key"],
            "model": env_config["model"],
            "has_env_key": bool(env_config["api_key"]),
        }
    return jsonify(merged)


@app.route("/api/config", methods=["POST"])
def api_config_save():
    data = request.get_json() or {}
    sid = _get_sid()
    _api_configs[sid] = {
        "api_base": data.get("api_base", "").strip(),
        "api_key": data.get("api_key", "").strip(),
        "model": data.get("model", "").strip(),
    }
    return jsonify({"ok": True})


@app.route("/api/job/<job_id>/run/<int:index>", methods=["POST"])
@login_required
def run_single_dimension(job_id, index):
    # 单个维度积分检查
    if current_user.credits < CREDIT_COST["single_dimension"]:
        return jsonify({"error": f"积分不足，单个维度分析需要 {CREDIT_COST['single_dimension']} 积分"}), 402
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
        job["results"][index]["cancel"] = False

    task = job["tasks"][index]
    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    cancel_event = threading.Event()
    _cancel_events[(job_id, index)] = cancel_event
    user_id = current_user.id

    def _run_one():
        try:
            if job["is_demo"]:
                _log(f"[job={job_id}] dim={index} demo mode start")
                time.sleep(0.5)
                if cancel_event.is_set():
                    _log(f"[job={job_id}] dim={index} cancelled before done")
                    with _lock:
                        job["results"][index]["status"] = "idle"
                        _save_job(job_id)
                    return
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
                    _save_job(job_id)
                _log(f"[job={job_id}] dim={index} demo mode done")
            else:
                _log(f"[job={job_id}] dim={index} ({task['label']}) calling LLM")
                full_prompt = f"{task['instruction']}\n\n{task['user']}"
                try:
                    output = call_llm(
                        full_prompt, system_prompt=task["system"],
                        api_base=sc.get("api_base") or None,
                        api_key=sc.get("api_key") or None,
                        model=sc.get("model") or None,
                        cancel_event=cancel_event,
                    )
                    _log(f"[job={job_id}] dim={index} ({task['label']}) LLM returned {len(output)} chars")
                    with _lock:
                        job["results"][index] = {
                            "label": task["label"],
                            "content": _render_md(output),
                            "error": None,
                            "status": "done",
                        }
                        _save_job(job_id)
                    _deduct_credits(CREDIT_COST["single_dimension"], f"单维度分析: {task['label']}", user_id=user_id)
                except RuntimeError as e:
                    _log(f"[job={job_id}] dim={index} ({task['label']}) cancelled: {e}")
                    with _lock:
                        job["results"][index] = {
                            "label": task["label"],
                            "content": "",
                            "error": None,
                            "status": "idle",
                        }
                        _save_job(job_id)
                except Exception as e:
                    _log(f"[job={job_id}] dim={index} ({task['label']}) ERROR: {e}")
                    with _lock:
                        job["results"][index] = {
                            "label": task["label"],
                            "content": "",
                            "error": str(e),
                            "status": "error",
                        }
                        _save_job(job_id)
        finally:
            _cancel_events.pop((job_id, index), None)

    threading.Thread(target=_run_one, daemon=True).start()
    _log(f"[job={job_id}] dim={index} thread started")

    return jsonify({"ok": True})


@app.route("/api/job/<job_id>/cancel/<int:index>", methods=["POST"])
@login_required
def cancel_dimension(job_id, index):
    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        return jsonify({"error": "任务不存在"}), 404

    if index < 0 or index >= len(job["results"]):
        return jsonify({"error": "无效的分析维度"}), 400

    with _lock:
        r = job["results"][index]
        if r["status"] != "running":
            return jsonify({"error": "该维度未在运行中"}), 409
        r["status"] = "idle"
        _save_job(job_id)

    # 设置取消事件 — 这会终止正在进行的 HTTP 流式连接
    ev = _cancel_events.get((job_id, index))
    if ev:
        ev.set()

    return jsonify({"ok": True})


@app.route("/api/job/<job_id>/overview", methods=["POST"])
@login_required
def run_overview(job_id):
    if current_user.credits < CREDIT_COST["overview"]:
        return jsonify({"error": f"积分不足，概览生成需要 {CREDIT_COST['overview']} 积分"}), 402

    with _lock:
        job = _jobs.get(job_id)

    if job is None:
        return jsonify({"error": "任务不存在"}), 404

    done_results = [r for r in job["results"] if r["status"] == "done"]
    if len(done_results) < 3:
        return jsonify({"error": f"至少需要3个维度完成才能生成概览，当前已完成 {len(done_results)} 个"}), 400

    with _lock:
        if job.get("overview", {}).get("status") == "running":
            return jsonify({"error": "概览正在生成中"}), 409
        job["overview"] = {"content": "", "error": None, "status": "running"}
    overview_cancel = threading.Event()
    _cancel_events[(job_id, -1)] = overview_cancel  # -1 = overview

    combined = "\n\n---\n\n".join(
        f"## {r['label']}\n{r['content']}" for r in done_results
    )
    full_prompt = f"以下是已完成维度的详细分析报告，请汇总成分析概览（已完成 {len(done_results)}/7 个维度）：\n\n{combined}"
    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    user_id = current_user.id

    def _run_overview():
        try:
            if job["is_demo"]:
                _log(f"[job={job_id}] overview demo mode start")
                time.sleep(0.5)
                if overview_cancel.is_set():
                    _log(f"[job={job_id}] overview cancelled")
                    with _lock:
                        job["overview"]["status"] = "idle"
                        _save_job(job_id)
                    return
                demo = (
                    f"**[演示模式 - 分析概览]**\n\n"
                    f"已基于 {len(done_results)} 个维度的分析结果生成概览。\n\n"
                    f"配置 API 接口信息后获取真实概览。"
                )
                with _lock:
                    job["overview"] = {"content": _render_md(demo), "error": None, "status": "done"}
                    _save_job(job_id)
                _log(f"[job={job_id}] overview demo mode done")
            else:
                _log(f"[job={job_id}] overview calling LLM with {len(done_results)} dimensions")
                try:
                    output = call_llm(
                        full_prompt, system_prompt=SYSTEM_ROLE,
                        api_base=sc.get("api_base") or None,
                        api_key=sc.get("api_key") or None,
                        model=sc.get("model") or None,
                        cancel_event=overview_cancel,
                    )
                    _log(f"[job={job_id}] overview LLM returned {len(output)} chars")
                    with _lock:
                        job["overview"] = {"content": _render_md(output), "error": None, "status": "done"}
                        _save_job(job_id)
                    _deduct_credits(CREDIT_COST["overview"], "生成分析概览", user_id=user_id)
                except RuntimeError:
                    _log(f"[job={job_id}] overview cancelled via RuntimeError")
                    with _lock:
                        job["overview"] = {"content": "", "error": None, "status": "idle"}
                        _save_job(job_id)
                except Exception as e:
                    _log(f"[job={job_id}] overview ERROR: {e}")
                    with _lock:
                        job["overview"] = {"content": "", "error": str(e), "status": "error"}
                        _save_job(job_id)
        finally:
            _cancel_events.pop((job_id, -1), None)

    threading.Thread(target=_run_overview, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/analyze", methods=["POST"])
@login_required
def api_analyze():
    data = request.get_json()
    if not data or "script_text" not in data:
        return jsonify({"error": "缺少 script_text 字段"}), 400
    try:
        script_text = parse_text(data["script_text"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    if not os.getenv("LLM_API_KEY") and not sc.get("api_key"):
        return jsonify({"error": "请先配置 API 接口信息"}), 500

    tasks = build_analysis_tasks(script_text)
    results = []
    for task in tasks:
        full_prompt = f"{task['instruction']}\n\n{task['user']}"
        try:
            output = call_llm(
                full_prompt, system_prompt=task["system"],
                api_base=sc.get("api_base") or None,
                api_key=sc.get("api_key") or None,
                model=sc.get("model") or None,
            )
            results.append({"label": task["label"], "content": _render_md(output), "error": None})
        except Exception as e:
            results.append({"label": task["label"], "content": "", "error": str(e)})
    return jsonify({"results": results})


@app.route("/api/translate", methods=["POST"])
@login_required
def api_translate():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "缺少 text 字段"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "文本为空"}), 400

    if current_user.credits < CREDIT_COST["translate"]:
        return jsonify({"error": f"积分不足，翻译需要 {CREDIT_COST['translate']} 积分"}), 402

    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    if not os.getenv("LLM_API_KEY") and not sc.get("api_key"):
        return jsonify({"error": "请先配置 API 接口信息"}), 500

    system = "你是一个专业的AI绘图提示词翻译器。将用户输入的中文提示词翻译成英文。要求：保持风格标签的专业性，逗号分隔，适合直接用于Midjourney/Stable Diffusion。只输出英文翻译结果，不要任何解释。"
    try:
        output = call_llm(
            text, system_prompt=system,
            api_base=sc.get("api_base") or None,
            api_key=sc.get("api_key") or None,
            model=sc.get("model") or None,
        )
        _deduct_credits(CREDIT_COST["translate"], "提示词翻译")
        return jsonify({"translated": output.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/dashboard")
@login_required
def dashboard():
    from datetime import date
    from models import DAILY_SIGNIN
    logs = (CreditLog.query
            .filter_by(user_id=current_user.id)
            .order_by(CreditLog.created_at.desc())
            .limit(50)
            .all())
    return render_template("dashboard.html",
        logs=logs,
        signin_bonus=DAILY_SIGNIN,
        today=date.today())


@app.errorhandler(413)
def too_large(e):
    return render_template("index.html", error="文件过大，上传限制为 10MB，请压缩或拆分后重试"), 413


def _deduct_credits(amount: int, description: str, user_id: int = None):
    if user_id is None:
        user_id = current_user.id
    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError("用户不存在")
    user.credits -= amount
    log = CreditLog(
        user_id=user.id,
        type="consume",
        amount=-amount,
        balance_after=user.credits,
        description=description,
    )
    db.session.add(log)
    db.session.commit()


def _render_md(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=["extra", "nl2br"],
    )


if __name__ == "__main__":
    import sys

    with app.app_context():
        db.create_all()

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
        app.run(host="0.0.0.0", debug=True, threaded=True)

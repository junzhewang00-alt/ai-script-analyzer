import os
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import time
from pathlib import Path

import markdown
import bleach
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
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB (for video uploads)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'instance' / 'app.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
(BASE_DIR / "instance").mkdir(exist_ok=True)

from models import db, User, CreditLog, get_analysis_cost, CREDIT_COST
from models import ReviewJob, ReviewResult, ReviewSummary, REVIEW_COST
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


from limiter import rate_limit


@app.before_request
def _hide_api_from_public():
    """对未登录用户隐藏 API/Pay 路由，直接返回 404（不暴露接口存在）"""
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return
    if not current_user.is_authenticated:
        if request.path.startswith("/api/") or (
            request.path.startswith("/pay/") and request.path not in ("/pay/notify", "/pay/webhook")
        ):
            return jsonify({"error": "Not Found"}), 404

UPLOAD_FOLDER = tempfile.gettempdir()
JOBS_DIR = BASE_DIR / ".jobs"
JOBS_DIR.mkdir(exist_ok=True)

# 服务端 API 配置存储 (key=sid, 不在 cookie 中传密钥)
_api_configs: dict = {}
_lock = threading.Lock()


class JobStore:
    """线程安全的任务存储，包装内存字典和取消事件。"""

    def __init__(self):
        self._jobs: dict = {}
        self._cancel_events: dict = {}

    def get(self, job_id: str):
        with _lock:
            return self._jobs.get(job_id)

    def set(self, job_id: str, job: dict):
        with _lock:
            self._jobs[job_id] = job

    def has(self, job_id: str) -> bool:
        with _lock:
            return job_id in self._jobs

    def update_result(self, job_id: str, index: int, result: dict):
        with _lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["results"][index] = result

    def update_overview(self, job_id: str, overview: dict):
        with _lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["overview"] = overview

    def set_cancel_event(self, job_id: str, index: int, event):
        with _lock:
            self._cancel_events[(job_id, index)] = event

    def get_cancel_event(self, job_id: str, index: int):
        with _lock:
            return self._cancel_events.get((job_id, index))

    def pop_cancel_event(self, job_id: str, index: int):
        with _lock:
            return self._cancel_events.pop((job_id, index), None)

    def cleanup_stale(self, ttl_seconds: int):
        """移除过期任务及其取消事件，返回被移除的 job_id 列表。"""
        now = time.time()
        with _lock:
            stale = [
                jid for jid, j in self._jobs.items()
                if now - j.get("created_at", 0) > ttl_seconds
            ]
            for jid in stale:
                del self._jobs[jid]
                keys_to_remove = [k for k in self._cancel_events if k[0] == jid]
                for k in keys_to_remove:
                    del self._cancel_events[k]
            return stale


_jobs_store = JobStore()


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
    job = _jobs_store.get(job_id)
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
        "user_id": job.get("user_id"),
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
        if _jobs_store.has(job_id):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if now - data.get("created_at", 0) > JOB_TTL_SECONDS:
                fp.unlink(missing_ok=True)
                continue
            _jobs_store.set(job_id, {
                "script_text": data.get("script_text", ""),
                "tasks": data.get("tasks", []),
                "results": data.get("results", []),
                "is_demo": data.get("is_demo", False),
                "total": data.get("total", 0),
                "script_preview": data.get("script_preview", ""),
                "char_count": data.get("char_count", 0),
                "overview": data.get("overview"),
                "created_at": data.get("created_at", time.time()),
                "user_id": data.get("user_id"),
            })
            count += 1
        except Exception:
            fp.unlink(missing_ok=True)
    if count:
        print(f"  已加载 {count} 个历史分析任务")


def _cleanup_stale_jobs():
    stale = _jobs_store.cleanup_stale(JOB_TTL_SECONDS)
    for jid in stale:
        _job_path(jid).unlink(missing_ok=True)


# 启动时加载历史任务
_load_jobs()


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/prompts")
@login_required
def prompts_studio():
    return render_template("prompts.html")


@app.route("/analyze", methods=["POST"])
@login_required
@rate_limit(10, 60)
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

    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    config_ok = bool(os.getenv("LLM_API_KEY") or sc.get("api_key"))
    tasks = build_analysis_tasks(script_text)

    job_id = uuid.uuid4().hex[:12]

    _jobs_store.set(job_id, {
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
        "user_id": current_user.id,
    })
    _save_job(job_id)

    return redirect(url_for("manual_analyze", job_id=job_id), code=303)


@app.route("/analyze/<job_id>")
@login_required
def manual_analyze(job_id):
    job = _jobs_store.get(job_id)

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
    job = _jobs_store.get(job_id)

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


def _mask_key(key: str) -> str:
    if not key or len(key) <= 8:
        return key[:4] + "****" if key else ""
    return key[:4] + "****" + key[-4:]


@app.route("/api/config", methods=["GET"])
@login_required
def api_config_get():
    is_local = request.remote_addr in ("127.0.0.1", "localhost", "::1")
    sid = _get_sid()
    server_config = _api_configs.get(sid, {})
    env_config = get_config() if is_local else {"api_base": "", "api_key": "", "model": ""}

    if server_config:
        merged = {
            "api_base": server_config.get("api_base", ""),
            "api_key": _mask_key(server_config.get("api_key", "")),
            "model": server_config.get("model", ""),
            "has_env_key": bool(env_config["api_key"]),
        }
    else:
        merged = {
            "api_base": env_config["api_base"],
            "api_key": _mask_key(env_config["api_key"]),
            "model": env_config["model"],
            "has_env_key": bool(env_config["api_key"]),
        }
    return jsonify(merged)


@app.route("/api/config", methods=["POST"])
@login_required
def api_config_save():
    data = request.get_json() or {}
    sid = _get_sid()
    new_key = data.get("api_key", "").strip()
    if "****" in new_key:
        new_key = _api_configs.get(sid, {}).get("api_key", new_key)
    _api_configs[sid] = {
        "api_base": data.get("api_base", "").strip(),
        "api_key": new_key,
        "model": data.get("model", "").strip(),
    }
    return jsonify({"ok": True})


@app.route("/api/job/<job_id>/run/<int:index>", methods=["POST"])
@login_required
@rate_limit(30, 60)
def run_single_dimension(job_id, index):
    # 单个维度积分检查
    if current_user.credits < CREDIT_COST["single_dimension"]:
        return jsonify({"error": f"积分不足，单个维度分析需要 {CREDIT_COST['single_dimension']} 积分"}), 402
    job = _jobs_store.get(job_id)

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
    _jobs_store.set_cancel_event(job_id, index, cancel_event)
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
                _jobs_store.update_result(job_id, index, {
                    "label": task["label"],
                    "content": _render_md(demo),
                    "error": None,
                    "status": "done",
                })
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
                    _jobs_store.update_result(job_id, index, {
                        "label": task["label"],
                        "content": _render_md(output),
                        "error": None,
                        "status": "done",
                    })
                    _save_job(job_id)
                    _deduct_credits(CREDIT_COST["single_dimension"], f"单维度分析: {task['label']}", user_id=user_id)
                except RuntimeError as e:
                    if "分析已取消" in str(e):
                        _log(f"[job={job_id}] dim={index} ({task['label']}) cancelled by user")
                        _jobs_store.update_result(job_id, index, {
                            "label": task["label"],
                            "content": "",
                            "error": None,
                            "status": "idle",
                        })
                        _save_job(job_id)
                    else:
                        _log(f"[job={job_id}] dim={index} ({task['label']}) RuntimeError: {e}")
                        _jobs_store.update_result(job_id, index, {
                            "label": task["label"],
                            "content": "",
                            "error": "分析服务暂时不可用，请稍后重试",
                            "status": "error",
                        })
                        _save_job(job_id)
                except Exception as e:
                    _log(f"[job={job_id}] dim={index} ({task['label']}) ERROR: {e}")
                    _jobs_store.update_result(job_id, index, {
                        "label": task["label"],
                        "content": "",
                        "error": "分析服务暂时不可用，请稍后重试",
                        "status": "error",
                    })
                    _save_job(job_id)
        finally:
            _jobs_store.pop_cancel_event(job_id, index)

    threading.Thread(target=_run_one, daemon=True).start()
    _log(f"[job={job_id}] dim={index} thread started")

    return jsonify({"ok": True})


@app.route("/api/job/<job_id>/cancel/<int:index>", methods=["POST"])
@login_required
def cancel_dimension(job_id, index):
    job = _jobs_store.get(job_id)

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
    ev = _jobs_store.get_cancel_event(job_id, index)
    if ev:
        ev.set()

    return jsonify({"ok": True})


@app.route("/api/job/<job_id>/overview", methods=["POST"])
@login_required
@rate_limit(10, 60)
def run_overview(job_id):
    if current_user.credits < CREDIT_COST["overview"]:
        return jsonify({"error": f"积分不足，概览生成需要 {CREDIT_COST['overview']} 积分"}), 402

    job = _jobs_store.get(job_id)

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
    _jobs_store.set_cancel_event(job_id, -1, overview_cancel)  # -1 = overview

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
                    _jobs_store.update_overview(job_id, {"content": job.get("overview", {}).get("content", ""), "error": None, "status": "idle"})
                    _save_job(job_id)
                    return
                demo = (
                    f"**[演示模式 - 分析概览]**\n\n"
                    f"已基于 {len(done_results)} 个维度的分析结果生成概览。\n\n"
                    f"配置 API 接口信息后获取真实概览。"
                )
                _jobs_store.update_overview(job_id, {"content": _render_md(demo), "error": None, "status": "done"})
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
                    _jobs_store.update_overview(job_id, {"content": _render_md(output), "error": None, "status": "done"})
                    _save_job(job_id)
                    _deduct_credits(CREDIT_COST["overview"], "生成分析概览", user_id=user_id)
                except RuntimeError as e:
                    if "分析已取消" in str(e):
                        _log(f"[job={job_id}] overview cancelled by user")
                        _jobs_store.update_overview(job_id, {"content": "", "error": None, "status": "idle"})
                        _save_job(job_id)
                    else:
                        _log(f"[job={job_id}] overview RuntimeError: {e}")
                        with _lock:
                            job["overview"] = {"content": "", "error": "概览生成失败，请稍后重试", "status": "error"}
                            _save_job(job_id)
                except Exception as e:
                    _log(f"[job={job_id}] overview error: {e}")
                    with _lock:
                        job["overview"] = {"content": "", "error": "概览生成失败，请稍后重试", "status": "error"}
                        _save_job(job_id)
        finally:
            _jobs_store.pop_cancel_event(job_id, -1)

    threading.Thread(target=_run_overview, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/analyze", methods=["POST"])
@login_required
@rate_limit(5, 60)
def api_analyze():
    data = request.get_json()
    if not data or "script_text" not in data:
        return jsonify({"error": "缺少 script_text 字段"}), 400
    try:
        script_text = parse_text(data["script_text"])
    except ValueError:
        return jsonify({"error": "文件解析失败，请检查文件格式"}), 400

    # 积分校验和扣减
    cost = get_analysis_cost(len(script_text))
    if current_user.credits < cost:
        return jsonify({"error": f"积分不足，需要 {cost} 积分，当前余额 {current_user.credits}"}), 402
    _deduct_credits(cost, f"一键全维度分析 ({len(script_text)}字)")

    sid = _get_sid()
    sc = _api_configs.get(sid, {})
    if not os.getenv("LLM_API_KEY") and not sc.get("api_key"):
        return jsonify({"error": "请先配置 API 接口信息"}), 500
    tasks = build_analysis_tasks(script_text)
    results = [None] * len(tasks)  # preserve order

    def _run_task(index: int, task: dict):
        full_prompt = f"{task['instruction']}\n\n{task['user']}"
        try:
            output = call_llm(
                full_prompt, system_prompt=task["system"],
                api_base=sc.get("api_base") or None,
                api_key=sc.get("api_key") or None,
                model=sc.get("model") or None,
            )
            return index, {"label": task["label"], "content": _render_md(output), "error": None}
        except Exception as e:
            _log(f"Analysis error ({task['label']}): {e}")
            return index, {"label": task["label"], "content": "", "error": "分析服务暂时不可用，请稍后重试"}

    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = {
            executor.submit(_run_task, i, task): i
            for i, task in enumerate(tasks)
        }
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    return jsonify({"results": results})


@app.route("/api/translate", methods=["POST"])
@login_required
@rate_limit(10, 60)
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
        _log(f"Translate error: {e}")
        return jsonify({"error": "翻译服务暂时不可用，请稍后重试"}), 500


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


@app.route("/api/dashboard/stats")
@login_required
def api_dashboard_stats():
    from datetime import date, datetime, time as datetime_time, timedelta
    from sqlalchemy import case, func

    range_days = request.args.get("range", "7")

    allowed_ranges = {"7": 7, "30": 30, "all": None}
    days = allowed_ranges.get(range_days, 7)
    since = None
    if days is not None:
        since_date = date.today() - timedelta(days=days)
        since = datetime.combine(since_date, datetime_time.min)

    # KPI 计算（全量）
    kpi_row = db.session.query(
        func.coalesce(func.sum(case((CreditLog.amount < 0, 1), else_=0)), 0),
        func.coalesce(func.sum(case((CreditLog.amount < 0, -CreditLog.amount), else_=0)), 0),
        func.coalesce(func.sum(case((CreditLog.amount > 0, CreditLog.amount), else_=0)), 0),
    ).filter(CreditLog.user_id == current_user.id).one()
    total_analyses, total_spent, total_earned = (int(v or 0) for v in kpi_row)

    range_query = db.session.query(CreditLog).filter(CreditLog.user_id == current_user.id)
    if since is not None:
        range_query = range_query.filter(CreditLog.created_at >= since)

    # 每日消费/获取趋势（范围内）
    day_expr = func.date(CreditLog.created_at)
    trend_rows = (
        range_query.with_entities(
            day_expr.label("day"),
            func.coalesce(func.sum(case((CreditLog.amount < 0, -CreditLog.amount), else_=0)), 0).label("spent"),
            func.coalesce(func.sum(case((CreditLog.amount > 0, CreditLog.amount), else_=0)), 0).label("earned"),
        )
        .group_by(day_expr)
        .order_by(day_expr)
        .all()
    )

    trend = [
        {"date": day, "spent": int(spent or 0), "earned": int(earned or 0)}
        for day, spent, earned in trend_rows
    ]

    # 分析类型分布
    type_names = {
        "full_analysis": "完整分析",
        "single_dimension": "单项分析",
        "overview": "概览",
        "translate": "翻译",
        "signin": "签到",
    }
    type_rows = (
        range_query.with_entities(CreditLog.type, func.count(CreditLog.id))
        .filter(CreditLog.amount < 0)
        .group_by(CreditLog.type)
        .order_by(func.count(CreditLog.id).desc(), CreditLog.type)
        .all()
    )
    type_distribution = [
        {"name": type_names.get(log_type, log_type), "value": count}
        for log_type, count in type_rows
    ]

    return jsonify({
        "kpis": {
            "credits": current_user.credits,
            "total_analyses": total_analyses,
            "total_spent": total_spent,
            "total_earned": total_earned,
        },
        "trend": trend,
        "type_distribution": type_distribution,
    })


@app.errorhandler(413)
def too_large(e):
    return render_template("index.html", error="文件过大，上传限制为 10MB，请压缩或拆分后重试"), 413


def _deduct_credits(amount: int, description: str, user_id: int = None):
    if user_id is None:
        user_id = current_user.id
    with app.app_context():
        user = User.query.filter_by(id=user_id).with_for_update().first()
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
    html = markdown.markdown(
        text,
        extensions=["extra", "nl2br"],
    )
    return bleach.clean(
        html,
        tags=["h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr",
              "ul", "ol", "li", "blockquote", "pre", "code",
              "strong", "em", "a", "table", "thead", "tbody", "tr", "th", "td",
              "img", "span", "div"],
        attributes={"a": ["href", "title"], "img": ["src", "alt"], "th": ["align"], "td": ["align"]},
        strip=True,
    )


# ── AI Chat (侧边栏助手) ──

@app.route("/api/chat", methods=["POST"])
@login_required
@rate_limit(20, 60)
def api_chat():
    """侧边栏 AI 助手对话"""
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"reply": "请输入内容"})

    try:
        from analyzer.llm import call_llm, get_config
        sid = _get_sid()
        sc = _api_configs.get(sid, {})

        chat_prompt = (
            "【角色】你是「AI 短剧分析器」内置助手，专门解答短剧创作与分析相关问题。\n\n"
            "【能力范围】剧本分析/审核流程/积分使用/提示词技巧/短剧行业知识\n\n"
            "【规则】\n"
            "• 回答简洁，3-5 句话以内\n"
            "• 如果不确定，直接说「建议咨询专业编剧」\n"
            "• 不讨论与短剧无关的话题\n\n"
            f"用户: {user_message}\n助手:"
        )

        reply = call_llm(
            prompt=chat_prompt,
            system_prompt=SYSTEM_ROLE,
        )
        return jsonify({"reply": reply or "抱歉，我暂时无法回复，请稍后再试。"})
    except Exception as e:
        _log(f"api_chat error: {e}")
        return jsonify({"reply": "AI 助手暂不可用，请稍后再试。"})


REVIEW_VIDEO_FOLDER = BASE_DIR / "uploads" / "videos"
REVIEW_AUDIO_FOLDER = BASE_DIR / "uploads" / "audio"
REVIEW_VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
REVIEW_AUDIO_FOLDER.mkdir(parents=True, exist_ok=True)

# 审核任务存储
_review_lock = threading.Lock()
_review_jobs: dict = {}
_review_cancel_events: dict = {}


# ── 视频审核页面路由 ──

@app.route("/review")
@login_required
def review_page():
    """审核页面"""
    return render_template("review.html")


@app.route("/api/review", methods=["POST"])
@login_required
@rate_limit(5, 60)
def api_create_review():
    """创建审核任务"""
    if current_user.credits < REVIEW_COST:
        return jsonify({"error": f"积分不足，需要 {REVIEW_COST} 积分"}), 402

    video_file = request.files.get("video")
    script_text = request.form.get("script_text", "").strip()

    if not video_file or not video_file.filename:
        return jsonify({"error": "请上传视频文件"}), 400

    import uuid, os

    # 保存视频
    ext = os.path.splitext(video_file.filename)[1] or ".mp4"
    video_name = f"{uuid.uuid4().hex}{ext}"
    video_path = REVIEW_VIDEO_FOLDER / video_name
    video_file.save(str(video_path))

    # 创建数据库记录
    job = ReviewJob(
        user_id=current_user.id,
        video_filename=video_file.filename,
        video_path=str(video_path),
        script_text=script_text,
        status="pending",
    )
    db.session.add(job)
    db.session.commit()

    job_id = job.id

    # 扣积分
    try:
        _deduct_credits(REVIEW_COST,
                        f"视频审核: {video_file.filename[:30]}",
                        user_id=current_user.id)
    except Exception as e:
        db.session.delete(job)
        db.session.commit()
        if video_path.exists():
            video_path.unlink()
        return jsonify({"error": f"积分扣除失败: {e}"}), 500

    # 启动后台审核线程
    cancel_event = threading.Event()
    with _review_lock:
        _review_cancel_events[job_id] = cancel_event

    def _run_review_async():
        from reviewer.orchestrator import ReviewOrchestrator
        _log(f"[review job={job_id}] Thread started")
        orchestrator = ReviewOrchestrator()
        try:
            with app.app_context():
                job = db.session.get(ReviewJob, job_id)
                if job:
                    job.status = "running"
                    db.session.commit()
                _log(f"[review job={job_id}] Running pipeline")

                result = orchestrator.run_review(
                    job_id=job_id,
                    video_path=str(video_path),
                    script_text=script_text,
                    cancel_event=cancel_event,
                    flask_app=app,
                )
                _log(f"[review job={job_id}] Pipeline done: success={result.get('success')}")
        except Exception as e:
            _log(f"[review job={job_id}] ERROR: {e}")
            import traceback
            _log(f"[review job={job_id}] Traceback: {traceback.format_exc()}")
            with app.app_context():
                job = db.session.get(ReviewJob, job_id)
                if job:
                    job.status = "failed"
                    db.session.commit()
        finally:
            with _review_lock:
                _review_cancel_events.pop(job_id, None)

    t = threading.Thread(target=_run_review_async, daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/api/review/<int:job_id>")
@login_required
def api_get_review(job_id):
    """获取审核任务状态和结果"""
    job = db.session.get(ReviewJob, job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "无权访问"}), 403

    results = {}
    for r in job.results:
        try:
            results[r.dimension] = json.loads(r.result_json)
        except (json.JSONDecodeError, TypeError):
            results[r.dimension] = {}

    summary = None
    if job.summary:
        summary = {
            "overall_score": job.summary.overall_score,
            "opinion": job.summary.ai_opinion,
            "passed": job.summary.passed,
        }

    with _review_lock:
        cancel_event = _review_cancel_events.get(job_id)
    can_cancel = cancel_event is not None and not cancel_event.is_set()

    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "video_filename": job.video_filename,
        "script_text": job.script_text[:500],
        "results": results,
        "summary": summary,
        "can_cancel": can_cancel,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    })


@app.route("/api/review/latest")
@login_required
def api_latest_review():
    """获取当前用户最近一次完成的审核"""
    job = (ReviewJob.query
           .filter_by(user_id=current_user.id)
           .filter(ReviewJob.status == "completed")
           .order_by(ReviewJob.id.desc())
           .first())
    if not job:
        return jsonify({"found": False})

    results = {}
    for r in job.results:
        try:
            results[r.dimension] = json.loads(r.result_json)
        except (json.JSONDecodeError, TypeError):
            results[r.dimension] = {}

    summary = None
    if job.summary:
        summary = {
            "overall_score": job.summary.overall_score,
            "opinion": job.summary.ai_opinion,
            "passed": job.summary.passed,
        }

    return jsonify({
        "found": True,
        "job_id": job.id,
        "status": job.status,
        "video_filename": job.video_filename,
        "results": results,
        "summary": summary,
    })


@app.route("/api/review/<int:job_id>/cancel", methods=["POST"])
@login_required
def api_cancel_review(job_id):
    """取消运行中的审核"""
    job = db.session.get(ReviewJob, job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "无权操作"}), 403

    with _review_lock:
        cancel_event = _review_cancel_events.get(job_id)
    if cancel_event and not cancel_event.is_set():
        cancel_event.set()
        return jsonify({"status": "cancelling"})
    return jsonify({"error": "任务不在运行中或已结束"}), 400


@app.route("/api/review/<int:job_id>/run/<dimension>", methods=["POST"])
@login_required
def api_run_dimension(job_id, dimension):
    """手动触发单个维度分析（可选：emotion/dialogue/tech）"""
    job = db.session.get(ReviewJob, job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "无权操作"}), 403
    if dimension not in ("emotion", "dialogue", "tech"):
        return jsonify({"error": f"未知维度: {dimension}"}), 400

    with _review_lock:
        cancel_event = _review_cancel_events.get(job_id)

    def _run_single():
        from reviewer.orchestrator import ReviewOrchestrator
        orchestrator = ReviewOrchestrator()
        try:
            with app.app_context():
                vid = job.video_path
                scr = job.script_text
                result_data = {}

                if dimension == "tech":
                    result_data = orchestrator.video.analyze_technical(vid)
                elif dimension == "emotion":
                    result_data = orchestrator.qwen.analyze_emotion(vid)
                elif dimension == "dialogue":
                    audio = orchestrator.video.extract_audio(vid)
                    asr = orchestrator.asr.transcribe(str(audio)) if audio else {"text": ""}
                    result_data = orchestrator.claude.compare_dialogue(scr, asr.get("text", ""))

                # 保存
                existing = ReviewResult.query.filter_by(
                    job_id=job_id, dimension=dimension,
                ).first()
                if existing:
                    existing.result_json = json.dumps(result_data, ensure_ascii=False)
                    existing.issues_count = len(result_data.get("issues", []))
                else:
                    db.session.add(ReviewResult(
                        job_id=job_id,
                        dimension=dimension,
                        result_json=json.dumps(result_data, ensure_ascii=False),
                        issues_count=len(result_data.get("issues", [])),
                    ))
                db.session.commit()

        except Exception as e:
            with app.app_context():
                db_job = db.session.get(ReviewJob, job_id)
                if db_job:
                    db_job.status = "failed"
                    db.session.commit()

    t = threading.Thread(target=_run_single, daemon=True)
    t.start()

    return jsonify({"status": "started", "dimension": dimension})


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
        app.run(host="127.0.0.1", debug=True, threaded=True)

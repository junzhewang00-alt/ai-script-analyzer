"""
Runway 共享配置 — 被 runway_browser.py、runway_api.py、app.py 共同引用。
单点维护所有常量、默认值和路径。
"""
import json
import os
from pathlib import Path

RUNWAY_URL = "https://app.runwayml.com"

# 各模型支持的时长（秒），用于智能回退
MODEL_DURATIONS = {
    "seedance2": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "seedance":  [4, 5, 6, 7, 8, 9, 10],
    "gen4-turbo": [2, 3, 4, 5, 6, 7, 8, 9, 10],
    "gen4":      [2, 3, 4, 5, 6, 7, 8, 9, 10],
    "gen4.5":    [2, 3, 4, 5, 6, 7, 8, 9, 10],
    "gen3-alpha": [4, 5, 8, 10],
    "gen3-turbo": [4, 5, 8, 10],
    "kling":     [4, 5, 8, 10],
    "kling3":    [4, 5, 8, 10],
    "veo":       [4, 5, 8, 10],
    "veo3":      [4, 5, 8, 10],
}

# 模型显示名映射（浏览器模式用）
MODEL_LABELS = {
    "gen4-turbo": "Gen-4 Turbo",
    "gen4": "Gen-4",
    "gen4.5": "Gen-4.5",
    "gen3-alpha": "Gen-3 Alpha",
    "gen3-turbo": "Gen-3 Alpha Turbo",
    "seedance": "Seedance",
    "seedance2": "Seedance 2.0",
    "kling": "Kling",
    "kling3": "Kling 3.0",
    "veo": "Veo",
    "veo3": "Veo 3",
}

RUNWAY_SLOTS = 10
MAX_IMAGES_PER_JOB = 4

DEFAULT_MODEL = "gen4.5"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "720p"


def get_paths():
    """返回数据存储目录下所有路径（跨平台）"""
    # 优先用项目目录下的 data/，其次用 Desktop/runway-bot
    project_data = Path(__file__).resolve().parent / "data"
    if project_data.exists():
        profile_dir = project_data
    else:
        profile_dir = Path.home() / "Desktop" / "runway-bot"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return {
        "config": profile_dir / "jobs.json",
        "state": profile_dir / "state.json",
        "chrome_profile": profile_dir / "chrome_data",
    }


def default_job_template(job_id):
    """返回一个新 job 的默认字典"""
    return {
        "id": job_id, "prompt": "", "image_paths": [],
        "model": DEFAULT_MODEL, "duration": DEFAULT_DURATION,
        "resolution": DEFAULT_RESOLUTION,
        "task_id": None, "status": "pending",
        "result_url": None, "error": None,
        "created_at": None, "completed_at": None,
    }


def default_jobs():
    """返回 RUNWAY_SLOTS 个默认 job 的列表"""
    return [default_job_template(i) for i in range(1, RUNWAY_SLOTS + 1)]


def load_config(path):
    """加载 JSON 配置，自动补齐缺失字段和槽位（向后兼容）"""
    if not path.exists():
        return {"jobs": default_jobs()}
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    template = default_job_template(0)
    for job in cfg.get("jobs", []):
        for key in template:
            if key not in job:
                job[key] = template[key]
        # 向后兼容：旧的 image_path 字符串 → 新 image_paths 数组
        if "image_path" in job and not job.get("image_paths"):
            old = job.pop("image_path")
            job["image_paths"] = [old] if old else []
        job.setdefault("image_paths", [])
    existing_ids = {j["id"] for j in cfg.get("jobs", [])}
    for d in default_jobs():
        if d["id"] not in existing_ids:
            cfg["jobs"].append(d)
    cfg["jobs"] = sorted(cfg["jobs"], key=lambda j: j["id"])
    return cfg


def save_config(path, cfg):
    """原子写入：先写临时文件，再替换，防止并发脏读"""
    tmp = path.with_suffix(".tmp")
    # 删除可能存在但权限不对的旧临时文件
    if tmp.exists():
        try:
            tmp.unlink()
        except PermissionError:
            pass
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def safe_save_config(path, cfg):
    """安全写入：重新读取磁盘文件，保留用户在此期间编辑的字段（prompt/image/model等），
    只覆盖子进程负责的状态字段。解决 Web UI 保存与子进程之间的读写竞态。"""
    status_fields = {"status", "task_id", "result_url", "error", "created_at", "completed_at"}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            disk_cfg = json.load(f)
        disk_jobs = {j["id"]: j for j in disk_cfg.get("jobs", [])}
        for job in cfg.get("jobs", []):
            disk_job = disk_jobs.get(job["id"])
            if disk_job:
                for key in list(job.keys()):
                    if key not in status_fields:
                        job[key] = disk_job.get(key, job[key])
    save_config(path, cfg)


STUCK_MINUTES = 45


def auto_fail_stuck_jobs(cfg):
    """将超过 STUCK_MINUTES 的 submitted/processing 任务自动标记为 failed"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    changed = False
    for job in cfg.get("jobs", []):
        if job.get("status") in ("submitted", "processing") and job.get("created_at"):
            try:
                created = datetime.fromisoformat(job["created_at"])
                if (now - created).total_seconds() > STUCK_MINUTES * 60:
                    job["status"] = "failed"
                    job["error"] = f"任务超时 (>{STUCK_MINUTES}分钟)"
                    changed = True
            except (ValueError, TypeError):
                pass
    return changed

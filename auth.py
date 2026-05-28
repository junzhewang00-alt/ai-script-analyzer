from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, CreditLog, REGISTER_BONUS, DAILY_SIGNIN
from limiter import _limiter

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        ip = request.remote_addr or "127.0.0.1"
        email = request.form.get("email", "").strip().lower()
        if not _limiter.is_allowed(f"rl:/auth/login:{ip}:{email}", 10, 60):
            flash("请求过于频繁，请稍后再试", "error")
            return render_template("login.html")
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            _limiter.is_allowed(f"rl:/auth/login:{ip}:{email}", 0, 1)  # reset on success
            login_user(user, remember=request.form.get("remember") == "1")
            flash("登录成功", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("index"))
        flash("邮箱或密码错误", "error")
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        ip = request.remote_addr or "127.0.0.1"
        email = request.form.get("email", "").strip().lower()
        if not _limiter.is_allowed(f"rl:/auth/register:{ip}:{email}", 5, 300):
            flash("请求过于频繁，请稍后再试", "error")
            return render_template("register.html")
        password = request.form.get("password", "")
        nickname = request.form.get("nickname", "").strip()

        if not email or "@" not in email:
            flash("请输入有效的邮箱地址", "error")
        elif len(password) < 6:
            flash("密码至少 6 位", "error")
        elif User.query.filter_by(email=email).first():
            flash("该邮箱已注册", "error")
        else:
            user = User(
                email=email,
                password_hash=generate_password_hash(password),
                nickname=nickname or email.split("@")[0],
                credits=REGISTER_BONUS,
            )
            db.session.add(user)
            db.session.flush()
            log = CreditLog(
                user_id=user.id,
                type="signup_bonus",
                amount=REGISTER_BONUS,
                balance_after=REGISTER_BONUS,
                description="新用户注册赠送积分",
            )
            db.session.add(log)
            db.session.commit()
            login_user(user)
            flash(f"注册成功！已赠送 {REGISTER_BONUS} 积分", "success")
            return redirect(url_for("index"))
    return render_template("register.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))


@auth_bp.route("/signin", methods=["POST"])
@login_required
def signin():
    today = date.today()
    if current_user.last_signin_date == today:
        return jsonify({"ok": False, "error": "今日已签到"}), 400

    ip = request.remote_addr or "127.0.0.1"
    if not _limiter.is_allowed(f"rl:/auth/signin:{ip}", 20, 60):
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    current_user.last_signin_date = today
    current_user.credits += DAILY_SIGNIN
    log = CreditLog(
        user_id=current_user.id,
        type="daily_signin",
        amount=DAILY_SIGNIN,
        balance_after=current_user.credits,
        description="每日签到奖励",
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True, "credits": current_user.credits})

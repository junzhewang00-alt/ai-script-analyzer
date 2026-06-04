from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

# 积分常量
REGISTER_BONUS = 200
DAILY_SIGNIN = 5
CREDIT_COST = {
    "full_analysis_5000": 12,
    "full_analysis_15000": 25,
    "full_analysis_30000": 40,
    "single_dimension": 5,
    "overview": 5,
    "translate": 2,
}

REVIEW_COST = 5  # 每次视频审核消耗积分

RECHARGE_PACKAGES = [
    {"amount_yuan": 10, "credits": 100, "label": "基础包", "bonus": ""},
    {"amount_yuan": 20, "credits": 220, "label": "进阶包 +10%", "bonus": "+20积分"},
    {"amount_yuan": 50, "credits": 600, "label": "专业包 +20%", "bonus": "+100积分"},
    {"amount_yuan": 100, "credits": 1300, "label": "企业包 +30%", "bonus": "+300积分"},
]


def get_recharge_packages():
    return RECHARGE_PACKAGES


def get_analysis_cost(char_count: int) -> int:
    if char_count <= 5000:
        return CREDIT_COST["full_analysis_5000"]
    elif char_count <= 15000:
        return CREDIT_COST["full_analysis_15000"]
    else:
        return CREDIT_COST["full_analysis_30000"]


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    nickname = db.Column(db.String(60), default="")
    credits = db.Column(db.Integer, default=REGISTER_BONUS)
    last_signin_date = db.Column(db.Date)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def display_name(self):
        return self.nickname or self.email.split("@")[0]


class CreditLog(db.Model):
    __tablename__ = "credit_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    type = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # 正=获得, 负=消耗
    balance_after = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("credit_logs", lazy="dynamic"))


class RechargeOrder(db.Model):
    __tablename__ = "recharge_order"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    out_trade_no = db.Column(db.String(32), unique=True, nullable=False)
    pay_channel = db.Column(db.String(16), default="stripe")  # stripe / payjs
    payjs_order_id = db.Column(db.String(32))
    amount_fen = db.Column(db.Integer, nullable=False)
    amount_yuan = db.Column(db.Integer, nullable=False)
    credits = db.Column(db.Integer, nullable=False)  # 获得的积分数
    body = db.Column(db.String(64))
    status = db.Column(db.String(16), default="pending")  # pending / paid / failed
    payjs_raw = db.Column(db.Text)  # 回调原始数据 JSON
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    paid_at = db.Column(db.DateTime)

    user = db.relationship("User", backref=db.backref("recharge_orders", lazy="dynamic"))


# ---- 视频审核系统模型 ----


class ReviewJob(db.Model):
    """视频审核任务"""
    __tablename__ = "review_job"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    video_filename = db.Column(db.String(256), default="")
    video_path = db.Column(db.String(512), default="")
    script_text = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="pending")  # pending / running / completed / failed
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("review_jobs", lazy="dynamic"))
    results = db.relationship("ReviewResult", backref="job", lazy="dynamic",
                              cascade="all, delete-orphan")


class ReviewResult(db.Model):
    """单个维度的审核结果"""
    __tablename__ = "review_result"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("review_job.id"), nullable=False, index=True)
    dimension = db.Column(db.String(20), nullable=False)  # emotion / dialogue / tech
    result_json = db.Column(db.Text, default="{}")
    issues_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ReviewSummary(db.Model):
    """审核汇总（综合评分 + AI 意见）"""
    __tablename__ = "review_summary"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("review_job.id"), unique=True,
                       nullable=False, index=True)
    overall_score = db.Column(db.Integer, default=0)  # 0-100
    ai_opinion = db.Column(db.Text, default="")
    passed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    job = db.relationship("ReviewJob", backref=db.backref("summary", uselist=False))

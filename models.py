from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

# 积分常量
REGISTER_BONUS = 30
DAILY_SIGNIN = 5
CREDIT_COST = {
    "full_analysis_5000": 10,
    "full_analysis_15000": 20,
    "full_analysis_30000": 35,
    "single_dimension": 5,
    "overview": 5,
    "translate": 2,
}


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("credit_logs", lazy="dynamic"))

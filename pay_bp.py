import os
import json
import uuid
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from models import db, CreditLog, RechargeOrder, User
from xorpay import create_native_order, verify_notify, get_recharge_packages

pay_bp = Blueprint("pay", __name__, url_prefix="/pay")


def _get_xorpay_config():
    return {
        "aid": os.getenv("XORPAY_AID", ""),
        "secret": os.getenv("XORPAY_SECRET", ""),
        "notify_url": os.getenv("XORPAY_NOTIFY_URL", ""),
    }


def _credits_for_yuan(amount_yuan: int) -> int:
    """金额(元) 对应积分"""
    packages = {p["amount_yuan"]: p["credits"] for p in get_recharge_packages()}
    return packages.get(amount_yuan, amount_yuan * 10)


@pay_bp.route("/recharge")
@login_required
def recharge():
    config = _get_xorpay_config()
    configured = bool(config["aid"] and config["secret"])
    return render_template(
        "recharge.html",
        configured=configured,
        packages=get_recharge_packages(),
    )


@pay_bp.route("/create", methods=["POST"])
@login_required
def create_order():
    config = _get_xorpay_config()
    if not config["aid"] or not config["secret"]:
        return jsonify({"ok": False, "error": "支付接口未配置，请联系管理员"}), 400

    data = request.get_json() or {}
    amount_yuan = data.get("amount_yuan", 0)
    if isinstance(amount_yuan, str):
        amount_yuan = int(amount_yuan)
    if amount_yuan not in [p["amount_yuan"] for p in get_recharge_packages()]:
        return jsonify({"ok": False, "error": "无效的充值金额"}), 400

    credits = _credits_for_yuan(amount_yuan)
    out_trade_no = datetime.utcnow().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]

    order = RechargeOrder(
        user_id=current_user.id,
        out_trade_no=out_trade_no,
        amount_fen=amount_yuan * 100,
        amount_yuan=amount_yuan,
        credits=credits,
        body=f"AI剧本分析器充值 {amount_yuan}元",
        status="pending",
    )
    db.session.add(order)
    db.session.commit()

    result = create_native_order(
        aid=config["aid"],
        app_secret=config["secret"],
        name=f"{amount_yuan}元充值",
        price=f"{amount_yuan}.00",
        order_id=out_trade_no,
        notify_url=config["notify_url"],
        order_uid=current_user.email,
    )

    if result.get("status") != "ok":
        order.status = "failed"
        order.payjs_raw = json.dumps(result, ensure_ascii=False)
        db.session.commit()
        return jsonify({"ok": False, "error": result.get("error", result.get("status", "创建订单失败"))}), 500

    order.payjs_order_id = result.get("aoid", "")
    order.payjs_raw = json.dumps(result, ensure_ascii=False)
    db.session.commit()

    return jsonify({
        "ok": True,
        "out_trade_no": out_trade_no,
        "code_url": result.get("info", {}).get("qr", ""),
        "amount_yuan": amount_yuan,
        "credits": credits,
    })


@pay_bp.route("/notify", methods=["POST"])
def notify():
    """XorPay 异步回调 — 不要求登录，无 CSRF"""
    config = _get_xorpay_config()
    if not config["aid"] or not config["secret"]:
        return "config error", 500

    data = request.form.to_dict()
    aoid = data.get("aoid", "")
    order_id = data.get("order_id", "")
    pay_price = data.get("pay_price", "")
    pay_time = data.get("pay_time", "")
    received_sign = data.get("sign", "")

    expected_sign = verify_notify(aoid, order_id, pay_price, pay_time, config["secret"])
    if received_sign.lower() != expected_sign.lower():
        return "sign error", 403

    order = RechargeOrder.query.filter_by(out_trade_no=order_id).first()
    if order is None:
        return "order not found", 404

    if order.status == "paid":
        return "success"

    order.status = "paid"
    order.payjs_order_id = aoid
    order.payjs_raw = json.dumps(data, ensure_ascii=False)
    order.paid_at = datetime.utcnow()

    user = User.query.get(order.user_id)
    if user:
        user.credits += order.credits
        log = CreditLog(
            user_id=user.id,
            type="recharge",
            amount=order.credits,
            balance_after=user.credits,
            description=f"充值 {order.amount_yuan} 元",
        )
        db.session.add(log)

    db.session.commit()
    return "success"


@pay_bp.route("/status/<out_trade_no>")
@login_required
def order_status(out_trade_no):
    order = RechargeOrder.query.filter_by(
        out_trade_no=out_trade_no,
        user_id=current_user.id,
    ).first()
    if order is None:
        return jsonify({"error": "订单不存在"}), 404
    return jsonify({
        "status": order.status,
        "amount_yuan": order.amount_yuan,
        "credits": order.credits,
    })

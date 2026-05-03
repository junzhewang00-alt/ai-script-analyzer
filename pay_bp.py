import os
import json
import uuid
from datetime import datetime

import stripe
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from models import db, CreditLog, RechargeOrder, User
from stripe_pay import create_payment_intent, retrieve_payment_intent, get_recharge_packages

pay_bp = Blueprint("pay", __name__, url_prefix="/pay")


def _get_stripe_config():
    return {
        "secret_key": os.getenv("STRIPE_SECRET_KEY", ""),
        "publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        "webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET", ""),
    }


def _credits_for_yuan(amount_yuan: int) -> int:
    packages = {p["amount_yuan"]: p["credits"] for p in get_recharge_packages()}
    return packages.get(amount_yuan, amount_yuan * 10)


@pay_bp.route("/recharge")
@login_required
def recharge():
    config = _get_stripe_config()
    configured = bool(config["secret_key"] and config["publishable_key"])
    return render_template(
        "recharge.html",
        configured=configured,
        packages=get_recharge_packages(),
        stripe_publishable_key=config["publishable_key"],
    )


@pay_bp.route("/create", methods=["POST"])
@login_required
def create_order():
    config = _get_stripe_config()
    if not config["secret_key"]:
        return jsonify({"ok": False, "error": "支付接口未配置"}), 400

    stripe.api_key = config["secret_key"]

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

    try:
        intent = create_payment_intent(amount_yuan, out_trade_no, current_user.id)
        order.payjs_order_id = intent.id
        db.session.commit()
        return jsonify({
            "ok": True,
            "clientSecret": intent.client_secret,
            "amount_yuan": amount_yuan,
            "credits": credits,
            "order_id": out_trade_no,
        })
    except stripe.StripeError as e:
        order.status = "failed"
        order.payjs_raw = str(e)
        db.session.commit()
        return jsonify({"ok": False, "error": str(e)}), 500


@pay_bp.route("/confirm", methods=["POST"])
@login_required
def confirm_payment():
    config = _get_stripe_config()
    if not config["secret_key"]:
        return jsonify({"ok": False, "error": "支付未配置"}), 400

    stripe.api_key = config["secret_key"]

    data = request.get_json() or {}
    payment_intent_id = data.get("payment_intent_id", "")

    try:
        intent = retrieve_payment_intent(payment_intent_id)
    except stripe.StripeError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if intent.status != "succeeded":
        return jsonify({"ok": False, "error": f"支付状态: {intent.status}"}), 400

    out_trade_no = intent.metadata.get("out_trade_no", "")
    order = RechargeOrder.query.filter_by(out_trade_no=out_trade_no).first()
    if order is None:
        return jsonify({"ok": False, "error": "订单不存在"}), 404

    if order.status == "paid":
        return jsonify({"ok": True, "credits": current_user.credits, "duplicate": True})

    order.status = "paid"
    order.payjs_raw = json.dumps({"payment_intent_id": intent.id, "status": intent.status})
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
    return jsonify({"ok": True, "credits": user.credits if user else 0})


@pay_bp.route("/webhook", methods=["POST"])
def webhook():
    """Stripe Webhook — 异步确认支付"""
    config = _get_stripe_config()
    if not config["secret_key"] or not config["webhook_secret"]:
        return "config error", 500

    stripe.api_key = config["secret_key"]
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, config["webhook_secret"])
    except (ValueError, stripe.SignatureVerificationError):
        return "invalid signature", 400

    if event["type"] != "payment_intent.succeeded":
        return "ignored", 200

    intent = event["data"]["object"]
    out_trade_no = intent["metadata"].get("out_trade_no", "")
    order = RechargeOrder.query.filter_by(out_trade_no=out_trade_no).first()
    if order is None:
        return "order not found", 404

    if order.status == "paid":
        return "ok"

    order.status = "paid"
    order.paid_at = datetime.utcnow()
    order.payjs_raw = json.dumps({"event": event["type"], "payment_intent_id": intent["id"]})

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
    return "ok"


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

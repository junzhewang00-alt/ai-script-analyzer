import os
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache

import stripe
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from models import db, CreditLog, RechargeOrder, User, get_recharge_packages
from stripe_pay import create_payment_intent, retrieve_payment_intent
from payjs_pay import (
    create_native_order,
    check_order,
    verify_notify,
)

pay_bp = Blueprint("pay", __name__, url_prefix="/pay")


def _get_stripe_config():
    return {
        "secret_key": os.getenv("STRIPE_SECRET_KEY", ""),
        "publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        "webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET", ""),
    }


def _get_payjs_config():
    return {
        "mchid": os.getenv("PAYJS_MCHID", ""),
        "key": os.getenv("PAYJS_KEY", ""),
    }


@lru_cache(maxsize=1)
def _packages_lookup():
    return {p["amount_yuan"]: p["credits"] for p in get_recharge_packages()}


def _credits_for_yuan(amount_yuan: int) -> int:
    return _packages_lookup().get(amount_yuan, amount_yuan * 10)


def _credit_user(order: RechargeOrder):
    """到账: 给用户加积分 + 写流水"""
    user = User.query.get(order.user_id)
    if user is None:
        return
    user.credits += order.credits
    log = CreditLog(
        user_id=user.id,
        type="recharge",
        amount=order.credits,
        balance_after=user.credits,
        description=f"充值 {order.amount_yuan} 元",
    )
    db.session.add(log)


def _mark_paid_and_credit(out_trade_no: str, raw_data, now=None) -> tuple[bool, str]:
    """Atomically lock the order row, mark paid, and credit the user.

    Returns (ok, message). Only one caller (webhook / notify / confirm)
    will succeed; subsequent callers see already-paid and return safely.
    """
    order = (
        RechargeOrder.query
        .filter_by(out_trade_no=out_trade_no)
        .with_for_update()
        .first()
    )
    if order is None:
        return False, "order not found"
    if order.status == "paid":
        return True, "already paid"

    order.status = "paid"
    order.paid_at = now or datetime.now(timezone.utc)
    order.payjs_raw = json.dumps(raw_data, ensure_ascii=False)
    _credit_user(order)
    db.session.commit()
    return True, "ok"


@pay_bp.route("/recharge")
@login_required
def recharge():
    stripe_config = _get_stripe_config()
    payjs_config = _get_payjs_config()
    return render_template(
        "recharge.html",
        stripe_configured=bool(stripe_config["secret_key"] and stripe_config["publishable_key"]),
        payjs_configured=bool(payjs_config["mchid"] and payjs_config["key"]),
        packages=get_recharge_packages(),
        stripe_publishable_key=stripe_config["publishable_key"],
    )


@pay_bp.route("/create", methods=["POST"])
@login_required
def create_order():
    data = request.get_json() or {}
    channel = data.get("channel", "stripe")
    amount_yuan = data.get("amount_yuan", 0)
    if isinstance(amount_yuan, str):
        try:
            amount_yuan = int(amount_yuan)
        except ValueError:
            return jsonify({"ok": False, "error": "无效的充值金额"}), 400
    if amount_yuan not in [p["amount_yuan"] for p in get_recharge_packages()]:
        return jsonify({"ok": False, "error": "无效的充值金额"}), 400

    credits = _credits_for_yuan(amount_yuan)
    out_trade_no = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]

    order = RechargeOrder(
        user_id=current_user.id,
        out_trade_no=out_trade_no,
        pay_channel=channel,
        amount_fen=amount_yuan * 100,
        amount_yuan=amount_yuan,
        credits=credits,
        body=f"AI剧本分析器充值 {amount_yuan}元",
        status="pending",
    )
    db.session.add(order)
    db.session.commit()

    if channel == "payjs":
        return _create_payjs(order)
    else:
        return _create_stripe(order)


def _create_payjs(order: RechargeOrder):
    config = _get_payjs_config()
    if not config["mchid"]:
        return jsonify({"ok": False, "error": "PayJS 支付未配置"}), 400

    notify_url = os.getenv("PAYJS_NOTIFY_URL", "")
    try:
        result = create_native_order(
            mchid=config["mchid"],
            key=config["key"],
            total_fee=order.amount_yuan * 100,
            out_trade_no=order.out_trade_no,
            body=order.body or "AI剧本分析器充值",
            notify_url=notify_url,
        )
    except Exception as e:
        order.status = "failed"
        order.payjs_raw = str(e)
        db.session.commit()
        return jsonify({"ok": False, "error": f"PayJS 请求失败: {e}"}), 500

    if result.get("return_code") != 1:
        order.status = "failed"
        order.payjs_raw = json.dumps(result, ensure_ascii=False)
        db.session.commit()
        return jsonify({"ok": False, "error": result.get("return_msg", "PayJS 创建订单失败")}), 500

    order.payjs_order_id = result.get("payjs_order_id", "")
    order.payjs_raw = json.dumps(result, ensure_ascii=False)
    db.session.commit()

    return jsonify({
        "ok": True,
        "channel": "payjs",
        "code_url": result.get("code_url", ""),
        "payjs_order_id": order.payjs_order_id,
        "out_trade_no": order.out_trade_no,
        "amount_yuan": order.amount_yuan,
        "credits": order.credits,
    })


def _create_stripe(order: RechargeOrder):
    config = _get_stripe_config()
    if not config["secret_key"]:
        return jsonify({"ok": False, "error": "Stripe 支付未配置"}), 400

    stripe.api_key = config["secret_key"]
    try:
        intent = create_payment_intent(order.amount_yuan, order.out_trade_no, current_user.id)
        return jsonify({
            "ok": True,
            "channel": "stripe",
            "client_secret": intent.client_secret,
            "out_trade_no": order.out_trade_no,
            "amount_yuan": order.amount_yuan,
            "credits": order.credits,
            "order_id": order.out_trade_no,
        })
    except stripe.StripeError as e:
        order.status = "failed"
        order.payjs_raw = str(e)
        db.session.commit()
        return jsonify({"ok": False, "error": str(e)}), 500


@pay_bp.route("/confirm", methods=["POST"])
@login_required
def confirm_payment():
    """Stripe 前端确认支付"""
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
    ok, msg = _mark_paid_and_credit(
        out_trade_no,
        {"payment_intent_id": intent.id, "status": intent.status},
    )
    if not ok:
        return jsonify({"ok": False, "error": "订单不存在"}), 404
    if msg == "already paid":
        return jsonify({"ok": True, "credits": current_user.credits, "duplicate": True})
    return jsonify({"ok": True, "credits": current_user.credits})


@pay_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
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
    ok, msg = _mark_paid_and_credit(
        out_trade_no,
        {"event": event["type"], "payment_intent_id": intent["id"]},
    )
    if not ok:
        return "order not found", 404
    return "ok"


@pay_bp.route("/notify", methods=["POST"])
def payjs_notify():
    """PayJS 异步回调"""
    config = _get_payjs_config()
    if not config["mchid"] or not config["key"]:
        return "config error", 500

    params = request.form.to_dict()
    if not verify_notify(params, config["key"]):
        return "sign error", 400

    out_trade_no = params.get("out_trade_no", "")
    ok, msg = _mark_paid_and_credit(out_trade_no, params)
    if not ok:
        return "order not found", 404
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

    # 如果订单还是 pending, 主动查询一下 PayJS
    if order.status == "pending" and order.pay_channel == "payjs" and order.payjs_order_id:
        config = _get_payjs_config()
        if config["mchid"]:
            try:
                result = check_order(
                    payjs_order_id=order.payjs_order_id,
                    mchid=config["mchid"],
                    key=config["key"],
                )
                if result.get("return_code") == 1 and result.get("status") == 1:
                    ok, _ = _mark_paid_and_credit(out_trade_no, result)
            except Exception:
                pass

    return jsonify({
        "status": order.status,
        "amount_yuan": order.amount_yuan,
        "credits": order.credits,
    })

import stripe


def get_recharge_packages():
    return [
        {"amount_yuan": 10, "credits": 100, "label": "入门体验", "bonus": ""},
        {"amount_yuan": 20, "credits": 220, "label": "赠送10%", "bonus": "送20积分"},
        {"amount_yuan": 50, "credits": 600, "label": "赠送20%", "bonus": "送100积分"},
        {"amount_yuan": 100, "credits": 1300, "label": "赠送30%", "bonus": "送300积分"},
    ]


def create_payment_intent(amount_yuan: int, order_id: str, user_id: int) -> stripe.PaymentIntent:
    return stripe.PaymentIntent.create(
        amount=amount_yuan * 100,  # Stripe 单位：分
        currency="cny",
        metadata={
            "out_trade_no": order_id,
            "user_id": str(user_id),
            "amount_yuan": str(amount_yuan),
        },
    )


def retrieve_payment_intent(payment_intent_id: str) -> stripe.PaymentIntent:
    return stripe.PaymentIntent.retrieve(payment_intent_id)

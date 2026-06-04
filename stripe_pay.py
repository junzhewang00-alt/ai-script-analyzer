import stripe


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

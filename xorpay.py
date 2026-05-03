import hashlib
import urllib.parse
import urllib.request
import json

XORPAY_API_BASE = "https://xorpay.com/api"


def sign_native(name: str, price: str, order_id: str, notify_url: str, app_secret: str) -> str:
    """XorPay 签名：固定顺序拼接值 → MD5 → 小写"""
    raw = name + "native" + price + order_id + notify_url + app_secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()


def verify_notify(aoid: str, order_id: str, pay_price: str, pay_time: str, app_secret: str) -> str:
    """回调签名：aoid + order_id + pay_price + pay_time + app_secret → MD5 → 小写"""
    raw = aoid + order_id + pay_price + pay_time + app_secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()


def create_native_order(aid: str, app_secret: str, name: str, price: str,
                        order_id: str, notify_url: str, order_uid: str = "",
                        more: str = "", expire: int = 7200) -> dict:
    """调用 XorPay 扫码支付接口，返回 {status, aoid, info: {qr}, ...}"""
    sign = sign_native(name, price, order_id, notify_url, app_secret)

    params = {
        "name": name,
        "pay_type": "native",
        "price": price,
        "order_id": order_id,
        "notify_url": notify_url,
        "sign": sign,
    }
    if order_uid:
        params["order_uid"] = order_uid
    if more:
        params["more"] = more
    if expire:
        params["expire"] = str(expire)

    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(f"{XORPAY_API_BASE}/pay/{aid}", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        result = json.loads(e.read().decode("utf-8"))
    except Exception as e:
        return {"status": "error", "error": str(e)}

    return result


def get_recharge_packages():
    """返回预设充值档位"""
    return [
        {"amount_yuan": 10, "credits": 100, "label": "入门体验", "bonus": ""},
        {"amount_yuan": 20, "credits": 220, "label": "赠送10%", "bonus": "送20积分"},
        {"amount_yuan": 50, "credits": 600, "label": "赠送20%", "bonus": "送100积分"},
        {"amount_yuan": 100, "credits": 1300, "label": "赠送30%", "bonus": "送300积分"},
    ]

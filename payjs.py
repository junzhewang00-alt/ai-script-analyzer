import hashlib
import urllib.parse
import urllib.request
import json


PAYJS_API_BASE = "https://payjs.cn/api"


def sign(params: dict, key: str) -> str:
    """PayJS 签名算法：ASCII排序 → key=value拼接 → 加&key= → MD5 → 大写"""
    filtered = {k: v for k, v in params.items() if v != "" and v is not None and k != "sign"}
    sorted_keys = sorted(filtered.keys())
    pairs = [f"{k}={filtered[k]}" for k in sorted_keys]
    string_a = "&".join(pairs)
    string_sign_temp = f"{string_a}&key={key}"
    return hashlib.md5(string_sign_temp.encode("utf-8")).hexdigest().upper()


def create_native_order(mchid: str, key: str, total_fee: int, out_trade_no: str,
                        body: str = "", attach: str = "", notify_url: str = "") -> dict:
    """调用 PayJS 扫码支付接口，返回 {payjs_order_id, code_url, qrcode, ...}"""
    params = {
        "mchid": mchid,
        "total_fee": str(total_fee),
        "out_trade_no": out_trade_no,
        "body": body,
        "attach": attach,
        "notify_url": notify_url,
    }
    params["sign"] = sign(params, key)

    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(f"{PAYJS_API_BASE}/native", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        result = json.loads(e.read().decode("utf-8"))
    except Exception as e:
        return {"return_code": 0, "return_msg": str(e)}

    return result


def verify_notify(data: dict, key: str) -> bool:
    """验证 PayJS 回调签名"""
    if "sign" not in data:
        return False
    received_sign = data["sign"]
    computed_sign = sign(data, key)
    return received_sign.upper() == computed_sign.upper()


def get_recharge_packages():
    """返回预设充值档位"""
    return [
        {"amount_yuan": 10, "credits": 100, "label": "入门体验", "bonus": ""},
        {"amount_yuan": 20, "credits": 220, "label": "赠送10%", "bonus": "送20积分"},
        {"amount_yuan": 50, "credits": 600, "label": "赠送20%", "bonus": "送100积分"},
        {"amount_yuan": 100, "credits": 1300, "label": "赠送30%", "bonus": "送300积分"},
    ]

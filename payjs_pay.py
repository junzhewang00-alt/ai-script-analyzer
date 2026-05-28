import hashlib
import urllib.parse
import urllib.request
import json

PAYJS_API_BASE = "https://payjs.cn/api"


def _sign(params: dict, key: str) -> str:
    sorted_items = sorted(
        (k, v) for k, v in params.items() if v != "" and k != "sign"
    )
    raw = "&".join(f"{k}={v}" for k, v in sorted_items)
    raw += f"&key={key}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def _post(api_path: str, params: dict, timeout: int = 15) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"{PAYJS_API_BASE}/{api_path}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def create_native_order(
    *,
    mchid: str,
    key: str,
    total_fee: int,
    out_trade_no: str,
    body: str,
    notify_url: str = "",
    attach: str = "",
) -> dict:
    """创建 PayJS 扫码支付订单, 返回 {payjs_order_id, code_url, qrcode, ...}"""
    params = {
        "mchid": mchid,
        "total_fee": total_fee,
        "out_trade_no": out_trade_no,
        "body": body,
        "notify_url": notify_url,
        "attach": attach,
    }
    params["sign"] = _sign(params, key)
    return _post("native", params)


def check_order(*, payjs_order_id: str = "", out_trade_no: str = "",
                mchid: str, key: str) -> dict:
    """查询 PayJS 订单状态, status=1 表示已支付"""
    params = {"mchid": mchid}
    if payjs_order_id:
        params["payjs_order_id"] = payjs_order_id
    if out_trade_no:
        params["out_trade_no"] = out_trade_no
    params["sign"] = _sign(params, key)
    return _post("check", params)


def verify_notify(params: dict, key: str) -> bool:
    """验证 PayJS 回调签名"""
    sign = params.get("sign", "")
    if not sign:
        return False
    return _sign(params, key) == sign

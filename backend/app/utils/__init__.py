import re
from typing import Optional


def parse_sina_realtime(code: str, raw: str) -> Optional[dict]:
    """
    Parse Sina Finance API response for real-time stock data.
    Format: var hq_str_sh600710="name,open,prev_close,price,high,low,..."
    """
    match = re.search(r'"([^"]*)"', raw)
    if not match:
        return None

    fields = match.group(1).split(",")
    if len(fields) < 32:
        return None

    try:
        return {
            "code": code,
            "name": fields[0],
            "open": _float(fields[1]),
            "prev_close": _float(fields[2]),
            "price": _float(fields[3]),
            "high": _float(fields[4]),
            "low": _float(fields[5]),
            "volume": _float(fields[8]),
            "amount": _float(fields[9]),
            "date": fields[30],
            "time": fields[31],
            "change_pct": round((_float(fields[3]) - _float(fields[2])) / _float(fields[2]) * 100, 2) if _float(fields[2]) > 0 else 0,
        }
    except (ValueError, IndexError):
        return None


def parse_tencent_realtime(code: str, raw: str) -> Optional[dict]:
    """Parse Tencent Finance API response. Format: v_sh600710="1~name~code~price~..." """
    match = re.search(r'"([^"]*)"', raw)
    if not match:
        return None
    fields = match.group(1).split("~")
    if len(fields) < 35:
        return None
    try:
        name = fields[1]
        price = _float(fields[3])
        if not name or price <= 0:
            return None
        return {
            "code": code,
            "name": name,
            "price": price,
            "change_pct": _float(fields[32]),
            "volume": int(_float(fields[6])) * 100 if _float(fields[6]) > 0 else 0,
            "amount": _float(fields[37]) if len(fields) > 37 else 0,
            "high": _float(fields[33]),
            "low": _float(fields[34]),
            "open": _float(fields[5]),
            "prev_close": _float(fields[4]),
        }
    except (ValueError, IndexError):
        return None


def _float(val: str) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def get_sina_code(stock_code: str) -> str:
    """Convert stock code to Sina API format: 600710 -> sh600710, 000001 -> sz000001"""
    code = stock_code.strip()
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def get_tencent_code(stock_code: str) -> str:
    """Convert stock code to Tencent API format: 600710 -> sh600710, 000001 -> sz000001"""
    code = stock_code.strip()
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"

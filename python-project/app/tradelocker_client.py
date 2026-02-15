import requests
import time
from datetime import datetime, timezone, timedelta

from app.config import TRADELOCKER_DEMO_BASE_URL, TRADELOCKER_LIVE_BASE_URL


def _get_base_url(environment: str) -> str:
    """Return the correct base URL for 'demo' or 'live'."""
    if environment == "live":
        return TRADELOCKER_LIVE_BASE_URL
    return TRADELOCKER_DEMO_BASE_URL


def tradelocker_authenticate(email: str, password: str, server: str, environment: str = "demo") -> dict | None:
    """
    POST /auth/jwt/token
    Returns {"accessToken", "refreshToken", "expireDate"} or None on failure.
    """
    base_url = _get_base_url(environment)
    resp = requests.post(
        f"{base_url}/auth/jwt/token",
        json={"email": email, "password": password, "server": server},
        headers={"accept": "application/json", "content-type": "application/json"},
    )
    if resp.status_code == 201:
        return resp.json()
    return None


def tradelocker_refresh(refresh_token: str, environment: str = "demo") -> dict | None:
    """
    POST /auth/jwt/refresh
    Returns new {"accessToken", "refreshToken", "expireDate"} or None.
    """
    base_url = _get_base_url(environment)
    resp = requests.post(
        f"{base_url}/auth/jwt/refresh",
        json={"refreshToken": refresh_token},
        headers={"accept": "application/json", "content-type": "application/json"},
    )
    if resp.status_code == 201:
        return resp.json()
    return None


def tradelocker_get_accounts(access_token: str, environment: str = "demo") -> list | None:
    """
    GET /auth/jwt/all-accounts
    Returns list of account dicts or None on failure.
    """
    base_url = _get_base_url(environment)
    resp = requests.get(
        f"{base_url}/auth/jwt/all-accounts",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("accounts", [])
    return None


def tradelocker_get_config(access_token: str, acc_num: str, environment: str = "demo") -> dict | None:
    """
    GET /trade/config
    Returns column names for accountDetails, positions, orders, etc.
    We use accountDetailsColumns to map the state array to named fields.
    """
    base_url = _get_base_url(environment)
    resp = requests.get(
        f"{base_url}/trade/config",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        return resp.json()
    return None


def tradelocker_get_account_state(access_token: str, account_id: str, acc_num: str, environment: str = "demo") -> list | None:
    """
    GET /trade/accounts/{accountId}/state
    Returns the accountDetailsData array (numbers) for the account.
    Field names come from /trade/config → accountDetailsColumns.
    """
    base_url = _get_base_url(environment)
    resp = requests.get(
        f"{base_url}/trade/accounts/{account_id}/state",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        d = data.get("d", {})
        return d.get("accountDetailsData", [])
    return None


def tradelocker_get_orders(access_token: str, account_id: str, acc_num: str, environment: str = "demo",
                           from_ms: int = None, to_ms: int = None, tradable_instrument_id: int = None) -> list | None:
    """
    GET /trade/accounts/{accountId}/orders
    Returns the non-final (active) orders as a list of arrays, or None on failure.
    Column names come from /trade/config → ordersConfig.
    """
    base_url = _get_base_url(environment)
    params = {}
    if from_ms is not None:
        params["from"] = from_ms
    if to_ms is not None:
        params["to"] = to_ms
    if tradable_instrument_id is not None:
        params["tradableInstrumentId"] = tradable_instrument_id
    resp = requests.get(
        f"{base_url}/trade/accounts/{account_id}/orders",
        params=params or None,
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("d", {}).get("orders", [])
    return None


def tradelocker_get_orders_history(access_token: str, account_id: str, acc_num: str, environment: str = "demo",
                                   from_ms: int = None, to_ms: int = None, tradable_instrument_id: int = None) -> dict | None:
    """
    GET /trade/accounts/{accountId}/ordersHistory
    Returns dict with 'ordersHistory' (list of arrays) and 'hasMore' (bool), or None on failure.
    Column names come from /trade/config → ordersHistoryConfig.
    """
    base_url = _get_base_url(environment)
    params = {}
    if from_ms is not None:
        params["from"] = from_ms
    if to_ms is not None:
        params["to"] = to_ms
    if tradable_instrument_id is not None:
        params["tradableInstrumentId"] = tradable_instrument_id
    resp = requests.get(
        f"{base_url}/trade/accounts/{account_id}/ordersHistory",
        params=params or None,
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        d = data.get("d", {})
        return {"ordersHistory": d.get("ordersHistory", []), "hasMore": d.get("hasMore", False)}
    return None


def tradelocker_get_positions(access_token: str, account_id: str, acc_num: str, environment: str = "demo") -> list | None:
    """
    GET /trade/accounts/{accountId}/positions
    Returns the open positions as a list of arrays, or None on failure.
    Column names come from /trade/config → positionsConfig.
    """
    base_url = _get_base_url(environment)
    resp = requests.get(
        f"{base_url}/trade/accounts/{account_id}/positions",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("d", {}).get("positions", [])
    return None


def tradelocker_get_instruments(access_token: str, account_id: str, acc_num: str, environment: str = "demo") -> list | None:
    """
    GET /trade/accounts/{accountId}/instruments
    Returns list of instrument dicts or None on failure.
    """
    base_url = _get_base_url(environment)
    resp = requests.get(
        f"{base_url}/trade/accounts/{account_id}/instruments",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        d = data.get("d", {})
        return d.get("instruments", [])
    return None


# Resolution mapping: user-friendly → TradeLocker format
TIMEFRAME_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1H",
    "H4": "4H",
    "D1": "1D",
    "W1": "1W",
    "MN1": "1M",
}

VALID_TIMEFRAMES = list(TIMEFRAME_MAP.keys())

# Aliases agents/users commonly use → canonical form
TIMEFRAME_ALIASES = {
    "1M":  "M1",   "1MIN": "M1",
    "5M":  "M5",   "5MIN": "M5",
    "15M": "M15",  "15MIN": "M15",
    "30M": "M30",  "30MIN": "M30",
    "1H":  "H1",   "60M":  "H1",  "60MIN": "H1",
    "4H":  "H4",   "240M": "H4",
    "1D":  "D1",   "DAILY": "D1", "DAY": "D1",
    "1W":  "W1",   "WEEKLY": "W1", "WEEK": "W1",
    "MO":  "MN1",  "MON":  "MN1", "MONTHLY": "MN1", "MONTH": "MN1", "1MN": "MN1",
}


def normalize_timeframe(tf: str) -> str:
    """
    Normalize a timeframe string to canonical form (case-insensitive).
    Accepts common aliases: 1D→D1, 1H→H1, 1W→W1, daily→D1, etc.
    Returns the canonical timeframe or the uppercased input if no alias found.
    """
    if not tf:
        return tf
    up = tf.strip().upper()
    # Already valid?
    if up in TIMEFRAME_MAP:
        return up
    # Check aliases
    return TIMEFRAME_ALIASES.get(up, up)


def tradelocker_get_market_data(
    access_token: str,
    account_id: str,
    acc_num: str,
    tradable_instrument_id: str,
    route_id: str,
    resolution: str,
    count: int = None,
    environment: str = "demo",
    is_continuous: bool = False,
    from_override_ms: int = None,
    to_override_ms: int = None,
) -> dict | None:
    """
    GET /trade/history
    Returns OHLCV bars or None on failure.
    resolution should be TradeLocker format (1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M).
    count = number of bars to return (calculates 'from' timestamp).
    from_override_ms = explicit 'from' timestamp in ms (used by period param, skips count-based calc).
    to_override_ms = explicit 'to' timestamp in ms (used by pretend_date/pretend_time to simulate a different 'now').
    is_continuous = True for 24/7 instruments (crypto), False for forex/stocks with weekend gaps.
    """
    base_url = _get_base_url(environment)

    # 'to' is now (ms) — or pretend now if overridden
    to_ts = to_override_ms if to_override_ms is not None else int(time.time() * 1000)

    if from_override_ms is not None:
        # Period-based: use the explicit from timestamp
        from_ts = from_override_ms
    else:
        # Count-based: estimate bar duration to calculate 'from'
        if count is None:
            count = 100
        bar_durations = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1H": 3_600_000,
            "4H": 14_400_000,
            "1D": 86_400_000,
            "1W": 604_800_000,
            "1M": 2_592_000_000,
        }
        bar_ms = bar_durations.get(resolution, 60_000)
        trading_span = (count * bar_ms) + bar_ms  # requested span + buffer

        if is_continuous:
            # Crypto trades 24/7 — no weekend gaps
            from_ts = to_ts - trading_span
        else:
            # Non-continuous instruments (forex, stocks, etc.) — skip weekends
            # For every 5 trading days there are 7 calendar days → multiply by 7/5
            calendar_span = int(trading_span * 7 / 5)
            # If we're currently on a weekend, add extra days to reach back to Friday
            now_dt = datetime.fromtimestamp(to_ts / 1000, tz=timezone.utc)
            if now_dt.weekday() == 5:  # Saturday
                calendar_span += 2 * 86_400_000
            elif now_dt.weekday() == 6:  # Sunday
                calendar_span += 3 * 86_400_000
            from_ts = to_ts - calendar_span

    resp = requests.get(
        f"{base_url}/trade/history",
        params={
            "tradableInstrumentId": tradable_instrument_id,
            "routeId": route_id,
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
        },
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        d = data.get("d", {})
        bars = d.get("barDetails", [])
        # Trim to requested count (from the end / most recent) — only when count-based
        if count is not None and len(bars) > count:
            bars = bars[-count:]
        return {"bars": bars, "status": d.get("s", "ok")}
    return None


# ═══════════════════════════════════════════════════════════════════════════
# TRADING — Place / Close / Modify orders & positions
# ═══════════════════════════════════════════════════════════════════════════


def tradelocker_place_order(
    access_token: str,
    account_id: str,
    acc_num: str,
    tradable_instrument_id: int,
    route_id: int,
    side: str,
    order_type: str,
    qty: float,
    price: float = 0,
    stop_price: float = None,
    stop_loss: float = None,
    take_profit: float = None,
    strategy_id: str = None,
    environment: str = "demo",
) -> dict | None:
    """
    POST /trade/accounts/{accountId}/orders
    Place a market, limit, or stop order.
    Returns {"orderId": "..."} on success or None on failure.
    """
    base_url = _get_base_url(environment)
    validity = "IOC" if order_type == "market" else "GTC"
    body = {
        "tradableInstrumentId": tradable_instrument_id,
        "routeId": route_id,
        "side": side,
        "type": order_type,
        "qty": qty,
        "price": price,
        "validity": validity,
    }
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
        body["stopLossType"] = "absolute"
    if take_profit is not None:
        body["takeProfit"] = take_profit
        body["takeProfitType"] = "absolute"
    if stop_price is not None:
        body["stopPrice"] = stop_price
    if strategy_id:
        body["strategyId"] = strategy_id

    resp = requests.post(
        f"{base_url}/trade/accounts/{account_id}/orders",
        json=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("d", data)
    return {"error": resp.text, "status_code": resp.status_code}


def tradelocker_close_position(
    access_token: str,
    position_id: str,
    acc_num: str,
    qty: float = 0,
    environment: str = "demo",
) -> dict | None:
    """
    DELETE /trade/positions/{positionId}
    Close (fully or partially) an open position.
    qty=0 means close fully.
    """
    base_url = _get_base_url(environment)
    resp = requests.delete(
        f"{base_url}/trade/positions/{position_id}",
        json={"qty": qty},
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 204):
        try:
            return resp.json()
        except Exception:
            return {"s": "ok"}
    return {"error": resp.text, "status_code": resp.status_code}


def tradelocker_close_all_positions(
    access_token: str,
    account_id: str,
    acc_num: str,
    tradable_instrument_id: int = None,
    environment: str = "demo",
) -> dict | None:
    """
    DELETE /trade/accounts/{accountId}/positions
    Close all positions, optionally filtered by instrument.
    """
    base_url = _get_base_url(environment)
    params = {}
    if tradable_instrument_id is not None:
        params["tradableInstrumentId"] = tradable_instrument_id
    resp = requests.delete(
        f"{base_url}/trade/accounts/{account_id}/positions",
        params=params or None,
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 204):
        try:
            return resp.json()
        except Exception:
            return {"s": "ok"}
    return {"error": resp.text, "status_code": resp.status_code}


def tradelocker_modify_position(
    access_token: str,
    position_id: str,
    acc_num: str,
    stop_loss: float = None,
    take_profit: float = None,
    trailing_offset: float = None,
    environment: str = "demo",
) -> dict | None:
    """
    PATCH /trade/positions/{positionId}
    Modify SL / TP on an open position.
    """
    base_url = _get_base_url(environment)
    body = {}
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if trailing_offset is not None:
        body["trailingOffset"] = trailing_offset
    resp = requests.patch(
        f"{base_url}/trade/positions/{position_id}",
        json=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 204):
        try:
            return resp.json()
        except Exception:
            return {"s": "ok"}
    return {"error": resp.text, "status_code": resp.status_code}


def tradelocker_cancel_order(
    access_token: str,
    order_id: str,
    acc_num: str,
    environment: str = "demo",
) -> dict | None:
    """
    DELETE /trade/orders/{orderId}
    Cancel a pending order.
    """
    base_url = _get_base_url(environment)
    resp = requests.delete(
        f"{base_url}/trade/orders/{order_id}",
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 204):
        try:
            return resp.json()
        except Exception:
            return {"s": "ok"}
    return {"error": resp.text, "status_code": resp.status_code}


def tradelocker_cancel_all_orders(
    access_token: str,
    account_id: str,
    acc_num: str,
    tradable_instrument_id: int = None,
    environment: str = "demo",
) -> dict | None:
    """
    DELETE /trade/accounts/{accountId}/orders
    Cancel all pending orders, optionally filtered by instrument.
    """
    base_url = _get_base_url(environment)
    params = {}
    if tradable_instrument_id is not None:
        params["tradableInstrumentId"] = tradable_instrument_id
    resp = requests.delete(
        f"{base_url}/trade/accounts/{account_id}/orders",
        params=params or None,
        headers={
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 204):
        try:
            return resp.json()
        except Exception:
            return {"s": "ok"}
    return {"error": resp.text, "status_code": resp.status_code}


def tradelocker_modify_order(
    access_token: str,
    order_id: str,
    acc_num: str,
    price: float = None,
    stop_price: float = None,
    qty: float = None,
    stop_loss: float = None,
    take_profit: float = None,
    environment: str = "demo",
) -> dict | None:
    """
    PATCH /trade/orders/{orderId}
    Modify a pending order's price, qty, SL, or TP.
    """
    base_url = _get_base_url(environment)
    body = {}
    if price is not None:
        body["price"] = price
    if stop_price is not None:
        body["stopPrice"] = stop_price
    if qty is not None:
        body["qty"] = qty
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
        body["stopLossType"] = "absolute"
    if take_profit is not None:
        body["takeProfit"] = take_profit
        body["takeProfitType"] = "absolute"
    resp = requests.patch(
        f"{base_url}/trade/orders/{order_id}",
        json=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),
        },
    )
    if resp.status_code in (200, 204):
        try:
            return resp.json()
        except Exception:
            return {"s": "ok"}
    return {"error": resp.text, "status_code": resp.status_code}

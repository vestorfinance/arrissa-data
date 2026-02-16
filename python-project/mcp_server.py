"""
Arrissa MCP Server — exposes the entire Arrissa trading API as MCP tools.

Copyright (c) 2026 Arrissa Pty Ltd
https://arrissadata.com · https://arrissa.trade · https://arrissacapital.com
Author: @mystprevail · https://github.com/vestorfinance
See LICENSE for attribution requirements.

Run locally (stdio):   python mcp_server.py
Run remotely (SSE):    python mcp_server.py --sse [--host 0.0.0.0] [--port 5002]

Transport: stdio (for Claude Desktop, Cursor, VS Code, etc.)
           sse  (for remote connections — VS Code, Cursor, etc. connect via URL)

Environment variables (all optional — set via MCP client config):
  ARRISSA_API_URL     — Flask API base URL (default: http://localhost:5001)
  ARRISSA_API_KEY     — Default API key (so the AI never has to ask)
  MCP_TRANSPORT       — "stdio" or "sse" (default: stdio, overridden by --sse flag)
  MCP_HOST            — SSE bind host (default: 0.0.0.0)
  MCP_PORT            — SSE bind port (default: 5002)
"""

import os
import json
import base64
import logging
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

from app.tradelocker_client import normalize_timeframe

# ─── Configuration ───────────────────────────────────────────────────────────

API_BASE = os.environ.get("ARRISSA_API_URL", "http://localhost:5001").rstrip("/")
DEFAULT_API_KEY = os.environ.get("ARRISSA_API_KEY", "")

log = logging.getLogger("arrissa-mcp")

mcp = FastMCP(
    "Arrissa Trading API",
    instructions=(
        "Complete trading API for TradeLocker brokerage accounts. "
        "Provides market data, charting, economic news, order management, "
        "position management, account details, and web scraping.\n\n"
        "IMPORTANT: api_key is pre-configured via environment variable — "
        "you do NOT need to ask the user for it, just omit it.\n\n"
        "ACCOUNTS: Users can have multiple trading accounts with nicknames "
        "(e.g. 'my demo', 'live account'). Use list_my_accounts first to "
        "see available accounts with their nicknames and arrissa_account_id. "
        "For tools that need arrissa_account_id:\n"
        "  • If the user refers to an account by nickname (e.g. 'my demo account'), "
        "pass that text as account_name and leave arrissa_account_id empty.\n"
        "  • If there is only one account, it will be used automatically.\n"
        "  • For non-account-specific data (news, scraping), no account is needed.\n"
        "  • NEVER ask the user for arrissa_account_id — use nicknames or auto-select."
    ),
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get(endpoint: str, params: dict = None, headers: dict = None) -> dict:
    """Make a GET request to the Flask API and return JSON."""
    url = f"{API_BASE}{endpoint}"
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=120)
        # For binary responses (chart image)
        if resp.headers.get("content-type", "").startswith("image/"):
            return {"_image": True, "_data": resp.content, "_status": resp.status_code}
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        return {"response": resp.text, "status_code": resp.status_code}
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot connect to Arrissa API at {API_BASE}. Is the Flask server running?"}
    except Exception as e:
        return {"error": str(e)}


def _post(endpoint: str, json_body: dict = None, params: dict = None, headers: dict = None) -> dict:
    """Make a POST request to the Flask API and return JSON."""
    url = f"{API_BASE}{endpoint}"
    try:
        resp = requests.post(url, json=json_body, params=params, headers=headers, timeout=60)
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        return {"response": resp.text, "status_code": resp.status_code}
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot connect to Arrissa API at {API_BASE}. Is the Flask server running?"}
    except Exception as e:
        return {"error": str(e)}


def _fmt(data: Any) -> str:
    """Format response data as pretty JSON string."""
    if isinstance(data, dict) and data.get("_image"):
        return "[Chart image returned — see resource]"
    return json.dumps(data, indent=2, default=str)


def _key(api_key: str = "") -> str:
    """Resolve API key — use provided value or fall back to env default."""
    return api_key or DEFAULT_API_KEY


def _resolve_acct(arrissa_account_id: str = "", account_name: str = "") -> str:
    """Resolve account ID — by explicit ID, by nickname search, or user's default, or auto-select.

    Priority: arrissa_account_id > account_name search > user default > first account.
    """
    if arrissa_account_id:
        return arrissa_account_id

    # Ask the API to resolve by name or return all accounts
    params = {"api_key": _key()}
    if account_name:
        params["name"] = account_name
    try:
        resp = requests.get(f"{API_BASE}/api/accounts/resolve", params=params, timeout=10)
        data = resp.json()
        accounts = data.get("accounts", [])
        default_id = data.get("default_account_id")

        if len(accounts) == 1:
            return accounts[0]["arrissa_account_id"]
        if len(accounts) > 1 and account_name:
            # Exact nickname match first
            for a in accounts:
                if a.get("nickname") and a["nickname"].lower() == account_name.lower():
                    return a["arrissa_account_id"]
            # Partial match — return first
            return accounts[0]["arrissa_account_id"]
        if len(accounts) > 1:
            # Use user's default account if set, otherwise first
            if default_id:
                return default_id
            return accounts[0]["arrissa_account_id"]
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT MANAGEMENT TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def list_my_accounts(api_key: str = "", name: str = "") -> str:
    """
    List all trading accounts with their nicknames, IDs, environment, and balances.
    Call this FIRST to discover available accounts before using account-specific tools.
    Users can set nicknames on the Brokers page (e.g. "my demo", "live USD").

    If a name is given, filters accounts by that nickname/name.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        name: Optional — filter by nickname or account name (e.g. "demo", "live")
    """
    params = {"api_key": _key(api_key)}
    if name:
        params["name"] = name
    result = _get("/api/accounts/resolve", params=params)
    return _fmt(result)


@mcp.tool()
def get_synced_accounts(api_key: str = "", user_id: int = 1) -> str:
    """
    Get all TradeLocker brokerage accounts synced for a user.

    Returns credential details (email, server, environment) and all linked
    trading accounts with their arrissa_account_id (needed for other tools).

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        user_id: Your user ID
    """
    result = _get(
        f"/users/{user_id}/tradelocker/accounts",
        headers={"X-API-Key": _key(api_key)},
    )
    return _fmt(result)


@mcp.tool()
def add_tradelocker_credentials(
    api_key: str = "",
    user_id: int = 1,
    email: str = "",
    password: str = "",
    server: str = "",
    environment: str = "demo",
) -> str:
    """
    Connect a TradeLocker brokerage account. Authenticates with TradeLocker,
    saves tokens, and syncs all trading accounts.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        user_id: Your user ID
        email: TradeLocker login email
        password: TradeLocker login password
        server: TradeLocker server name (e.g. "OSP-DEMO", "ICMarkets")
        environment: "demo" or "live" (default: "demo")
    """
    result = _post(
        f"/users/{user_id}/tradelocker/credentials",
        json_body={"email": email, "password": password, "server": server, "environment": environment},
        headers={"X-API-Key": _key(api_key)},
    )
    return _fmt(result)


@mcp.tool()
def refresh_tradelocker_credentials(
    api_key: str = "",
    user_id: int = 1,
    credential_id: int = 0,
) -> str:
    """
    Refresh TradeLocker tokens and re-sync accounts for a specific credential.
    Use when tokens expire or accounts change.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        user_id: Your user ID
        credential_id: The credential ID to refresh (from get_synced_accounts)
    """
    result = _post(
        f"/users/{user_id}/tradelocker/credentials/{credential_id}/refresh",
        headers={"X-API-Key": _key(api_key)},
    )
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUMENTS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_instruments(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    search: str = "",
    type_filter: str = "",
) -> str:
    """
    List all tradeable instruments (symbols) available on a trading account.
    Use this to find valid symbols for market data and trading.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        search: Optional filter — only return instruments containing this text (e.g. "EUR", "BTC")
        type_filter: Optional filter by instrument type (e.g. "FOREX", "CRYPTO", "STOCK", "INDEX", "COMMODITY")
    """
    params = {"api_key": _key(api_key), "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name)}
    if search:
        params["search"] = search
    if type_filter:
        params["type"] = type_filter
    result = _get("/api/instruments", params=params)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT DETAILS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_account_details(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    field: str = "",
) -> str:
    """
    Get real-time account state from the broker — balance, equity, margin,
    unrealised P&L, free margin, and more.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        field: Optional — return only a specific field (e.g. "balance", "equity", "unrealizedPl")
    """
    params = {"api_key": _key(api_key), "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name)}
    if field:
        params["field"] = field
    result = _get("/api/account-details", params=params)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET DATA
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_market_data(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    symbol: str = "",
    timeframe: str = "",
    count: int = 0,
    period: str = "",
    ma: str = "",
    quarters_s_n_r: bool = False,
    volume: bool = False,
    order_blocks: bool = False,
    pretend_date: str = "",
    pretend_time: str = "",
    future_limit: str = "",
) -> str:
    """
    Get OHLCV candlestick bars for a trading instrument (symbol).

    Timeframes: M1, M5, M15, M30, H1, H4, D1, W1, MN1
    Use either count OR period (not both).
    Period examples: last-30-minutes, last-7-days, last-1-month, future
    Future requires pretend_date + future_limit (e.g. next-2-days)

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        symbol: Trading symbol (e.g. "EURUSD", "BTCUSD", "AAPL")
        timeframe: Candle timeframe — M1, M5, M15, M30, H1, H4, D1, W1, MN1
        count: Number of bars to return (1-5000, default 100). Mutually exclusive with period.
        period: Time period — e.g. "last-7-days", "last-30-minutes", "last-1-month", "future"
        ma: Comma-separated moving average periods (e.g. "20,50,200")
        quarters_s_n_r: Include quarter-based support & resistance levels
        volume: Include volume data in each bar
        order_blocks: Include order block analysis (requires quarters_s_n_r=true)
        pretend_date: Simulate a different date (YYYY-MM-DD) — for historical analysis
        pretend_time: Simulate a different time (HH:MM) — used with pretend_date
        future_limit: For period=future only — e.g. "next-2-days", "next-4-hours"
    """
    params: dict[str, Any] = {
        "api_key": _key(api_key),
        "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name),
        "symbol": symbol.strip().upper(),
        "timeframe": normalize_timeframe(timeframe),
    }
    if count and count > 0:
        params["count"] = count
    if period:
        params["period"] = period
    if ma:
        params["ma"] = ma
    if quarters_s_n_r:
        params["quarters_s_n_r"] = "true"
    if volume:
        params["volume"] = "true"
    if order_blocks:
        params["order_blocks"] = "true"
    if pretend_date:
        params["pretend_date"] = pretend_date
    if pretend_time:
        params["pretend_time"] = pretend_time
    if future_limit:
        params["future_limit"] = future_limit

    result = _get("/api/market-data", params=params)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# CHART IMAGE
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_chart_image(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    symbol: str = "",
    timeframe: str = "",
    count: int = 0,
    period: str = "",
    ma: str = "",
    quarters_s_n_r: bool = False,
    volume: bool = False,
    order_blocks: bool = False,
    width: int = 1200,
    height: int = 700,
    theme: str = "dark",
    entry: str = "",
    direction: str = "",
    sl: str = "",
    tp: str = "",
    sl_points: str = "",
    tp_points: str = "",
    pretend_date: str = "",
    pretend_time: str = "",
    future_limit: str = "",
) -> list:
    """
    Generate a Japanese candlestick chart as a PNG image.
    Same data params as get_market_data plus visual options.

    Position drawing: set entry ("market" or "YYYY-MM-DD-HH:MM"), direction ("LONG"/"SHORT"),
    and sl/tp (absolute price) or sl_points/tp_points (distance in points).

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        symbol: Trading symbol (e.g. "EURUSD", "BTCUSD")
        timeframe: Candle timeframe — M1, M5, M15, M30, H1, H4, D1, W1, MN1
        count: Number of bars (1-5000, default 100). Mutually exclusive with period.
        period: Time period — e.g. "last-7-days", "last-30-minutes"
        ma: Comma-separated MA periods (e.g. "20,50,200")
        quarters_s_n_r: Show quarter-based S&R levels
        volume: Show volume panel
        order_blocks: Show order blocks (requires quarters_s_n_r)
        width: Image width in pixels (400-3840, default 1200)
        height: Image height in pixels (300-2160, default 700)
        theme: "dark" or "light" (default "dark")
        entry: Position entry — "market" or datetime "YYYY-MM-DD-HH:MM"
        direction: Position direction — "LONG" or "SHORT"
        sl: Stop loss absolute price
        tp: Take profit absolute price
        sl_points: Stop loss distance in points (alternative to sl)
        tp_points: Take profit distance in points (alternative to tp)
        pretend_date: Historical date simulation (YYYY-MM-DD)
        pretend_time: Historical time simulation (HH:MM)
        future_limit: For period=future — e.g. "next-2-days"
    """
    params: dict[str, Any] = {
        "api_key": _key(api_key),
        "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name),
        "symbol": symbol.strip().upper(),
        "timeframe": normalize_timeframe(timeframe),
        "width": width,
        "height": height,
        "theme": theme,
    }
    if count and count > 0:
        params["count"] = count
    if period:
        params["period"] = period
    if ma:
        params["ma"] = ma
    if quarters_s_n_r:
        params["quarters_s_n_r"] = "true"
    if volume:
        params["volume"] = "true"
    if order_blocks:
        params["order_blocks"] = "true"
    if entry:
        params["entry"] = entry
    if direction:
        params["direction"] = direction
    if sl:
        params["sl"] = sl
    if tp:
        params["tp"] = tp
    if sl_points:
        params["sl_points"] = sl_points
    if tp_points:
        params["tp_points"] = tp_points
    if pretend_date:
        params["pretend_date"] = pretend_date
    if pretend_time:
        params["pretend_time"] = pretend_time
    if future_limit:
        params["future_limit"] = future_limit

    result = _get("/api/chart-image", params=params)

    if isinstance(result, dict) and result.get("_image"):
        # Return as embedded image content
        from mcp.types import ImageContent, TextContent
        img_data = base64.b64encode(result["_data"]).decode("utf-8")
        return [
            ImageContent(type="image", data=img_data, mimeType="image/png"),
            TextContent(type="text", text=f"Chart: {symbol} {timeframe}"),
        ]

    # Error case — return JSON
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# ORDERS & POSITIONS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_orders(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
) -> str:
    """
    Get all active (pending) orders on the trading account.
    Returns order details including symbol, side, type, price, volume, SL, TP.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
    """
    params = {"api_key": _key(api_key), "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name)}
    result = _get("/api/orders", params=params)
    return _fmt(result)


@mcp.tool()
def get_orders_history(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
) -> str:
    """
    Get order history — filled, cancelled, and rejected orders.
    Includes symbol names and human-readable timestamps.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
    """
    params = {"api_key": _key(api_key), "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name)}
    result = _get("/api/orders-history", params=params)
    return _fmt(result)


@mcp.tool()
def get_positions(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
) -> str:
    """
    Get all currently open trading positions.
    Returns position details including symbol, side, volume, entry price,
    current P&L, SL, TP, and position ID (ticket).

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
    """
    params = {"api_key": _key(api_key), "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name)}
    result = _get("/api/positions", params=params)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TRADING
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def trade(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    action: str = "",
    symbol: str = "",
    volume: str = "",
    sl: str = "",
    tp: str = "",
    price: str = "",
    ticket: str = "",
    new_value: str = "",
) -> str:
    """
    Execute trading actions on a brokerage account.

    OPEN POSITIONS:
      action=BUY — Market buy. Requires: symbol, volume. Optional: sl, tp
      action=SELL — Market sell. Requires: symbol, volume. Optional: sl, tp

    PENDING ORDERS:
      action=BUY_LIMIT — Buy at lower price. Requires: symbol, volume, price. Optional: sl, tp
      action=SELL_LIMIT — Sell at higher price. Requires: symbol, volume, price. Optional: sl, tp
      action=BUY_STOP — Buy at higher price. Requires: symbol, volume, price. Optional: sl, tp
      action=SELL_STOP — Sell at lower price. Requires: symbol, volume, price. Optional: sl, tp

    CLOSE POSITIONS:
      action=CLOSE — Close by ticket or symbol. Requires: ticket OR symbol
      action=CLOSE_ALL — Close all positions. Optional: symbol (to filter)
      action=CLOSE_LOSS — Close all losing positions. Optional: symbol
      action=CLOSE_PROFIT — Close all profitable positions. Optional: symbol

    MODIFY POSITIONS:
      action=MODIFY_TP — Set take profit. Requires: ticket, new_value (price)
      action=MODIFY_SL — Set stop loss. Requires: ticket, new_value (price)
      action=BREAK_EVEN — Move SL to entry price. Requires: ticket
      action=BREAK_EVEN_ALL — Break even all positions. Optional: symbol
      action=TRAIL_SL — Set trailing stop. Requires: ticket, new_value (points)

    MANAGE ORDERS:
      action=DELETE_ORDER — Cancel pending order. Requires: ticket
      action=DELETE_ALL_ORDERS — Cancel all pending orders. Optional: symbol
      action=MODIFY_ORDER — Change order price. Requires: ticket, new_value (price)

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        action: Trading action (BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, CLOSE, CLOSE_ALL, CLOSE_LOSS, CLOSE_PROFIT, MODIFY_TP, MODIFY_SL, BREAK_EVEN, BREAK_EVEN_ALL, TRAIL_SL, DELETE_ORDER, DELETE_ALL_ORDERS, MODIFY_ORDER)
        symbol: Trading symbol (e.g. "EURUSD") — required for open/close by symbol
        volume: Trade volume in lots (e.g. "0.01") — required for opening trades
        sl: Stop loss price (absolute) — optional for open trades
        tp: Take profit price (absolute) — optional for open trades
        price: Limit/stop order price — required for pending orders
        ticket: Position or order ID — required for close/modify by ticket
        new_value: New value for modifications (price for TP/SL/ORDER, points for TRAIL_SL)
    """
    params: dict[str, Any] = {
        "api_key": _key(api_key),
        "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name),
        "action": action.strip().upper(),
    }
    if symbol:
        params["symbol"] = symbol.strip().upper()
    if volume:
        params["volume"] = volume
    if sl:
        params["sl"] = sl
    if tp:
        params["tp"] = tp
    if price:
        params["price"] = price
    if ticket:
        params["ticket"] = ticket
    if new_value:
        params["new_value"] = new_value

    result = _get("/api/trade", params=params)
    return _fmt(result)


@mcp.tool()
def get_trade_history(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    history: str = "",
) -> str:
    """
    Get recent trade history (filled orders).

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        history: Time filter — "today", "last-hour", "last-10", "last-20", "last-7days", "last-30days"
    """
    params = {
        "api_key": _key(api_key),
        "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name),
        "history": history,
    }
    result = _get("/api/trade", params=params)
    return _fmt(result)


@mcp.tool()
def get_profit_summary(
    api_key: str = "",
    arrissa_account_id: str = "",
    account_name: str = "",
    profit: str = "",
) -> str:
    """
    Get profit/loss summary for a time period.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        arrissa_account_id: The Arrissa account ID (auto-resolved if omitted)
        account_name: Account nickname (e.g. "my demo") — alternative to arrissa_account_id
        profit: Period — "today", "last-hour", "this-week", "this-month", "last-7days", "last-30days"
    """
    params = {
        "api_key": _key(api_key),
        "arrissa_account_id": _resolve_acct(arrissa_account_id, account_name),
        "profit": profit,
    }
    result = _get("/api/trade", params=params)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# ECONOMIC NEWS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_economic_news(
    api_key: str = "",
    from_date: str = "",
    to_date: str = "",
    period: str = "",
    currencies: str = "",
    impact: str = "medium",
    event_type_id: str = "",
    pretend_date: str = "",
    pretend_time: str = "",
    future_limit: str = "",
) -> str:
    """
    Get economic calendar events (news releases, data, speeches).
    Use either from_date+to_date OR period (not both).

    Supported currencies: USD, CAD, JPY, EUR, CHF, AUD, NZD, GBP

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        from_date: Start date YYYY-MM-DD (use with to_date)
        to_date: End date YYYY-MM-DD (use with from_date)
        period: Time period — e.g. "last-7-days", "last-30-days", "future"
        currencies: Comma-separated currency codes (e.g. "USD,EUR,GBP"). Default: all
        impact: Filter — "all", "medium" (medium+high, default), "high" (high only)
        event_type_id: Filter by specific event type IDs (comma-separated)
        pretend_date: Simulate different date (YYYY-MM-DD)
        pretend_time: Simulate different time (HH:MM)
        future_limit: For period=future — e.g. "next-7-days", "next-24-hours"
    """
    params: dict[str, Any] = {"api_key": _key(api_key), "impact": impact}
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    if period:
        params["period"] = period
    if currencies:
        params["currencies"] = currencies
    if event_type_id:
        params["event_type_id"] = event_type_id
    if pretend_date:
        params["pretend_date"] = pretend_date
    if pretend_time:
        params["pretend_time"] = pretend_time
    if future_limit:
        params["future_limit"] = future_limit

    result = _get("/api/news", params=params)
    return _fmt(result)


@mcp.tool()
def save_economic_news(
    api_key: str = "",
    from_date: str = "",
    to_date: str = "",
    period: str = "",
    currencies: str = "",
    impact: str = "medium",
    pretend_date: str = "",
    pretend_time: str = "",
    future_limit: str = "",
) -> str:
    """
    Fetch economic events and save them to the database for later querying.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        from_date: Start date YYYY-MM-DD (use with to_date)
        to_date: End date YYYY-MM-DD (use with from_date)
        period: Time period — e.g. "last-7-days", "last-30-days"
        currencies: Comma-separated currencies (e.g. "USD,EUR")
        impact: "all", "medium", or "high"
        pretend_date: Simulate different date (YYYY-MM-DD)
        pretend_time: Simulate different time (HH:MM)
        future_limit: For period=future — e.g. "next-7-days"
    """
    body: dict[str, Any] = {"impact": impact}
    if from_date:
        body["from_date"] = from_date
    if to_date:
        body["to_date"] = to_date
    if period:
        body["period"] = period
    if currencies:
        body["currencies"] = currencies
    if pretend_date:
        body["pretend_date"] = pretend_date
    if pretend_time:
        body["pretend_time"] = pretend_time
    if future_limit:
        body["future_limit"] = future_limit

    result = _post(
        "/api/news/save",
        json_body=body,
        headers={"X-API-Key": _key(api_key)},
    )
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# WEB SCRAPE
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def scrape_webpage(
    api_key: str = "",
    url: str = "",
    auth_user: str = "",
    auth_pass: str = "",
    bearer_token: str = "",
    session_cookie: str = "",
    custom_headers: str = "",
) -> str:
    """
    Scrape a webpage and extract its title and meaningful text content.
    Uses full browser mimicking (cookies, headers, redirects) to bypass
    basic bot protection. Returns clean text, not raw HTML.

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
        url: The URL to scrape (e.g. "https://www.reuters.com/markets")
        auth_user: Optional HTTP basic auth username
        auth_pass: Optional HTTP basic auth password
        bearer_token: Optional Bearer token for authenticated pages
        session_cookie: Optional session cookie string
        custom_headers: Optional JSON string of extra headers (e.g. '{"X-Custom": "value"}')
    """
    params: dict[str, Any] = {"api_key": _key(api_key), "url": url}
    if auth_user:
        params["auth_user"] = auth_user
    if auth_pass:
        params["auth_pass"] = auth_pass
    if bearer_token:
        params["bearer_token"] = bearer_token
    if session_cookie:
        params["session_cookie"] = session_cookie
    if custom_headers:
        params["custom_headers"] = custom_headers

    result = _get("/api/scrape", params=params)
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM & HEALTH
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_system_health(api_key: str = "") -> str:
    """
    Check health status of all API services — TradeLocker connection,
    instruments, market data, trading, news, chart, scrape, and server stats
    (CPU, memory, disk, uptime).

    Args:
        api_key: Your Arrissa API key (auto-configured if omitted)
    """
    result = _get("/api/system-health", params={"api_key": _key(api_key)})
    return _fmt(result)


@mcp.tool()
def get_smart_updater_status() -> str:
    """
    Get the status of the smart economic event updater — whether it's running,
    last periodic update time, and next scheduled event chase.
    """
    result = _get("/api/smart-updater/status")
    return _fmt(result)


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Arrissa MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run with SSE transport (for remote connections)")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"), help="SSE bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "5002")), help="SSE bind port (default: 5002)")
    parser.add_argument("--mount-path", default=os.environ.get("MCP_MOUNT_PATH", "/"), help="Mount path prefix (default: /)")
    args = parser.parse_args()

    transport = "sse" if args.sse or os.environ.get("MCP_TRANSPORT", "").lower() == "sse" else "stdio"

    if transport == "sse":
        # Set host/port/mount_path directly on the Settings object (env vars
        # are read at FastMCP construction time, which happens at module load
        # before argparse runs — so we mutate after the fact).
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if args.mount_path != "/":
            mcp.settings.mount_path = args.mount_path
        print(f"Starting Arrissa MCP Server (SSE) on {args.host}:{args.port}")
        print(f"  API: {API_BASE}")
        print(f"  Mount path: {args.mount_path}")
        print(f"  SSE endpoint: http://{args.host}:{args.port}{args.mount_path.rstrip('/')}/sse")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")

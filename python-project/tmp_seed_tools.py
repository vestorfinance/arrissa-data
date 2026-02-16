"""
TMP Tool Seeder — Indexes all Arrissa API tools into the TMP registry.

This script reads the tool definitions (from the MCP server's tool registry)
and seeds them into the TMP database with precomputed embeddings.

Run:  python tmp_seed_tools.py
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, Base, SessionLocal
from app.models.tmp_tool import TMPTool
from app.tmp_embeddings import compute_embeddings_batch, build_tool_embedding_text, rebuild_faiss_index


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS — All Arrissa API tools
# ═══════════════════════════════════════════════════════════════════════════════

ARRISSA_TOOLS = [
    {
        "name": "list_my_accounts",
        "description": "List all trading accounts with their nicknames, IDs, environment, and balances. Use this first to discover available accounts.",
        "category": "account",
        "tags": ["account", "list", "balance", "broker", "discover"],
        "examples": [
            "show me my accounts",
            "what accounts do I have",
            "list trading accounts",
            "what is my balance",
            "which brokers are connected",
        ],
        "endpoint": "/api/accounts/resolve",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "name": {"type": "str", "required": False, "description": "Filter by account nickname"},
        },
    },
    {
        "name": "get_synced_accounts",
        "description": "Get all TradeLocker brokerage accounts synced for a user. Returns credential details (email, server, environment) and all linked trading accounts.",
        "category": "account",
        "tags": ["account", "sync", "credentials", "tradelocker", "broker"],
        "examples": [
            "show synced accounts",
            "which brokers are synced",
            "get my tradelocker accounts",
            "show broker credentials",
        ],
        "endpoint": "/users/{user_id}/tradelocker/accounts",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "user_id": {"type": "int", "required": True, "description": "User ID (default 1)"},
        },
    },
    {
        "name": "add_tradelocker_credentials",
        "description": "Connect a TradeLocker brokerage account. Authenticates with TradeLocker, saves tokens, and syncs all trading accounts.",
        "category": "account",
        "tags": ["account", "connect", "authenticate", "tradelocker", "broker", "login"],
        "examples": [
            "connect my broker",
            "add tradelocker account",
            "login to tradelocker",
            "authenticate broker",
        ],
        "endpoint": "/users/{user_id}/tradelocker/credentials",
        "method": "POST",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "user_id": {"type": "int", "required": True, "description": "User ID"},
            "email": {"type": "str", "required": True, "description": "TradeLocker login email"},
            "password": {"type": "str", "required": True, "description": "TradeLocker login password"},
            "server": {"type": "str", "required": True, "description": "TradeLocker server (e.g. OSP-DEMO)"},
            "environment": {"type": "str", "required": False, "description": "demo or live (default: demo)"},
        },
    },
    {
        "name": "refresh_tradelocker_credentials",
        "description": "Refresh TradeLocker tokens and re-sync accounts for a specific credential. Use when tokens expire or accounts change.",
        "category": "account",
        "tags": ["account", "refresh", "token", "tradelocker"],
        "examples": [
            "refresh my tokens",
            "re-authenticate broker",
            "tokens expired",
            "refresh credentials",
        ],
        "endpoint": "/users/{user_id}/tradelocker/credentials/{credential_id}/refresh",
        "method": "POST",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "user_id": {"type": "int", "required": True, "description": "User ID"},
            "credential_id": {"type": "int", "required": True, "description": "Credential ID to refresh"},
        },
    },
    {
        "name": "get_instruments",
        "description": "List all tradeable instruments (symbols) available on a trading account. Use to find valid symbols for market data and trading.",
        "category": "market_data",
        "tags": ["instruments", "symbols", "forex", "crypto", "stocks", "search"],
        "examples": [
            "what symbols can I trade",
            "show available instruments",
            "search for EUR pairs",
            "find BTC symbol",
            "list forex pairs",
            "what crypto is available",
        ],
        "endpoint": "/api/instruments",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "search": {"type": "str", "required": False, "description": "Filter instruments containing this text (e.g. EUR, BTC)"},
            "type": {"type": "str", "required": False, "description": "Filter by type: FOREX, CRYPTO, STOCK, INDEX, COMMODITY"},
        },
    },
    {
        "name": "get_account_details",
        "description": "Get real-time account state from the broker — balance, equity, margin, unrealised P&L, free margin, and more.",
        "category": "account",
        "tags": ["account", "balance", "equity", "margin", "pnl", "details"],
        "examples": [
            "what is my balance",
            "show account details",
            "how much equity do I have",
            "what is my margin",
            "show unrealised P&L",
            "how much free margin",
            "what is my exposure",
        ],
        "endpoint": "/api/account-details",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "field": {"type": "str", "required": False, "description": "Return only a specific field (e.g. balance, equity, unrealizedPl)"},
        },
    },
    {
        "name": "get_market_data",
        "description": "Get OHLCV candlestick bars for a trading instrument. Returns open, high, low, close, volume data with optional moving averages, support/resistance levels, and order blocks.",
        "category": "market_data",
        "tags": ["market", "data", "candles", "ohlcv", "price", "chart", "analysis", "moving average", "support", "resistance"],
        "examples": [
            "get EURUSD price data",
            "show BTCUSD candles",
            "what is the price of gold",
            "get market data for AAPL",
            "show last 7 days of EURUSD",
            "get 4 hour candles",
            "what is the trend of BTCUSD",
            "show me support and resistance levels",
            "get moving averages",
        ],
        "endpoint": "/api/market-data",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "symbol": {"type": "str", "required": True, "description": "Trading symbol (e.g. EURUSD, BTCUSD)"},
            "timeframe": {"type": "str", "required": True, "description": "Candle timeframe: M1, M5, M15, M30, H1, H4, D1, W1, MN1"},
            "count": {"type": "int", "required": False, "description": "Number of bars (1-5000, default 100). Mutually exclusive with period"},
            "period": {"type": "str", "required": False, "description": "Time period e.g. last-7-days, last-30-minutes. Mutually exclusive with count"},
            "ma": {"type": "str", "required": False, "description": "Comma-separated MA periods (e.g. 20,50,200)"},
            "quarters_s_n_r": {"type": "bool", "required": False, "description": "Include quarter-based support & resistance levels"},
            "volume": {"type": "bool", "required": False, "description": "Include volume data"},
            "order_blocks": {"type": "bool", "required": False, "description": "Include order block analysis (requires quarters_s_n_r)"},
        },
    },
    {
        "name": "get_chart_image",
        "description": "Generate a Japanese candlestick chart as a PNG image. Supports moving averages, support/resistance, volume, order blocks, and position drawing with entry/SL/TP visualization.",
        "category": "market_data",
        "tags": ["chart", "image", "candlestick", "visual", "analysis", "trade visualization"],
        "examples": [
            "show me a chart of BTCUSD",
            "generate EURUSD chart",
            "draw a candlestick chart",
            "visualize my trade",
            "show chart with my position",
            "draw the trade on chart",
        ],
        "endpoint": "/api/chart-image",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "symbol": {"type": "str", "required": True, "description": "Trading symbol (e.g. EURUSD, BTCUSD)"},
            "timeframe": {"type": "str", "required": True, "description": "Candle timeframe: M1, M5, M15, M30, H1, H4, D1, W1, MN1"},
            "count": {"type": "int", "required": False, "description": "Number of bars (default 100)"},
            "width": {"type": "int", "required": False, "description": "Image width in pixels (400-3840, default 1200)"},
            "height": {"type": "int", "required": False, "description": "Image height in pixels (300-2160, default 700)"},
            "entry": {"type": "str", "required": False, "description": "Position entry: 'market' or datetime YYYY-MM-DD-HH:MM"},
            "direction": {"type": "str", "required": False, "description": "Position direction: LONG or SHORT"},
            "sl": {"type": "str", "required": False, "description": "Stop loss absolute price"},
            "tp": {"type": "str", "required": False, "description": "Take profit absolute price"},
        },
    },
    {
        "name": "get_orders",
        "description": "Get all active (pending) orders on the trading account. Returns order details including symbol, side, type, price, volume, SL, TP.",
        "category": "trading",
        "tags": ["orders", "pending", "limit", "stop", "active"],
        "examples": [
            "show my orders",
            "any pending orders",
            "list active orders",
            "what orders do I have open",
        ],
        "endpoint": "/api/orders",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
        },
    },
    {
        "name": "get_orders_history",
        "description": "Get order history — filled, cancelled, and rejected orders. Includes symbol names and human-readable timestamps.",
        "category": "trading",
        "tags": ["orders", "history", "filled", "cancelled", "past"],
        "examples": [
            "show order history",
            "past orders",
            "what orders were filled",
            "show cancelled orders",
        ],
        "endpoint": "/api/orders-history",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
        },
    },
    {
        "name": "get_positions",
        "description": "Get all currently open trading positions. Returns position details including symbol, side, volume, entry price, current P&L, SL, TP, and position ID.",
        "category": "trading",
        "tags": ["positions", "open", "trades", "pnl", "exposure"],
        "examples": [
            "show my positions",
            "what trades are open",
            "current exposure",
            "show open trades",
            "any open positions",
            "show P&L",
        ],
        "endpoint": "/api/positions",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
        },
    },
    {
        "name": "trade",
        "description": "Execute trading actions — buy, sell, close positions, place pending orders, modify SL/TP, break even, trailing stop, delete orders. Full trade management.",
        "category": "trading",
        "tags": ["trade", "buy", "sell", "close", "order", "stop loss", "take profit", "execute", "scalp", "position"],
        "examples": [
            "buy EURUSD",
            "sell BTCUSD 0.1 lot",
            "close all positions",
            "close losing trades",
            "set stop loss",
            "modify take profit",
            "break even",
            "place limit order",
            "scalp trade",
            "open a position",
        ],
        "endpoint": "/api/trade",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "action": {"type": "str", "required": True, "description": "Trading action: BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, CLOSE, CLOSE_ALL, CLOSE_LOSS, CLOSE_PROFIT, MODIFY_TP, MODIFY_SL, BREAK_EVEN, BREAK_EVEN_ALL, TRAIL_SL, DELETE_ORDER, DELETE_ALL_ORDERS, MODIFY_ORDER"},
            "symbol": {"type": "str", "required": False, "description": "Trading symbol (required for open/close by symbol)"},
            "volume": {"type": "str", "required": False, "description": "Trade volume in lots (required for opening trades, e.g. 0.01)"},
            "sl": {"type": "str", "required": False, "description": "Stop loss absolute price"},
            "tp": {"type": "str", "required": False, "description": "Take profit absolute price"},
            "price": {"type": "str", "required": False, "description": "Limit/stop order price (required for pending orders)"},
            "ticket": {"type": "str", "required": False, "description": "Position or order ID (required for close/modify by ticket)"},
            "new_value": {"type": "str", "required": False, "description": "New value for modifications (price for TP/SL, points for TRAIL_SL)"},
        },
    },
    {
        "name": "get_trade_history",
        "description": "Get recent trade history — filled orders, past trades with timestamps and results.",
        "category": "trading",
        "tags": ["history", "trades", "past", "filled", "results"],
        "examples": [
            "show trade history",
            "what trades did I make today",
            "recent trades",
            "last 10 trades",
            "trading results",
        ],
        "endpoint": "/api/trade",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "history": {"type": "str", "required": True, "description": "Time filter: today, last-hour, last-10, last-20, last-7days, last-30days"},
        },
    },
    {
        "name": "get_profit_summary",
        "description": "Get profit/loss summary for a time period — today, this week, this month, last 7 days, last 30 days.",
        "category": "trading",
        "tags": ["profit", "loss", "summary", "pnl", "performance", "results"],
        "examples": [
            "how much profit today",
            "weekly P&L",
            "monthly performance",
            "am I profitable",
            "total profit this month",
            "trading results for the week",
        ],
        "endpoint": "/api/trade",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "arrissa_account_id": {"type": "str", "required": True, "description": "Account ID from list_my_accounts"},
            "profit": {"type": "str", "required": True, "description": "Period: today, last-hour, this-week, this-month, last-7days, last-30days"},
        },
    },
    {
        "name": "get_economic_news",
        "description": "Get economic calendar events — news releases, data, speeches. Filter by date, currency, impact level. Supports USD, CAD, JPY, EUR, CHF, AUD, NZD, GBP.",
        "category": "news",
        "tags": ["news", "economic", "calendar", "events", "nfp", "cpi", "fomc", "interest rate"],
        "examples": [
            "any news today",
            "upcoming economic events",
            "high impact news this week",
            "USD news",
            "when is NFP",
            "FOMC meeting date",
            "what economic data is coming",
        ],
        "endpoint": "/api/news",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "from_date": {"type": "str", "required": False, "description": "Start date YYYY-MM-DD (use with to_date)"},
            "to_date": {"type": "str", "required": False, "description": "End date YYYY-MM-DD (use with from_date)"},
            "period": {"type": "str", "required": False, "description": "Time period e.g. last-7-days, last-30-days, future"},
            "currencies": {"type": "str", "required": False, "description": "Comma-separated currencies (e.g. USD,EUR,GBP). Default: all"},
            "impact": {"type": "str", "required": False, "description": "Filter: all, medium (default), high"},
        },
    },
    {
        "name": "save_economic_news",
        "description": "Fetch economic events and save them to the database for later querying. Stores events for historical analysis.",
        "category": "news",
        "tags": ["news", "save", "database", "store", "economic"],
        "examples": [
            "save economic events",
            "store news data",
            "download economic calendar",
        ],
        "endpoint": "/api/news/save",
        "method": "POST",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "from_date": {"type": "str", "required": False, "description": "Start date YYYY-MM-DD"},
            "to_date": {"type": "str", "required": False, "description": "End date YYYY-MM-DD"},
            "period": {"type": "str", "required": False, "description": "Time period e.g. last-7-days"},
            "currencies": {"type": "str", "required": False, "description": "Comma-separated currencies"},
            "impact": {"type": "str", "required": False, "description": "Filter: all, medium, high"},
        },
    },
    {
        "name": "scrape_webpage",
        "description": "Scrape a webpage and extract its title and meaningful text content. Uses browser mimicking to bypass basic bot protection. Returns clean text.",
        "category": "utility",
        "tags": ["scrape", "web", "url", "content", "extract", "browse"],
        "examples": [
            "scrape this URL",
            "get content from webpage",
            "read a website",
            "extract text from page",
            "fetch article content",
        ],
        "endpoint": "/api/scrape",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
            "url": {"type": "str", "required": True, "description": "The URL to scrape"},
            "auth_user": {"type": "str", "required": False, "description": "HTTP basic auth username"},
            "auth_pass": {"type": "str", "required": False, "description": "HTTP basic auth password"},
            "bearer_token": {"type": "str", "required": False, "description": "Bearer token for authenticated pages"},
        },
    },
    {
        "name": "get_system_health",
        "description": "Check health status of all API services — TradeLocker connection, instruments, market data, trading, news, chart, scrape, and server stats (CPU, memory, disk, uptime).",
        "category": "system",
        "tags": ["health", "status", "system", "diagnostics", "server"],
        "examples": [
            "is the system healthy",
            "check API status",
            "system diagnostics",
            "server health",
            "any errors",
        ],
        "endpoint": "/api/system-health",
        "method": "GET",
        "parameters": {
            "api_key": {"type": "str", "required": True, "description": "Your Arrissa API key"},
        },
    },
    {
        "name": "get_smart_updater_status",
        "description": "Get the status of the smart economic event updater — whether it's running, last periodic update time, and next scheduled event chase.",
        "category": "system",
        "tags": ["updater", "smart", "status", "scheduler", "events"],
        "examples": [
            "is the updater running",
            "smart updater status",
            "event updater health",
        ],
        "endpoint": "/api/smart-updater/status",
        "method": "GET",
        "parameters": {},
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# SEED
# ═══════════════════════════════════════════════════════════════════════════════

def seed_tools():
    """Seed all Arrissa tools into the TMP registry with embeddings."""
    # Ensure table exists
    Base.metadata.create_all(bind=engine)

    print(f"Seeding {len(ARRISSA_TOOLS)} tools into TMP registry...")

    # Build embedding texts
    texts = []
    for tool in ARRISSA_TOOLS:
        text = build_tool_embedding_text(
            name=tool["name"],
            description=tool["description"],
            parameters=tool.get("parameters"),
            examples=tool.get("examples"),
            tags=tool.get("tags"),
            category=tool.get("category"),
        )
        texts.append(text)

    # Batch compute embeddings
    print("Computing embeddings (this may take a moment on first run)...")
    embeddings = compute_embeddings_batch(texts)
    print(f"Computed {len(embeddings)} embeddings (dimension: {len(embeddings[0]) if embeddings else 0})")

    # Save to database
    db = SessionLocal()
    try:
        for i, tool in enumerate(ARRISSA_TOOLS):
            existing = db.query(TMPTool).filter(TMPTool.name == tool["name"]).first()

            if existing:
                existing.description = tool["description"]
                existing.parameters = tool.get("parameters")
                existing.category = tool.get("category")
                existing.tags = tool.get("tags")
                existing.examples = tool.get("examples")
                existing.endpoint = tool.get("endpoint")
                existing.method = tool.get("method", "GET")
                existing.embedding = embeddings[i] if i < len(embeddings) else None
                existing.embedding_text = texts[i]
                print(f"  Updated: {tool['name']}")
            else:
                new_tool = TMPTool(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=tool.get("parameters"),
                    category=tool.get("category"),
                    tags=tool.get("tags"),
                    examples=tool.get("examples"),
                    endpoint=tool.get("endpoint"),
                    method=tool.get("method", "GET"),
                    embedding=embeddings[i] if i < len(embeddings) else None,
                    embedding_text=texts[i],
                )
                db.add(new_tool)
                print(f"  Added: {tool['name']}")

        db.commit()
        print(f"\nDone! {len(ARRISSA_TOOLS)} tools seeded into TMP registry.")

        # Build FAISS index from all seeded tools
        print("Building FAISS vector index...")
        idx = rebuild_faiss_index()
        print(f"FAISS index built: {idx.tool_count} tools → {idx.total_vectors} vectors")
        print("TMP is ready to serve tool discovery requests at /tmp/search")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_tools()

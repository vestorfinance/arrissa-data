"""Debug embedding scores to understand why 'buy bitcoin' doesn't match trade tool."""
import sys
sys.path.insert(0, '.')

from app.tmp_embeddings import compute_embedding, cosine_similarity, build_tool_embedding_text

queries = [
    "buy bitcoin",
    "I want to buy bitcoin",
    "sell EURUSD",
    "close all my losing trades",
    "whats my balance",
    "show me a chart",
]

tools = [
    {
        "name": "trade",
        "desc": "Execute trading actions — buy, sell, close positions, place pending orders, modify SL/TP, break even, trailing stop, delete orders. Full trade management.",
        "cat": "trading",
        "tags": ["trade", "buy", "sell", "close", "order", "stop loss", "take profit", "execute", "scalp", "position"],
        "examples": ["buy EURUSD", "sell BTCUSD 0.1 lot", "close all positions", "close losing trades", "set stop loss"],
    },
    {
        "name": "get_instruments",
        "desc": "List all tradeable instruments (symbols) available on a trading account. Use to find valid symbols for market data and trading.",
        "cat": "market_data",
        "tags": ["instruments", "symbols", "forex", "crypto", "stocks", "search"],
        "examples": ["what symbols can I trade", "show available instruments", "search for EUR pairs", "find BTC symbol"],
    },
    {
        "name": "get_account_details",
        "desc": "Get real-time account state from the broker — balance, equity, margin, unrealised P&L, free margin.",
        "cat": "account",
        "tags": ["account", "balance", "equity", "margin", "details", "state"],
        "examples": ["whats my balance", "show account details", "how much equity"],
    },
    {
        "name": "get_chart_image",
        "desc": "Generate a Japanese candlestick chart as a PNG image with optional indicators and position drawing.",
        "cat": "market_data",
        "tags": ["chart", "image", "candlestick", "png", "visual"],
        "examples": ["show me a chart", "EURUSD chart", "candlestick chart"],
    },
]

# Build embedding texts and compute embeddings for each tool
print("=" * 60)
tool_embeddings = {}
for t in tools:
    text = build_tool_embedding_text(t["name"], t["desc"], tags=t["tags"], examples=t["examples"], category=t["cat"])
    emb = compute_embedding(text)
    tool_embeddings[t["name"]] = (emb, text)
    print(f"\n--- {t['name']} embedding text ---")
    print(text)

print("\n" + "=" * 60)
print("SCORES:")
print("=" * 60)

for q in queries:
    q_emb = compute_embedding(q)
    scores = []
    for name, (emb, _) in tool_embeddings.items():
        score = cosine_similarity(q_emb, emb)
        scores.append((name, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    print(f"\n  Query: \"{q}\"")
    for name, score in scores:
        marker = " <<<" if score == scores[0][1] else ""
        print(f"    {name:30s} {score:.4f}{marker}")

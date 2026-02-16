# Arrissa Data

A self-hosted trading data API that connects to [TradeLocker](https://tradelocker.com)-powered brokers. Provides market data, charting, economic news, order/position management, and an MCP server for AI agents (Claude, Cursor, VS Code Copilot, etc.).

---

## Features

- **Market Data** — OHLCV candlestick data for any tradeable instrument
- **Charting** — Generate candlestick chart images (PNG) with moving averages, S&R, and order blocks
- **Economic News** — Real-time economic calendar with impact filtering
- **Trading** — Place, modify, and close trades via API or MCP
- **Account Management** — Balance, equity, margin, P&L tracking
- **MCP Server** — Full AI agent integration (Claude, Cursor, VS Code Copilot)
- **Web Dashboard** — Browser-based UI for account management, broker connections, and settings

---

## Quick Start

### Option A: VPS Deployment (Recommended)

Deploy on any Ubuntu VPS with a single copy-paste script. Requires Ubuntu 22.04+.

**Before you start:**
1. Get a VPS from any provider (DigitalOcean, Hetzner, Contabo, etc.) — minimum 1 CPU / 1 GB RAM
2. Add your domain to [Cloudflare](https://dash.cloudflare.com)
3. In Cloudflare DNS, create an **A record** for your subdomain (e.g. `data.yourdomain.com`) pointing to your VPS IP. Set proxy to **DNS only** (gray cloud).

**Connect to your VPS** — open a terminal and run:

```bash
ssh root@YOUR_VPS_IP
```

**Then paste this entire block** (replace the 3 values at the top):

```bash
# ═══════════════════════════════════════════════════
#  EDIT THESE THREE VALUES
# ═══════════════════════════════════════════════════
MY_DOMAIN="data.yourdomain.com"
MY_MYSQL_PASS="ChooseAStr0ngPassword!"
MY_APP_NAME="Arrissa Data"
# ═══════════════════════════════════════════════════

# Generate a random API key
MY_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)

# 1. Install system dependencies
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv mariadb-server redis-server git curl \
  debian-keyring debian-archive-keyring apt-transport-https software-properties-common
systemctl start mariadb && systemctl enable mariadb
systemctl start redis-server && systemctl enable redis-server

# 2. Create database
mysql -u root -e "CREATE DATABASE IF NOT EXISTS arrissa_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -e "CREATE USER IF NOT EXISTS 'arrissa_user'@'localhost' IDENTIFIED BY '${MY_MYSQL_PASS}';"
mysql -u root -e "GRANT ALL PRIVILEGES ON arrissa_db.* TO 'arrissa_user'@'localhost'; FLUSH PRIVILEGES;"

# 3. Clone & install app
cd /root
git clone https://github.com/vestorfinance/arrissa-data.git
cd /root/arrissa-data/python-project
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create .env config
cat > .env << ENVEOF
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=arrissa_user
MYSQL_PASSWORD=${MY_MYSQL_PASS}
MYSQL_DATABASE=arrissa_db
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
API_KEY=${MY_API_KEY}
APP_NAME=${MY_APP_NAME}
TRADELOCKER_DEMO_BASE_URL=https://demo.tradelocker.com/backend-api
TRADELOCKER_LIVE_BASE_URL=https://live.tradelocker.com/backend-api
ENVEOF

# 5. Create systemd services
cat > /etc/systemd/system/arrissa-data.service << 'EOF'
[Unit]
Description=Arrissa Data API
After=network.target mariadb.service redis-server.service
[Service]
Type=simple
User=root
WorkingDirectory=/root/arrissa-data/python-project
ExecStart=/root/arrissa-data/python-project/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/arrissa-mcp.service << EOF
[Unit]
Description=Arrissa MCP Server (SSE)
After=network.target arrissa-data.service
[Service]
Type=simple
User=root
WorkingDirectory=/root/arrissa-data/python-project
ExecStart=/root/arrissa-data/python-project/.venv/bin/python mcp_server.py --sse --host 127.0.0.1 --port 5002 --mount-path /mcp
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=ARRISSA_API_URL=http://localhost:5001
Environment=ARRISSA_API_KEY=${MY_API_KEY}
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable arrissa-data arrissa-mcp

# 6. Install & configure Caddy (HTTPS reverse proxy)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy

cat > /etc/caddy/Caddyfile << CADDYEOF
${MY_DOMAIN} {
    handle_path /mcp/* {
        reverse_proxy localhost:5002 {
            flush_interval -1
            header_up Host localhost:5002
        }
    }
    handle {
        reverse_proxy localhost:5001
    }
    encode gzip
}
CADDYEOF

mkdir -p /var/log/caddy
caddy fmt --overwrite /etc/caddy/Caddyfile
systemctl enable caddy

# 7. Start everything
systemctl restart mariadb redis-server
systemctl start arrissa-data && sleep 3
systemctl start arrissa-mcp && sleep 2
systemctl restart caddy && sleep 3

echo ""
echo "════════════════════════════════════════════════"
echo "  ✓ Installation complete!"
echo "  Open: https://${MY_DOMAIN}"
echo "  MCP:  https://${MY_DOMAIN}/mcp/sse"
echo "════════════════════════════════════════════════"
```

Open **https://your-subdomain** in your browser — the setup wizard will walk you through creating your account and connecting a broker.

### Option B: Local Development

```bash
# Clone
git clone https://github.com/vestorfinance/arrissa-data.git
cd arrissa-data/python-project

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Database (MySQL/MariaDB must be running)
mysql -u root -p -e "CREATE DATABASE arrissa_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Configure
cp .env.example .env
# Edit .env with your MySQL credentials and a random API_KEY

# Start
python main.py
```

Open **http://localhost:5001** — the setup wizard will guide you through creating your account and connecting a broker.

---

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| **Python** | 3.10+ | 3.11 or 3.12 recommended |
| **MySQL** | 8.0+ | MariaDB 10.6+ also works |
| **Redis** | 6.0+ | Used for caching & smart updater |
| **Git** | any | To clone this repo |

---

## Environment Variables

Create a `.env` file in `python-project/`:

```dotenv
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=arrissa_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=arrissa_db

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

API_KEY=your_random_api_key
APP_NAME=Arrissa Data

TRADELOCKER_DEMO_BASE_URL=https://demo.tradelocker.com/backend-api
TRADELOCKER_LIVE_BASE_URL=https://live.tradelocker.com/backend-api
```

> **Tip:** Generate a random API_KEY: `python3 -c "import secrets; print(secrets.token_hex(32))"`

---

## First-Time Setup

When you open the app for the first time, a **web-based setup wizard** walks you through:

1. **Create your account** — username, email, password
2. **Connect a broker** — enter your TradeLocker credentials
3. **Done** — your API key is displayed, and you're ready to trade

No command-line setup required.

### Getting a Broker Account

Arrissa connects to **TradeLocker**-powered brokers. You need a broker account to access market data and trade.

1. Open a **FREE demo account** at a TradeLocker broker (e.g. [HeroFX](https://herofx.co))
2. Choose **TradeLocker** as your trading platform during sign-up
3. Note your email, password, and server name (e.g. `OSP-DEMO`)

---

## MCP Server (AI Agent Integration)

Arrissa includes an MCP (Model Context Protocol) server so AI agents can interact with your trading data.

### Remote SSE (Recommended for VPS)

```json
{
  "mcpServers": {
    "arrissa-trading-api": {
      "type": "sse",
      "url": "https://data.yourdomain.com/mcp/sse"
    }
  }
}
```

### Local stdio

```json
{
  "mcpServers": {
    "arrissa-trading-api": {
      "command": "python",
      "args": ["/path/to/arrissa-data/python-project/mcp_server.py"],
      "env": {
        "ARRISSA_API_URL": "http://localhost:5001",
        "ARRISSA_API_KEY": "your_api_key"
      }
    }
  }
}
```

Full setup instructions are available in the web UI at **/mcp-server**.

---

## API Endpoints

| Category | Endpoint | Method | Description |
|----------|----------|--------|-------------|
| **Health** | `/api/system-health` | GET | System status check |
| **Accounts** | `/api/account-details` | GET | Account balance, equity, margin |
| **Instruments** | `/api/instruments` | GET | List tradeable symbols |
| **Market Data** | `/api/market-data` | GET | OHLCV candlestick data |
| **Charts** | `/api/chart-image` | GET | Candlestick chart as PNG |
| **News** | `/api/news` | GET | Economic calendar events |
| **Orders** | `/api/orders` | GET | Active pending orders |
| **Positions** | `/api/positions` | GET | Open positions |
| **Trading** | `/api/trade` | GET | Execute trades |
| **Scrape** | `/api/scrape` | GET | Scrape & extract web content |

All API endpoints require an `X-API-Key` header. Get your key from the **Settings** page.

---

## Project Structure

```
python-project/
├── main.py              # Entry point — starts Flask server
├── mcp_server.py        # MCP server for AI agents
├── requirements.txt     # Python dependencies
├── .env                 # Your local config (git-ignored)
└── app/
    ├── config.py        # Environment variable loading
    ├── database.py      # SQLAlchemy engine & session
    ├── routes.py        # All Flask routes & API endpoints
    ├── smart_updater.py # Background economic event updater
    ├── news_client.py   # Economic data client
    ├── tradelocker_client.py  # TradeLocker API client
    ├── models/          # SQLAlchemy models
    └── templates/       # Jinja2 HTML templates (web UI)
```

---

## Troubleshooting

### MySQL connection refused

- Ensure MySQL is running: `sudo systemctl status mysql` (Linux) or `brew services list` (macOS)
- Check `.env` values for `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`
- Verify the database exists: `mysql -u root -p -e "SHOW DATABASES;"`

### Redis connection refused

- Ensure Redis is running: `redis-cli ping` should return `PONG`
- Check `.env` values for `REDIS_HOST` and `REDIS_PORT`

### ModuleNotFoundError

- Make sure your virtual environment is activated: `source .venv/bin/activate`
- Re-install dependencies: `pip install -r requirements.txt`

### Port 5001 already in use

```bash
lsof -i :5001       # macOS / Linux
netstat -ano | findstr :5001  # Windows
```

---

## License

Proprietary software by [Arrissa Pty Ltd](https://github.com/vestorfinance).

# Arrissa Data

A self-hosted trading data API that connects to [TradeLocker](https://tradelocker.com)-powered brokers. Provides market data, charting, economic news, order/position management, and an MCP server for AI agents (Claude, Cursor, VS Code Copilot, etc.).

---

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| **Python** | 3.10+ | 3.11 or 3.12 recommended |
| **MySQL** | 8.0+ | MariaDB 10.6+ also works |
| **Redis** | 6.0+ | Used for caching & smart updater |
| **Git** | any | To clone this repo |

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/vestorfinance/arrissa-data.git
cd arrissa-data/python-project
```

### 2. Install Dependencies

<details>
<summary><strong>macOS</strong></summary>

```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install system deps
brew install python@3.12 mysql redis git

# Start MySQL & Redis
brew services start mysql
brew services start redis

# Create virtual environment & install Python packages
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

</details>

<details>
<summary><strong>Ubuntu / Debian</strong></summary>

```bash
# Update & install system deps
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv mysql-server redis-server git

# Start MySQL & Redis
sudo systemctl start mysql
sudo systemctl enable mysql
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Secure MySQL (set root password)
sudo mysql_secure_installation

# Create virtual environment & install Python packages
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

</details>

<details>
<summary><strong>Windows</strong></summary>

```powershell
# Install Python 3.12+ from https://www.python.org/downloads/
# Install MySQL 8.0+ from https://dev.mysql.com/downloads/installer/
# Install Redis via WSL2 or https://github.com/microsoftarchive/redis/releases
# Install Git from https://git-scm.com/download/win

# Open PowerShell / Command Prompt
cd python-project

# Create virtual environment & install
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

</details>

<details>
<summary><strong>Docker / Ubuntu Container</strong></summary>

```bash
# Pull and run an Ubuntu container
docker run -it --name arrissa -p 5001:5001 ubuntu:22.04 bash

# Inside the container:
apt update && apt install -y python3 python3-pip python3-venv mysql-server redis-server git curl

# Start MySQL & Redis
service mysql start
service redis-server start

# Set MySQL root password
mysql -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'your_password'; FLUSH PRIVILEGES;"

# Clone & install
cd /opt
git clone https://github.com/vestorfinance/arrissa-data.git
cd arrissa-data/python-project

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

</details>

### 3. Create the MySQL Database

```bash
# Log in to MySQL
mysql -u root -p

# Run this SQL:
CREATE DATABASE arrissa_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
exit;
```

### 4. Configure Environment Variables

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your values
nano .env   # or use any text editor
```

Set these values in `.env`:

```dotenv
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=arrissa_db

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

API_KEY=change_me_to_a_random_secret
APP_NAME=Arrissa Data

TRADELOCKER_DEMO_BASE_URL=https://demo.tradelocker.com/backend-api
TRADELOCKER_LIVE_BASE_URL=https://live.tradelocker.com/backend-api
```

> **Tip:** Generate a random API_KEY with: `python3 -c "import secrets; print(secrets.token_hex(32))"`

### 5. First-Time Setup (Create Your Account)

```bash
python setup.py
```

This will:
- Create all database tables
- Walk you through creating your admin user account
- Display your personal API key
- Show you how to connect a broker

### 6. Open a Broker Account

Arrissa connects to **TradeLocker**-powered brokers. You need a broker account to access market data and trade.

1. **Open a FREE demo account at HeroFX:**

   **https://herofx.co/?partner_code=8138744**

2. During sign-up, choose **"TradeLocker"** as your trading platform.

3. Once registered, note your:
   - **Email** — your HeroFX login email
   - **Password** — your HeroFX login password
   - **Server** — e.g. `OSP-DEMO` for demo accounts

### 7. Start the Server

```bash
python main.py
```

The server starts at **http://localhost:5001**.

### 8. Connect Your Broker

1. Open **http://localhost:5001** in your browser
2. Log in with the credentials you created in step 5
3. Go to the **Brokers** page
4. Click **Add Broker** and enter your HeroFX / TradeLocker credentials
5. Arrissa syncs your trading accounts automatically

You're ready to go!

---

## MCP Server (AI Agent Integration)

Arrissa includes an MCP (Model Context Protocol) server so AI agents like Claude Desktop, Cursor, or VS Code Copilot can interact with your trading data.

### Setup for Claude Desktop / Cursor / VS Code

1. Get your MCP config from the web UI at **http://localhost:5001/mcp-server**

2. Or manually add to your MCP client config:

```json
{
  "mcpServers": {
    "arrissa-trading-api": {
      "command": "python",
      "args": ["/full/path/to/arrissa-data/python-project/mcp_server.py"],
      "env": {
        "ARRISSA_API_URL": "http://localhost:5001",
        "ARRISSA_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

3. Make sure the Flask server (`python main.py`) is running before using MCP tools.

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
├── setup.py             # First-run setup script
├── mcp_server.py        # MCP server for AI agents
├── mcp_config.json      # MCP config template
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── .env                 # Your local config (git-ignored)
└── app/
    ├── config.py        # Environment variable loading
    ├── database.py      # SQLAlchemy engine & session
    ├── routes.py        # All Flask routes & API endpoints
    ├── smart_updater.py # Background economic event updater
    ├── news_client.py   # TradingView economic data client
    ├── tradelocker_client.py  # TradeLocker API client
    ├── models/          # SQLAlchemy models
    │   ├── user.py
    │   ├── tradelocker.py
    │   ├── economic_event.py
    │   └── asp_tool.py
    └── templates/       # Jinja2 HTML templates (web UI)
```

---

## Troubleshooting

### MySQL connection refused

```
sqlalchemy.exc.OperationalError: Can't connect to MySQL server
```

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
# Find what's using port 5001
lsof -i :5001       # macOS / Linux
netstat -ano | findstr :5001  # Windows

# Or change the port in main.py
```

---

## Credits

Created by **Ngonidzashe Jiji** (David Richchild)

- [Facebook](https://www.facebook.com/davidrichchild/)
- [YouTube](https://www.youtube.com/@davidrichchild)
- [Instagram](https://www.instagram.com/davidrichchild/)
- [Telegram](https://t.me/real_david_richchild)

---

## License

This project is proprietary software by [Vestor Finance](https://github.com/vestorfinance).

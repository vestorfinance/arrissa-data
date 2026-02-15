import os
from dotenv import load_dotenv

load_dotenv()

# MySQL
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "arrissa_db")

DATABASE_URL = (
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
)

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# API Key
API_KEY = os.getenv("API_KEY")

# App
APP_NAME = os.getenv("APP_NAME", "Arrissa")

# TradeLocker
TRADELOCKER_DEMO_BASE_URL = os.getenv("TRADELOCKER_DEMO_BASE_URL", "https://demo.tradelocker.com/backend-api")
TRADELOCKER_LIVE_BASE_URL = os.getenv("TRADELOCKER_LIVE_BASE_URL", "https://live.tradelocker.com/backend-api")

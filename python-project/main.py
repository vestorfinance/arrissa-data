# ── Arrissa Data · Copyright (c) 2026 Arrissa Pty Ltd ──
# https://arrissadata.com · https://arrissa.trade · @davidrichchild
# See LICENSE for attribution requirements.

import redis
from sqlalchemy import text

# Integrity check — verifies attribution is intact (runs on import)
import app.integrity  # noqa: F401

from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
from app.database import engine, Base
from app.models.user import User  # noqa: F401
from app.models.tradelocker import TradeLockerCredential, TradeLockerAccount  # noqa: F401
from app.models.economic_event import EconomicEvent  # noqa: F401
from app.models.tmp_tool import TMPTool  # noqa: F401
from app.routes import app
from app.smart_updater import smart_updater


def init_db():
    """Create all tables in MySQL and run lightweight migrations."""
    Base.metadata.create_all(bind=engine)
    # --- migrations (add missing columns) ---
    migrations = [
        ("users", "site_url", "VARCHAR(500) NOT NULL DEFAULT 'http://localhost:5001'"),
        ("tradelocker_accounts", "nickname", "VARCHAR(100) NULL"),
    ]
    with engine.connect() as conn:
        for table, column, col_def in migrations:
            result = conn.execute(
                text("SELECT COUNT(*) FROM information_schema.columns "
                     "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"),
                {"t": table, "c": column},
            )
            if result.scalar() == 0:
                conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_def}"))
                print(f"  Migration: added {table}.{column}")
        conn.commit()
    print("Database tables created.")


def init_redis():
    """Return a Redis client."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )


if __name__ == "__main__":
    init_db()
    r = init_redis()
    print(f"Redis connected: {r.ping()}")
    # Start smart event updater (default: ON)
    smart_updater.start()
    print("Smart event updater started")
    print("Starting Flask server on http://localhost:5001")
    app.run(debug=True, host="0.0.0.0", port=5001, use_reloader=False)

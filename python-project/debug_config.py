#!/usr/bin/env python3
"""Temporary debug script — inspect /trade/config response structure."""
import sys, json, requests
sys.path.insert(0, ".")

from app.config import TRADELOCKER_LIVE_BASE_URL

# Read existing tokens from running server's DB
from app.database import SessionLocal
from app.models.user import User
from app.models.tradelocker import TradeLockerAccount, TradeLockerCredential

db = SessionLocal()
acct = db.query(TradeLockerAccount).first()
if not acct:
    print("No account found")
    sys.exit()

print(f"Account: accNum={acct.acc_num}, credId={acct.credential_id}, id={acct.account_id}")

# Get credential for auth
cred = db.query(TradeLockerCredential).filter(TradeLockerCredential.id == acct.credential_id).first()
if not cred:
    print("No credential found")
    sys.exit()

env = cred.environment
print(f"Credential: email={cred.email}, server={cred.server}, env={env}")

# Refresh to get fresh access token
from app.tradelocker_client import tradelocker_refresh
tokens = tradelocker_refresh(cred.refresh_token, env)
if not tokens:
    print("Auth failed")
    sys.exit()

access_token = tokens["accessToken"]
base_url = TRADELOCKER_LIVE_BASE_URL if env == "live" else "https://demo.tradelocker.com/backend-api"

# Fetch config directly
resp = requests.get(
    f"{base_url}/trade/config",
    headers={
        "accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "accNum": str(acct.acc_num),
    },
)

print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"TOP KEYS: {list(data.keys())}")
    if "d" in data:
        d = data["d"]
        if isinstance(d, dict):
            print(f"D KEYS ({len(d.keys())}): {sorted(d.keys())}")
            # Print all config sections
            for cfg_key in ["accountDetailsConfig", "ordersConfig", "ordersHistoryConfig", "positionsConfig", "filledOrdersConfig"]:
                cfg = d.get(cfg_key)
                if cfg:
                    cols = cfg.get("columns", [])
                    col_ids = [c.get("id", "?") for c in cols if isinstance(c, dict)]
                    print(f"\n{cfg_key} ({len(col_ids)} columns): {col_ids}")
            for k in sorted(d.keys()):
                if k in ["accountDetailsConfig", "ordersConfig", "ordersHistoryConfig", "positionsConfig", "filledOrdersConfig"]:
                    continue
                if "account" in k.lower() or "detail" in k.lower() or "column" in k.lower():
                    val = d[k]
                    if isinstance(val, list):
                        preview = val[:15]
                        suffix = f"... (total {len(val)} items)" if len(val) > 15 else ""
                        print(f"  ** {k}: {preview}{suffix}")
                    else:
                        print(f"  ** {k}: ({type(val).__name__}) {str(val)[:300]}")
        else:
            print(f"D is {type(d).__name__}")
    if "s" in data:
        print(f"S: {data['s']}")
else:
    print(f"Error: {resp.text[:500]}")

db.close()

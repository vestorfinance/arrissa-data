#!/usr/bin/env python3
"""
Arrissa Data — First-Run Setup

Creates the initial admin user account so you can log in to the web UI.
Run this ONCE after installing dependencies and starting MySQL/Redis.

Usage:  python setup.py
"""

import sys
import os

# Ensure we can import app modules
sys.path.insert(0, os.path.dirname(__file__))

from app.config import DATABASE_URL
from app.database import engine, Base, SessionLocal
from app.models.user import User
from app.models.tradelocker import TradeLockerCredential, TradeLockerAccount
from app.models.economic_event import EconomicEvent
from app.models.tmp_tool import TMPTool

HERO_FX_LINK = "https://herofx.co/?partner_code=8138744"

BANNER = r"""
    _                _                 ____        _
   / \   _ __ _ __  (_)___  ___  __ _ |  _ \  __ _| |_ __ _
  / _ \ | '__| '__| | / __|/ __|/ _` || | | |/ _` | __/ _` |
 / ___ \| |  | |    | \__ \\__ \ (_| || |_| | (_| | || (_| |
/_/   \_\_|  |_|    |_|___/|___/\__,_||____/ \__,_|\__\__,_|

  First-Run Setup
"""


def main():
    print(BANNER)

    # ── 1. Create database tables ─────────────────────────────────────────
    print("Creating database tables …")
    try:
        Base.metadata.create_all(bind=engine)
        print("  ✓  Database tables ready.\n")
    except Exception as e:
        print(f"\n  ✗  Could not connect to MySQL. Is the server running?\n     Error: {e}")
        print(f"\n     Check your .env file — DATABASE_URL = {DATABASE_URL}")
        sys.exit(1)

    db = SessionLocal()

    # ── 2. Check if a user already exists ─────────────────────────────────
    existing = db.query(User).first()
    if existing:
        print(f"  ℹ  A user already exists: {existing.username} ({existing.email})")
        print("     Skipping user creation. You can log in at http://localhost:5001")
        print(f"\n     Your API key: {existing.api_key}")
        db.close()
        return

    # ── 3. Collect user details ────────────────────────────────────────────
    print("Let's create your admin account.\n")

    username = input("  Username:    ").strip()
    while not username:
        username = input("  Username (required):  ").strip()

    first_name = input("  First name:  ").strip() or "Admin"
    last_name  = input("  Last name:   ").strip() or "User"

    email = input("  Email:       ").strip()
    while not email or "@" not in email:
        email = input("  Email (required):  ").strip()

    password = input("  Password:    ").strip()
    while not password or len(password) < 4:
        password = input("  Password (min 4 chars):  ").strip()

    # ── 4. Create the user ─────────────────────────────────────────────────
    user = User(
        username=username,
        first_name=first_name,
        last_name=last_name,
        email=email,
    )
    user.set_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)

    print(f"\n  ✓  User '{username}' created!")
    print(f"     API Key: {user.api_key}")

    # ── 5. Broker setup instructions ───────────────────────────────────────
    print("\n" + "─" * 60)
    print("  NEXT STEP — Connect a Broker")
    print("─" * 60)
    print(f"""
  Arrissa connects to TradeLocker-powered brokers.

  1. Open a FREE demo account at HeroFX:
     {HERO_FX_LINK}

  2. During sign-up, choose "TradeLocker" as your platform.

  3. Once registered, note your:
     • Email  (your HeroFX login email)
     • Password  (your HeroFX login password)
     • Server  (e.g. "OSP-DEMO" for demo)

  4. Start the server:
     python main.py

  5. Open the web UI at http://localhost:5001
     Log in with: {username} / <your password>

  6. Go to the "Brokers" page and click "Add Broker".
     Enter your HeroFX / TradeLocker credentials.
     Arrissa will sync your trading accounts automatically.

  That's it — you're ready to trade!
""")

    db.close()


if __name__ == "__main__":
    main()

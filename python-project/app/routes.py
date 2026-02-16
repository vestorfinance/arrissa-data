from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, session, url_for, send_file

from app.config import API_KEY
from app.config import APP_NAME
from app.database import SessionLocal, engine, Base
from app.models.user import User
from app.models.tradelocker import TradeLockerCredential, TradeLockerAccount, generate_arrissa_id
from app.models.economic_event import EconomicEvent, generate_event_type_id, importance_to_impact
from app.tradelocker_client import (
    tradelocker_authenticate,
    tradelocker_refresh,
    tradelocker_get_accounts,
    tradelocker_get_config,
    tradelocker_get_account_state,
    tradelocker_get_instruments,
    tradelocker_get_market_data,
    tradelocker_get_orders,
    tradelocker_get_orders_history,
    tradelocker_get_positions,
    tradelocker_place_order,
    tradelocker_close_position,
    tradelocker_close_all_positions,
    tradelocker_modify_position,
    tradelocker_cancel_order,
    tradelocker_cancel_all_orders,
    tradelocker_modify_order,
    TIMEFRAME_MAP,
    VALID_TIMEFRAMES,
    normalize_timeframe,
)
from app.news_client import fetch_economic_events, SUPPORTED_CURRENCIES
from app.smart_updater import smart_updater

app = Flask(__name__)
app.secret_key = API_KEY
app.jinja_env.globals["app_name"] = APP_NAME

# Register ASP (Agent Server Protocol) blueprint
from app.asp_routes import asp_bp
app.register_blueprint(asp_bp)


def _resolve_default_account(api_key, arrissa_account_id):
    """If arrissa_account_id is empty, resolve the user's default account (or first available).
    Returns the resolved arrissa_account_id string (may still be empty if no accounts exist).
    """
    if arrissa_account_id:
        return arrissa_account_id
    if not api_key:
        return arrissa_account_id
    db = get_db()
    try:
        if api_key == API_KEY:
            user = db.query(User).first()
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
        if not user:
            return arrissa_account_id
        # Use user's default if set
        if user.default_account_id:
            return user.default_account_id
        # Fall back to first account
        acc = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        return acc.arrissa_id if acc else arrissa_account_id
    finally:
        db.close()


@app.context_processor
def inject_site_url():
    """Make site_url available in every template."""
    if "user_id" in session:
        db = get_db()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if user:
                url = (user.site_url or "http://localhost:5001").rstrip("/")
                return {"site_url": url}
        finally:
            db.close()
    return {"site_url": "http://localhost:5001"}


def require_api_key(f):
    """Decorator that checks for a valid API key in the X-API-Key header.
    Accepts the internal app key OR any user's personal API key."""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return jsonify({"error": "Unauthorized — missing API key"}), 401
        if api_key == API_KEY:
            return f(*args, **kwargs)
        db = get_db()
        try:
            user = db.query(User).filter(User.api_key == api_key).first()
            if not user:
                return jsonify({"error": "Unauthorized — invalid API key"}), 401
            return f(*args, **kwargs)
        finally:
            db.close()
    return decorated


def get_db():
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


def _ensure_valid_token(db, credential, force_refresh=False):
    """
    Check if the credential's access token is expired and refresh it automatically.
    If force_refresh=True, refresh even if the token looks valid (for retries after 502).
    Updates the credential in-place and commits to DB.
    Returns (access_token, error_response) — if error_response is not None, return it.
    """
    if not credential or not credential.refresh_token:
        return None, (jsonify({"error": "No valid tokens. Re-authenticate via Brokers page."}), 401)

    # Check if token appears expired (token_expire_date is an epoch-ms string)
    token_expired = force_refresh
    if not token_expired:
        if credential.token_expire_date:
            try:
                expire_ms = int(credential.token_expire_date)
                now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
                # Refresh 60 seconds early to avoid edge-case failures
                token_expired = now_ms >= (expire_ms - 60_000)
            except (ValueError, TypeError):
                token_expired = True
        else:
            token_expired = True

    if not token_expired and credential.access_token:
        return credential.access_token, None

    # Token is expired — refresh it
    refreshed = tradelocker_refresh(credential.refresh_token, credential.environment)
    if refreshed is None:
        # Refresh token also expired — need full re-auth
        return None, (jsonify({"error": "Token refresh failed. Re-authenticate via Brokers page."}), 401)

    credential.access_token = refreshed.get("accessToken")
    credential.refresh_token = refreshed.get("refreshToken")
    credential.token_expire_date = str(refreshed.get("expireDate", ""))
    db.commit()

    return credential.access_token, None


# ─── TradeLocker Credentials ────────────────────────────────────────────────


@app.route("/users/<int:user_id>/tradelocker/credentials", methods=["POST"])
@require_api_key
def add_tradelocker_credentials(user_id):
    """
    Add TradeLocker credentials for a user.
    Authenticates with TradeLocker, saves tokens, fetches and saves accounts.

    Body: {"email": "...", "password": "...", "server": "..."}
    """
    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        server = data.get("server")
        environment = data.get("environment", "demo")  # "demo" or "live"

        if not all([email, password, server]):
            return jsonify({"error": "email, password, and server are required"}), 400

        if environment not in ("demo", "live"):
            return jsonify({"error": "environment must be 'demo' or 'live'"}), 400

        # Authenticate with TradeLocker
        auth = tradelocker_authenticate(email, password, server, environment)
        if not auth:
            return jsonify({"error": "TradeLocker authentication failed"}), 401

        # Save credential
        credential = TradeLockerCredential(
            user_id=user_id,
            email=email,
            server=server,
            environment=environment,
            access_token=auth["accessToken"],
            refresh_token=auth["refreshToken"],
            token_expire_date=auth.get("expireDate"),
        )
        db.add(credential)
        db.flush()

        # Fetch accounts from TradeLocker
        accounts = tradelocker_get_accounts(auth["accessToken"], environment)
        saved_accounts = []
        if accounts:
            for acc in accounts:
                aid = generate_arrissa_id(acc["accNum"], email)
                tl_account = TradeLockerAccount(
                    credential_id=credential.id,
                    user_id=user_id,
                    arrissa_id=aid,
                    account_id=acc["id"],
                    name=acc.get("name"),
                    currency=acc.get("currency"),
                    status=acc.get("status"),
                    acc_num=acc["accNum"],
                    account_balance=acc.get("accountBalance") or acc.get("aaccountBalance"),
                )
                db.add(tl_account)
                db.flush()
                saved_accounts.append({
                    "arrissa_id": aid,
                    "account_id": acc["id"],
                    "name": acc.get("name"),
                    "currency": acc.get("currency"),
                    "status": acc.get("status"),
                    "acc_num": acc["accNum"],
                    "account_balance": acc.get("accountBalance") or acc.get("aaccountBalance"),
                })

        db.commit()

        return jsonify({
            "message": "TradeLocker credentials added and accounts synced",
            "credential_id": credential.id,
            "accounts": saved_accounts,
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Refresh TradeLocker Accounts ────────────────────────────────────────────


@app.route("/users/<int:user_id>/tradelocker/credentials/<int:credential_id>/refresh", methods=["POST"])
@require_api_key
def refresh_tradelocker(user_id, credential_id):
    """
    Refresh TradeLocker tokens and re-sync accounts for a credential.
    """
    db = get_db()
    try:
        credential = (
            db.query(TradeLockerCredential)
            .filter(
                TradeLockerCredential.id == credential_id,
                TradeLockerCredential.user_id == user_id,
            )
            .first()
        )
        if not credential:
            return jsonify({"error": "Credential not found"}), 404

        # Refresh tokens
        refreshed = tradelocker_refresh(credential.refresh_token, credential.environment)
        if not refreshed:
            return jsonify({"error": "Token refresh failed — credentials may be expired"}), 401

        credential.access_token = refreshed["accessToken"]
        credential.refresh_token = refreshed["refreshToken"]
        credential.token_expire_date = refreshed.get("expireDate")

        # Re-fetch accounts
        accounts = tradelocker_get_accounts(refreshed["accessToken"], credential.environment)
        updated_accounts = []
        if accounts:
            # Remove old accounts for this credential
            db.query(TradeLockerAccount).filter(
                TradeLockerAccount.credential_id == credential_id
            ).delete()

            for acc in accounts:
                aid = generate_arrissa_id(acc["accNum"], credential.email)
                tl_account = TradeLockerAccount(
                    credential_id=credential.id,
                    user_id=user_id,
                    arrissa_id=aid,
                    account_id=acc["id"],
                    name=acc.get("name"),
                    currency=acc.get("currency"),
                    status=acc.get("status"),
                    acc_num=acc["accNum"],
                    account_balance=acc.get("accountBalance") or acc.get("aaccountBalance"),
                )
                db.add(tl_account)
                db.flush()
                updated_accounts.append({
                    "arrissa_id": aid,
                    "account_id": acc["id"],
                    "name": acc.get("name"),
                    "currency": acc.get("currency"),
                    "status": acc.get("status"),
                    "acc_num": acc["accNum"],
                    "account_balance": acc.get("accountBalance") or acc.get("aaccountBalance"),
                })

        db.commit()

        return jsonify({
            "message": "TradeLocker tokens refreshed and accounts re-synced",
            "credential_id": credential.id,
            "token_expire_date": refreshed.get("expireDate"),
            "accounts": updated_accounts,
        }), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Check Synced Accounts Status ───────────────────────────────────────────


@app.route("/users/<int:user_id>/tradelocker/accounts", methods=["GET"])
@require_api_key
def get_synced_accounts(user_id):
    """
    Return all TradeLocker accounts synced in the database for this user.
    """
    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        credentials = (
            db.query(TradeLockerCredential)
            .filter(TradeLockerCredential.user_id == user_id)
            .all()
        )

        result = []
        for cred in credentials:
            accounts = (
                db.query(TradeLockerAccount)
                .filter(TradeLockerAccount.credential_id == cred.id)
                .all()
            )
            result.append({
                "credential_id": cred.id,
                "tradelocker_email": cred.email,
                "server": cred.server,
                "token_expire_date": cred.token_expire_date,
                "accounts": [
                    {
                        "id": a.id,
                        "arrissa_id": a.arrissa_id,
                        "account_id": a.account_id,
                        "name": a.name,
                        "currency": a.currency,
                        "status": a.status,
                        "acc_num": a.acc_num,
                        "account_balance": a.account_balance,
                    }
                    for a in accounts
                ],
            })

        return jsonify({"user_id": user_id, "credentials": result}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# WEB UI ROUTES
# ═══════════════════════════════════════════════════════════════════════════


def login_required(f):
    """Redirect to /login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def _needs_setup():
    """Return True if no users exist (first-run setup required)."""
    db = get_db()
    try:
        return db.query(User).count() == 0
    finally:
        db.close()


@app.route("/")
def index():
    if _needs_setup():
        return redirect("/setup")
    if "user_id" in session:
        return redirect("/dashboard")
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if _needs_setup():
        return redirect("/setup")

    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")

    db = get_db()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.check_password(password):
            return render_template("login.html", error="Invalid username or password")

        session["user_id"] = user.id
        return redirect("/dashboard")
    finally:
        db.close()


# ─── Installation Guide (public) ─────────────────────────────────────────────

@app.route("/install")
def install_guide():
    """Public VPS installation guide with generated commands."""
    return render_template("install_guide.html", app_name=APP_NAME)


# ─── First-Run Setup Wizard ──────────────────────────────────────────────────

@app.route("/setup")
def setup_wizard():
    """Show the web-based setup wizard (only if no users exist)."""
    if not _needs_setup():
        return redirect("/login")
    return render_template("setup.html", app_name=APP_NAME)


@app.route("/setup/create-account", methods=["POST"])
def setup_create_account():
    """API: Create the first admin user account."""
    if not _needs_setup():
        return jsonify({"error": "Setup already completed. An account already exists."}), 400

    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    first_name = (data.get("first_name") or "").strip() or "Admin"
    last_name = (data.get("last_name") or "").strip() or "User"
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not username:
        return jsonify({"error": "Username is required."}), 400
    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required."}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters."}), 400

    db = get_db()
    try:
        user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
        user.set_password(password)
        # Detect site URL from the request
        site_url = request.host_url.rstrip("/")
        user.site_url = site_url
        db.add(user)
        db.commit()
        db.refresh(user)

        # Auto-login
        session["user_id"] = user.id

        return jsonify({"ok": True, "api_key": user.api_key, "user_id": user.id})
    except Exception as e:
        db.rollback()
        err = str(e)
        if "Duplicate" in err and "username" in err:
            return jsonify({"error": "That username is already taken."}), 400
        if "Duplicate" in err and "email" in err:
            return jsonify({"error": "That email is already registered."}), 400
        return jsonify({"error": f"Could not create account: {err}"}), 500
    finally:
        db.close()


@app.route("/setup/connect-broker", methods=["POST"])
def setup_connect_broker():
    """API: Connect a TradeLocker broker during setup."""
    if "user_id" not in session:
        return jsonify({"error": "Please create your account first (step 1)."}), 401

    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    server = (data.get("server") or "").strip()
    environment = (data.get("environment") or "demo").strip().lower()

    if not email or not password or not server:
        return jsonify({"error": "Email, password, and server are all required."}), 400

    auth = tradelocker_authenticate(email, password, server, environment)
    if not auth:
        return jsonify({"error": "TradeLocker authentication failed. Check your credentials and server name."}), 400

    db = get_db()
    try:
        user_id = session["user_id"]
        credential = TradeLockerCredential(
            user_id=user_id,
            email=email,
            server=server,
            environment=environment,
            access_token=auth["accessToken"],
            refresh_token=auth["refreshToken"],
            token_expire_date=auth.get("expireDate"),
        )
        db.add(credential)
        db.flush()

        accounts = tradelocker_get_accounts(auth["accessToken"], environment)
        synced = 0
        if accounts:
            for acc in accounts:
                db.add(TradeLockerAccount(
                    credential_id=credential.id,
                    user_id=user_id,
                    arrissa_id=generate_arrissa_id(acc["accNum"], email),
                    account_id=acc["id"],
                    name=acc.get("name"),
                    currency=acc.get("currency"),
                    status=acc.get("status"),
                    acc_num=acc["accNum"],
                    account_balance=acc.get("accountBalance") or acc.get("aaccountBalance"),
                ))
                synced += 1

        db.commit()
        return jsonify({"ok": True, "accounts_synced": synced})
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Failed to connect broker: {e}"}), 500
    finally:
        db.close()


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        credentials = (
            db.query(TradeLockerCredential)
            .filter(TradeLockerCredential.user_id == user.id)
            .all()
        )

        creds_data = []
        all_accounts = []
        total_accounts = 0
        active_accounts = 0

        for cred in credentials:
            accounts = (
                db.query(TradeLockerAccount)
                .filter(TradeLockerAccount.credential_id == cred.id)
                .all()
            )
            creds_data.append({
                "id": cred.id,
                "email": cred.email,
                "server": cred.server,
                "environment": cred.environment,
                "accounts": accounts,
            })
            for acc in accounts:
                total_accounts += 1
                if acc.status == "ACTIVE":
                    active_accounts += 1
                all_accounts.append({
                    "account": acc,
                    "broker_email": cred.email,
                    "environment": cred.environment,
                })

        # ── Server stats ────────────────────────────────────────────────
        import psutil, platform, os as _os
        _process = psutil.Process(_os.getpid())

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
        uptime_delta = datetime.now(tz=timezone.utc) - boot_time

        server_stats = {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=0.3),
            "mem_total_gb": round(mem.total / (1024 ** 3), 1),
            "mem_used_gb": round(mem.used / (1024 ** 3), 1),
            "mem_percent": mem.percent,
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "disk_used_gb": round(disk.used / (1024 ** 3), 1),
            "disk_percent": disk.percent,
            "process_mem_mb": round(_process.memory_info().rss / (1024 ** 2), 1),
            "uptime": str(uptime_delta).split(".")[0],
        }

        # ── Smart updater status ────────────────────────────────────────
        updater_status = smart_updater.status()

        return render_template(
            "dashboard.html",
            user=user,
            credentials=creds_data,
            all_accounts=all_accounts,
            total_accounts=total_accounts,
            active_accounts=active_accounts,
            server_stats=server_stats,
            updater_status=updater_status,
            active_page="dashboard",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


@app.route("/api/system-health")
def api_system_health():
    """
    Returns health status of each API endpoint plus server stats.
    Called via AJAX from the dashboard for live green/red dot status.
    """
    import psutil, platform, os as _os, time as _time

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not api_key:
        return jsonify({"error": "Missing api_key"}), 401

    results = {}

    # ── Check each external-facing API ──────────────────────────────
    api_checks = {
        "tradelocker_auth": {"desc": "TradeLocker Authentication", "icon": "key"},
        "instruments": {"desc": "Instruments API", "icon": "file-code"},
        "account_details": {"desc": "Account Details API", "icon": "user-circle"},
        "market_data": {"desc": "Market Data API", "icon": "candlestick-chart"},
        "orders": {"desc": "Orders API", "icon": "list-ordered"},
        "positions": {"desc": "Positions API", "icon": "wallet"},
        "trading": {"desc": "Trading API", "icon": "arrow-left-right"},
        "news": {"desc": "Economic Calendar API", "icon": "newspaper"},
        "chart_image": {"desc": "Chart Image API", "icon": "image"},
        "scrape": {"desc": "Web Scrape API", "icon": "globe"},
    }

    db = get_db()
    try:
        # Validate user
        user = None
        if api_key == API_KEY:
            user = db.query(User).first()
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 401

        # Check if we have any valid TradeLocker credentials
        cred = db.query(TradeLockerCredential).filter(
            TradeLockerCredential.user_id == user.id
        ).first()
        account = None
        tl_connected = False
        if cred:
            account = db.query(TradeLockerAccount).filter(
                TradeLockerAccount.credential_id == cred.id
            ).first()
            # Try a token refresh to validate connection
            if cred.access_token:
                try:
                    token, err = _ensure_valid_token(db, cred)
                    tl_connected = token is not None
                except Exception:
                    tl_connected = False

        # TradeLocker Auth
        results["tradelocker_auth"] = {
            "status": "healthy" if tl_connected else "unhealthy",
            "detail": "Connected" if tl_connected else "No valid credentials",
            **api_checks["tradelocker_auth"],
        }

        # TL-dependent APIs all healthy if TL is connected and account exists
        tl_apis = ["instruments", "account_details", "market_data", "orders", "positions", "trading"]
        for api_name in tl_apis:
            healthy = tl_connected and account is not None
            results[api_name] = {
                "status": "healthy" if healthy else "unhealthy",
                "detail": "Ready" if healthy else ("No account" if tl_connected else "TL disconnected"),
                **api_checks[api_name],
            }

        # Chart Image — depends on market data + matplotlib
        chart_ok = tl_connected and account is not None
        try:
            import matplotlib
            chart_detail = "Ready" if chart_ok else "TL disconnected"
        except ImportError:
            chart_ok = False
            chart_detail = "matplotlib not installed"
        results["chart_image"] = {
            "status": "healthy" if chart_ok else "unhealthy",
            "detail": chart_detail,
            **api_checks["chart_image"],
        }

        # News / Economic Calendar — test the external TradingView endpoint
        news_ok = False
        news_detail = "Unknown"
        try:
            import requests as _req
            r = _req.get(
                "https://economic-calendar.tradingview.com/events",
                headers={"Origin": "https://in.tradingview.com"},
                params={
                    "from": datetime.now(tz=timezone.utc).isoformat(),
                    "to": datetime.now(tz=timezone.utc).isoformat(),
                    "countries": "US",
                    "minImportance": 0,
                },
                timeout=5,
            )
            news_ok = r.status_code == 200
            news_detail = "Connected" if news_ok else f"HTTP {r.status_code}"
        except Exception as ex:
            news_detail = str(ex)[:60]
        results["news"] = {
            "status": "healthy" if news_ok else "unhealthy",
            "detail": news_detail,
            **api_checks["news"],
        }

        # Scrape — always available (just uses curl/requests internally)
        results["scrape"] = {
            "status": "healthy",
            "detail": "Ready",
            **api_checks["scrape"],
        }

        # SmartUpdater
        us = smart_updater.status()
        results["smart_updater"] = {
            "status": "healthy" if us["running"] else ("disabled" if not us["enabled"] else "unhealthy"),
            "detail": f"{'Running' if us['running'] else 'Stopped'} — last periodic: {us.get('last_periodic_update', 'never')}",
            "desc": "Economic Data Fetcher",
            "icon": "refresh-cw",
            "enabled": us["enabled"],
            "running": us["running"],
        }

        # Overall
        all_statuses = [v["status"] for v in results.values()]
        healthy_count = sum(1 for s in all_statuses if s == "healthy")
        total_count = len(all_statuses)

        # Server stats
        _process = psutil.Process(_os.getpid())
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
        uptime_delta = datetime.now(tz=timezone.utc) - boot_time

        return jsonify({
            "overall": "healthy" if healthy_count == total_count else ("degraded" if healthy_count > total_count // 2 else "unhealthy"),
            "healthy_count": healthy_count,
            "total_count": total_count,
            "services": results,
            "server": {
                "hostname": platform.node(),
                "os": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=0.3),
                "mem_total_gb": round(mem.total / (1024 ** 3), 1),
                "mem_used_gb": round(mem.used / (1024 ** 3), 1),
                "mem_percent": mem.percent,
                "disk_total_gb": round(disk.total / (1024 ** 3), 1),
                "disk_used_gb": round(disk.used / (1024 ** 3), 1),
                "disk_percent": disk.percent,
                "process_mem_mb": round(_process.memory_info().rss / (1024 ** 2), 1),
                "uptime": str(uptime_delta).split(".")[0],
            },
            "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/brokers")
@login_required
def brokers():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        credentials = (
            db.query(TradeLockerCredential)
            .filter(TradeLockerCredential.user_id == user.id)
            .all()
        )

        creds_data = []
        for cred in credentials:
            accounts = (
                db.query(TradeLockerAccount)
                .filter(TradeLockerAccount.credential_id == cred.id)
                .all()
            )
            creds_data.append({
                "id": cred.id,
                "email": cred.email,
                "server": cred.server,
                "environment": cred.environment,
                "accounts": accounts,
            })

        return render_template(
            "brokers.html",
            user=user,
            credentials=creds_data,
            active_page="brokers",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


@app.route("/brokers/add", methods=["POST"])
@login_required
def brokers_add():
    db = get_db()
    try:
        user_id = session["user_id"]
        email = request.form.get("email")
        password = request.form.get("password")
        server = request.form.get("server")
        environment = request.form.get("environment", "demo")

        auth = tradelocker_authenticate(email, password, server, environment)
        if not auth:
            return redirect("/brokers?error=TradeLocker+authentication+failed")

        credential = TradeLockerCredential(
            user_id=user_id,
            email=email,
            server=server,
            environment=environment,
            access_token=auth["accessToken"],
            refresh_token=auth["refreshToken"],
            token_expire_date=auth.get("expireDate"),
        )
        db.add(credential)
        db.flush()

        accounts = tradelocker_get_accounts(auth["accessToken"], environment)
        if accounts:
            for acc in accounts:
                db.add(TradeLockerAccount(
                    credential_id=credential.id,
                    user_id=user_id,
                    arrissa_id=generate_arrissa_id(acc["accNum"], email),
                    account_id=acc["id"],
                    name=acc.get("name"),
                    currency=acc.get("currency"),
                    status=acc.get("status"),
                    acc_num=acc["accNum"],
                    account_balance=acc.get("accountBalance") or acc.get("aaccountBalance"),
                ))

        db.commit()
        return redirect("/brokers?message=Broker+connected+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/brokers?error={e}")
    finally:
        db.close()


@app.route("/brokers/refresh/<int:credential_id>", methods=["POST"])
@login_required
def brokers_refresh(credential_id):
    db = get_db()
    try:
        user_id = session["user_id"]
        credential = (
            db.query(TradeLockerCredential)
            .filter(TradeLockerCredential.id == credential_id, TradeLockerCredential.user_id == user_id)
            .first()
        )
        if not credential:
            return redirect("/brokers?error=Credential+not+found")

        refreshed = tradelocker_refresh(credential.refresh_token, credential.environment)
        if not refreshed:
            return redirect("/brokers?error=Token+refresh+failed")

        credential.access_token = refreshed["accessToken"]
        credential.refresh_token = refreshed["refreshToken"]
        credential.token_expire_date = refreshed.get("expireDate")

        db.query(TradeLockerAccount).filter(TradeLockerAccount.credential_id == credential_id).delete()

        accounts = tradelocker_get_accounts(refreshed["accessToken"], credential.environment)
        if accounts:
            for acc in accounts:
                db.add(TradeLockerAccount(
                    credential_id=credential.id,
                    user_id=user_id,
                    arrissa_id=generate_arrissa_id(acc["accNum"], credential.email),
                    account_id=acc["id"],
                    name=acc.get("name"),
                    currency=acc.get("currency"),
                    status=acc.get("status"),
                    acc_num=acc["accNum"],
                    account_balance=acc.get("accountBalance") or acc.get("aaccountBalance"),
                ))

        db.commit()
        return redirect("/brokers?message=Accounts+refreshed+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/brokers?error={e}")
    finally:
        db.close()


@app.route("/brokers/delete/<int:credential_id>", methods=["POST"])
@login_required
def brokers_delete(credential_id):
    db = get_db()
    try:
        user_id = session["user_id"]
        credential = (
            db.query(TradeLockerCredential)
            .filter(TradeLockerCredential.id == credential_id, TradeLockerCredential.user_id == user_id)
            .first()
        )
        if not credential:
            return redirect("/brokers?error=Credential+not+found")

        db.query(TradeLockerAccount).filter(TradeLockerAccount.credential_id == credential_id).delete()
        db.delete(credential)
        db.commit()
        return redirect("/brokers?message=Broker+removed+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/brokers?error={e}")
    finally:
        db.close()


@app.route("/brokers/account/<string:arrissa_id>/nickname", methods=["POST"])
@login_required
def brokers_update_nickname(arrissa_id):
    """Set a nickname for a trading account (used by MCP to resolve accounts by name)."""
    db = get_db()
    try:
        account = (
            db.query(TradeLockerAccount)
            .filter(TradeLockerAccount.arrissa_id == arrissa_id,
                    TradeLockerAccount.user_id == session["user_id"])
            .first()
        )
        if not account:
            return redirect("/brokers?error=Account+not+found")
        account.nickname = request.form.get("nickname", "").strip() or None
        db.commit()
        return redirect("/brokers?message=Nickname+updated")
    except Exception as e:
        db.rollback()
        return redirect(f"/brokers?error={e}")
    finally:
        db.close()


# ─── API: Resolve account by nickname (for MCP server) ──────────────────


@app.route("/api/accounts/resolve")
def api_resolve_account():
    """Resolve an account by nickname or return all accounts.
    Query params: api_key, name (optional — nickname to find), user_id (default 1)
    Returns: { accounts: [...] } with arrissa_id, nickname, name, environment, etc.
    """
    api_key = request.args.get("api_key")
    if not api_key:
        return jsonify({"error": "Missing api_key"}), 401

    db = get_db()
    try:
        # Accept both internal API_KEY and user API keys
        if api_key == API_KEY:
            user = db.query(User).first()  # internal key → use first user
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 401

        query = db.query(TradeLockerAccount).filter(TradeLockerAccount.user_id == user.id)
        name_filter = request.args.get("name", "").strip().lower()

        accounts = query.all()
        results = []
        for acc in accounts:
            cred = acc.credential
            entry = {
                "arrissa_account_id": acc.arrissa_id,
                "nickname": acc.nickname,
                "account_name": acc.name,
                "acc_num": acc.acc_num,
                "currency": acc.currency,
                "status": acc.status,
                "balance": acc.account_balance,
                "environment": cred.environment if cred else None,
                "server": cred.server if cred else None,
                "broker_email": cred.email if cred else None,
            }
            results.append(entry)

        # If a name filter was given, fuzzy match on nickname, account_name, environment
        if name_filter:
            matched = [
                a for a in results
                if (a["nickname"] and name_filter in a["nickname"].lower())
                or (a["account_name"] and name_filter in a["account_name"].lower())
                or (a["environment"] and name_filter in a["environment"].lower())
                or (a["arrissa_account_id"] and name_filter in a["arrissa_account_id"].lower())
            ]
            return jsonify({"accounts": matched, "query": name_filter, "default_account_id": user.default_account_id})

        # Sort default account to the top
        if user.default_account_id:
            results.sort(key=lambda a: (0 if a["arrissa_account_id"] == user.default_account_id else 1))

        return jsonify({"accounts": results, "default_account_id": user.default_account_id})
    finally:
        db.close()


# ─── Settings ─────────────────────────────────────────────────────────────


@app.route("/settings")
@login_required
def settings():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        accounts = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).all()
        return render_template(
            "settings.html",
            user=user,
            api_key=user.api_key,
            accounts=accounts,
            default_account_id=user.default_account_id,
            active_page="settings",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


@app.route("/settings/regenerate-key", methods=["POST"])
@login_required
def regenerate_api_key():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        user.regenerate_api_key()
        db.commit()
        return redirect("/settings?message=API+key+regenerated+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/settings?error={e}")
    finally:
        db.close()


@app.route("/settings/change-password", methods=["POST"])
@login_required
def change_password():
    current = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user.check_password(current):
            return redirect("/settings?error=Current+password+is+incorrect")
        if len(new_pw) < 6:
            return redirect("/settings?error=New+password+must+be+at+least+6+characters")
        if new_pw != confirm:
            return redirect("/settings?error=New+passwords+do+not+match")
        user.set_password(new_pw)
        db.commit()
        return redirect("/settings?message=Password+changed+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/settings?error={e}")
    finally:
        db.close()


@app.route("/settings/update-default-account", methods=["POST"])
@login_required
def update_default_account():
    new_account_id = request.form.get("default_account_id", "").strip()
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if new_account_id:
            # Verify the account belongs to this user
            acc = db.query(TradeLockerAccount).filter(
                TradeLockerAccount.arrissa_id == new_account_id,
                TradeLockerAccount.user_id == user.id
            ).first()
            if not acc:
                return redirect("/settings?error=Account+not+found+or+not+yours")
            user.default_account_id = new_account_id
        else:
            user.default_account_id = None
        db.commit()
        return redirect("/settings?message=Default+account+updated+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/settings?error={e}")
    finally:
        db.close()


@app.route("/settings/update-site-url", methods=["POST"])
@login_required
def update_site_url():
    new_url = request.form.get("site_url", "").strip().rstrip("/")
    if not new_url:
        return redirect("/settings?error=Site+URL+cannot+be+empty")
    if not new_url.startswith(("http://", "https://")):
        return redirect("/settings?error=Site+URL+must+start+with+http://+or+https://")
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        user.site_url = new_url
        db.commit()
        return redirect("/settings?message=Site+URL+updated+successfully")
    except Exception as e:
        db.rollback()
        return redirect(f"/settings?error={e}")
    finally:
        db.close()


# ─── Public API: Instruments ──────────────────────────────────────────────


@app.route("/api/instruments")
def api_instruments():
    """
    List instruments available to a specific account.
    Accepts api_key and arrissa_account_id via headers (X-API-Key, X-Arrissa-Account-Id)
    or query parameters (?api_key=&arrissa_account_id=).
    Optional: ?search=EUR to filter, ?type=FOREX to filter by type.
    """
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
    search = request.args.get("search", "").strip().upper()
    type_filter = request.args.get("type", "").strip().upper()

    if not api_key:
        return jsonify({"error": "Missing api_key (header X-API-Key or query param)"}), 401
    arrissa_account_id = _resolve_default_account(api_key, arrissa_account_id)
    if not arrissa_account_id:
        return jsonify({"error": "Missing arrissa_account_id (header X-Arrissa-Account-Id or query param)"}), 400

    db = get_db()
    try:
        # Validate API key
        if api_key == API_KEY:
            user = None
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 401

        # Find the account by arrissa_id
        account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.arrissa_id == arrissa_account_id
        ).first()
        if not account:
            return jsonify({"error": f"Account not found for arrissa_account_id: {arrissa_account_id}"}), 404

        # If user key was used, verify they own this account
        if user and account.user_id != user.id:
            return jsonify({"error": "You do not have access to this account"}), 403

        # Get the credential and ensure token is valid
        credential = db.query(TradeLockerCredential).filter(
            TradeLockerCredential.id == account.credential_id
        ).first()
        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        # Fetch instruments from TradeLocker (retry once on failure after refresh)
        instruments = tradelocker_get_instruments(
            access_token=access_token,
            account_id=account.account_id,
            acc_num=account.acc_num,
            environment=credential.environment,
        )
        if instruments is None:
            # Token may have just expired mid-flight — force refresh and retry
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            instruments = tradelocker_get_instruments(
                access_token=access_token,
                account_id=account.account_id,
                acc_num=account.acc_num,
                environment=credential.environment,
            )
        if instruments is None:
            return jsonify({"error": "Failed to fetch instruments from TradeLocker after token refresh."}), 502

        # Build response — only ticker symbols
        results = []
        for inst in instruments:
            name = inst.get("name", "")
            inst_type = inst.get("type", "")

            if search and search not in name.upper():
                continue
            if type_filter and inst_type.upper() != type_filter:
                continue

            results.append({
                "symbol": name,
                "type": inst_type,
            })

        results.sort(key=lambda x: x["symbol"])
        all_types = sorted(set(inst.get("type", "") for inst in instruments if inst.get("type")))

        wrapper_key = f"arrissa_data_{credential.server}_{credential.environment}"
        return jsonify({
            wrapper_key: {
                "arrissa_account_id": arrissa_account_id,
                "total": len(results),
                "types": all_types,
                "instruments": results,
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Instruments API Guide Page ───────────────────────────────────────────


@app.route("/instruments-api")
@login_required
def instruments_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        first_account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        example_account_id = first_account.arrissa_id if first_account else "ACCTID"
        return render_template(
            "api_guide.html",
            user=user,
            api_key=user.api_key,
            example_account_id=example_account_id,
            active_page="instruments_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


# ─── Shared Period Helper ────────────────────────────────────────────────


def _period_delta(unit, amount):
    """Convert a period unit + amount to a timedelta. Returns None for unknown unit."""
    if unit == "minute":
        return timedelta(minutes=amount)
    elif unit == "hour":
        return timedelta(hours=amount)
    elif unit == "day":
        return timedelta(days=amount)
    elif unit == "week":
        return timedelta(weeks=amount)
    elif unit == "month":
        return timedelta(days=amount * 30)
    elif unit == "year":
        return timedelta(days=amount * 365)
    return None


# ─── Public API: Market Data ─────────────────────────────────────────────


@app.route("/api/market-data")
def api_market_data():
    """
    Get OHLCV candlestick bars for a symbol.
    Accepts api_key and arrissa_account_id via headers or query params.
    Required: symbol, timeframe. Optional: count (default 100, max 5000) or period (e.g. last-7-days).
    count and period are mutually exclusive.
    """
    import re as _re

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
    symbol = request.args.get("symbol", "").strip().upper()
    timeframe = normalize_timeframe(request.args.get("timeframe", ""))
    count_raw = request.args.get("count", "").strip()
    period_raw = request.args.get("period", "").strip().lower()
    future_limit_raw = request.args.get("future_limit", "").strip().lower()
    pretend_date_raw = request.args.get("pretend_date", "").strip()
    pretend_time_raw = request.args.get("pretend_time", "").strip()
    ma_raw = request.args.get("ma", "").strip()
    quarters_snr = request.args.get("quarters_s_n_r", "").strip().lower() in ("true", "1", "yes")
    show_volume = request.args.get("volume", "").strip().lower() in ("true", "1", "yes")
    order_blocks = request.args.get("order_blocks", "").strip().lower() in ("true", "1", "yes")

    # ── Parse MA periods ──
    ma_periods = []
    if ma_raw:
        for part in ma_raw.split(","):
            part = part.strip()
            if part:
                try:
                    p = int(part)
                    if p < 2 or p > 500:
                        return jsonify({"error": f"MA period must be between 2 and 500, got {p}"}), 400
                    ma_periods.append(p)
                except ValueError:
                    return jsonify({"error": f"Invalid MA period: {part}. Must be an integer."}), 400
    ma_periods = sorted(set(ma_periods))  # deduplicate & sort
    max_ma = max(ma_periods) if ma_periods else 0

    if not api_key:
        return jsonify({"error": "Missing api_key (header X-API-Key or query param)"}), 401
    arrissa_account_id = _resolve_default_account(api_key, arrissa_account_id)
    if not arrissa_account_id:
        return jsonify({"error": "Missing arrissa_account_id (header X-Arrissa-Account-Id or query param)"}), 400
    if not symbol:
        return jsonify({"error": "Missing required parameter: symbol"}), 400
    if not timeframe:
        return jsonify({"error": "Missing required parameter: timeframe"}), 400
    if timeframe not in VALID_TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}. Valid: {', '.join(VALID_TIMEFRAMES)}"}), 400

    # period and count are mutually exclusive
    if count_raw and period_raw:
        return jsonify({"error": "Cannot use both count and period. Use one or the other."}), 400

    # future requires period=future + future_limit
    is_future = period_raw == "future"
    if is_future and not future_limit_raw:
        return jsonify({"error": "period=future requires future_limit parameter (e.g. next-2-days)"}), 400
    if is_future and not pretend_date_raw:
        return jsonify({"error": "period=future requires pretend_date in market data API (can't get future market data without pretending)"}), 400
    if future_limit_raw and not is_future:
        return jsonify({"error": "future_limit can only be used with period=future"}), 400

    # Parse pretend_date / pretend_time (simulate a different "now")
    pretend_now_ms = None
    pretend_dt = None
    if pretend_date_raw:
        try:
            time_str = pretend_time_raw or "00:00"
            pretend_dt = datetime.strptime(f"{pretend_date_raw} {time_str}", "%Y-%m-%d %H:%M")
            pretend_dt = pretend_dt.replace(tzinfo=timezone.utc)
            pretend_now_ms = int(pretend_dt.timestamp() * 1000)
        except ValueError:
            return jsonify({"error": "Invalid pretend_date/pretend_time format. Use pretend_date=YYYY-MM-DD and pretend_time=HH:MM"}), 400

    count = None
    period_from_ms = None
    future_to_ms = None

    if is_future:
        # Parse future_limit: next-X-unit
        m = _re.match(r"^next-(\d+)-(minutes?|hours?|days?|weeks?|months?|years?)$", future_limit_raw)
        if not m:
            return jsonify({"error": "Invalid future_limit format. Use: next-X-minutes, next-X-hours, next-X-days, etc."}), 400
        amount = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if amount < 1:
            return jsonify({"error": "future_limit amount must be at least 1"}), 400
        delta = _period_delta(unit, amount)
        if delta is None:
            return jsonify({"error": f"Unknown future_limit unit: {unit}"}), 400
        # from = pretend_now, to = pretend_now + delta
        period_from_ms = pretend_now_ms
        future_to_ms = int((pretend_dt + delta).timestamp() * 1000)
    elif period_raw:
        # Parse period: last-X-minutes, last-X-hours, last-X-days, last-X-weeks, last-X-months, last-X-years
        m = _re.match(r"^last-(\d+)-(minutes?|hours?|days?|weeks?|months?|years?)$", period_raw)
        if not m:
            return jsonify({"error": "Invalid period format. Use: last-X-minutes, last-X-hours, last-X-days, last-X-weeks, last-X-months, last-X-years, or future (e.g. last-30-minutes, last-7-days)"}), 400
        amount = int(m.group(1))
        unit = m.group(2).rstrip("s")  # normalize: minutes→minute, days→day, etc.
        if amount < 1:
            return jsonify({"error": "Period amount must be at least 1"}), 400
        delta = _period_delta(unit, amount)
        if delta is None:
            return jsonify({"error": f"Unknown period unit: {unit}"}), 400
        # Calculate from_ts in ms
        now_dt = pretend_dt if pretend_now_ms else datetime.now(tz=timezone.utc)
        from_dt = now_dt - delta
        # +1ms so the bar exactly at the boundary is excluded (last-5-minutes = 5 bars, not 6)
        period_from_ms = int(from_dt.timestamp() * 1000) + 1
    elif count_raw:
        try:
            count = int(count_raw)
            if count < 1 or count > 5000:
                return jsonify({"error": "count must be between 1 and 5000"}), 400
        except ValueError:
            return jsonify({"error": "count must be an integer"}), 400
    else:
        # Neither provided — default to count 100
        count = 100

    # Inflate count by MA lookback so we can compute MA for the first output bar
    requested_count = count
    if count is not None and max_ma > 0:
        count = count + max_ma - 1

    db = get_db()
    try:
        # Validate API key
        if api_key == API_KEY:
            user = None
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 401

        # Find the account
        account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.arrissa_id == arrissa_account_id
        ).first()
        if not account:
            return jsonify({"error": f"Account not found for arrissa_account_id: {arrissa_account_id}"}), 404

        if user and account.user_id != user.id:
            return jsonify({"error": "You do not have access to this account"}), 403

        # Get credential and ensure token is valid
        credential = db.query(TradeLockerCredential).filter(
            TradeLockerCredential.id == account.credential_id
        ).first()
        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        # First, get instruments to find tradableInstrumentId and routeId for the symbol
        instruments = tradelocker_get_instruments(
            access_token=access_token,
            account_id=account.account_id,
            acc_num=account.acc_num,
            environment=credential.environment,
        )
        if instruments is None:
            # Force refresh and retry
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            instruments = tradelocker_get_instruments(
                access_token=access_token,
                account_id=account.account_id,
                acc_num=account.acc_num,
                environment=credential.environment,
            )
        if instruments is None:
            return jsonify({"error": "Failed to fetch instruments from TradeLocker after token refresh."}), 502

        # Find the matching instrument
        matched = None
        for inst in instruments:
            if inst.get("name", "").upper() == symbol:
                matched = inst
                break

        if not matched:
            return jsonify({"error": f"Symbol '{symbol}' not found for this account"}), 404

        tradable_id = matched.get("tradableInstrumentId")
        # routeId is inside the routes array — use the INFO route for market data
        routes = matched.get("routes", [])
        route_id = None
        for r in routes:
            if r.get("type") == "INFO":
                route_id = r.get("id")
                break
        if not route_id and routes:
            route_id = routes[0].get("id")
        if not tradable_id or not route_id:
            return jsonify({"error": f"Symbol '{symbol}' is missing instrument/route identifiers"}), 500

        # Convert timeframe to TradeLocker resolution
        resolution = TIMEFRAME_MAP[timeframe]

        # Determine if instrument trades continuously (crypto = 24/7, no weekend gaps)
        instrument_type = (matched.get("type") or "").upper()
        is_continuous = "CRYPTO" in instrument_type

        # Fetch market data
        result = tradelocker_get_market_data(
            access_token=access_token,
            account_id=account.account_id,
            acc_num=account.acc_num,
            tradable_instrument_id=tradable_id,
            route_id=route_id,
            resolution=resolution,
            count=count,
            environment=credential.environment,
            is_continuous=is_continuous,
            from_override_ms=period_from_ms,
            to_override_ms=future_to_ms if is_future else pretend_now_ms,
        )
        if result is None:
            return jsonify({"error": "Failed to fetch market data from TradeLocker."}), 502

        # Format the bars
        def _ms_to_utc(ms):
            if ms is None:
                return None
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            return dt.strftime("%a %Y-%m-%d %H:%M")

        raw_bars = result["bars"]

        # ── Calculate MAs on the full (inflated) data, then trim ──
        all_closes = [b.get("c", 0) for b in raw_bars]
        ma_values = {}  # {period: [values_per_bar]}
        for p in ma_periods:
            vals = []
            for i in range(len(all_closes)):
                if i + 1 >= p:
                    avg = sum(all_closes[i - p + 1 : i + 1]) / p
                    vals.append(round(avg, 6))
                else:
                    vals.append(None)
            ma_values[p] = vals

        # Trim to requested range (remove the extra lookback bars)
        if requested_count is not None and max_ma > 0:
            trim = len(raw_bars) - requested_count
            if trim > 0:
                raw_bars = raw_bars[trim:]
                for p in ma_periods:
                    ma_values[p] = ma_values[p][trim:]

        bars = []
        for idx, bar in enumerate(raw_bars):
            entry = {
                "time": _ms_to_utc(bar.get("t")),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
            }
            if show_volume:
                entry["volume"] = bar.get("v")
            for p in ma_periods:
                entry[f"ma_{p}"] = ma_values[p][idx]
            bars.append(entry)

        wrapper_key = f"arrissa_data_{credential.server}_{credential.environment}"
        response_data = {
            "arrissa_account_id": arrissa_account_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(bars),
            "bars": bars,
        }
        if ma_periods:
            response_data["moving_averages"] = [f"ma_{p}" for p in ma_periods]
        if quarters_snr and bars:
            highs = [b["high"] for b in bars if b["high"] is not None]
            lows = [b["low"] for b in bars if b["low"] is not None]
            if highs and lows:
                hh = max(highs)
                ll = min(lows)
                q = (hh - ll) / 4
                response_data["quarters_s_n_r"] = {
                    "high": round(hh, 6),
                    "low": round(ll, 6),
                    "range": round(hh - ll, 6),
                    "quarter_size": round(q, 6),
                    "supports": [
                        {"label": "Extension Low", "price": round(ll - q, 6)},
                        {"label": "Low", "price": round(ll, 6)},
                        {"label": "25%", "price": round(ll + q, 6)},
                    ],
                    "pivot": {"label": "50%", "price": round(ll + 2 * q, 6)},
                    "resistances": [
                        {"label": "75%", "price": round(ll + 3 * q, 6)},
                        {"label": "High", "price": round(hh, 6)},
                        {"label": "Extension High", "price": round(hh + q, 6)},
                    ],
                }
        if order_blocks and quarters_snr and bars:
            highs_list = [b["high"] for b in bars if b["high"] is not None]
            lows_list = [b["low"] for b in bars if b["low"] is not None]
            if highs_list and lows_list:
                ob_hh = max(highs_list)
                ob_ll = min(lows_list)
                ob_q = (ob_hh - ob_ll) / 4
                ob_q25 = ob_ll + ob_q
                ob_q75 = ob_ll + 3 * ob_q
                ob_results = []

                def _find_ob(bars, trigger_idx, bearish):
                    """Scan backwards from trigger_idx for last bearish/bullish candle."""
                    for j in range(trigger_idx - 1, -1, -1):
                        o, c = bars[j]["open"], bars[j]["close"]
                        if o is None or c is None:
                            continue
                        if bearish and c < o:
                            return j
                        if not bearish and c > o:
                            return j
                    return None

                # Low OB: the actual candle that touched the low
                for i in range(len(bars) - 1, -1, -1):
                    if bars[i]["low"] is not None and bars[i]["low"] <= ob_ll * 1.00001:
                        ob_results.append({"level": "Low", "type": "support", "bar_index": i, "time": bars[i]["time"], "open": bars[i]["open"], "close": bars[i]["close"], "high": bars[i]["high"], "low": bars[i]["low"]})
                        break

                # 25% OB: last bearish candle before rightmost break of 25%
                for i in range(len(bars) - 1, -1, -1):
                    if bars[i]["low"] is not None and bars[i]["low"] <= ob_q25:
                        idx = _find_ob(bars, i, bearish=True)
                        if idx is not None:
                            ob_results.append({"level": "25%", "type": "support", "bar_index": idx, "time": bars[idx]["time"], "open": bars[idx]["open"], "close": bars[idx]["close"], "high": bars[idx]["high"], "low": bars[idx]["low"]})
                        break

                # 75% OB: last bullish candle before rightmost cross of 75%
                for i in range(len(bars) - 1, -1, -1):
                    if bars[i]["high"] is not None and bars[i]["high"] >= ob_q75:
                        idx = _find_ob(bars, i, bearish=False)
                        if idx is not None:
                            ob_results.append({"level": "75%", "type": "resistance", "bar_index": idx, "time": bars[idx]["time"], "open": bars[idx]["open"], "close": bars[idx]["close"], "high": bars[idx]["high"], "low": bars[idx]["low"]})
                        break

                # High OB: the actual candle that touched the high
                for i in range(len(bars) - 1, -1, -1):
                    if bars[i]["high"] is not None and bars[i]["high"] >= ob_hh * 0.99999:
                        ob_results.append({"level": "High", "type": "resistance", "bar_index": i, "time": bars[i]["time"], "open": bars[i]["open"], "close": bars[i]["close"], "high": bars[i]["high"], "low": bars[i]["low"]})
                        break

                response_data["order_blocks"] = ob_results
        if period_raw:
            response_data["period"] = period_raw
        if future_limit_raw:
            response_data["future_limit"] = future_limit_raw
        if pretend_now_ms:
            response_data["pretend_now"] = _ms_to_utc(pretend_now_ms)
        if bars:
            response_data["from"] = bars[0]["time"]
            response_data["to"] = bars[-1]["time"]
        return jsonify({wrapper_key: response_data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Chart Image API ─────────────────────────────────────────────────────


@app.route("/api/chart-image")
def api_chart_image():
    """
    Render a Japanese candlestick chart as a PNG image.
    Same params as /api/market-data but returns an image instead of JSON.
    Extra optional params: width, height, theme (dark/light).
    """
    import re as _re
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as mticker
    from matplotlib.patches import FancyBboxPatch
    import pandas as pd
    from datetime import datetime as _dt

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
    symbol = request.args.get("symbol", "").strip().upper()
    timeframe = normalize_timeframe(request.args.get("timeframe", ""))
    count_raw = request.args.get("count", "").strip()
    period_raw = request.args.get("period", "").strip().lower()
    future_limit_raw = request.args.get("future_limit", "").strip().lower()
    pretend_date_raw = request.args.get("pretend_date", "").strip()
    pretend_time_raw = request.args.get("pretend_time", "").strip()
    ma_raw = request.args.get("ma", "").strip()
    quarters_snr = request.args.get("quarters_s_n_r", "").strip().lower() in ("true", "1", "yes")
    show_volume = request.args.get("volume", "").strip().lower() in ("true", "1", "yes")
    order_blocks = request.args.get("order_blocks", "").strip().lower() in ("true", "1", "yes")
    width = int(request.args.get("width", "1200"))
    height = int(request.args.get("height", "700"))
    theme = request.args.get("theme", "dark").strip().lower()

    # ── Position drawing params ──
    entry_raw = request.args.get("entry", "").strip()
    direction_raw = request.args.get("direction", "").strip().upper()
    sl_raw = request.args.get("sl", "").strip()          # absolute price
    tp_raw = request.args.get("tp", "").strip()          # absolute price
    sl_points_raw = request.args.get("sl_points", "").strip()  # points
    tp_points_raw = request.args.get("tp_points", "").strip()  # points

    draw_position = False
    pos_entry_type = None
    pos_entry_dt = None
    pos_sl_price = None       # absolute SL price
    pos_tp_price = None       # absolute TP price
    pos_sl_points = None      # SL in points
    pos_tp_points = None      # TP in points
    pos_direction = None

    _has_any_pos = entry_raw or direction_raw or sl_raw or tp_raw or sl_points_raw or tp_points_raw
    if _has_any_pos:
        # Must have entry + direction
        if not entry_raw or not direction_raw:
            return jsonify({"error": "Position drawing requires entry and direction parameters"}), 400
        # Must have at least one SL source and one TP source
        if not sl_raw and not sl_points_raw:
            return jsonify({"error": "Position drawing requires sl (absolute price) or sl_points (distance in points)"}), 400
        if not tp_raw and not tp_points_raw:
            return jsonify({"error": "Position drawing requires tp (absolute price) or tp_points (distance in points)"}), 400
        if sl_raw and sl_points_raw:
            return jsonify({"error": "Provide either sl or sl_points, not both"}), 400
        if tp_raw and tp_points_raw:
            return jsonify({"error": "Provide either tp or tp_points, not both"}), 400
        if direction_raw not in ("LONG", "SHORT"):
            return jsonify({"error": "direction must be LONG or SHORT"}), 400
        try:
            if sl_raw:
                pos_sl_price = float(sl_raw)
                if pos_sl_price <= 0:
                    raise ValueError
            if tp_raw:
                pos_tp_price = float(tp_raw)
                if pos_tp_price <= 0:
                    raise ValueError
            if sl_points_raw:
                pos_sl_points = float(sl_points_raw)
                if pos_sl_points <= 0:
                    raise ValueError
            if tp_points_raw:
                pos_tp_points = float(tp_points_raw)
                if pos_tp_points <= 0:
                    raise ValueError
        except ValueError:
            return jsonify({"error": "sl, tp, sl_points, tp_points must be positive numbers"}), 400
        pos_direction = direction_raw
        draw_position = True
        if entry_raw.lower() == "market":
            pos_entry_type = "market"
        else:
            pos_entry_type = "datetime"
            try:
                pos_entry_dt = _dt.strptime(entry_raw, "%Y-%m-%d-%H:%M")
                pos_entry_dt = pos_entry_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({"error": "Invalid entry format. Use 'market' or datetime like '2026-01-10-10:20'"}), 400

    # ── Parse MA periods ──
    ma_periods = []
    if ma_raw:
        for part in ma_raw.split(","):
            part = part.strip()
            if part:
                try:
                    p = int(part)
                    if 2 <= p <= 500:
                        ma_periods.append(p)
                except ValueError:
                    pass
    ma_periods = sorted(set(ma_periods))
    max_ma = max(ma_periods) if ma_periods else 0

    # Clamp dimensions
    width = max(400, min(width, 3840))
    height = max(300, min(height, 2160))

    if not api_key:
        return jsonify({"error": "Missing api_key (header X-API-Key or query param)"}), 401
    arrissa_account_id = _resolve_default_account(api_key, arrissa_account_id)
    if not arrissa_account_id:
        return jsonify({"error": "Missing arrissa_account_id (header X-Arrissa-Account-Id or query param)"}), 400
    if not symbol:
        return jsonify({"error": "Missing required parameter: symbol"}), 400
    if not timeframe:
        return jsonify({"error": "Missing required parameter: timeframe"}), 400
    if timeframe not in VALID_TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}. Valid: {', '.join(VALID_TIMEFRAMES)}"}), 400

    if count_raw and period_raw:
        return jsonify({"error": "Cannot use both count and period. Use one or the other."}), 400

    is_future = period_raw == "future"
    if is_future and not future_limit_raw:
        return jsonify({"error": "period=future requires future_limit parameter"}), 400
    if is_future and not pretend_date_raw:
        return jsonify({"error": "period=future requires pretend_date"}), 400
    if future_limit_raw and not is_future:
        return jsonify({"error": "future_limit can only be used with period=future"}), 400

    pretend_now_ms = None
    pretend_dt = None
    if pretend_date_raw:
        try:
            time_str = pretend_time_raw or "00:00"
            pretend_dt = datetime.strptime(f"{pretend_date_raw} {time_str}", "%Y-%m-%d %H:%M")
            pretend_dt = pretend_dt.replace(tzinfo=timezone.utc)
            pretend_now_ms = int(pretend_dt.timestamp() * 1000)
        except ValueError:
            return jsonify({"error": "Invalid pretend_date/pretend_time format"}), 400

    count = None
    period_from_ms = None
    future_to_ms = None

    if is_future:
        m = _re.match(r"^next-(\d+)-(minutes?|hours?|days?|weeks?|months?|years?)$", future_limit_raw)
        if not m:
            return jsonify({"error": "Invalid future_limit format"}), 400
        amount, unit = int(m.group(1)), m.group(2).rstrip("s")
        if amount < 1:
            return jsonify({"error": "future_limit amount must be at least 1"}), 400
        delta = _period_delta(unit, amount)
        if delta is None:
            return jsonify({"error": f"Unknown future_limit unit: {unit}"}), 400
        period_from_ms = pretend_now_ms
        future_to_ms = int((pretend_dt + delta).timestamp() * 1000)
    elif period_raw:
        m = _re.match(r"^last-(\d+)-(minutes?|hours?|days?|weeks?|months?|years?)$", period_raw)
        if not m:
            return jsonify({"error": "Invalid period format"}), 400
        amount, unit = int(m.group(1)), m.group(2).rstrip("s")
        if amount < 1:
            return jsonify({"error": "Period amount must be at least 1"}), 400
        delta = _period_delta(unit, amount)
        if delta is None:
            return jsonify({"error": f"Unknown period unit: {unit}"}), 400
        now_dt = pretend_dt if pretend_now_ms else datetime.now(tz=timezone.utc)
        from_dt = now_dt - delta
        period_from_ms = int(from_dt.timestamp() * 1000) + 1
    elif count_raw:
        try:
            count = int(count_raw)
            if count < 1 or count > 5000:
                return jsonify({"error": "count must be between 1 and 5000"}), 400
        except ValueError:
            return jsonify({"error": "count must be an integer"}), 400
    else:
        count = 100

    # Inflate count by MA lookback for calculation
    requested_count = count
    if count is not None and max_ma > 0:
        count = count + max_ma - 1

    db = get_db()
    try:
        if api_key == API_KEY:
            user = None
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 401

        account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.arrissa_id == arrissa_account_id
        ).first()
        if not account:
            return jsonify({"error": f"Account not found for arrissa_account_id: {arrissa_account_id}"}), 404
        if user and account.user_id != user.id:
            return jsonify({"error": "You do not have access to this account"}), 403

        credential = db.query(TradeLockerCredential).filter(
            TradeLockerCredential.id == account.credential_id
        ).first()
        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        instruments = tradelocker_get_instruments(
            access_token=access_token,
            account_id=account.account_id,
            acc_num=account.acc_num,
            environment=credential.environment,
        )
        if instruments is None:
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            instruments = tradelocker_get_instruments(
                access_token=access_token,
                account_id=account.account_id,
                acc_num=account.acc_num,
                environment=credential.environment,
            )
        if instruments is None:
            return jsonify({"error": "Failed to fetch instruments from TradeLocker after token refresh."}), 502

        matched = None
        for inst in instruments:
            if inst.get("name", "").upper() == symbol:
                matched = inst
                break
        if not matched:
            return jsonify({"error": f"Symbol '{symbol}' not found for this account"}), 404

        tradable_id = matched.get("tradableInstrumentId")
        routes = matched.get("routes", [])
        route_id = None
        for r in routes:
            if r.get("type") == "INFO":
                route_id = r.get("id")
                break
        if not route_id and routes:
            route_id = routes[0].get("id")
        if not tradable_id or not route_id:
            return jsonify({"error": f"Symbol '{symbol}' is missing instrument/route identifiers"}), 500

        resolution = TIMEFRAME_MAP[timeframe]
        instrument_type = (matched.get("type") or "").upper()
        is_continuous = "CRYPTO" in instrument_type

        result = tradelocker_get_market_data(
            access_token=access_token,
            account_id=account.account_id,
            acc_num=account.acc_num,
            tradable_instrument_id=tradable_id,
            route_id=route_id,
            resolution=resolution,
            count=count,
            environment=credential.environment,
            is_continuous=is_continuous,
            from_override_ms=period_from_ms,
            to_override_ms=future_to_ms if is_future else pretend_now_ms,
        )
        if result is None:
            return jsonify({"error": "Failed to fetch market data from TradeLocker."}), 502

        bars = result.get("bars", [])
        if not bars:
            return jsonify({"error": "No bars returned for the given parameters."}), 404

        # ── Build DataFrame for chart ──
        dates = []
        opens = []
        highs = []
        lows = []
        closes = []
        volumes = []
        for bar in bars:
            ts = bar.get("t")
            if ts is None:
                continue
            dt = _dt.fromtimestamp(ts / 1000, tz=timezone.utc)
            dates.append(dt)
            opens.append(float(bar.get("o", 0)))
            highs.append(float(bar.get("h", 0)))
            lows.append(float(bar.get("l", 0)))
            closes.append(float(bar.get("c", 0)))
            volumes.append(float(bar.get("v", 0)))

        if not dates:
            return jsonify({"error": "No valid bars to chart."}), 404

        df = pd.DataFrame({
            "Date": dates,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        })
        df.set_index("Date", inplace=True)
        df.index = pd.DatetimeIndex(df.index)

        # ── Calculate MAs on the full (inflated) data ──
        for p in ma_periods:
            df[f"MA_{p}"] = df["Close"].rolling(window=p, min_periods=p).mean()

        # Trim to requested range (remove the extra lookback bars)
        if requested_count is not None and max_ma > 0:
            trim = len(df) - requested_count
            if trim > 0:
                df = df.iloc[trim:]

        # ── TradingView-style colour palette ──
        if theme == "light":
            bg_color = "#FFFFFF"
            face_color = "#FFFFFF"
            text_color = "#131722"
            grid_color = "#E0E3EB"
            border_color = "#E0E3EB"
            up_color = "#26A69A"
            down_color = "#EF5350"
            vol_up = "#26A69A"
            vol_down = "#EF5350"
            wick_up = "#26A69A"
            wick_down = "#EF5350"
        else:
            bg_color = "#131722"
            face_color = "#131722"
            text_color = "#D1D4DC"
            grid_color = "#1E222D"
            border_color = "#2A2E39"
            up_color = "#26A69A"
            down_color = "#EF5350"
            vol_up = "#26A69A"
            vol_down = "#EF5350"
            wick_up = "#26A69A"
            wick_down = "#EF5350"

        # ── Build custom style ──
        import mplfinance as mpf

        mc = mpf.make_marketcolors(
            up=up_color,
            down=down_color,
            edge={"up": up_color, "down": down_color},
            wick={"up": wick_up, "down": wick_down},
            volume={"up": vol_up, "down": vol_down},
            ohlc=up_color,
        )

        style = mpf.make_mpf_style(
            marketcolors=mc,
            facecolor=face_color,
            edgecolor=border_color,
            figcolor=bg_color,
            gridcolor=grid_color,
            gridstyle="-",
            gridaxis="both",
            y_on_right=True,
            rc={
                "font.size": 10,
                "axes.labelcolor": text_color,
                "xtick.color": text_color,
                "ytick.color": text_color,
            },
        )

        # ── Chart title ──
        period_label = period_raw if period_raw else f"{len(df)} bars"
        title = f"{symbol}  ·  {timeframe}  ·  {period_label}"

        dpi = 100
        fig_w = width / dpi
        fig_h = height / dpi

        # ── Build addplots: volume + MA lines ──
        addplots = []

        # Volume in panel 1 (if enabled)
        if show_volume:
            vol_colors = [vol_up if c >= o else vol_down for o, c in zip(df["Open"], df["Close"])]
            addplots.append(mpf.make_addplot(
                df["Volume"], panel=1, type="bar",
                color=vol_colors,
                ylabel="",
            ))

        # MA line colour cycle (TradingView-like)
        ma_line_colors = ["#2962FF", "#FF6D00", "#AB47BC", "#00BCD4", "#FF5252", "#66BB6A"]
        for i, p in enumerate(ma_periods):
            col_name = f"MA_{p}"
            if col_name in df.columns:
                color = ma_line_colors[i % len(ma_line_colors)]
                addplots.append(mpf.make_addplot(
                    df[col_name], panel=0, type="line",
                    color=color, width=1.2,
                ))

        plot_kwargs = dict(
            type="candle",
            style=style,
            volume=False,
            title="",
            ylabel="",
            ylabel_lower="",
            figsize=(fig_w, fig_h),
            returnfig=True,
            tight_layout=False,
            scale_padding={"left": 0.08, "top": 0.6, "right": 1.0, "bottom": 0.5},
        )
        if addplots:
            plot_kwargs["addplot"] = addplots
            plot_kwargs["panel_ratios"] = (4, 1) if show_volume else (1,)
        elif show_volume:
            plot_kwargs["panel_ratios"] = (4, 1)

        fig, axes = mpf.plot(df, **plot_kwargs)

        # Add title text manually for proper colour
        fig.text(
            0.04, 0.97, title,
            fontsize=13, fontweight="bold", color=text_color,
            va="top", ha="left",
        )

        # Watermark top-right
        fig.text(
            0.96, 0.97, "arrissadata.com",
            fontsize=9, fontweight="normal", color=text_color, alpha=0.45,
            va="top", ha="right",
        )

        # Add MA legend labels below the title
        if ma_periods:
            ma_labels = []
            for i, p in enumerate(ma_periods):
                color = ma_line_colors[i % len(ma_line_colors)]
                ma_labels.append((f"MA({p})", color))
            x_pos = 0.04
            for label_text, color in ma_labels:
                fig.text(
                    x_pos, 0.94, label_text,
                    fontsize=9, color=color,
                    va="top", ha="left",
                )
                x_pos += 0.06

        # ── Horizontal x-axis labels + clean borders ──
        price_ax = axes[0]
        for ax in axes:
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_color(border_color)
            ax.spines["left"].set_visible(False)
            ax.spines["bottom"].set_color(border_color)
            for label in ax.get_xticklabels():
                label.set_rotation(0)
                label.set_ha("center")

        if show_volume:
            vol_ax = axes[2]  # mplfinance creates axes[0]=price, axes[1]=price-twin, axes[2]=vol, axes[3]=vol-twin

            # Widen the gap between price and volume panels
            fig.subplots_adjust(hspace=0.35)

            # Draw a separator line between price and volume panels
            from matplotlib.lines import Line2D
            vol_bbox = vol_ax.get_position()
            price_bbox = price_ax.get_position()
            sep_y = (price_bbox.y0 + vol_bbox.y1) / 2
            sep_line = Line2D(
                [vol_bbox.x0, vol_bbox.x1], [sep_y, sep_y],
                transform=fig.transFigure, color=border_color,
                linewidth=1.0, clip_on=False,
            )
            fig.add_artist(sep_line)

            # Add a "Vol" label on the volume panel
            vol_ax.text(
                0.01, 0.92, "Vol", transform=vol_ax.transAxes,
                fontsize=9, color=text_color, alpha=0.6,
                va="top", ha="left",
            )

        # ── Current price dashed line (skip when drawing position) ──
        if not draw_position:
            last_close = df["Close"].iloc[-1]
            price_ax.axhline(
                y=last_close, color="#EF5350", linestyle="--",
                linewidth=1.0, alpha=0.85, zorder=5,
            )
            # Price label on the right edge
            price_ax.text(
                1.002, last_close, f" {last_close:.5g}",
                transform=price_ax.get_yaxis_transform(),
                fontsize=8, color="#FFFFFF", fontweight="bold",
                va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#EF5350", edgecolor="none", alpha=0.9),
            )

        # ── Quarters S&R lines ──
        if quarters_snr:
            hh = df["High"].max()
            ll = df["Low"].min()
            q = (hh - ll) / 4
            snr_levels = [
                (ll - q,       "Ext Low",  "#2196F3"),
                (ll,           "Low",      "#2196F3"),
                (ll + q,       "25%",      "#2196F3"),
                (ll + 2 * q,   "50%",      "#FF9800"),
                (ll + 3 * q,   "75%",      "#EF5350"),
                (hh,           "High",     "#EF5350"),
                (hh + q,       "Ext High", "#EF5350"),
            ]
            for level_price, label, color in snr_levels:
                price_ax.axhline(
                    y=level_price, color=color, linestyle="--",
                    linewidth=0.8, alpha=0.6, zorder=4,
                )
                price_ax.text(
                    -0.002, level_price, f"{label} {level_price:.5g} ",
                    transform=price_ax.get_yaxis_transform(),
                    fontsize=7, color=color, alpha=0.85,
                    va="center", ha="right",
                )

        # ── Order Blocks ──
        if order_blocks and quarters_snr:
            from matplotlib.patches import Rectangle
            ob_hh = df["High"].max()
            ob_ll = df["Low"].min()
            ob_q = (ob_hh - ob_ll) / 4
            ob_q25 = ob_ll + ob_q
            ob_q75 = ob_ll + 3 * ob_q
            n = len(df)
            x_indices = list(range(n))

            def _find_ob_idx(df, trigger_i, bearish):
                for j in range(trigger_i - 1, -1, -1):
                    o, c = df["Open"].iloc[j], df["Close"].iloc[j]
                    if bearish and c < o:
                        return j
                    if not bearish and c > o:
                        return j
                return None

            ob_rects = []  # (bar_idx, body_lo, body_hi, color)

            # Low OB: the actual candle that touched the low
            for i in range(n - 1, -1, -1):
                if df["Low"].iloc[i] <= ob_ll * 1.00001:
                    ob_rects.append((i, min(df["Open"].iloc[i], df["Close"].iloc[i]),
                                     max(df["Open"].iloc[i], df["Close"].iloc[i]), "#2196F3"))
                    break

            # 25% OB
            for i in range(n - 1, -1, -1):
                if df["Low"].iloc[i] <= ob_q25:
                    idx = _find_ob_idx(df, i, bearish=True)
                    if idx is not None:
                        ob_rects.append((idx, min(df["Open"].iloc[idx], df["Close"].iloc[idx]),
                                         max(df["Open"].iloc[idx], df["Close"].iloc[idx]), "#2196F3"))
                    break

            # 75% OB
            for i in range(n - 1, -1, -1):
                if df["High"].iloc[i] >= ob_q75:
                    idx = _find_ob_idx(df, i, bearish=False)
                    if idx is not None:
                        ob_rects.append((idx, min(df["Open"].iloc[idx], df["Close"].iloc[idx]),
                                         max(df["Open"].iloc[idx], df["Close"].iloc[idx]), "#EF5350"))
                    break

            # High OB: the actual candle that touched the high
            for i in range(n - 1, -1, -1):
                if df["High"].iloc[i] >= ob_hh * 0.99999:
                    ob_rects.append((i, min(df["Open"].iloc[i], df["Close"].iloc[i]),
                                     max(df["Open"].iloc[i], df["Close"].iloc[i]), "#EF5350"))
                    break

            for bar_i, body_lo, body_hi, color in ob_rects:
                rect_width = n - bar_i + 2
                body_height = body_hi - body_lo
                if body_height < 1e-10:
                    body_height = ob_q * 0.05  # minimum visible height
                rect = Rectangle(
                    (bar_i - 0.5, body_lo), rect_width, body_height,
                    linewidth=0.8, edgecolor=color, facecolor=color,
                    alpha=0.15, zorder=1,
                )
                price_ax.add_patch(rect)

        # ── Position Drawing (Long / Short) ──
        if draw_position:
            from matplotlib.patches import Rectangle as PosRect

            n = len(df)

            # Determine entry bar index and price
            if pos_entry_type == "market":
                _pos_idx = n - 1
                _pos_price = df["Close"].iloc[-1]
            else:
                _idx_arr = df.index.get_indexer([pos_entry_dt], method="nearest")
                _pos_idx = _idx_arr[0]
                _pos_price = df["Close"].iloc[_pos_idx]

            # Auto-detect point size from price magnitude (only needed for points mode)
            _avg = df["Close"].mean()
            if _avg >= 10000:
                _pt = 1.0
            elif _avg >= 1000:
                _pt = 0.1
            elif _avg >= 50:
                _pt = 0.01
            else:
                _pt = 0.0001

            # Compute SL / TP absolute prices
            if pos_sl_price is not None:
                # Absolute price mode for SL
                _sl_p = pos_sl_price
            else:
                # Points mode for SL
                _sl_d = pos_sl_points * _pt
                if pos_direction == "LONG":
                    _sl_p = _pos_price - _sl_d
                else:
                    _sl_p = _pos_price + _sl_d

            if pos_tp_price is not None:
                # Absolute price mode for TP
                _tp_p = pos_tp_price
            else:
                # Points mode for TP
                _tp_d = pos_tp_points * _pt
                if pos_direction == "LONG":
                    _tp_p = _pos_price + _tp_d
                else:
                    _tp_p = _pos_price - _tp_d

            # Compute distances in points for labels and R:R
            _sl_pts = abs(_pos_price - _sl_p) / _pt
            _tp_pts = abs(_pos_price - _tp_p) / _pt

            _x0 = _pos_idx - 0.5
            _xlim_right = price_ax.get_xlim()[1]
            _x1 = max(n + 2, _xlim_right)
            _rw = _x1 - _x0

            # TP zone (green)
            _tp_lo = min(_pos_price, _tp_p)
            _tp_hi = max(_pos_price, _tp_p)
            price_ax.add_patch(PosRect(
                (_x0, _tp_lo), _rw, _tp_hi - _tp_lo,
                linewidth=0, facecolor="#26A69A", alpha=0.20, zorder=3,
            ))

            # SL zone (red)
            _sl_lo = min(_pos_price, _sl_p)
            _sl_hi = max(_pos_price, _sl_p)
            price_ax.add_patch(PosRect(
                (_x0, _sl_lo), _rw, _sl_hi - _sl_lo,
                linewidth=0, facecolor="#EF5350", alpha=0.20, zorder=3,
            ))

            # Entry line (white solid)
            price_ax.hlines(_pos_price, _x0, _x1, colors="#FFFFFF",
                            linewidths=1.2, linestyles="-", zorder=4)
            # TP line (green dashed)
            price_ax.hlines(_tp_p, _x0, _x1, colors="#26A69A",
                            linewidths=0.8, linestyles="--", zorder=4)
            # SL line (red dashed)
            price_ax.hlines(_sl_p, _x0, _x1, colors="#EF5350",
                            linewidths=0.8, linestyles="--", zorder=4)

            # R:R ratio
            _rr = _tp_pts / _sl_pts if _sl_pts > 0 else 0

            # Right-margin labels
            price_ax.text(
                1.002, _pos_price, f" Entry {_pos_price:.5g}",
                transform=price_ax.get_yaxis_transform(),
                fontsize=7, color="#FFFFFF", fontweight="bold",
                va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#555555",
                          edgecolor="none", alpha=0.9),
            )
            price_ax.text(
                1.002, _tp_p, f" TP {_tp_p:.5g}  +{_tp_pts:.0f}pts",
                transform=price_ax.get_yaxis_transform(),
                fontsize=7, color="#FFFFFF", fontweight="bold",
                va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#26A69A",
                          edgecolor="none", alpha=0.9),
            )
            price_ax.text(
                1.002, _sl_p, f" SL {_sl_p:.5g}  -{_sl_pts:.0f}pts",
                transform=price_ax.get_yaxis_transform(),
                fontsize=7, color="#FFFFFF", fontweight="bold",
                va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#EF5350",
                          edgecolor="none", alpha=0.9),
            )

            # BUY/SELL label next to the chart title
            _pos_label = "BUY" if pos_direction == "LONG" else "SELL"
            _pos_label_color = "#26A69A" if pos_direction == "LONG" else "#EF5350"
            fig.text(
                0.04, 0.93,
                f"{_pos_label}   R:R  1:{_rr:.1f}",
                fontsize=11, fontweight="bold", color=_pos_label_color,
                va="top", ha="left",
            )

            # Expand y-limits to fit TP / SL
            _cur_lo, _cur_hi = price_ax.get_ylim()
            _margin = max(_tp_hi - _sl_lo, 0) * 0.08
            _new_lo = min(_cur_lo, _sl_lo - _margin)
            _new_hi = max(_cur_hi, _tp_hi + _margin)
            if _new_lo < _cur_lo or _new_hi > _cur_hi:
                price_ax.set_ylim(_new_lo, _new_hi)

        # ── Render to in-memory PNG ──
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)

        return send_file(buf, mimetype="image/png", download_name=f"{symbol}_{timeframe}.png")

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Chart Image API Guide Page ─────────────────────────────────────────


@app.route("/chart-image-api")
@login_required
def chart_image_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        first_account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        example_account_id = first_account.arrissa_id if first_account else "ACCTID"
        return render_template(
            "chart_image_guide.html",
            user=user,
            api_key=user.api_key,
            example_account_id=example_account_id,
            active_page="chart_image_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


# ─── Market Data API Guide Page ──────────────────────────────────────────


@app.route("/market-data-api")
@login_required
def market_data_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        first_account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        example_account_id = first_account.arrissa_id if first_account else "ACCTID"
        return render_template(
            "market_data_guide.html",
            user=user,
            api_key=user.api_key,
            example_account_id=example_account_id,
            active_page="market_data_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


# ─── Economic News API ───────────────────────────────────────────────────


def _parse_news_period(period_raw, pretend_date_raw, pretend_time_raw, future_limit_raw=None):
    """
    Shared helper: parse period & pretend params for news endpoints.
    Supports period=last-X-unit and period=future with future_limit=next-X-unit.
    Returns (from_dt, to_dt, error_response).
    If error_response is not None, return it immediately.
    """
    import re as _re

    # Determine "now"
    if pretend_date_raw:
        try:
            time_str = pretend_time_raw or "00:00"
            now_dt = datetime.strptime(f"{pretend_date_raw} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None, None, (jsonify({"error": "Invalid pretend_date/pretend_time format. Use pretend_date=YYYY-MM-DD and pretend_time=HH:MM"}), 400)
    else:
        now_dt = datetime.now(tz=timezone.utc)

    if period_raw == "future":
        if not future_limit_raw:
            return None, None, (jsonify({"error": "period=future requires future_limit parameter (e.g. next-2-days)"}), 400)
        m = _re.match(r"^next-(\d+)-(minutes?|hours?|days?|weeks?|months?|years?)$", future_limit_raw)
        if not m:
            return None, None, (jsonify({"error": "Invalid future_limit format. Use: next-X-minutes, next-X-hours, next-X-days, etc."}), 400)
        amount = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if amount < 1:
            return None, None, (jsonify({"error": "future_limit amount must be at least 1"}), 400)
        delta = _period_delta(unit, amount)
        if delta is None:
            return None, None, (jsonify({"error": f"Unknown future_limit unit: {unit}"}), 400)
        from_dt = now_dt
        to_dt = now_dt + delta
        return from_dt, to_dt, None

    m = _re.match(r"^last-(\d+)-(minutes?|hours?|days?|weeks?|months?|years?)$", period_raw)
    if not m:
        return None, None, (jsonify({"error": "Invalid period format. Use: last-X-unit (e.g. last-7-days) or future with future_limit=next-X-unit"}), 400)

    amount = int(m.group(1))
    unit = m.group(2).rstrip("s")
    if amount < 1:
        return None, None, (jsonify({"error": "Period amount must be at least 1"}), 400)

    delta = _period_delta(unit, amount)
    if delta is None:
        return None, None, (jsonify({"error": f"Unknown period unit: {unit}"}), 400)

    from_dt = now_dt - delta
    to_dt = now_dt
    return from_dt, to_dt, None


def _save_events_to_db(db, events):
    """
    Save a list of raw TradingView events to the database.
    Overwrites existing events (matched by source_id + event_time).
    Returns (saved_count, updated_count).
    """
    saved = 0
    updated = 0
    for e in events:
        source_id = str(e.get("id", ""))
        date_str = e.get("date", "")
        try:
            event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            continue

        event_type_id = generate_event_type_id(e.get("title", ""), e.get("country", ""))
        impact = importance_to_impact(e.get("importance", 0))

        existing = db.query(EconomicEvent).filter(
            EconomicEvent.source_id == source_id,
            EconomicEvent.event_time == event_time,
        ).first()

        if existing:
            existing.actual = e.get("actual")
            existing.previous = e.get("previous")
            existing.forecast = e.get("forecast")
            existing.title = e.get("title", "")
            existing.indicator = e.get("indicator")
            existing.impact = impact
            updated += 1
        else:
            event = EconomicEvent(
                event_type_id=event_type_id,
                source_id=source_id,
                title=e.get("title", ""),
                country=e.get("country", ""),
                indicator=e.get("indicator"),
                category=e.get("category"),
                currency=e.get("currency"),
                impact=impact,
                event_time=event_time,
                actual=e.get("actual"),
                previous=e.get("previous"),
                forecast=e.get("forecast"),
                source=e.get("source"),
                source_url=e.get("source_url"),
            )
            db.add(event)
            saved += 1

    db.commit()
    return saved, updated


@app.route("/api/news")
def api_news():
    """
    Get economic news events.
    Accepts api_key via header or query param.
    Date range: from_date + to_date (YYYY-MM-DD), OR period (last-X-days etc.).
    Optional: currencies (comma-separated), impact, event_type_id, pretend_date, pretend_time.
    """
    import re as _re

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    period_raw = request.args.get("period", "").strip().lower()
    future_limit_raw = request.args.get("future_limit", "").strip().lower()
    pretend_date_raw = request.args.get("pretend_date", "").strip()
    pretend_time_raw = request.args.get("pretend_time", "").strip()
    currencies_raw = request.args.get("currencies", "").strip().upper()
    impact_filter = request.args.get("impact", "medium").strip().lower()
    event_type_id_raw = request.args.get("event_type_id", "").strip().upper()
    event_type_id_filters = [e.strip() for e in event_type_id_raw.split(",") if e.strip()] if event_type_id_raw else []

    if not api_key:
        return jsonify({"error": "Missing api_key (header X-API-Key or query param)"}), 401

    # future_limit only with period=future
    if future_limit_raw and period_raw != "future":
        return jsonify({"error": "future_limit can only be used with period=future"}), 400

    # period and from_date/to_date are mutually exclusive
    if period_raw and (from_date or to_date):
        return jsonify({"error": "Cannot use both period and from_date/to_date. Use one or the other."}), 400

    if not period_raw and (not from_date or not to_date):
        return jsonify({"error": "Missing required parameters: from_date and to_date (YYYY-MM-DD), or period (e.g. last-7-days)"}), 400

    # Resolve date range
    if period_raw:
        from_dt, to_dt, err = _parse_news_period(period_raw, pretend_date_raw, pretend_time_raw, future_limit_raw)
        if err:
            return err
        from_date = from_dt.strftime("%Y-%m-%d")
        to_date = to_dt.strftime("%Y-%m-%d")
    else:
        # Parse pretend for context but dates are explicit
        try:
            from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    db = get_db()
    try:
        # Validate API key
        if api_key == API_KEY:
            user = None
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 401

        # Parse currencies
        currencies = [c.strip() for c in currencies_raw.split(",") if c.strip()] if currencies_raw else None

        # Map impact filter to minImportance
        if impact_filter == "high":
            min_importance = 1
        elif impact_filter == "all":
            min_importance = -1
        else:
            min_importance = 0

        # Fetch from TradingView
        events = fetch_economic_events(from_dt, to_dt, currencies, min_importance)
        if events is None:
            return jsonify({"error": "Failed to fetch economic events"}), 502

        result = []
        for e in events:
            event_type_id = generate_event_type_id(e.get("title", ""), e.get("country", ""))
            impact = importance_to_impact(e.get("importance", 0))

            # Filter by event_type_id if specified
            if event_type_id_filters and event_type_id not in event_type_id_filters:
                continue

            # Convert ISO date to readable UTC timestamp
            raw_date = e.get("date", "")
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).astimezone(timezone.utc)
                readable_date = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, AttributeError):
                readable_date = raw_date

            result.append({
                "event_type_id": event_type_id,
                "date": readable_date,
                "title": e.get("title"),
                "country": e.get("country"),
                "currency": e.get("currency"),
                "indicator": e.get("indicator"),
                "impact": impact,
                "actual": e.get("actual"),
                "previous": e.get("previous"),
                "forecast": e.get("forecast"),
            })

        return jsonify({
            "arrissa_data_news": {
                "from": from_date,
                "to": to_date,
                "count": len(result),
                "events": result,
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/news/save", methods=["POST"])
def api_news_save():
    """
    Fetch economic events for a date range and save to database.
    Accepts JSON body: {from_date, to_date, currencies?, impact?}
    OR {period, pretend_date?, pretend_time?, currencies?, impact?}
    Overwrites existing events.
    """
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not api_key:
        return jsonify({"error": "Missing api_key"}), 401

    db = get_db()
    try:
        if api_key == API_KEY:
            pass
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 401

        data = request.get_json() or {}
        from_date = data.get("from_date", "").strip()
        to_date = data.get("to_date", "").strip()
        period_raw = data.get("period", "").strip().lower()
        future_limit_raw = data.get("future_limit", "").strip().lower()
        pretend_date_raw = data.get("pretend_date", "").strip()
        pretend_time_raw = data.get("pretend_time", "").strip()
        currencies_raw = data.get("currencies", "")
        impact_filter = data.get("impact", "medium").strip().lower()

        if future_limit_raw and period_raw != "future":
            return jsonify({"error": "future_limit can only be used with period=future"}), 400

        if period_raw and (from_date or to_date):
            return jsonify({"error": "Cannot use both period and from_date/to_date"}), 400

        if period_raw:
            from_dt, to_dt, err = _parse_news_period(period_raw, pretend_date_raw, pretend_time_raw, future_limit_raw)
            if err:
                return err
        elif from_date and to_date:
            try:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        else:
            return jsonify({"error": "Missing from_date/to_date or period"}), 400

        currencies = [c.strip().upper() for c in currencies_raw.split(",") if c.strip()] if currencies_raw else None

        if impact_filter == "high":
            min_importance = 1
        elif impact_filter == "all":
            min_importance = -1
        else:
            min_importance = 0

        events = fetch_economic_events(from_dt, to_dt, currencies, min_importance)
        if events is None:
            return jsonify({"error": "Failed to fetch economic events"}), 502

        saved, updated = _save_events_to_db(db, events)
        return jsonify({"saved": saved, "updated": updated, "total_fetched": len(events)}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Event ID Reference Page (Web) ───────────────────────────────────────


@app.route("/event-ids")
@login_required
def event_id_reference():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        rows = (
            db.query(EconomicEvent.event_type_id, EconomicEvent.title, EconomicEvent.country, EconomicEvent.currency)
            .group_by(EconomicEvent.event_type_id, EconomicEvent.title, EconomicEvent.country, EconomicEvent.currency)
            .order_by(EconomicEvent.country, EconomicEvent.title)
            .all()
        )
        events = [
            {"event_type_id": r.event_type_id, "title": r.title, "country": r.country, "currency": r.currency}
            for r in rows
        ]
        return render_template(
            "event_id_reference.html",
            user=user,
            events=events,
            active_page="event_ids",
        )
    finally:
        db.close()


# ─── News API Guide Page (Web) ───────────────────────────────────────────


@app.route("/news-api")
@login_required
def news_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        now = datetime.utcnow()
        now_date = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        return render_template(
            "news_guide.html",
            user=user,
            api_key=user.api_key,
            now_date=now_date,
            week_ago=week_ago,
            active_page="news_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
            updater_status=smart_updater.status(),
        )
    finally:
        db.close()


@app.route("/news/update", methods=["POST"])
@login_required
def news_update_db():
    """
    Web route: fetch events for selected period and save to database.
    Form fields: update_period (1-week, 1-month, 2-months)
    """
    db = get_db()
    try:
        period = request.form.get("update_period", "1-week")

        now = datetime.now(tz=timezone.utc)
        if period == "2-months":
            from_dt = now - timedelta(days=60)
        elif period == "1-month":
            from_dt = now - timedelta(days=30)
        else:
            from_dt = now - timedelta(days=7)

        from_dt = from_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        to_dt = now

        events = fetch_economic_events(from_dt, to_dt)
        if events is None:
            return redirect(url_for("news_api_guide", error="Failed to fetch events from source"))

        saved, updated = _save_events_to_db(db, events)
        return redirect(url_for("news_api_guide", message=f"Updated: {saved} new, {updated} overwritten ({len(events)} fetched)"))

    except Exception as e:
        db.rollback()
        return redirect(url_for("news_api_guide", error=str(e)))
    finally:
        db.close()


@app.route("/news/save-range", methods=["POST"])
@login_required
def news_save_range():
    """
    Web route: fetch events for a custom date range and save to database.
    Form fields: from_date, to_date
    """
    db = get_db()
    try:
        from_date = request.form.get("from_date", "").strip()
        to_date = request.form.get("to_date", "").strip()

        if not from_date or not to_date:
            return redirect(url_for("news_api_guide", error="Both dates are required"))

        try:
            from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            return redirect(url_for("news_api_guide", error="Invalid date format"))

        events = fetch_economic_events(from_dt, to_dt)
        if events is None:
            return redirect(url_for("news_api_guide", error="Failed to fetch events from source"))

        saved, updated = _save_events_to_db(db, events)
        return redirect(url_for("news_api_guide", message=f"Saved {saved} new, {updated} overwritten from {from_date} to {to_date} ({len(events)} fetched)"))

    except Exception as e:
        db.rollback()
        return redirect(url_for("news_api_guide", error=str(e)))
    finally:
        db.close()


# ─── Smart Updater Toggle ────────────────────────────────────────────


@app.route("/news/smart-updater/toggle", methods=["POST"])
@login_required
def smart_updater_toggle():
    action = request.form.get("action", "").strip()
    if action == "enable":
        smart_updater.enable()
        return redirect(url_for("news_api_guide", message="Smart updater enabled"))
    elif action == "disable":
        smart_updater.disable()
        return redirect(url_for("news_api_guide", message="Smart updater disabled"))
    return redirect(url_for("news_api_guide"))


@app.route("/api/smart-updater/status")
def api_smart_updater_status():
    """JSON endpoint for smart updater status."""
    return jsonify(smart_updater.status())


# ─── Web Scrape API ─────────────────────────────────────────────────────

import subprocess as _subprocess
import random as _random
import shlex as _shlex
import re as _re
from html import unescape as _html_unescape

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def _extract_content(html):
    """Extract title and meaningful text content from HTML (mirrors PHP extractMeaningfulContent)."""
    if not html:
        return "", ""

    # Remove scripts, styles, comments
    cleaned = _re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", "", html, flags=_re.I | _re.S)
    cleaned = _re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", "", cleaned, flags=_re.I | _re.S)
    cleaned = _re.sub(r"<!--.*?-->", "", cleaned, flags=_re.S)

    # Remove navigation / chrome elements that pollute content
    for tag in ("nav", "header", "footer", "aside", "noscript", "svg", "iframe", "form"):
        cleaned = _re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>", "", cleaned, flags=_re.I | _re.S
        )

    # Remove common noise: buttons, inputs, selects, labels
    cleaned = _re.sub(r"<(button|input|select|option|label)\b[^>]*>.*?</\1>", "", cleaned, flags=_re.I | _re.S)
    cleaned = _re.sub(r"<(button|input|select|option|label)\b[^>]*/?>", "", cleaned, flags=_re.I | _re.S)

    # Remove img/br/hr self-closing tags
    cleaned = _re.sub(r"<(img|br|hr)\b[^>]*/?>", "", cleaned, flags=_re.I)

    # Extract title
    title = ""
    m = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.I | _re.S)
    if m:
        title = _html_unescape(_re.sub(r"<[^>]+>", "", m.group(1))).strip()

    # Extract content from semantic elements (priority order, stop at first match)
    content_parts = []
    for pattern in [
        r"<main[^>]*>(.*?)</main>",
        r"<article[^>]*>(.*?)</article>",
        r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
        r"<section[^>]*>(.*?)</section>",
        r"<p[^>]*>(.*?)</p>",
    ]:
        matches = _re.findall(pattern, cleaned, _re.I | _re.S)
        if matches:
            content_parts.extend(matches)
            break

    # If we got a large container (main/article), re-extract just <p> tags from it
    if content_parts and len(content_parts) <= 3:
        inner_html = " ".join(content_parts)
        paragraphs = _re.findall(r"<p[^>]*>(.*?)</p>", inner_html, _re.I | _re.S)
        if paragraphs:
            content_parts = paragraphs

    meaningful = []
    seen = set()
    for part in content_parts:
        # Strip all HTML tags
        text = _re.sub(r"<[^>]+>", "", part)
        text = _html_unescape(text)
        text = _re.sub(r"\s+", " ", text).strip()
        if len(text) > 20 and text not in seen:
            seen.add(text)
            meaningful.append(text)

    content = "\n\n".join(meaningful)
    return title, content


@app.route("/api/scrape")
def api_scrape():
    api_key = request.args.get("api_key", "").strip()

    # Reconstruct the full target URL from the raw query string so that
    # URLs containing their own ?key=val (e.g. Google search) aren't
    # truncated by Flask's query-string parsing.
    url_param = ""
    raw_qs = request.query_string.decode("utf-8", errors="replace")
    if "url=" in raw_qs:
        # Grab everything after the first 'url=' up to the next known param
        _known_params = ("&api_key=", "&auth_user=", "&auth_pass=",
                         "&bearer_token=", "&session_cookie=", "&custom_headers=")
        after = raw_qs.split("url=", 1)[1]
        # Strip any trailing known params
        for kp in _known_params:
            idx = after.find(kp)
            if idx != -1:
                after = after[:idx]
        url_param = after.strip()

    if not api_key:
        return jsonify({"error": "api_key is required"}), 401
    if not url_param:
        return jsonify({"error": "url is required"}), 400

    db = get_db()
    try:
        user = db.query(User).filter(User.api_key == api_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 401

        # Validate / normalize URL
        if not url_param.startswith(("http://", "https://")):
            url_param = "https://" + url_param

        # Build the curl command — full browser mimicking (cookie jar, referer, sec-* headers)
        import tempfile as _tempfile
        import os as _os

        ua = _random.choice(_USER_AGENTS)
        parsed = url_param.split("/")
        origin = "/".join(parsed[:3])  # e.g. https://www.news24.com
        referer = origin + "/"

        # Cookie jar for storing/sending cookies across redirects
        cookie_file = _tempfile.NamedTemporaryFile(
            prefix="scrape_cookie_", suffix=".txt", delete=False
        ).name

        # Pre-flight: hit the homepage first to collect cookies (like a real browser)
        preflight_cmd = [
            "curl", "-s", "-o", "/dev/null",
            "-L", "--max-redirs", "5",
            "--connect-timeout", "10", "--max-time", "15",
            "-k", "--compressed", "--http2",
            "-c", cookie_file,
            "-H", f"User-Agent: {ua}",
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "Accept-Language: en-US,en;q=0.9",
            origin + "/",
        ]
        _subprocess.run(preflight_cmd, capture_output=True, text=True, timeout=20)
        import time as _time
        _time.sleep(_random.uniform(0.5, 1.5))  # brief pause like a human

        cmd = [
            "curl", "-s",
            "-L",                       # follow redirects (CURLOPT_FOLLOWLOCATION)
            "--max-redirs", "10",
            "--connect-timeout", "20",
            "--max-time", "60",
            "-k",                       # SSL verify off (CURLOPT_SSL_VERIFYPEER=false)
            "--compressed",             # Accept-Encoding gzip/deflate/br
            "--http2",                  # HTTP/2 — all modern browsers use it
            "-c", cookie_file,          # CURLOPT_COOKIEJAR — save cookies
            "-b", cookie_file,          # CURLOPT_COOKIEFILE — send cookies
            "-e", referer,              # Referer header (CURLOPT_AUTOREFERER)
            "-w", "\n__HTTP_CODE__:%{http_code}\n__CONTENT_TYPE__:%{content_type}\n__EFFECTIVE_URL__:%{url_effective}",
            # Full browser headers
            "-H", f"User-Agent: {ua}",
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "-H", "Accept-Language: en-US,en;q=0.9",
            "-H", "Upgrade-Insecure-Requests: 1",
            "-H", "Cache-Control: no-cache",
            "-H", "Pragma: no-cache",
            # Sec-* headers (sent by all modern browsers)
            "-H", "Sec-Fetch-Dest: document",
            "-H", "Sec-Fetch-Mode: navigate",
            "-H", "Sec-Fetch-Site: same-origin",
            "-H", "Sec-Fetch-User: ?1",
            "-H", "Sec-Ch-Ua: \"Not_A Brand\";v=\"8\", \"Chromium\";v=\"120\", \"Google Chrome\";v=\"120\"",
            "-H", "Sec-Ch-Ua-Mobile: ?0",
            "-H", "Sec-Ch-Ua-Platform: \"macOS\"",
        ]

        # Optional authentication (mirrors PHP auth options)
        auth_user = request.args.get("auth_user", "").strip()
        auth_pass = request.args.get("auth_pass", "").strip()
        if auth_user:
            cmd += ["-u", f"{auth_user}:{auth_pass}"]

        bearer_token = request.args.get("bearer_token", "").strip()
        if bearer_token:
            cmd += ["-H", f"Authorization: Bearer {bearer_token}"]

        session_cookie = request.args.get("session_cookie", "").strip()
        if session_cookie:
            cmd += ["-b", session_cookie]

        custom_headers_raw = request.args.get("custom_headers", "").strip()
        if custom_headers_raw:
            import json as _json
            try:
                extra = _json.loads(custom_headers_raw)
                if isinstance(extra, dict):
                    for k, v in extra.items():
                        cmd += ["-H", f"{k}: {v}"]
            except _json.JSONDecodeError:
                pass

        cmd.append(url_param)

        # Retry loop (up to 3 attempts with delays, like PHP)
        max_retries = 3
        last_error = ""
        body = ""
        status_code = 0
        content_type = ""
        effective_url = url_param

        try:
            for attempt in range(1, max_retries + 1):
                result = _subprocess.run(cmd, capture_output=True, text=True, timeout=65)

                # Parse metadata from -w output
                output = result.stdout
                status_code = 0
                content_type = ""
                effective_url = url_param

                for line in reversed(output.split("\n")):
                    if line.startswith("__HTTP_CODE__:"):
                        try:
                            status_code = int(line.split(":", 1)[1])
                        except ValueError:
                            pass
                    elif line.startswith("__CONTENT_TYPE__:"):
                        content_type = line.split(":", 1)[1]
                    elif line.startswith("__EFFECTIVE_URL__:"):
                        effective_url = line.split(":", 1)[1]

                # Remove the metadata lines from body
                body_lines = []
                for line in output.split("\n"):
                    if line.startswith(("__HTTP_CODE__:", "__CONTENT_TYPE__:", "__EFFECTIVE_URL__:")):
                        continue
                    body_lines.append(line)
                body = "\n".join(body_lines).rstrip("\n")

                # Success — break out of retry loop
                if status_code and status_code < 400:
                    break

                # Don't retry client errors except 401/403/429 (might pass on retry)
                if 400 <= status_code < 500 and status_code not in (401, 403, 429):
                    break

                last_error = f"HTTP {status_code}"
                if attempt < max_retries:
                    _time.sleep(_random.uniform(2, 5))
                    # Update referer for subsequent attempts
                    for i, arg in enumerate(cmd):
                        if arg == "-e" and i + 1 < len(cmd):
                            cmd[i + 1] = effective_url
                            break
        finally:
            # Clean up cookie jar file
            try:
                _os.unlink(cookie_file)
            except OSError:
                pass

        # Detect bot-protection challenge pages
        _challenge_signatures = [
            ("Just a moment...", "Cloudflare"),
            ("Attention Required!", "Cloudflare"),
            ("captcha-delivery.com", "Datadome"),
            ("Please enable JS and disable any ad blocker", "Datadome"),
            ("Checking your browser", "Bot protection"),
            ("Access denied", "WAF"),
            ("cf-browser-verification", "Cloudflare"),
            ("_cf_chl_opt", "Cloudflare"),
        ]
        for sig, provider in _challenge_signatures:
            if sig in body:
                return jsonify({
                    "error": f"Bot protection detected ({provider}). This site requires a real browser to bypass its JS challenge.",
                    "url": effective_url,
                    "status_code": status_code,
                    "protection": provider,
                }), 403

        # Extract meaningful content
        title, content = _extract_content(body)

        return jsonify({
            "url": effective_url,
            "status_code": status_code,
            "title": title,
            "content": content,
            "content_length": len(content),
        }), 200

    except _subprocess.TimeoutExpired:
        try:
            _os.unlink(cookie_file)
        except Exception:
            pass
        return jsonify({"error": "Request timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Scrape API Guide Page ──────────────────────────────────────────────


@app.route("/scrape-api")
@login_required
def scrape_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        return render_template(
            "scrape_guide.html",
            user=user,
            api_key=user.api_key,
            active_page="scrape_api",
            app_name=APP_NAME,
        )
    finally:
        db.close()


# ─── MCP Server Guide Page ──────────────────────────────────────────────


@app.route("/mcp-server")
@login_required
def mcp_server_guide():
    import sys, os
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        # Auto-detect paths — works on any machine
        python_path = sys.executable
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mcp_path = os.path.join(project_dir, "mcp_server.py")
        site_url = (user.site_url or "http://localhost:5001").rstrip("/")
        return render_template(
            "mcp_guide.html",
            user=user,
            api_key=user.api_key,
            active_page="mcp_server",
            app_name=APP_NAME,
            python_path=python_path,
            mcp_server_path=mcp_path,
            site_url_value=site_url,
        )
    finally:
        db.close()


@app.route("/asp-guide")
def asp_guide_page():
    """ASP (Agent Server Protocol) documentation page."""
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        site_url = (user.site_url or "http://localhost:5001").rstrip("/")
        return render_template(
            "asp_guide.html",
            user=user,
            api_key=user.api_key,
            active_page="asp_guide",
            app_name=APP_NAME,
            site_url=site_url,
        )
    finally:
        db.close()


@app.route("/api/mcp-config")
def api_mcp_config():
    """Return auto-detected MCP config JSON — ready to paste into any MCP client.
    Optional query param: ?format=claude|vscode|cursor (default: claude)"""
    import sys, os
    fmt = request.args.get("format", "claude").lower()
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_path = sys.executable
    mcp_path = os.path.join(project_dir, "mcp_server.py")

    # Get site_url and api_key from user
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    site_url = "http://localhost:5001"
    user_api_key = ""
    if api_key:
        db = get_db()
        try:
            user = db.query(User).filter(User.api_key == api_key).first()
            if user:
                if user.site_url:
                    site_url = user.site_url.rstrip("/")
                user_api_key = user.api_key
        finally:
            db.close()

    server_entry = {
        "command": python_path,
        "args": [mcp_path],
        "env": {
            "ARRISSA_API_URL": site_url,
            "ARRISSA_API_KEY": user_api_key,
        },
    }

    if fmt == "vscode":
        config = {"servers": {"arrissa-trading-api": server_entry}}
    else:
        config = {"mcpServers": {"arrissa-trading-api": server_entry}}

    return jsonify(config)


# ─── Public API: Account Details (State) ─────────────────────────────────


# Cache for config column names (per environment) — avoids re-fetching every request
_config_cache = {}  # { (env): { "columns": [...], "fetched_at": timestamp } }
_CONFIG_CACHE_TTL = 3600  # 1 hour


def _get_account_detail_columns(access_token, acc_num, environment):
    """Fetch and cache the accountDetailsConfig columns from /trade/config."""
    return _get_config_columns(access_token, acc_num, environment, "accountDetailsConfig")


def _get_config_columns(access_token, acc_num, environment, config_key):
    """Generic helper: fetch and cache columns from a /trade/config section."""
    import time as _time
    cache_key = (environment, config_key)
    cached = _config_cache.get(cache_key)
    if cached and (_time.time() - cached["fetched_at"]) < _CONFIG_CACHE_TTL:
        return cached["columns"]

    config = tradelocker_get_config(access_token, acc_num, environment)
    if config and "d" in config:
        section = config["d"].get(config_key, {})
        raw_columns = section.get("columns", [])
        columns = [col["id"] for col in raw_columns if isinstance(col, dict) and "id" in col]
        _config_cache[cache_key] = {"columns": columns, "fetched_at": _time.time()}
        # Cache all other sections from the same config response to avoid repeated calls
        for other_key in ["accountDetailsConfig", "ordersConfig", "ordersHistoryConfig", "positionsConfig", "filledOrdersConfig"]:
            if other_key != config_key and other_key in config["d"]:
                other_section = config["d"][other_key]
                other_cols = [col["id"] for col in other_section.get("columns", []) if isinstance(col, dict) and "id" in col]
                other_cache_key = (environment, other_key)
                if other_cache_key not in _config_cache:
                    _config_cache[other_cache_key] = {"columns": other_cols, "fetched_at": _time.time()}
        return columns
    return None


@app.route("/api/account-details")
def api_account_details():
    """
    Get current account state from TradeLocker (balance, equity, PnL, margin, etc.).
    Accepts api_key and arrissa_account_id via headers or query params.
    Optional: field — return only a specific field by name.
    """
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
    field = request.args.get("field", "").strip()

    if not api_key:
        return jsonify({"error": "Missing api_key — pass via X-API-Key header or ?api_key="}), 401

    arrissa_account_id = _resolve_default_account(api_key, arrissa_account_id)
    if not arrissa_account_id:
        return jsonify({"error": "Missing arrissa_account_id — pass via X-Arrissa-Account-Id header or ?arrissa_account_id="}), 400

    db = get_db()
    try:
        # Validate API key
        user = None
        if api_key == API_KEY:
            user = db.query(User).first()
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
        if not user:
            return jsonify({"error": "Unauthorized — invalid API key"}), 401

        # Find account
        account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.arrissa_id == arrissa_account_id,
            TradeLockerAccount.user_id == user.id,
        ).first()
        if not account:
            return jsonify({"error": f"Account '{arrissa_account_id}' not found for this user"}), 404

        credential = db.query(TradeLockerCredential).filter(
            TradeLockerCredential.id == account.credential_id
        ).first()
        if not credential:
            return jsonify({"error": "No credential found for this account"}), 404

        # Ensure valid token
        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        # Fetch config columns and account state
        columns = _get_account_detail_columns(access_token, account.acc_num, credential.environment)
        state_data = tradelocker_get_account_state(
            access_token, account.account_id, account.acc_num, credential.environment
        )

        if state_data is None:
            # Retry once with forced token refresh
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            columns = _get_account_detail_columns(access_token, account.acc_num, credential.environment)
            state_data = tradelocker_get_account_state(
                access_token, account.account_id, account.acc_num, credential.environment
            )

        if state_data is None:
            return jsonify({"error": "Failed to fetch account state from TradeLocker"}), 502

        if columns is None:
            return jsonify({"error": "Failed to fetch config columns from TradeLocker"}), 502

        # Zip columns + values into a named dict
        named = {}
        for i, val in enumerate(state_data):
            col_name = columns[i] if i < len(columns) else f"field_{i}"
            named[col_name] = val

        # Build wrapper key
        server_name = credential.server.replace(" ", "_").upper()
        env = credential.environment
        wrapper_key = f"arrissa_data_{server_name}_{env}"

        # If a specific field is requested
        if field:
            if field in named:
                return jsonify({
                    wrapper_key: {
                        "arrissa_account_id": arrissa_account_id,
                        "field": field,
                        "value": named[field],
                    }
                })
            available = list(named.keys())
            return jsonify({"error": f"Unknown field '{field}'. Available fields: {', '.join(available)}"}), 400

        # Return full summary
        result = {
            "arrissa_account_id": arrissa_account_id,
            **named,
        }

        return jsonify({wrapper_key: result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Account Details API Guide Page ─────────────────────────────────────


@app.route("/account-details-api")
@login_required
def account_details_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        first_account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        example_account_id = first_account.arrissa_id if first_account else "ACCTID"

        # Try to get the column names for the guide
        detail_columns = []
        if first_account:
            cred = db.query(TradeLockerCredential).filter(
                TradeLockerCredential.id == first_account.credential_id
            ).first()
            if cred and cred.access_token:
                try:
                    token, _ = _ensure_valid_token(db, cred)
                    if token:
                        detail_columns = _get_account_detail_columns(token, first_account.acc_num, cred.environment) or []
                except Exception:
                    pass

        return render_template(
            "account_details_guide.html",
            user=user,
            api_key=user.api_key,
            example_account_id=example_account_id,
            detail_columns=detail_columns,
            active_page="account_details_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ─── Order API — orders, orders history, positions ────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _rows_to_dicts(rows, columns):
    """Convert a list of raw arrays into a list of named dicts using config columns."""
    # columns may be a dict {index: name} or a list — normalise to list
    if isinstance(columns, dict):
        max_idx = max((int(k) for k in columns), default=-1)
        col_list = [columns.get(str(i), columns.get(i, f"field_{i}")) for i in range(max_idx + 1)]
    else:
        col_list = columns
    result = []
    for row in rows:
        obj = {}
        for i, val in enumerate(row):
            col_name = col_list[i] if i < len(col_list) else f"field_{i}"
            obj[col_name] = val
        result.append(obj)
    return result


# ── Instrument map & record enrichment ────────────────────────────────────────

_instrument_map_cache = {}  # { (env, account_id): { "map": {...}, "fetched_at": ts } }
_INSTRUMENT_MAP_TTL = 3600  # 1 hour


def _build_instrument_map(access_token, account_id, acc_num, environment):
    """
    Build and cache a dict mapping tradableInstrumentId (str) → symbol name.
    e.g. {"206": "BTCUSD", "34": "EURUSD", ...}
    """
    import time as _time
    cache_key = (environment, account_id)
    cached = _instrument_map_cache.get(cache_key)
    if cached and (_time.time() - cached["fetched_at"]) < _INSTRUMENT_MAP_TTL:
        return cached["map"]

    instruments = tradelocker_get_instruments(access_token, account_id, acc_num, environment)
    inst_map = {}
    if instruments:
        for inst in instruments:
            tid = inst.get("tradableInstrumentId")
            name = inst.get("name", "")
            if tid is not None:
                inst_map[str(tid)] = name
    _instrument_map_cache[cache_key] = {"map": inst_map, "fetched_at": _time.time()}
    return inst_map


# Fields known to contain Unix-millisecond timestamps
_TIMESTAMP_FIELDS = {
    "openDate", "closeDate", "createdDate", "modifiedDate",
    "expirationDate", "filledDate", "cancelledDate", "lastModified",
    "lastUpdateDate", "updateDate", "created", "closed",
}


def _ms_to_utc(val):
    """Convert a Unix-millisecond value (str or int) to a readable UTC timestamp."""
    try:
        ts = int(val)
        if ts <= 0:
            return val
        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return val


def _enrich_records(records, instrument_map):
    """
    Enrich a list of dicts:
      1) Add 'symbol' from tradableInstrumentId lookup
      2) Convert known timestamp fields from Unix ms → readable UTC
    """
    for rec in records:
        # ── Add symbol name ──────────────────────────────────────────
        tid = rec.get("tradableInstrumentId")
        if tid is not None:
            sym = instrument_map.get(str(tid))
            if sym:
                rec["symbol"] = sym
            else:
                rec["symbol"] = f"unknown({tid})"

        # ── Convert timestamps ───────────────────────────────────────
        for key in list(rec.keys()):
            if key in _TIMESTAMP_FIELDS and rec[key] is not None:
                rec[key] = _ms_to_utc(rec[key])
    return records


def _validate_api_and_account(db):
    """Shared validation for Order API endpoints. Returns (user, account, credential, error_resp)."""
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")

    if not api_key:
        return None, None, None, (jsonify({"error": "Missing api_key — pass via X-API-Key header or ?api_key="}), 401)
    arrissa_account_id = _resolve_default_account(api_key, arrissa_account_id)
    if not arrissa_account_id:
        return None, None, None, (jsonify({"error": "Missing arrissa_account_id — pass via X-Arrissa-Account-Id header or ?arrissa_account_id="}), 400)

    user = None
    if api_key == API_KEY:
        user = db.query(User).first()
    else:
        user = db.query(User).filter(User.api_key == api_key).first()
    if not user:
        return None, None, None, (jsonify({"error": "Unauthorized — invalid API key"}), 401)

    account = db.query(TradeLockerAccount).filter(
        TradeLockerAccount.arrissa_id == arrissa_account_id,
        TradeLockerAccount.user_id == user.id,
    ).first()
    if not account:
        return None, None, None, (jsonify({"error": f"Account '{arrissa_account_id}' not found for this user"}), 404)

    credential = db.query(TradeLockerCredential).filter(
        TradeLockerCredential.id == account.credential_id
    ).first()
    if not credential:
        return None, None, None, (jsonify({"error": "No credential found for this account"}), 404)

    return user, account, credential, None


def _build_wrapper_key(credential):
    server_name = credential.server.replace(" ", "_").upper()
    env = credential.environment
    return f"arrissa_data_{server_name}_{env}"


@app.route("/api/orders")
def api_orders():
    """
    Get active (non-final) orders from TradeLocker.
    Optional query params: from, to (Unix ms), tradable_instrument_id.
    """
    db = get_db()
    try:
        user, account, credential, err = _validate_api_and_account(db)
        if err:
            return err

        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        from_ms = request.args.get("from", type=int)
        to_ms = request.args.get("to", type=int)
        instrument_id = request.args.get("tradable_instrument_id", type=int)

        columns = _get_config_columns(access_token, account.acc_num, credential.environment, "ordersConfig")
        raw_orders = tradelocker_get_orders(
            access_token, account.account_id, account.acc_num, credential.environment,
            from_ms=from_ms, to_ms=to_ms, tradable_instrument_id=instrument_id,
        )

        if raw_orders is None:
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            columns = _get_config_columns(access_token, account.acc_num, credential.environment, "ordersConfig")
            raw_orders = tradelocker_get_orders(
                access_token, account.account_id, account.acc_num, credential.environment,
                from_ms=from_ms, to_ms=to_ms, tradable_instrument_id=instrument_id,
            )

        if raw_orders is None:
            return jsonify({"error": "Failed to fetch orders from TradeLocker"}), 502
        if columns is None:
            return jsonify({"error": "Failed to fetch config columns from TradeLocker"}), 502

        arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
        wrapper_key = _build_wrapper_key(credential)
        orders = _rows_to_dicts(raw_orders, columns)

        # Enrich with symbol name & readable timestamps
        inst_map = _build_instrument_map(access_token, account.account_id, account.acc_num, credential.environment)
        _enrich_records(orders, inst_map)

        return jsonify({
            wrapper_key: {
                "arrissa_account_id": arrissa_account_id,
                "count": len(orders),
                "orders": orders,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/orders-history")
def api_orders_history():
    """
    Get orders history (filled, cancelled, rejected) from TradeLocker.
    Optional query params: from, to (Unix ms), tradable_instrument_id.
    """
    db = get_db()
    try:
        user, account, credential, err = _validate_api_and_account(db)
        if err:
            return err

        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        from_ms = request.args.get("from", type=int)
        to_ms = request.args.get("to", type=int)
        instrument_id = request.args.get("tradable_instrument_id", type=int)

        columns = _get_config_columns(access_token, account.acc_num, credential.environment, "ordersHistoryConfig")
        result = tradelocker_get_orders_history(
            access_token, account.account_id, account.acc_num, credential.environment,
            from_ms=from_ms, to_ms=to_ms, tradable_instrument_id=instrument_id,
        )

        if result is None:
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            columns = _get_config_columns(access_token, account.acc_num, credential.environment, "ordersHistoryConfig")
            result = tradelocker_get_orders_history(
                access_token, account.account_id, account.acc_num, credential.environment,
                from_ms=from_ms, to_ms=to_ms, tradable_instrument_id=instrument_id,
            )

        if result is None:
            return jsonify({"error": "Failed to fetch order history from TradeLocker"}), 502
        if columns is None:
            return jsonify({"error": "Failed to fetch config columns from TradeLocker"}), 502

        arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
        wrapper_key = _build_wrapper_key(credential)
        orders = _rows_to_dicts(result["ordersHistory"], columns)

        # Enrich with symbol name & readable timestamps
        inst_map = _build_instrument_map(access_token, account.account_id, account.acc_num, credential.environment)
        _enrich_records(orders, inst_map)

        return jsonify({
            wrapper_key: {
                "arrissa_account_id": arrissa_account_id,
                "count": len(orders),
                "has_more": result["hasMore"],
                "orders_history": orders,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/positions")
def api_positions():
    """
    Get currently open positions from TradeLocker.
    """
    db = get_db()
    try:
        user, account, credential, err = _validate_api_and_account(db)
        if err:
            return err

        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        columns = _get_config_columns(access_token, account.acc_num, credential.environment, "positionsConfig")
        raw_positions = tradelocker_get_positions(
            access_token, account.account_id, account.acc_num, credential.environment,
        )

        if raw_positions is None:
            access_token, err = _ensure_valid_token(db, credential, force_refresh=True)
            if err:
                return err
            columns = _get_config_columns(access_token, account.acc_num, credential.environment, "positionsConfig")
            raw_positions = tradelocker_get_positions(
                access_token, account.account_id, account.acc_num, credential.environment,
            )

        if raw_positions is None:
            return jsonify({"error": "Failed to fetch positions from TradeLocker"}), 502
        if columns is None:
            return jsonify({"error": "Failed to fetch config columns from TradeLocker"}), 502

        arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
        wrapper_key = _build_wrapper_key(credential)
        positions = _rows_to_dicts(raw_positions, columns)

        # Enrich with symbol name & readable timestamps
        inst_map = _build_instrument_map(access_token, account.account_id, account.acc_num, credential.environment)
        _enrich_records(positions, inst_map)

        return jsonify({
            wrapper_key: {
                "arrissa_account_id": arrissa_account_id,
                "count": len(positions),
                "positions": positions,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Order API Guide Page ───────────────────────────────────────────────


@app.route("/order-api")
@login_required
def order_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        first_account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        example_account_id = first_account.arrissa_id if first_account else "ACCTID"

        orders_columns = []
        orders_history_columns = []
        positions_columns = []
        if first_account:
            cred = db.query(TradeLockerCredential).filter(
                TradeLockerCredential.id == first_account.credential_id
            ).first()
            if cred and cred.access_token:
                try:
                    token, _ = _ensure_valid_token(db, cred)
                    if token:
                        orders_columns = _get_config_columns(token, first_account.acc_num, cred.environment, "ordersConfig") or []
                        orders_history_columns = _get_config_columns(token, first_account.acc_num, cred.environment, "ordersHistoryConfig") or []
                        positions_columns = _get_config_columns(token, first_account.acc_num, cred.environment, "positionsConfig") or []
                except Exception:
                    pass

        return render_template(
            "order_guide.html",
            user=user,
            api_key=user.api_key,
            example_account_id=example_account_id,
            orders_columns=orders_columns,
            orders_history_columns=orders_history_columns,
            positions_columns=positions_columns,
            active_page="order_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ─── Trading API — open, close, modify trades via simple query params ─────────
# ═══════════════════════════════════════════════════════════════════════════════


def _find_instrument(instruments, symbol_name):
    """Find instrument dict by symbol name (case-insensitive)."""
    symbol_upper = symbol_name.upper()
    for inst in instruments:
        if inst.get("name", "").upper() == symbol_upper:
            return inst
    return None


def _get_instrument_ids(instruments, symbol_name):
    """Return (tradableInstrumentId, routeId) for a symbol, or (None, None)."""
    inst = _find_instrument(instruments, symbol_name)
    if not inst:
        return None, None
    tradable_id = inst.get("tradableInstrumentId")
    routes = inst.get("routes", [])
    route_id = None
    for r in routes:
        if r.get("type") == "TRADE":
            route_id = r.get("id")
            break
    if not route_id and routes:
        route_id = routes[0].get("id")
    return tradable_id, route_id


def _positions_to_dicts(positions_raw, config_columns):
    """Convert position arrays to dicts with column names."""
    # config_columns may be a dict {index: name} or a list — normalise to list
    if isinstance(config_columns, dict):
        max_idx = max((int(k) for k in config_columns), default=-1)
        col_list = [config_columns.get(str(i), config_columns.get(i, f"field_{i}")) for i in range(max_idx + 1)]
    else:
        col_list = config_columns
    result = []
    for row in positions_raw:
        obj = {}
        for i, val in enumerate(row):
            col = col_list[i] if i < len(col_list) else f"field_{i}"
            obj[col] = val
        result.append(obj)
    return result


@app.route("/api/trade")
def api_trade():
    """
    Unified Trading API — execute trading actions via simple query parameters.

    Supported actions:
      Market:  BUY, SELL
      Pending: BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP
      Close:   CLOSE (by ticket), CLOSE_ALL, CLOSE_LOSS, CLOSE_PROFIT
      Modify:  MODIFY_TP, MODIFY_SL, BREAK_EVEN, BREAK_EVEN_ALL, TRAIL_SL
      Orders:  DELETE_ORDER, DELETE_ALL_ORDERS, MODIFY_ORDER

    Query-string history & profit tracking:
      ?history=today|last-hour|last-10|last-20|last-7days|last-30days
      ?profit=today|last-hour|this-week|this-month|last-7days|last-30days
    """
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    arrissa_account_id = request.headers.get("X-Arrissa-Account-Id") or request.args.get("arrissa_account_id")
    action = request.args.get("action", "").strip().upper()
    symbol = request.args.get("symbol", "").strip().upper()
    volume = request.args.get("volume", "").strip()
    sl_raw = request.args.get("sl", "").strip()
    tp_raw = request.args.get("tp", "").strip()
    price_raw = request.args.get("price", "").strip()
    ticket = request.args.get("ticket", "").strip()
    new_value_raw = request.args.get("new_value", "").strip()
    history_param = request.args.get("history", "").strip().lower()
    profit_param = request.args.get("profit", "").strip().lower()

    if not api_key:
        return jsonify({"error": "Missing api_key"}), 401
    arrissa_account_id = _resolve_default_account(api_key, arrissa_account_id)
    if not arrissa_account_id:
        return jsonify({"error": "Missing arrissa_account_id"}), 400

    # Must have at least one action, history, or profit param
    if not action and not history_param and not profit_param:
        return jsonify({"error": "Missing required parameter: action, history, or profit"}), 400

    db = get_db()
    try:
        # ── Auth ─────────────────────────────────────────────────────────
        user = None
        if api_key == API_KEY:
            user = db.query(User).first()
        else:
            user = db.query(User).filter(User.api_key == api_key).first()
        if not user:
            return jsonify({"error": "Unauthorized — invalid API key"}), 401

        account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.arrissa_id == arrissa_account_id,
            TradeLockerAccount.user_id == user.id,
        ).first()
        if not account:
            return jsonify({"error": f"Account '{arrissa_account_id}' not found"}), 404

        credential = db.query(TradeLockerCredential).filter(
            TradeLockerCredential.id == account.credential_id
        ).first()
        if not credential:
            return jsonify({"error": "No credential found"}), 404

        access_token, err = _ensure_valid_token(db, credential)
        if err:
            return err

        wrapper_key = _build_wrapper_key(credential)

        # ── Helper: get config columns ───────────────────────────────────
        def _get_pos_columns():
            return _get_config_columns(access_token, account.acc_num, credential.environment, "positionsConfig") or []

        def _get_order_columns():
            return _get_config_columns(access_token, account.acc_num, credential.environment, "ordersConfig") or []

        def _get_history_columns():
            return _get_config_columns(access_token, account.acc_num, credential.environment, "ordersHistoryConfig") or []

        # ── Helper: get instruments once if needed ─────────────────────
        _instruments_cache = {}

        def _get_instruments():
            if "data" not in _instruments_cache:
                _instruments_cache["data"] = tradelocker_get_instruments(
                    access_token, account.account_id, account.acc_num, credential.environment
                )
            return _instruments_cache["data"]

        # ── Helper: float parsing ────────────────────────────────────────
        def _float(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # ══════════════════════════════════════════════════════════════════
        # HISTORY queries
        # ══════════════════════════════════════════════════════════════════
        if history_param:
            now = datetime.now(tz=timezone.utc)
            from_ms = None
            to_ms = int(now.timestamp() * 1000)
            limit_count = None

            if history_param == "today":
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                from_ms = int(start_of_day.timestamp() * 1000)
            elif history_param == "last-hour":
                from_ms = int((now - timedelta(hours=1)).timestamp() * 1000)
            elif history_param.startswith("last-") and history_param.endswith("days"):
                try:
                    days = int(history_param.replace("last-", "").replace("days", ""))
                    from_ms = int((now - timedelta(days=days)).timestamp() * 1000)
                except ValueError:
                    return jsonify({"error": f"Invalid history param: {history_param}"}), 400
            elif history_param.startswith("last-"):
                try:
                    limit_count = int(history_param.replace("last-", ""))
                except ValueError:
                    return jsonify({"error": f"Invalid history param: {history_param}"}), 400
            else:
                return jsonify({"error": f"Unknown history value: {history_param}. Use: today, last-hour, last-10, last-20, last-7days, last-30days"}), 400

            history_data = tradelocker_get_orders_history(
                access_token, account.account_id, account.acc_num, credential.environment,
                from_ms=from_ms, to_ms=to_ms,
            )
            if history_data is None:
                return jsonify({"error": "Failed to fetch trade history"}), 502

            cols = _get_history_columns()
            trades = _rows_to_dicts(history_data.get("ordersHistory", []), cols)

            # Enrich with symbol name & readable timestamps
            inst_map = _build_instrument_map(access_token, account.account_id, account.acc_num, credential.environment)
            _enrich_records(trades, inst_map)

            # Only include orders that actually opened/closed positions (status=Filled)
            filled_trades = [t for t in trades if t.get("status") == "Filled"]

            if limit_count is not None:
                filled_trades = filled_trades[-limit_count:]

            return jsonify({wrapper_key: {
                "arrissa_account_id": arrissa_account_id,
                "query": f"history={history_param}",
                "count": len(filled_trades),
                "trades": filled_trades,
            }}), 200

        # ══════════════════════════════════════════════════════════════════
        # PROFIT queries
        # ══════════════════════════════════════════════════════════════════
        if profit_param:
            now = datetime.now(tz=timezone.utc)
            from_ms = None
            to_ms = int(now.timestamp() * 1000)

            if profit_param == "today":
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                from_ms = int(start_of_day.timestamp() * 1000)
            elif profit_param == "last-hour":
                from_ms = int((now - timedelta(hours=1)).timestamp() * 1000)
            elif profit_param == "this-week":
                start_of_week = now - timedelta(days=now.weekday())
                start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
                from_ms = int(start_of_week.timestamp() * 1000)
            elif profit_param == "this-month":
                start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                from_ms = int(start_of_month.timestamp() * 1000)
            elif profit_param.startswith("last-") and profit_param.endswith("days"):
                try:
                    days = int(profit_param.replace("last-", "").replace("days", ""))
                    from_ms = int((now - timedelta(days=days)).timestamp() * 1000)
                except ValueError:
                    return jsonify({"error": f"Invalid profit param: {profit_param}"}), 400
            else:
                return jsonify({"error": f"Unknown profit value: {profit_param}. Use: today, last-hour, this-week, this-month, last-7days, last-30days"}), 400

            history_data = tradelocker_get_orders_history(
                access_token, account.account_id, account.acc_num, credential.environment,
                from_ms=from_ms, to_ms=to_ms,
            )
            if history_data is None:
                return jsonify({"error": "Failed to fetch trade history for profit calculation"}), 502

            # Also get open positions for unrealised P/L
            positions_raw = tradelocker_get_positions(access_token, account.account_id, account.acc_num, credential.environment)
            pos_cols = _get_pos_columns()
            open_positions = _positions_to_dicts(positions_raw or [], pos_cols) if positions_raw else []
            unrealised_pl = sum(_float(p.get("unrealizedPl", 0)) or 0 for p in open_positions)

            # Sum realised P/L from closed trades (use avgPrice, qty, side heuristics)
            # TradeLocker doesn't give explicit P/L per closed trade; we sum based on filled orders
            # For simplicity, report the unrealised P/L from positions + number of closed trades
            cols = _get_history_columns()
            trades = _rows_to_dicts(history_data.get("ordersHistory", []), cols)

            # Enrich with symbol name & readable timestamps
            inst_map = _build_instrument_map(access_token, account.account_id, account.acc_num, credential.environment)
            _enrich_records(trades, inst_map)

            filled = [t for t in trades if t.get("status") == "Filled"]

            return jsonify({wrapper_key: {
                "arrissa_account_id": arrissa_account_id,
                "query": f"profit={profit_param}",
                "period_closed_trades": len(filled),
                "open_positions": len(open_positions),
                "unrealised_pl": round(unrealised_pl, 2),
                "note": "For realised P/L, check account balance changes via Account Details API.",
            }}), 200

        # ══════════════════════════════════════════════════════════════════
        # TRADING ACTIONS  (execute → return broker response, no pre-fetching)
        # ══════════════════════════════════════════════════════════════════

        # ── Market & Pending Orders: BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP
        if action in ("BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
            if not symbol:
                return jsonify({"error": "Missing required parameter: symbol"}), 400
            if not volume:
                return jsonify({"error": "Missing required parameter: volume"}), 400
            vol = _float(volume)
            if vol is None or vol <= 0:
                return jsonify({"error": "volume must be a positive number"}), 400

            instruments = _get_instruments()
            if not instruments:
                return jsonify({"error": "Failed to fetch instruments"}), 502

            tradable_id, route_id = _get_instrument_ids(instruments, symbol)
            if not tradable_id or not route_id:
                return jsonify({"error": f"Symbol '{symbol}' not found for this account"}), 404

            side = "buy" if action in ("BUY", "BUY_LIMIT", "BUY_STOP") else "sell"

            if action in ("BUY", "SELL"):
                order_type = "market"
                price = 0
            elif action in ("BUY_LIMIT", "SELL_LIMIT"):
                order_type = "limit"
                price = _float(price_raw)
                if price is None or price <= 0:
                    return jsonify({"error": "Limit orders require a valid price parameter"}), 400
            else:  # BUY_STOP, SELL_STOP
                order_type = "stop"
                price = _float(price_raw)
                if price is None or price <= 0:
                    return jsonify({"error": "Stop orders require a valid price parameter"}), 400

            sl = _float(sl_raw) if sl_raw else None
            tp = _float(tp_raw) if tp_raw else None
            stop_price = price if order_type == "stop" else None

            result = tradelocker_place_order(
                access_token=access_token,
                account_id=account.account_id,
                acc_num=account.acc_num,
                tradable_instrument_id=tradable_id,
                route_id=route_id,
                side=side,
                order_type=order_type,
                qty=vol,
                price=price if order_type == "limit" else 0,
                stop_price=stop_price,
                stop_loss=sl,
                take_profit=tp,
                environment=credential.environment,
            )

            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": action, "symbol": symbol, "status": "error",
                    "message": f"Failed to place {action} order for {symbol}",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)

            order_id = result.get("orderId") if result else None
            return jsonify({wrapper_key: {
                "action": action,
                "status": "executed",
                "message": f"{action} {vol} lot(s) {symbol} — order placed" + (f" (ID: {order_id})" if order_id else ""),
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "volume": vol,
                "price": price if order_type != "market" else "market",
                "stop_loss": sl,
                "take_profit": tp,
                "broker_response": result,
            }}), 200

        # ── CLOSE — close by ticket or by symbol ────────────────────────
        if action == "CLOSE":
            if ticket:
                result = tradelocker_close_position(access_token, ticket, account.acc_num, qty=0, environment=credential.environment)
                if result and "error" in result:
                    return jsonify({wrapper_key: {
                        "action": "CLOSE", "ticket": ticket, "status": "error",
                        "message": f"Failed to close position {ticket} — it may not exist or is already closed",
                        "broker_error": result.get("error"),
                    }}), result.get("status_code", 500)
                return jsonify({wrapper_key: {
                    "action": "CLOSE",
                    "status": "executed",
                    "message": f"Close order placed for position {ticket}",
                    "ticket": ticket,
                    "broker_response": result,
                }}), 200

            if symbol:
                instruments = _get_instruments()
                if not instruments:
                    return jsonify({"error": "Failed to fetch instruments"}), 502
                tradable_id, _ = _get_instrument_ids(instruments, symbol)
                if not tradable_id:
                    return jsonify({"error": f"Symbol '{symbol}' not found"}), 404

                result = tradelocker_close_all_positions(access_token, account.account_id, account.acc_num, tradable_instrument_id=tradable_id, environment=credential.environment)
                if result and "error" in result:
                    return jsonify({wrapper_key: {
                        "action": "CLOSE", "symbol": symbol, "status": "error",
                        "message": f"Failed to close {symbol} positions",
                        "broker_error": result.get("error"),
                    }}), result.get("status_code", 500)
                return jsonify({wrapper_key: {
                    "action": "CLOSE",
                    "status": "executed",
                    "message": f"Close order placed for all {symbol} positions",
                    "symbol": symbol,
                    "broker_response": result,
                }}), 200

            return jsonify({"error": "CLOSE requires ticket or symbol parameter"}), 400

        # ── CLOSE_ALL ────────────────────────────────────────────────────
        if action == "CLOSE_ALL":
            tradable_id = None
            if symbol and symbol != "ALL":
                instruments = _get_instruments()
                if instruments:
                    tradable_id, _ = _get_instrument_ids(instruments, symbol)

            result = tradelocker_close_all_positions(access_token, account.account_id, account.acc_num, tradable_instrument_id=tradable_id, environment=credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "CLOSE_ALL", "symbol": symbol or "ALL", "status": "error",
                    "message": f"Failed to close positions",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)

            return jsonify({wrapper_key: {
                "action": "CLOSE_ALL",
                "status": "executed",
                "message": f"Close order placed for all positions" + (f" ({symbol})" if symbol and symbol != "ALL" else ""),
                "symbol": symbol or "ALL",
                "broker_response": result,
            }}), 200

        # ── CLOSE_LOSS / CLOSE_PROFIT — must fetch positions to check P/L ──
        if action in ("CLOSE_LOSS", "CLOSE_PROFIT"):
            positions_raw = tradelocker_get_positions(access_token, account.account_id, account.acc_num, credential.environment)
            if positions_raw is None:
                return jsonify({"error": "Failed to fetch positions"}), 502

            pos_cols = _get_pos_columns()
            positions = _positions_to_dicts(positions_raw, pos_cols)

            if not positions:
                return jsonify({wrapper_key: {
                    "action": action, "symbol": symbol or "ALL", "status": "no_positions",
                    "message": "No open positions found",
                }}), 200

            # Filter by symbol if not ALL
            if symbol and symbol != "ALL":
                imap = {str(i.get("tradableInstrumentId", "")): i.get("name", "") for i in (_get_instruments() or [])}
                positions = [p for p in positions if imap.get(str(p.get("tradableInstrumentId", "")), "").upper() == symbol]

            # Close qualifying positions
            closed = []
            failed = []
            skipped = 0
            for pos in positions:
                pl = _float(pos.get("unrealizedPl", 0)) or 0
                should_close = (action == "CLOSE_LOSS" and pl < 0) or (action == "CLOSE_PROFIT" and pl > 0)
                if not should_close:
                    skipped += 1
                    continue
                pos_id = pos.get("id")
                if pos_id:
                    res = tradelocker_close_position(access_token, pos_id, account.acc_num, qty=0, environment=credential.environment)
                    if res and "error" not in res:
                        closed.append({"position_id": pos_id, "side": pos.get("side"), "qty": pos.get("qty"), "pl": pl, "status": "closed"})
                    else:
                        failed.append({"position_id": pos_id, "pl": pl, "status": "failed", "broker_error": res.get("error") if res else "Unknown"})

            pl_type = "losing" if action == "CLOSE_LOSS" else "profitable"
            if not closed and not failed:
                return jsonify({wrapper_key: {
                    "action": action, "symbol": symbol or "ALL", "status": "no_matching",
                    "message": f"No {pl_type} positions found to close",
                    "positions_checked": len(positions),
                }}), 200

            return jsonify({wrapper_key: {
                "action": action,
                "status": "executed",
                "message": f"Closed {len(closed)} {pl_type} position(s), {len(failed)} failed, {skipped} skipped",
                "closed": closed,
                "failed": failed,
            }}), 200

        # ── MODIFY_TP ────────────────────────────────────────────────────
        if action == "MODIFY_TP":
            if not ticket:
                return jsonify({"error": "MODIFY_TP requires ticket parameter"}), 400
            new_tp = _float(new_value_raw)
            if new_tp is None:
                return jsonify({"error": "MODIFY_TP requires new_value parameter (the new TP price)"}), 400

            result = tradelocker_modify_position(access_token, ticket, account.acc_num, take_profit=new_tp, environment=credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "MODIFY_TP", "ticket": ticket, "status": "error",
                    "message": f"Failed to modify TP on position {ticket}",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)
            return jsonify({wrapper_key: {
                "action": "MODIFY_TP",
                "status": "executed",
                "message": f"Take profit set to {new_tp} on position {ticket}",
                "ticket": ticket,
                "new_take_profit": new_tp,
                "broker_response": result,
            }}), 200

        # ── MODIFY_SL ────────────────────────────────────────────────────
        if action == "MODIFY_SL":
            if not ticket:
                return jsonify({"error": "MODIFY_SL requires ticket parameter"}), 400
            new_sl = _float(new_value_raw)
            if new_sl is None:
                return jsonify({"error": "MODIFY_SL requires new_value parameter (the new SL price)"}), 400

            # Try as position first
            result = tradelocker_modify_position(access_token, ticket, account.acc_num, stop_loss=new_sl, environment=credential.environment)
            if result and "error" not in result:
                return jsonify({wrapper_key: {
                    "action": "MODIFY_SL",
                    "status": "executed",
                    "message": f"Stop loss set to {new_sl} on position {ticket}",
                    "ticket": ticket,
                    "new_stop_loss": new_sl,
                    "broker_response": result,
                }}), 200

            # If position modify failed, try as pending order
            result2 = tradelocker_modify_order(access_token, ticket, account.acc_num, stop_loss=new_sl, environment=credential.environment)
            if result2 and "error" not in result2:
                return jsonify({wrapper_key: {
                    "action": "MODIFY_SL",
                    "status": "executed",
                    "target_type": "pending_order",
                    "message": f"Stop loss set to {new_sl} on order {ticket}",
                    "ticket": ticket,
                    "new_stop_loss": new_sl,
                    "broker_response": result2,
                }}), 200

            return jsonify({wrapper_key: {
                "action": "MODIFY_SL", "ticket": ticket, "status": "error",
                "message": f"Failed to modify SL on position or order {ticket}",
                "position_error": result.get("error") if result else None,
                "order_error": result2.get("error") if result2 else None,
            }}), 404

        # ── BREAK_EVEN — needs entry price so must fetch position ──────
        if action == "BREAK_EVEN":
            if not ticket:
                return jsonify({"error": "BREAK_EVEN requires ticket parameter"}), 400

            positions_raw = tradelocker_get_positions(access_token, account.account_id, account.acc_num, credential.environment)
            if positions_raw is None:
                return jsonify({"error": "Failed to fetch positions"}), 502
            pos_cols = _get_pos_columns()
            positions = _positions_to_dicts(positions_raw, pos_cols)

            target = None
            for p in positions:
                if str(p.get("id", "")) == str(ticket):
                    target = p
                    break
            if not target:
                return jsonify({wrapper_key: {
                    "action": "BREAK_EVEN", "ticket": ticket, "status": "not_found",
                    "message": f"Position {ticket} not found",
                }}), 404

            entry_price = _float(target.get("avgPrice"))
            if entry_price is None:
                return jsonify({"error": "Cannot determine entry price for position"}), 500

            result = tradelocker_modify_position(access_token, ticket, account.acc_num, stop_loss=entry_price, environment=credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "BREAK_EVEN", "ticket": ticket, "status": "error",
                    "message": f"Failed to set break even on position {ticket}",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)

            return jsonify({wrapper_key: {
                "action": "BREAK_EVEN",
                "status": "executed",
                "message": f"Stop loss moved to entry price {entry_price} on position {ticket}",
                "ticket": ticket,
                "entry_price": entry_price,
                "broker_response": result,
            }}), 200

        # ── BREAK_EVEN_ALL — needs entry prices so must fetch positions ─
        if action == "BREAK_EVEN_ALL":
            positions_raw = tradelocker_get_positions(access_token, account.account_id, account.acc_num, credential.environment)
            if positions_raw is None:
                return jsonify({"error": "Failed to fetch positions"}), 502
            pos_cols = _get_pos_columns()
            positions = _positions_to_dicts(positions_raw, pos_cols)

            if not positions:
                return jsonify({wrapper_key: {
                    "action": "BREAK_EVEN_ALL", "symbol": symbol or "ALL", "status": "no_positions",
                    "message": "No open positions found",
                }}), 200

            if symbol and symbol != "ALL":
                imap = {str(i.get("tradableInstrumentId", "")): i.get("name", "") for i in (_get_instruments() or [])}
                positions = [p for p in positions if imap.get(str(p.get("tradableInstrumentId", "")), "").upper() == symbol]

            modified = []
            failed = []
            for pos in positions:
                pos_id = pos.get("id")
                entry = _float(pos.get("avgPrice"))
                if pos_id and entry:
                    res = tradelocker_modify_position(access_token, pos_id, account.acc_num, stop_loss=entry, environment=credential.environment)
                    if res and "error" not in res:
                        modified.append({"position_id": pos_id, "entry_price": entry, "status": "success"})
                    else:
                        failed.append({"position_id": pos_id, "entry_price": entry, "status": "failed", "broker_error": res.get("error") if res else "Unknown"})

            return jsonify({wrapper_key: {
                "action": "BREAK_EVEN_ALL",
                "status": "executed",
                "message": f"Break even set on {len(modified)} position(s), {len(failed)} failed",
                "modified": modified,
                "failed": failed,
            }}), 200

        # ── TRAIL_SL ─────────────────────────────────────────────────────
        if action == "TRAIL_SL":
            if not ticket:
                return jsonify({"error": "TRAIL_SL requires ticket parameter"}), 400
            trail_points = _float(new_value_raw)
            if trail_points is None or trail_points <= 0:
                return jsonify({"error": "TRAIL_SL requires new_value parameter (trailing distance in points)"}), 400

            result = tradelocker_modify_position(access_token, ticket, account.acc_num, trailing_offset=trail_points, environment=credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "TRAIL_SL", "ticket": ticket, "status": "error",
                    "message": f"Failed to set trailing stop on position {ticket}",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)
            return jsonify({wrapper_key: {
                "action": "TRAIL_SL",
                "status": "executed",
                "message": f"Trailing stop of {trail_points} points set on position {ticket}",
                "ticket": ticket,
                "trailing_points": trail_points,
                "broker_response": result,
            }}), 200

        # ── DELETE_ORDER ─────────────────────────────────────────────────
        if action == "DELETE_ORDER":
            if not ticket:
                return jsonify({"error": "DELETE_ORDER requires ticket parameter"}), 400

            result = tradelocker_cancel_order(access_token, ticket, account.acc_num, credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "DELETE_ORDER", "ticket": ticket, "status": "error",
                    "message": f"Failed to cancel order {ticket} — it may not exist or is already filled/cancelled",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)
            return jsonify({wrapper_key: {
                "action": "DELETE_ORDER",
                "status": "executed",
                "message": f"Pending order {ticket} cancelled",
                "ticket": ticket,
                "broker_response": result,
            }}), 200

        # ── DELETE_ALL_ORDERS ────────────────────────────────────────────
        if action == "DELETE_ALL_ORDERS":
            tradable_id = None
            if symbol and symbol != "ALL":
                instruments = _get_instruments()
                if instruments:
                    tradable_id, _ = _get_instrument_ids(instruments, symbol)

            result = tradelocker_cancel_all_orders(access_token, account.account_id, account.acc_num, tradable_instrument_id=tradable_id, environment=credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "DELETE_ALL_ORDERS", "symbol": symbol or "ALL", "status": "error",
                    "message": f"Failed to cancel orders",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)
            return jsonify({wrapper_key: {
                "action": "DELETE_ALL_ORDERS",
                "status": "executed",
                "message": f"All pending orders cancelled" + (f" for {symbol}" if symbol and symbol != "ALL" else ""),
                "symbol": symbol or "ALL",
                "broker_response": result,
            }}), 200

        # ── MODIFY_ORDER ─────────────────────────────────────────────────
        if action == "MODIFY_ORDER":
            if not ticket:
                return jsonify({"error": "MODIFY_ORDER requires ticket parameter"}), 400
            new_price = _float(new_value_raw)
            if new_price is None:
                return jsonify({"error": "MODIFY_ORDER requires new_value parameter (the new order price)"}), 400

            result = tradelocker_modify_order(access_token, ticket, account.acc_num, price=new_price, environment=credential.environment)
            if result and "error" in result:
                return jsonify({wrapper_key: {
                    "action": "MODIFY_ORDER", "ticket": ticket, "status": "error",
                    "message": f"Failed to modify order {ticket}",
                    "broker_error": result.get("error"),
                }}), result.get("status_code", 500)
            return jsonify({wrapper_key: {
                "action": "MODIFY_ORDER",
                "status": "executed",
                "message": f"Order {ticket} price updated to {new_price}",
                "ticket": ticket,
                "new_price": new_price,
                "broker_response": result,
            }}), 200

        return jsonify({"error": f"Unknown action: {action}. Valid actions: BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, CLOSE, CLOSE_ALL, CLOSE_LOSS, CLOSE_PROFIT, MODIFY_TP, MODIFY_SL, BREAK_EVEN, BREAK_EVEN_ALL, TRAIL_SL, DELETE_ORDER, DELETE_ALL_ORDERS, MODIFY_ORDER"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─── Trading API Guide Page ─────────────────────────────────────────────


@app.route("/trading-api")
@login_required
def trading_api_guide():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == session["user_id"]).first()
        first_account = db.query(TradeLockerAccount).filter(
            TradeLockerAccount.user_id == user.id
        ).first()
        example_account_id = first_account.arrissa_id if first_account else "ACCTID"
        return render_template(
            "trading_guide.html",
            user=user,
            api_key=user.api_key,
            example_account_id=example_account_id,
            active_page="trading_api",
            message=request.args.get("message"),
            error=request.args.get("error"),
        )
    finally:
        db.close()
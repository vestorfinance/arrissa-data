"""
Smart Event Updater — background service that keeps economic events fresh.

1. Every 4 hours: update events for this week + next week.
2. Track upcoming events: after each event's scheduled time, re-fetch to capture
   released data at +30s, +90s, and +15min.  If multiple event times cluster,
   they run sequentially with 5s sleep between.
"""

import threading
import time
import logging
from datetime import datetime, timezone, timedelta

from app.database import SessionLocal
from app.news_client import fetch_economic_events
from app.models.economic_event import EconomicEvent, generate_event_type_id, importance_to_impact

log = logging.getLogger("smart_updater")
log.setLevel(logging.INFO)
if not log.handlers:
    log.addHandler(logging.StreamHandler())

# Chase offsets in seconds after an event's scheduled time
CHASE_OFFSETS = [30, 90, 15 * 60]  # 30s, 90s, 15min


def _save_events(db, events):
    """Save raw TradingView events to DB (mirrors _save_events_to_db in routes)."""
    saved = 0
    updated = 0
    for e in events:
        source_id = str(e.get("id", ""))
        date_str = e.get("date", "")
        try:
            event_time = (
                datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
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


def _update_week_range():
    """Fetch this week (Mon-Sun) + next week of events and save."""
    now = datetime.now(tz=timezone.utc)
    # Start of this week (Monday 00:00)
    monday = now - timedelta(days=now.weekday())
    from_dt = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    # End of next week (Sunday 23:59)
    to_dt = from_dt + timedelta(days=14) - timedelta(seconds=1)

    events = fetch_economic_events(from_dt, to_dt)
    if events is None:
        log.warning("[smart_updater] Failed to fetch events for week range")
        return 0, 0, 0

    db = SessionLocal()
    try:
        saved, updated = _save_events(db, events)
        log.info(
            f"[smart_updater] Week update: {saved} new, {updated} updated ({len(events)} fetched)"
        )
        return saved, updated, len(events)
    except Exception as exc:
        db.rollback()
        log.error(f"[smart_updater] Week update error: {exc}")
        return 0, 0, 0
    finally:
        db.close()


def _chase_event_time(event_time_utc: datetime):
    """Re-fetch this-week events to capture data released at the given event time."""
    now = datetime.now(tz=timezone.utc)
    monday = now - timedelta(days=now.weekday())
    from_dt = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt = from_dt + timedelta(days=14) - timedelta(seconds=1)

    events = fetch_economic_events(from_dt, to_dt)
    if events is None:
        log.warning(f"[smart_updater] Chase fetch failed for event at {event_time_utc}")
        return

    db = SessionLocal()
    try:
        saved, updated = _save_events(db, events)
        log.info(
            f"[smart_updater] Chase @{event_time_utc.strftime('%H:%M')}: "
            f"{saved} new, {updated} updated"
        )
    except Exception as exc:
        db.rollback()
        log.error(f"[smart_updater] Chase error: {exc}")
    finally:
        db.close()


class SmartUpdater:
    """Singleton background service that manages scheduled event updates."""

    def __init__(self):
        self._enabled = True
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_periodic: datetime | None = None
        self._last_chase_info: str = ""
        self._next_event_time: datetime | None = None
        self._status_log: list[str] = []  # last N log lines

    # ── public API ──────────────────────────────────────────────

    @property
    def enabled(self):
        return self._enabled

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "running": self.running,
            "last_periodic_update": (
                self._last_periodic.strftime("%a %Y-%m-%d %H:%M") if self._last_periodic else None
            ),
            "next_event_chase": (
                self._next_event_time.strftime("%a %Y-%m-%d %H:%M") if self._next_event_time else None
            ),
            "last_chase_info": self._last_chase_info,
            "recent_log": list(self._status_log[-10:]),
        }

    def enable(self):
        self._enabled = True
        if not self.running:
            self.start()

    def disable(self):
        self._enabled = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def start(self):
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="smart_updater")
        self._thread.start()
        self._log("Smart updater started")

    # ── internals ───────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        log.info(entry)
        self._status_log.append(entry)
        if len(self._status_log) > 50:
            self._status_log = self._status_log[-50:]

    def _run_loop(self):
        # Initial update on start
        self._do_periodic()

        while not self._stop_event.is_set():
            now = datetime.now(tz=timezone.utc)

            # Check if 4-hour periodic is due
            if self._last_periodic is None or (now - self._last_periodic) >= timedelta(hours=4):
                self._do_periodic()

            # Schedule chases for upcoming events
            self._do_chase_cycle()

            # Sleep 10s between loop iterations (responsive to stop)
            self._stop_event.wait(10)

    def _do_periodic(self):
        """Run the 4-hourly this-week+next-week update."""
        self._log("Periodic update: fetching this week + next week")
        saved, updated, fetched = _update_week_range()
        self._last_periodic = datetime.now(tz=timezone.utc)
        self._log(f"Periodic done: {saved} new, {updated} updated ({fetched} fetched)")

    def _get_upcoming_event_times(self, horizon_hours: int = 4) -> list[datetime]:
        """Query DB for distinct event times in the next N hours."""
        now_utc = datetime.utcnow()
        horizon = now_utc + timedelta(hours=horizon_hours)

        db = SessionLocal()
        try:
            rows = (
                db.query(EconomicEvent.event_time)
                .filter(
                    EconomicEvent.event_time >= now_utc,
                    EconomicEvent.event_time <= horizon,
                )
                .distinct()
                .order_by(EconomicEvent.event_time)
                .all()
            )
            return [r[0].replace(tzinfo=timezone.utc) for r in rows]
        finally:
            db.close()

    def _get_next_event_time(self) -> datetime | None:
        """Get the very next upcoming event time (no horizon limit)."""
        now_utc = datetime.utcnow()
        db = SessionLocal()
        try:
            row = (
                db.query(EconomicEvent.event_time)
                .filter(EconomicEvent.event_time >= now_utc)
                .order_by(EconomicEvent.event_time)
                .first()
            )
            return row[0].replace(tzinfo=timezone.utc) if row else None
        finally:
            db.close()

    def _do_chase_cycle(self):
        """Find upcoming events and chase them at +30s, +90s, +15min after their time."""
        # Always update the display with the true next event (no horizon limit)
        self._next_event_time = self._get_next_event_time()

        # Only chase events within the next 4 hours
        upcoming = self._get_upcoming_event_times(horizon_hours=4)
        if not upcoming:
            return

        now = datetime.now(tz=timezone.utc)

        for event_time in upcoming:
            if self._stop_event.is_set():
                return

            for offset in CHASE_OFFSETS:
                chase_at = event_time + timedelta(seconds=offset)

                # Only chase if the chase time is within the next 15 seconds
                # (our loop runs every 10s, so this catches them)
                diff = (chase_at - now).total_seconds()
                if -5 <= diff <= 15:
                    # Wait until the exact chase moment
                    if diff > 0:
                        self._stop_event.wait(diff)
                        if self._stop_event.is_set():
                            return

                    label = f"+{offset}s" if offset < 60 else f"+{offset // 60}min"
                    self._log(
                        f"Chase {label} for event @ {event_time.strftime('%H:%M')}"
                    )
                    _chase_event_time(event_time)
                    self._last_chase_info = (
                        f"{label} for {event_time.strftime('%H:%M')} at "
                        f"{datetime.now(tz=timezone.utc).strftime('%H:%M:%S')}"
                    )

                    # 5 second pause between sequential chases
                    if not self._stop_event.is_set():
                        self._stop_event.wait(5)


# ── module-level singleton ──────────────────────────────────────
smart_updater = SmartUpdater()

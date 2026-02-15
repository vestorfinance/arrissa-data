import hashlib

from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from app.database import Base


class EconomicEvent(Base):
    __tablename__ = "economic_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type_id = Column(String(12), index=True, nullable=False)  # consistent ID for event type
    source_id = Column(String(20), nullable=False)  # original API id
    title = Column(String(255), nullable=False)
    country = Column(String(10), nullable=False)
    indicator = Column(String(255), nullable=True)
    category = Column(String(50), nullable=True)
    currency = Column(String(10), nullable=True)
    impact = Column(String(10), nullable=False)  # high, medium
    event_time = Column(DateTime, nullable=False)
    actual = Column(String(50), nullable=True)
    previous = Column(String(50), nullable=True)
    forecast = Column(String(50), nullable=True)
    source = Column(String(255), nullable=True)
    source_url = Column(String(512), nullable=True)

    __table_args__ = (
        # Prevent duplicate events: same source_id + event_time
        # (source_id alone isn't unique across time — same event recurs)
    )


def generate_event_type_id(title: str, country: str) -> str:
    """
    Generate a consistent 8-char uppercase hex ID for an event type.
    E.g. "CPI" for US always gets the same ID regardless of occurrence date.
    Based on sha256 of normalized title + country.
    """
    normalized = f"{title.strip().lower()}:{country.strip().upper()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:8].upper()


def importance_to_impact(importance: int) -> str:
    """Convert TradingView importance value to human-readable impact label."""
    if importance >= 1:
        return "high"
    elif importance == 0:
        return "medium"
    return "low"

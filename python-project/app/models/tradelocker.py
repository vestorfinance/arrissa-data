import hashlib

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.database import Base


def generate_arrissa_id(acc_num, broker_email):
    """Generate a deterministic 6-char alphanumeric ID from account number + broker email."""
    raw = f"{acc_num}:{broker_email}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:6].upper()
    return digest


class TradeLockerCredential(Base):
    """Stores a user's TradeLocker login credentials and JWT tokens."""

    __tablename__ = "tradelocker_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    email = Column(String(255), nullable=False)
    server = Column(String(255), nullable=False)
    environment = Column(String(10), nullable=False, default="demo")  # "demo" or "live"
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expire_date = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="tradelocker_credentials")
    accounts = relationship("TradeLockerAccount", back_populates="credential", cascade="all, delete-orphan")


class TradeLockerAccount(Base):
    """Stores individual TradeLocker trading accounts linked to a credential."""

    __tablename__ = "tradelocker_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    arrissa_id = Column(String(6), unique=True, nullable=False)
    credential_id = Column(Integer, ForeignKey("tradelocker_credentials.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=True)
    currency = Column(String(10), nullable=True)
    status = Column(String(50), nullable=True)
    acc_num = Column(String(100), nullable=False)
    nickname = Column(String(100), nullable=True)  # user-chosen name, e.g. "my demo account"
    account_balance = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    credential = relationship("TradeLockerCredential", back_populates="accounts")
    user = relationship("User", back_populates="tradelocker_accounts")

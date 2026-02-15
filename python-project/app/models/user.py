import secrets

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

from app.database import Base


def generate_api_key():
    return secrets.token_hex(32)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    api_key = Column(String(64), unique=True, nullable=True, default=generate_api_key)
    site_url = Column(String(500), nullable=False, default="http://localhost:5001")
    default_account_id = Column(String(10), nullable=True)  # arrissa_id of default trading account

    tradelocker_credentials = relationship("TradeLockerCredential", back_populates="user", cascade="all, delete-orphan")
    tradelocker_accounts = relationship("TradeLockerAccount", back_populates="user")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def regenerate_api_key(self):
        self.api_key = generate_api_key()
        return self.api_key

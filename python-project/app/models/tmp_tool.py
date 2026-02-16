"""
TMP (Tool Matching Protocol) — Tool Registry Model

Stores tool definitions with their embedding vectors for semantic search.
Completely separate from MCP — this is a new protocol.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON
from datetime import datetime, timezone

from app.database import Base


class TMPTool(Base):
    """A registered tool in the Tool Matching Protocol registry."""
    __tablename__ = "asp_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)
    parameters = Column(JSON, nullable=True)  # JSON schema of parameters
    category = Column(String(100), nullable=True, index=True)
    tags = Column(JSON, nullable=True)  # list of string tags
    examples = Column(JSON, nullable=True)  # example queries this tool handles
    endpoint = Column(String(500), nullable=True)  # the API endpoint this tool calls
    method = Column(String(10), nullable=True, default="GET")  # HTTP method
    embedding = Column(JSON, nullable=True)  # the vector embedding (list of floats)
    embedding_text = Column(Text, nullable=True)  # the text that was embedded
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self, include_embedding=False):
        """Serialize to dictionary."""
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "tags": self.tags,
            "examples": self.examples,
            "endpoint": self.endpoint,
            "method": self.method,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_embedding:
            d["embedding"] = self.embedding
            d["embedding_text"] = self.embedding_text
        return d

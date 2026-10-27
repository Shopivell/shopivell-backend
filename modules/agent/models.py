# modules/agent/models.py
"""Agent chat models: persistent conversations with the Shopivell AI agent."""
from sqlalchemy import Column, String, Text, JSON, DateTime, Integer, ForeignKey
from db_compat import UUID
from datetime import datetime
import uuid

from database import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)

    title = Column(String(255), default="New chat")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"),
                             nullable=False, index=True)

    role = Column(String(20), nullable=False)  # "user" | "assistant"
    # Rich parts for the UI: [{type: text|ad_variations|image|tool|links, ...}]
    # Text-only messages may use the plain `content` column instead.
    content = Column(Text, nullable=True)
    parts = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentCreditLedger(Base):
    """Token wallet ledger for the agent. One row per balance change; the latest
    row's balance_after is the user's current token balance (O(1) reads)."""
    __tablename__ = "agent_credit_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    # Which store the usage belongs to (None for top-ups and usage with no store). A plain
    # indexed column, not a foreign key: the ledger is append-only history and must outlive
    # a deleted store.
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    delta = Column(Integer, nullable=False)  # + top-up / grant, - usage
    balance_after = Column(Integer, nullable=False)
    reason = Column(String(60), nullable=False)  # topup | grant | chat | tool:<name>
    detail = Column(String(255), nullable=True)  # human-readable note (model, tool args...)
    created_at = Column(DateTime, default=datetime.utcnow)

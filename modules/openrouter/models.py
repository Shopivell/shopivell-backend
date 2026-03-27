# modules/openrouter/models.py
"""Database models for AI usage tracking and billing."""

from typing import Optional, Dict, Any
from sqlalchemy import String, Boolean, DateTime, Integer, Float, Text, JSON, Index
from db_compat import PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
import uuid

from database import Base


class AIUsageLog(Base):
    """
    Logs every LLM API call for usage tracking and billing.
    Central audit trail for all AI token consumption.
    """
    __tablename__ = "ai_usage_logs"

    id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Who made the call
    store_id: Mapped[Optional[PG_UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    user_id: Mapped[Optional[PG_UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    campaign_id: Mapped[Optional[PG_UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )

    # What was called
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(
        String(50), default="chat/completions"
    )

    # Token counts
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Cost (calculated from model pricing)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Request metadata
    request_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Status
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    __table_args__ = (
        Index('ix_ai_usage_store_created', 'store_id', 'created_at'),
        Index('ix_ai_usage_store_agent', 'store_id', 'agent_name'),
    )


class StoreAIUsageSummary(Base):
    """
    Monthly aggregated AI usage per store.
    Updated incrementally to avoid expensive COUNT queries.
    """
    __tablename__ = "store_ai_usage_summaries"

    id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    store_id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )

    # Period
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    # Aggregated counts
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Breakdown by agent
    calls_by_agent: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_by_agent: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Timestamps
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index('ix_ai_summary_store_period', 'store_id', 'year', 'month', unique=True),
    )

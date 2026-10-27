import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Boolean, Float, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class StoreMarketingEvent(Base):
    """A store's own custom marketing event (sale, launch, etc.) - the tenant
    creates these directly, distinct from the built-in retail calendar."""
    __tablename__ = "store_marketing_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    event_type = Column(String(50), nullable=False, default="custom")  # sale, launch, seasonal, holiday, custom
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    budget_multiplier = Column(Float, nullable=False, default=1.0)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoreRetailEventOverride(Base):
    """Per-store customization of one of the built-in retail calendar events
    (RETAIL_EVENTS in router.py) - enable/disable it, or override its dates,
    name, impact, and budget multiplier for this store specifically."""
    __tablename__ = "store_retail_event_overrides"
    __table_args__ = (UniqueConstraint("store_id", "event_key", name="uq_store_retail_event"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    event_key = Column(String(100), nullable=False)

    is_enabled = Column(Boolean, nullable=True)  # NULL = default (enabled)
    custom_name = Column(String(255), nullable=True)
    custom_budget_multiplier = Column(Float, nullable=True)
    custom_impact = Column(String(20), nullable=True)
    custom_start_month = Column(Integer, nullable=True)
    custom_start_day = Column(Integer, nullable=True)
    custom_duration_days = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

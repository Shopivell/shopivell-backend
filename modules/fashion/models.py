from typing import Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
import enum

from database import Base


class MeasurementStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class TryOnSession(Base):
    __tablename__ = "tryon_sessions"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    store_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)

    # Input data
    height_cm: Mapped[float] = mapped_column(Float, nullable=False, default=152.0)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=MeasurementStatus.COMPLETED.value)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Results
    measurements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    debug_info: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", backref="tryon_sessions")
    store = relationship("Store", backref="tryon_sessions")

# modules/returns/models.py
"""
SQLAlchemy models for returns and refunds.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, JSON
from db_compat import UUID

from database import Base


class ReturnRequest(Base):
    """Model for customer return and refund requests."""
    __tablename__ = "return_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    reason = Column(String(100), nullable=False)  # defective, wrong_item, not_as_described, changed_mind, other
    description = Column(Text, nullable=True)
    images = Column(JSON, default=[])

    status = Column(String(20), default="pending")  # pending, approved, rejected, refunded, completed
    refund_amount = Column(Float, nullable=True)
    refund_method = Column(String(50), nullable=True)  # original_payment, store_credit, bank_transfer

    admin_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

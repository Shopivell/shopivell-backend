# modules/coupons/models.py
"""
SQLAlchemy models for coupons and promotions.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class Coupon(Base):
    """Model for store coupons and discount codes."""
    __tablename__ = "coupons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)

    code = Column(String(50), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    type = Column(String(20), nullable=False)  # percentage, fixed, free_shipping
    value = Column(Float, nullable=False)  # discount percentage or fixed amount

    min_order_amount = Column(Float, nullable=True)
    max_discount = Column(Float, nullable=True)  # cap for percentage discounts
    usage_limit = Column(Integer, nullable=True)  # total uses allowed
    used_count = Column(Integer, default=0)
    per_user_limit = Column(Integer, default=1)

    applicable_products = Column(JSON, default=[])  # list of product IDs
    applicable_categories = Column(JSON, default=[])  # list of category names

    starts_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", backref="coupons")
    usages = relationship("CouponUsage", back_populates="coupon", cascade="all, delete-orphan")


class CouponUsage(Base):
    """Model for tracking coupon usage per user/order."""
    __tablename__ = "coupon_usages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coupon_id = Column(UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), nullable=True)
    discount_amount = Column(Float, nullable=False)

    used_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    coupon = relationship("Coupon", back_populates="usages")
    user = relationship("User", backref="coupon_usages")

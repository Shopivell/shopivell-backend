# modules/payment/models.py - DIRECT FIX
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SQLEnum, Integer, Float, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base
import enum

class PaymentMethod(str, enum.Enum):
    ECOCASH = "ecocash"
    INNBUCKS = "innbucks"
    BANK_TRANSFER = "bank_transfer"
    STRIPE = "stripe"
    PAYPAL = "paypal"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class SubscriptionPlan(str, enum.Enum):
    FREE = "free"
    PREMIUM = "premium"
    BUSINESS = "business"

class PackageFeature(Base):
    __tablename__ = "package_features"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PackagePricing(Base):
    __tablename__ = "package_pricing"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_name: Mapped[SubscriptionPlan] = mapped_column(SQLEnum(SubscriptionPlan), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monthly_price: Mapped[float] = mapped_column(Numeric(10, 2), default=0.10)
    annual_price: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    features: Mapped[List[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    user_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    # Payment details
    reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    payment_method: Mapped[PaymentMethod] = mapped_column(SQLEnum(PaymentMethod), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    
    # PayNow specific fields
    poll_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    paynow_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mobile_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Package subscription info
    package_name: Mapped[SubscriptionPlan] = mapped_column(SQLEnum(SubscriptionPlan), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(20), default="monthly")
    subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # FIXED: Renamed from 'metadata' to 'payment_metadata'
    payment_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    initiated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships - Keep using string references
    store = relationship("Store", back_populates="payments")

class StoreSubscription(Base):
    __tablename__ = "store_subscriptions"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, unique=True, index=True)
    
    # Subscription details
    package_name: Mapped[SubscriptionPlan] = mapped_column(SQLEnum(SubscriptionPlan), default=SubscriptionPlan.FREE)
    billing_period: Mapped[str] = mapped_column(String(20), default="monthly")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Payment info
    current_payment_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=True)
    last_payment_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=True)
    
    # Dates
    subscribed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Features access
    enabled_features: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    usage_limits: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # Relationships - Keep using string references
    store = relationship("Store", back_populates="subscription", uselist=False)
    current_payment = relationship("PaymentTransaction", foreign_keys=[current_payment_id])
    last_payment = relationship("PaymentTransaction", foreign_keys=[last_payment_id])
# modules/pos/models.py
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer, Boolean, JSON, Enum as SQLEnum, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base
import enum


class POSRegisterStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class POSSessionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    SUSPENDED = "suspended"


class POSTransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    VOIDED = "voided"
    REFUNDED = "refunded"
    FAILED = "failed"


class POSPaymentMethod(str, enum.Enum):
    CASH = "cash"
    ECOCASH = "ecocash"
    INNBUCKS = "innbucks"
    STRIPE = "stripe"
    PAYPAL = "paypal"
    BANK_TRANSFER = "bank_transfer"


class ExternalPOSProvider(str, enum.Enum):
    SQUARE = "square"
    CLOVER = "clover"


class POSRegister(Base):
    """Terminal/Register configuration for POS"""
    __tablename__ = "pos_registers"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[POSRegisterStatus] = mapped_column(SQLEnum(POSRegisterStatus), default=POSRegisterStatus.ACTIVE)

    default_payment_method: Mapped[POSPaymentMethod] = mapped_column(SQLEnum(POSPaymentMethod), default=POSPaymentMethod.CASH)
    receipt_header: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt_footer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    external_provider: Mapped[Optional[ExternalPOSProvider]] = mapped_column(SQLEnum(ExternalPOSProvider), nullable=True)
    external_register_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="pos_registers")
    sessions = relationship("POSSession", back_populates="register", cascade="all, delete-orphan")


class POSSession(Base):
    """Daily POS sessions with opening/closing balance tracking"""
    __tablename__ = "pos_sessions"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    register_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pos_registers.id"), nullable=False)
    user_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    session_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[POSSessionStatus] = mapped_column(SQLEnum(POSSessionStatus), default=POSSessionStatus.OPEN)

    opening_balance: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    closing_balance: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    expected_balance: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    cash_difference: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    total_sales: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_refunds: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)

    cash_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    card_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    mobile_money_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)

    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    store = relationship("Store", backref="pos_sessions")
    register = relationship("POSRegister", back_populates="sessions")
    user = relationship("User", backref="pos_sessions")
    transactions = relationship("POSTransaction", back_populates="session", cascade="all, delete-orphan")


class POSTransaction(Base):
    """Individual POS sales transactions"""
    __tablename__ = "pos_transactions"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    session_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pos_sessions.id"), nullable=False, index=True)

    transaction_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[POSTransactionStatus] = mapped_column(SQLEnum(POSTransactionStatus), default=POSTransactionStatus.PENDING)

    customer_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    payment_method: Mapped[POSPaymentMethod] = mapped_column(SQLEnum(POSPaymentMethod), nullable=False)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount_tendered: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    change_given: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    items: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    external_provider: Mapped[Optional[ExternalPOSProvider]] = mapped_column(SQLEnum(ExternalPOSProvider), nullable=True)
    external_transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    external_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    store = relationship("Store", backref="pos_transactions")
    session = relationship("POSSession", back_populates="transactions")
    customer = relationship("Customer", backref="pos_transactions")


class ExternalPOSIntegration(Base):
    """Configuration for external POS integrations (Square, Clover)"""
    __tablename__ = "external_pos_integrations"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    provider: Mapped[ExternalPOSProvider] = mapped_column(SQLEnum(ExternalPOSProvider), nullable=False)

    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    merchant_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    auto_sync_orders: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_sync_inventory: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="pos_integrations")

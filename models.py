from datetime import date, datetime, timezone # Import timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Integer, Numeric, String, Text, Date, Float,
    ForeignKey,
    func
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from database import Base # Assuming 'database' module provides Base
import uuid
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from typing import Optional, List


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    type: Mapped[str] = mapped_column(Enum("email_verification", "password_reset", "phone_verification", name="verification_types", create_type=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="verification_codes")


# --- User Model ---
class User(Base):
    __tablename__ = "users"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    role: Mapped[str] = mapped_column(Enum("customer", "supplier", "admin", "both", name="user_roles", create_type=True), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    surname: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Using `func.now()` for `onupdate` timestamp.
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    status: Mapped[str] = mapped_column(Enum("active", "disabled", "pending", name="user_statuses", create_type=True), server_default="active", nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Business specific fields (for suppliers)
    business_phone_number: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    business_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    personal_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    requests: Mapped[List["RequestPost"]] = relationship("RequestPost", back_populates="customer", cascade="all, delete-orphan")
    offers: Mapped[List["Offer"]] = relationship("Offer", back_populates="supplier", cascade="all, delete-orphan")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="supplier", cascade="all, delete-orphan")
    customer_orders: Mapped[List["Order"]] = relationship("Order", foreign_keys="[Order.customer_id]", back_populates="customer", cascade="all, delete-orphan")
    supplier_orders: Mapped[List["Order"]] = relationship("Order", foreign_keys="[Order.supplier_id]", back_populates="supplier", cascade="all, delete-orphan")
    device_tokens: Mapped[List["DeviceToken"]] = relationship("DeviceToken", back_populates="user", cascade="all, delete-orphan")
    sent_notifications: Mapped[List["Notification"]] = relationship("Notification", foreign_keys="[Notification.sender_id]", back_populates="sender", cascade="all, delete-orphan")
    received_notifications: Mapped[List["Notification"]] = relationship("Notification", foreign_keys="[Notification.recipient_id]", back_populates="recipient", cascade="all, delete-orphan")
    verification_codes: Mapped[List["VerificationCode"]] = relationship("VerificationCode", back_populates="user", cascade="all, delete-orphan")


# --- RequestPost Model ---
class RequestPost(Base):
    __tablename__ = "request_posts"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String, nullable=False) # Changed to String for consistency, can be Text if very long.
    offer_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Updated request_statuses for new supplier flow:
    # "open": Customer posted, waiting for any supplier action (accept or counter)
    # "supplier_accepted": Supplier directly accepted customer's offer_price, awaiting customer confirmation (if not immediately ordered)
    # "counter_offered": Supplier has made a counter-offer, awaiting customer response
    # "fulfilled": An order has been placed based on this request (either direct accept or counter-offer accepted)
    # "cancelled_by_customer": Customer explicitly cancelled the request
    # "rejected_by_customer": Customer rejected all offers for this request
    status: Mapped[str] = mapped_column(
        Enum("open", "supplier_accepted", "counter_offered", "fulfilled", "cancelled_by_customer", "rejected_by_customer", name="request_statuses", create_type=True),
        server_default="open", nullable=False
    )

    customer_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    customer: Mapped["User"] = relationship("User", back_populates="requests")
    offers: Mapped[List["Offer"]] = relationship("Offer", back_populates="request_post", cascade="all, delete-orphan")
    # `uselist=False` for one-to-one relationship when an order is created from this request
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="request_post", uselist=False, cascade="all, delete-orphan")


# --- Product Model ---
class Product(Base):
    __tablename__ = "products"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False) # Use Numeric for price for precision
    category: Mapped[str] = mapped_column(String, index=True, nullable=False)
    supplier_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    supplier: Mapped["User"] = relationship("User", back_populates="products")


# --- Offer Model ---
class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[PG_UUID] = mapped_column(ForeignKey("request_posts.id"), nullable=False)
    supplier_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    proposed_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Offer statuses:
    # "pending": Supplier made the offer/counter-offer, awaiting customer response
    # "accepted": Customer accepted this specific offer/counter-offer (leads to order)
    # "rejected": Customer rejected this specific offer/counter-offer
    # "cancelled_by_supplier": Supplier cancelled their own offer before customer action
    # "expired": Offer expired (e.g., customer didn't respond in time)
    status: Mapped[str] = mapped_column(
        Enum("pending", "accepted", "rejected", "cancelled_by_supplier", "expired", "countered", name="offer_statuses", create_type=True),
        server_default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    request_post: Mapped["RequestPost"] = relationship("RequestPost", back_populates="offers")
    supplier: Mapped["User"] = relationship("User", back_populates="offers")
    # One-to-one with Order: an offer can result in one order
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="offer", uselist=False, cascade="all, delete-orphan")


# --- DeviceToken Model ---
class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="device_tokens")


# --- Order Model ---
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    request_id: Mapped[PG_UUID] = mapped_column(ForeignKey("request_posts.id"), nullable=False, unique=True)
    # The `offer_id` is now nullable. When a supplier directly accepts a request,
    # an 'internal' offer might be created, or you could simply link the order to the request directly
    # and not require an `offer_id` if no explicit counter-offer was involved.
    # However, keeping it non-nullable simplifies relationships, meaning even a direct accept creates an `Offer` object.
    offer_id: Mapped[PG_UUID] = mapped_column(ForeignKey("offers.id"), nullable=False, unique=True)
    customer_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    supplier_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    total_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    # Order status lifecycle
    # "placed": Order confirmed (customer accepted counter-offer, or supplier directly accepted request)
    # "processing": Supplier is preparing the order (e.g., baking the cake)
    # "shipped": Order is out for delivery
    # "delivered": Order has reached the customer
    # "completed": Order is delivered and potentially payment/review finalized
    # "cancelled_by_customer": Customer cancelled after placement
    # "cancelled_by_supplier": Supplier cancelled after placement
    status: Mapped[str] = mapped_column(
        Enum("placed", "processing", "shipped", "delivered", "completed", "cancelled", "cancelled_by_supplier", name="order_statuses", create_type=True),
        server_default="placed", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    delivery_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    delivery_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    request_post: Mapped["RequestPost"] = relationship("RequestPost", back_populates="order")
    # For `Offer`, changed `back_backref` to `back_populates` for modern SQLAlchemy
    offer: Mapped["Offer"] = relationship("Offer", back_populates="order")
    customer: Mapped["User"] = relationship("User", foreign_keys=[customer_id], back_populates="customer_orders")
    supplier: Mapped["User"] = relationship("User", foreign_keys=[supplier_id], back_populates="supplier_orders")


# --- Notification Model ---
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id: Mapped[Optional[PG_UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    recipient_id: Mapped[PG_UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    type: Mapped[str] = mapped_column(Enum(
        "new_request",
        "new_offer",
        "request_accepted_by_supplier", # New type for when supplier directly accepts
        "offer_accepted_by_customer", # New, more specific type
        "offer_rejected_by_customer", # New, more specific type
        "offer_cancelled_by_supplier", # New, more specific type
        "order_placed",
        "order_status_update",
        "system_message",
        name="notification_types", create_type=True
    ), nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sender: Mapped[Optional["User"]] = relationship("User", foreign_keys=[sender_id], back_populates="sent_notifications")
    recipient: Mapped["User"] = relationship("User", foreign_keys=[recipient_id], back_populates="received_notifications")
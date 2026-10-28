from datetime import date, datetime
from sqlalchemy import String, Date, DateTime, Text, Boolean, ForeignKey, Integer
from sqlalchemy.orm import relationship, Mapped, mapped_column
from database import Base
import uuid
from db_compat import PG_UUID
from typing import Optional, List

# NO import from orders module!

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Tenant scoping — every customer belongs to a store. Nullable so legacy/orphaned
    # rows don't break; those (store_id IS NULL) are treated as belonging to no store
    # and are never returned by the store-scoped list endpoint.
    store_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)

    # Personal Information
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Email is unique PER STORE (see uq_customer_store_email), not globally — two
    # different stores may have the same customer email.
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Address Information
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Customer Profile
    customer_type: Mapped[str] = mapped_column(String(50), default="regular", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lead_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lead_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # cold, warm, hot, qualified
    
    # Additional Information
    profile_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_activity: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships using string references - NO imports needed
    segments = relationship("CustomerSegment", secondary="customer_segment_membership", back_populates="customers")
    orders = relationship("CustomerOrder", back_populates="customer")  # String reference
    requests = relationship("CustomerRequest", back_populates="customer")

# ... rest of your models (CustomerSegment, CustomerRequest, etc.)
class CustomerSegment(Base):
    __tablename__ = "customer_segments"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    percentage: Mapped[str] = mapped_column(String(10), default="0%", nullable=False)
    customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    customers = relationship("Customer", secondary="customer_segment_membership", back_populates="segments")

class CustomerSegmentMembership(Base):
    __tablename__ = "customer_segment_membership"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    segment_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer_segments.id"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

class CustomerRequest(Base):
    __tablename__ = "customer_requests"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    customer = relationship("Customer", back_populates="requests")

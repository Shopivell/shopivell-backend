from typing import Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base

class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    order_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # New fields
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    offered_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    customer_profile: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    profile_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    product_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    delivery_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Relationship using string reference - NO import needed
    customer = relationship("Customer", back_populates="orders")
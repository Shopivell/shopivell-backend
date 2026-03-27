import enum
import uuid
import random
import string
from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer, Boolean, Index, Enum as SAEnum
from db_compat import PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class VehicleType(str, enum.Enum):
    BICYCLE = "bicycle"
    MOTORCYCLE = "motorcycle"
    VAN = "van"
    TRUCK = "truck"


class VehicleStatus(str, enum.Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class DriverStatus(str, enum.Enum):
    AVAILABLE = "available"
    ON_DELIVERY = "on_delivery"
    OFF_DUTY = "off_duty"


class Vehicle(Base):
    """A vehicle available for deliveries."""
    __tablename__ = "vehicles"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    registration_number: Mapped[str] = mapped_column(String(50), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(SAEnum(VehicleType, name="vehicle_type_enum", create_constraint=False), default=VehicleType.MOTORCYCLE, nullable=False)
    make: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    capacity_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(SAEnum(VehicleStatus, name="vehicle_status_enum", create_constraint=False), default=VehicleStatus.AVAILABLE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="vehicles")
    drivers: Mapped[List["Driver"]] = relationship("Driver", back_populates="vehicle")


class Driver(Base):
    """A driver who can be assigned to deliveries."""
    __tablename__ = "drivers"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    license_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vehicle_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=True)
    status: Mapped[str] = mapped_column(SAEnum(DriverStatus, name="driver_status_enum", create_constraint=False), default=DriverStatus.AVAILABLE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_deliveries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="drivers")
    vehicle: Mapped[Optional["Vehicle"]] = relationship("Vehicle", back_populates="drivers")


class DeliveryZone(Base):
    """Defines delivery zones with per-kilometer pricing."""
    __tablename__ = "delivery_zones"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    per_km_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    min_distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_time_per_km_min: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    store = relationship("Store", backref="delivery_zones")


def _generate_tracking_number():
    prefix = "DLV"
    digits = ''.join(random.choices(string.digits, k=8))
    return f"{prefix}-{digits}"


class Delivery(Base):
    """A delivery record linked to a customer order."""
    __tablename__ = "deliveries"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    order_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer_orders.id"), nullable=True, index=True)
    tracking_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, default=_generate_tracking_number)
    status: Mapped[str] = mapped_column(SAEnum(DeliveryStatus, name="delivery_status_enum", create_constraint=False), default=DeliveryStatus.PENDING, nullable=False)

    # Customer info
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Addresses
    pickup_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pickup_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pickup_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Distance & cost
    distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_zone_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("delivery_zones.id"), nullable=True)
    base_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    per_km_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    delivery_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)

    # Delivery person
    delivery_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_person_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    driver_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True)
    vehicle_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=True)

    # Package info
    package_weight: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    package_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    special_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Times
    estimated_delivery: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    estimated_duration_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    store = relationship("Store", backref="deliveries")
    order = relationship("CustomerOrder", backref="delivery")
    zone = relationship("DeliveryZone", backref="deliveries")
    driver = relationship("Driver", backref="deliveries")
    vehicle = relationship("Vehicle", backref="deliveries")
    tracking_events: Mapped[List["DeliveryTracking"]] = relationship("DeliveryTracking", back_populates="delivery", order_by="DeliveryTracking.created_at")

    __table_args__ = (
        Index('ix_deliveries_store_status', 'store_id', 'status'),
    )


class DeliveryTracking(Base):
    """Status history / timeline for a delivery."""
    __tablename__ = "delivery_tracking"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(SAEnum(DeliveryStatus, name="delivery_status_enum", create_constraint=False), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    delivery: Mapped["Delivery"] = relationship("Delivery", back_populates="tracking_events")

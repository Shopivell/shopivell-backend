from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
import uuid


# --- Vehicle ---

class VehicleBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    registration_number: str
    vehicle_type: str = "motorcycle"
    make: Optional[str] = None
    model: Optional[str] = None
    capacity_kg: Optional[float] = None
    status: str = "available"
    is_active: bool = True


class VehicleCreate(VehicleBase):
    store_id: uuid.UUID


class VehicleUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    registration_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    capacity_kg: Optional[float] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class VehicleResponse(VehicleBase):
    id: uuid.UUID
    store_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- Driver ---

class DriverBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    license_number: Optional[str] = None
    vehicle_id: Optional[uuid.UUID] = None
    status: str = "available"
    is_active: bool = True


class DriverCreate(DriverBase):
    store_id: uuid.UUID


class DriverUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    license_number: Optional[str] = None
    vehicle_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class DriverResponse(DriverBase):
    id: uuid.UUID
    store_id: uuid.UUID
    total_deliveries: int = 0
    created_at: datetime
    updated_at: datetime


# --- DeliveryAssign ---

class DeliveryAssign(BaseModel):
    driver_id: uuid.UUID
    vehicle_id: Optional[uuid.UUID] = None


# --- DeliveryZone ---

class DeliveryZoneBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    base_fee: float = 0.0
    per_km_rate: float = 0.0
    min_distance_km: float = 0.0
    max_distance_km: Optional[float] = None
    estimated_time_per_km_min: float = 3.0
    is_active: bool = True
    currency: str = "USD"


class DeliveryZoneCreate(DeliveryZoneBase):
    store_id: uuid.UUID


class DeliveryZoneUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: Optional[str] = None
    base_fee: Optional[float] = None
    per_km_rate: Optional[float] = None
    min_distance_km: Optional[float] = None
    max_distance_km: Optional[float] = None
    estimated_time_per_km_min: Optional[float] = None
    is_active: Optional[bool] = None
    currency: Optional[str] = None


class DeliveryZoneResponse(DeliveryZoneBase):
    id: uuid.UUID
    store_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- DeliveryTracking ---

class DeliveryTrackingBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None


class DeliveryTrackingCreate(DeliveryTrackingBase):
    delivery_id: uuid.UUID


class DeliveryTrackingResponse(DeliveryTrackingBase):
    id: uuid.UUID
    delivery_id: uuid.UUID
    created_at: datetime


# --- Cost Calculation ---

class CostEstimateRequest(BaseModel):
    store_id: uuid.UUID
    distance_km: float
    zone_id: Optional[uuid.UUID] = None


class CostEstimateResponse(BaseModel):
    distance_km: float
    base_fee: float
    per_km_rate: float
    delivery_cost: float
    estimated_duration_min: float
    currency: str
    zone_name: Optional[str] = None


# --- Delivery ---

class DeliveryBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    pickup_address: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    delivery_address: str
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    distance_km: Optional[float] = None
    package_weight: Optional[str] = None
    package_description: Optional[str] = None
    special_instructions: Optional[str] = None
    delivery_person: Optional[str] = None
    delivery_person_phone: Optional[str] = None
    estimated_delivery: Optional[datetime] = None


class DeliveryCreate(DeliveryBase):
    store_id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    delivery_zone_id: Optional[uuid.UUID] = None


class DeliveryUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    delivery_address: Optional[str] = None
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    distance_km: Optional[float] = None
    delivery_person: Optional[str] = None
    delivery_person_phone: Optional[str] = None
    package_weight: Optional[str] = None
    package_description: Optional[str] = None
    special_instructions: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    delivery_zone_id: Optional[uuid.UUID] = None


class DeliveryResponse(DeliveryBase):
    id: uuid.UUID
    store_id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    tracking_number: str
    status: str
    delivery_zone_id: Optional[uuid.UUID] = None
    driver_id: Optional[uuid.UUID] = None
    vehicle_id: Optional[uuid.UUID] = None
    base_fee: float = 0.0
    per_km_rate: float = 0.0
    delivery_cost: float = 0.0
    currency: str = "USD"
    estimated_duration_min: Optional[float] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tracking_events: List[DeliveryTrackingResponse] = []


class DeliveryListResponse(BaseModel):
    deliveries: List[DeliveryResponse]
    total: int
    skip: int
    limit: int


class DeliveryStatusUpdate(BaseModel):
    status: str
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None
    failure_reason: Optional[str] = None


# --- Analytics ---

class DeliveryAnalytics(BaseModel):
    total_deliveries: int = 0
    delivered_count: int = 0
    in_transit_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    total_delivery_cost: float = 0.0
    avg_delivery_cost: float = 0.0
    avg_distance_km: float = 0.0
    avg_delivery_time_min: float = 0.0
    delivery_success_rate: float = 0.0

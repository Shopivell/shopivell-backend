
# Re-use from previous response
from datetime import date, datetime
from typing import List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class MonthlyUserCountSchema(BaseModel):
    month: str  # Format: "YYYY-MM"
    count: int

# Schema for role-based counts as a percentage of total users
class RoleCountSchema(BaseModel):
    role: str
    count: int
    percentage: float = Field(..., description="Percentage of total users")

# Schema for a single user's detailed profile
class UserProfileSchema(BaseModel):
    id: uuid.UUID
    username: Optional[str]
    role: str
    name: str
    surname: Optional[str]
    phone_number: Optional[str]
    email: str
    date_of_birth: Optional[date]
    gender: Optional[str]
    created_at: datetime
    status: str
    business_name: Optional[str]
    business_type: Optional[str]
    personal_image_path: Optional[str]

    model_config = ConfigDict(from_attributes=True)

# Final comprehensive schema for the API response
class ComprehensiveUserStatsResponseSchema(BaseModel):
    total_users: int
    active_users: int
    pending_users: int
    disabled_users: int
    business_accounts: int
    users_by_role: List[RoleCountSchema]
    monthly_registrations: List[MonthlyUserCountSchema]
    recent_users: List[UserProfileSchema]

    model_config = ConfigDict(from_attributes=True)


class MonthlyRequestCountSchema(BaseModel):
    """Represents the count of requests created in a specific month."""
    month: str
    count: int

class RequestStatusCountSchema(BaseModel):
    """Represents request counts by status, including percentage."""
    status: str
    count: int
    percentage: float = Field(..., description="Percentage of total requests")

class RequestDetailSchema(BaseModel):
    """Represents a single request with customer details."""
    title: str
    description: Optional[str]
    category: str
    quantity: int
    status: str
    created_at: datetime
    updated_at: Optional[datetime]
    image_path: Optional[str]
    customer_name: str
    customer_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

class ComprehensiveRequestStatsResponseSchema(BaseModel):
    """The complete response schema for request statistics."""
    total_requests: int
    active_requests: int
    requests_by_status: List[RequestStatusCountSchema]
    monthly_requests: List[MonthlyRequestCountSchema]
    recent_requests: List[RequestDetailSchema]

    model_config = ConfigDict(from_attributes=True)



class OfferStatusCountSchema(BaseModel):
    """Represents offer counts by status, including percentage."""
    status: str
    count: int
    percentage: float = Field(..., description="Percentage of total offers")

class MonthlyOfferCountSchema(BaseModel):
    """Represents the count of offers created in a specific month."""
    month: str
    count: int

class OfferDetailSchema(BaseModel):
    """Represents a single offer with related request and supplier details."""
    id: uuid.UUID
    request_id: uuid.UUID
    supplier_id: uuid.UUID
    proposed_price: float
    message: Optional[str]
    delivery_date: Optional[datetime]
    status: str
    created_at: datetime
    updated_at: Optional[datetime]
    request_title: str
    supplier_name: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class ComprehensiveOfferStatsResponseSchema(BaseModel):
    """The complete response schema for offer statistics."""
    total_offers: int
    offers_by_status: List[OfferStatusCountSchema]
    monthly_offers: List[MonthlyOfferCountSchema]
    recent_offers: List[OfferDetailSchema]

    model_config = ConfigDict(from_attributes=True)

   
class OrderStatusCountSchema(BaseModel):
    """Represents order counts by status, including percentage."""
    status: str
    count: int
    percentage: float = Field(..., description="Percentage of total orders")

class MonthlyOrderCountSchema(BaseModel):
    """Represents the count of orders created in a specific month."""
    month: str
    count: int

class OrderDetailSchema(BaseModel):
    """Represents a single order with related request, customer, and supplier details."""
    id: uuid.UUID
    request_id: uuid.UUID
    offer_id: uuid.UUID
    customer_id: uuid.UUID
    supplier_id: uuid.UUID
    total_price: float
    status: str
    created_at: datetime
    updated_at: Optional[datetime]
    delivered_at: Optional[datetime]
    request_title: str
    customer_name: Optional[str]
    supplier_name: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class ComprehensiveOrderStatsResponseSchema(BaseModel):
    """The complete response schema for order statistics."""
    total_orders: int
    orders_by_status: List[OrderStatusCountSchema]
    monthly_orders: List[MonthlyOrderCountSchema]
    recent_orders: List[OrderDetailSchema]

    model_config = ConfigDict(from_attributes=True)

   
class CategoryDistributionSchema(BaseModel):
    """Represents category counts by status, including percentage."""
    category: str
    count: int
    percentage: float = Field(..., description="Percentage of total products")
    
class PriceDistributionSchema(BaseModel):
    """Represents price counts by ranges, including percentage."""
    price_range: str
    count: int
    percentage: float = Field(..., description="Percentage of total products")

class ProductDetailSchema(BaseModel):
    """Represents a single product with related supplier details."""
    id: uuid.UUID
    name: str
    price: float
    category: str
    created_at: datetime
    supplier_name: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class ComprehensiveProductStatsResponseSchema(BaseModel):
    """The complete response schema for product statistics."""
    total_products: int
    average_price: float
    unique_categories: List[str]
    category_distribution: List[CategoryDistributionSchema]
    price_distribution: List[PriceDistributionSchema]
    recent_products: List[ProductDetailSchema]
    
    model_config = ConfigDict(from_attributes=True)
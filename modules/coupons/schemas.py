# modules/coupons/schemas.py
"""
Pydantic schemas for coupon endpoints.
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CouponType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    FREE_SHIPPING = "free_shipping"


class CouponCreate(BaseModel):
    """Schema for creating a new coupon."""
    store_id: UUID
    code: str = Field(..., min_length=3, max_length=50)
    description: Optional[str] = None
    type: CouponType
    value: float = Field(..., gt=0)
    min_order_amount: Optional[float] = None
    max_discount: Optional[float] = None
    usage_limit: Optional[int] = None
    per_user_limit: int = 1
    applicable_products: Optional[List[str]] = []
    applicable_categories: Optional[List[str]] = []
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


class CouponUpdate(BaseModel):
    """Schema for updating a coupon."""
    description: Optional[str] = None
    value: Optional[float] = Field(None, gt=0)
    min_order_amount: Optional[float] = None
    max_discount: Optional[float] = None
    usage_limit: Optional[int] = None
    per_user_limit: Optional[int] = None
    applicable_products: Optional[List[str]] = None
    applicable_categories: Optional[List[str]] = None
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


class CouponValidateRequest(BaseModel):
    """Schema for validating a coupon code."""
    code: str
    store_id: UUID
    order_amount: float = Field(..., gt=0)


class CouponApplyRequest(BaseModel):
    """Schema for applying a coupon to an order."""
    code: str
    store_id: UUID
    order_id: UUID
    order_amount: float = Field(..., gt=0)


class CouponResponse(BaseModel):
    """Schema for coupon response."""
    id: UUID
    store_id: UUID
    code: str
    description: Optional[str] = None
    type: str
    value: float
    min_order_amount: Optional[float] = None
    max_discount: Optional[float] = None
    usage_limit: Optional[int] = None
    used_count: int
    per_user_limit: int
    applicable_products: List[str] = []
    applicable_categories: List[str] = []
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CouponListResponse(BaseModel):
    """Schema for paginated coupon list."""
    coupons: List[CouponResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CouponValidateResponse(BaseModel):
    """Schema for coupon validation result."""
    valid: bool
    discount_amount: float = 0
    message: str


class CouponUsageResponse(BaseModel):
    """Schema for coupon usage record."""
    id: UUID
    coupon_id: UUID
    user_id: UUID
    order_id: Optional[UUID] = None
    discount_amount: float
    used_at: datetime

    class Config:
        from_attributes = True

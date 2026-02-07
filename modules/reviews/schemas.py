# modules/reviews/schemas.py
"""
Pydantic schemas for review endpoints.
"""

from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    """Schema for creating a new review."""
    store_id: UUID
    product_id: Optional[UUID] = None
    order_id: Optional[UUID] = None
    rating: int = Field(..., ge=1, le=5)
    title: Optional[str] = Field(None, max_length=255)
    comment: Optional[str] = None
    images: Optional[List[str]] = []


class ReviewUpdate(BaseModel):
    """Schema for updating a review."""
    rating: Optional[int] = Field(None, ge=1, le=5)
    title: Optional[str] = Field(None, max_length=255)
    comment: Optional[str] = None
    images: Optional[List[str]] = None


class SellerResponseCreate(BaseModel):
    """Schema for seller responding to a review."""
    seller_response: str = Field(..., min_length=1)


class ReviewVoteCreate(BaseModel):
    """Schema for voting on a review."""
    is_helpful: bool = True


class UserInfo(BaseModel):
    """Basic user information for review responses."""
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ReviewResponse(BaseModel):
    """Schema for review response."""
    id: UUID
    store_id: UUID
    product_id: Optional[UUID] = None
    customer_id: UUID
    order_id: Optional[UUID] = None
    rating: int
    title: Optional[str] = None
    comment: Optional[str] = None
    images: List[str] = []
    is_verified_purchase: bool
    is_approved: bool
    helpful_count: int
    reported_count: int
    seller_response: Optional[str] = None
    seller_response_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    customer: Optional[UserInfo] = None

    class Config:
        from_attributes = True


class ReviewListResponse(BaseModel):
    """Schema for paginated review list."""
    reviews: List[ReviewResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ReviewSummary(BaseModel):
    """Schema for review summary statistics."""
    avg_rating: float
    total_reviews: int
    rating_distribution: Dict[str, int]  # {"1": 5, "2": 10, ...}


class AdminReviewUpdate(BaseModel):
    """Schema for admin updating review status."""
    is_approved: Optional[bool] = None

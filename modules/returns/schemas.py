# modules/returns/schemas.py
"""
Pydantic schemas for return and refund endpoints.
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class ReturnReason(str, Enum):
    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    NOT_AS_DESCRIBED = "not_as_described"
    CHANGED_MIND = "changed_mind"
    OTHER = "other"


class ReturnStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFUNDED = "refunded"
    COMPLETED = "completed"


class RefundMethod(str, Enum):
    ORIGINAL_PAYMENT = "original_payment"
    STORE_CREDIT = "store_credit"
    BANK_TRANSFER = "bank_transfer"


class ReturnCreate(BaseModel):
    """Schema for creating a return request."""
    store_id: UUID
    order_id: UUID
    reason: ReturnReason
    description: Optional[str] = None
    images: Optional[List[str]] = []


class ReturnStatusUpdate(BaseModel):
    """Schema for updating return status."""
    status: ReturnStatus
    refund_amount: Optional[float] = None
    refund_method: Optional[RefundMethod] = None
    admin_notes: Optional[str] = None


class ReturnResponse(BaseModel):
    """Schema for return request response."""
    id: UUID
    store_id: UUID
    order_id: UUID
    customer_id: UUID
    reason: str
    description: Optional[str] = None
    images: List[str] = []
    status: str
    refund_amount: Optional[float] = None
    refund_method: Optional[str] = None
    admin_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReturnListResponse(BaseModel):
    """Schema for paginated return list."""
    returns: List[ReturnResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

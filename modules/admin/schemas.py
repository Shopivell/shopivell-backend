# modules/admin/schemas.py
"""
Pydantic schemas for the admin API.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


# ============ Enums ============

class AdminRole(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# ============ Auth Schemas ============

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class AdminLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "AdminUserResponse"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str


# ============ Admin User Schemas ============

class AdminUserResponse(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminUserListResponse(BaseModel):
    items: List[AdminUserResponse]
    total: int


# ============ Invitation Schemas ============

class InviteAdminRequest(BaseModel):
    email: EmailStr


class InviteAdminResponse(BaseModel):
    message: str
    invitation_id: UUID


class AcceptInvitationRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=50)
    last_name: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=8)


class InvitationVerifyResponse(BaseModel):
    email: str
    invited_by: str
    expires_at: datetime
    status: str


# ============ Dashboard Schemas ============

class DashboardOverview(BaseModel):
    total_agencies: int
    total_stores: int
    total_users: int
    total_revenue: float
    active_campaigns: int
    active_agencies: int
    new_signups_today: int
    revenue_growth: float


class RevenueDataPoint(BaseModel):
    date: str
    revenue: float


class ActivityItem(BaseModel):
    action: str
    user: str
    time: str
    type: str


# ============ Agency Schemas ============

class AgencyListItem(BaseModel):
    id: UUID
    name: str
    owner_name: str
    owner_email: str
    stores_count: int
    status: str
    total_revenue: float
    created_at: datetime

    class Config:
        from_attributes = True


class AgencyListResponse(BaseModel):
    items: List[AgencyListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class UpdateAgencyStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|suspended|pending)$")


# ============ Store Schemas ============

class StoreListItem(BaseModel):
    id: UUID
    store_name: str
    agency_name: Optional[str] = None
    owner_email: str
    products_count: int
    campaigns_count: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class StoreListResponse(BaseModel):
    items: List[StoreListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============ Campaign Schemas ============

class CampaignListItem(BaseModel):
    id: UUID
    name: str
    store_name: str
    platform: str
    status: str
    budget: float
    spent: float
    impressions: int
    clicks: int
    conversions: int
    created_at: datetime

    class Config:
        from_attributes = True


class CampaignListResponse(BaseModel):
    items: List[CampaignListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============ Asset Schemas ============

class AssetListItem(BaseModel):
    id: UUID
    name: str
    store_name: str
    file_type: str
    url: str
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


class AssetListResponse(BaseModel):
    items: List[AssetListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============ User Schemas ============

class UserListItem(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_verified: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    items: List[UserListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============ Payment Schemas ============

class PaymentListItem(BaseModel):
    id: UUID
    store_name: str
    amount: float
    currency: str
    payment_method: str
    package_name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentListResponse(BaseModel):
    items: List[PaymentListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class IncomeStats(BaseModel):
    total_revenue: float
    monthly_revenue: float
    by_package: List[Dict[str, Any]]
    by_method: List[Dict[str, Any]]


# ============ Feedback Schemas ============

class FeedbackListItem(BaseModel):
    id: UUID
    user_email: str
    type: str
    title: str
    description: str
    status: str
    priority: str
    admin_response: Optional[str] = None
    rating: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackListResponse(BaseModel):
    items: List[FeedbackListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class RespondToFeedbackRequest(BaseModel):
    admin_response: str = Field(..., min_length=1)


# ============ Store CRUD Schemas ============

class CreateStoreRequest(BaseModel):
    store_name: str = Field(..., min_length=2, max_length=100)
    owner_email: EmailStr
    agency_id: Optional[UUID] = None


class UpdateStoreStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|suspended|pending)$")


# ============ Agency CRUD Schemas ============

class CreateAgencyRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    owner_email: EmailStr


# ============ User CRUD Schemas ============

class UpdateUserStatusRequest(BaseModel):
    is_active: bool


# ============ Audit Log Schemas ============

class AuditLogItem(BaseModel):
    id: UUID
    admin_email: str
    action: str
    resource_type: str
    resource_id: Optional[UUID] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============ Store Discount Schemas ============

class SetStoreDiscountRequest(BaseModel):
    discount_percent: float = Field(..., gt=0, le=100, description="Discount percentage (1-100)")
    reason: str = Field(..., min_length=1, max_length=500, description="Reason for the discount")


class StoreDiscountResponse(BaseModel):
    store_id: UUID
    discount_percent: float
    reason: str
    is_active: bool
    created_by: Optional[UUID] = None
    created_at: Optional[str] = None


# Update forward reference
AdminLoginResponse.model_rebuild()

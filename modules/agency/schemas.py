from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from .models import AgencyStatus


class AgencyBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class AgencyCreate(AgencyBase):
    owner_id: uuid.UUID


class AgencyUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class AgencyResponse(AgencyBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    slug: str
    status: AgencyStatus
    settings: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class AgencyListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agencies: List[AgencyResponse]
    total: int
    page: int
    size: int


# Store summary for agency responses
class StoreBasicInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_name: str
    store_phone: Optional[str] = None
    store_email: Optional[str] = None
    store_link: Optional[str] = None
    logo_url: Optional[str] = None
    color_theme: Optional[str] = None
    business_type: Optional[str] = None
    is_setup_completed: bool = False
    created_at: datetime


class AgencyWithStoresResponse(AgencyResponse):
    stores: List[StoreBasicInfo] = []

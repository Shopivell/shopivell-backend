# modules/assets/schemas.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List
import uuid
from .models import AssetType


class AssetBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    file_type: AssetType = AssetType.IMAGE
    headline: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = []
    features: List[str] = []
    call_to_action: Optional[str] = None


class AssetCreate(AssetBase):
    store_id: uuid.UUID
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    cloudinary_public_id: Optional[str] = None
    cloudinary_url: Optional[str] = None
    cloudinary_secure_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    source: str = "upload"
    source_campaign_id: Optional[uuid.UUID] = None
    is_generated: bool = False


class AssetUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    features: Optional[List[str]] = None
    call_to_action: Optional[str] = None
    is_active: Optional[bool] = None


class AssetResponse(AssetBase):
    id: uuid.UUID
    store_id: uuid.UUID
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    cloudinary_public_id: Optional[str] = None
    cloudinary_url: Optional[str] = None
    cloudinary_secure_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    source: str = "upload"
    source_campaign_id: Optional[uuid.UUID] = None
    is_active: bool = True
    is_generated: bool = False
    created_at: datetime
    updated_at: datetime


class AssetListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assets: List[AssetResponse]
    total: int
    page: int
    size: int


class CloudinaryUploadResponse(BaseModel):
    public_id: str
    url: str
    secure_url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: str
    resource_type: str
    bytes: int


class GenerateAssetRequest(BaseModel):
    store_id: uuid.UUID
    campaign_id: Optional[uuid.UUID] = None
    headline: str
    description: Optional[str] = None
    features: List[str] = []
    call_to_action: str = "Learn More"
    style: str = "modern"  # modern, minimal, bold, elegant
    color_scheme: Optional[str] = None

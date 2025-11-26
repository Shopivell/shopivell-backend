from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID

# --- Request Schemas ---

class ContentCreate(BaseModel):
    """Schema for creating new content."""
    title: str
    content: str
    type: str
    platform: str
    status: str = "draft"
    date_posted: Optional[datetime] = None
    scheduled_date: Optional[datetime] = None
    file_type: Optional[str] = None
    file_size: Optional[str] = None
    author: str
    profile_image: Optional[str] = None
    engagement: Dict[str, Any] = {}
    thumbnail: Optional[str] = None
    metrics: Dict[str, Any] = {}

    model_config = ConfigDict(extra='allow')

class ContentUpdate(BaseModel):
    """Schema for updating existing content."""
    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[str] = None
    date_posted: Optional[datetime] = None
    scheduled_date: Optional[datetime] = None
    file_type: Optional[str] = None
    file_size: Optional[str] = None
    author: Optional[str] = None
    profile_image: Optional[str] = None
    engagement: Optional[Dict[str, Any]] = None
    thumbnail: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra='allow')

# --- Response Schemas ---

class ContentResponse(BaseModel):
    """Schema for returning content with all fields."""
    id: UUID
    title: str
    content: str
    type: str
    platform: str
    status: str
    date_posted: Optional[datetime] = None
    scheduled_date: Optional[datetime] = None
    file_type: Optional[str] = None
    file_size: Optional[str] = None
    author: str
    profile_image: Optional[str] = None
    engagement: Dict[str, Any]
    thumbnail: Optional[str] = None
    metrics: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

class ContentListResponse(BaseModel):
    """Schema for listing multiple content items with pagination info."""
    content: list[ContentResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int

class ContentStatsResponse(BaseModel):
    """Schema for content statistics."""
    total_content: int
    published_count: int
    scheduled_count: int
    draft_count: int
    platforms: Dict[str, int]
    content_types: Dict[str, int]
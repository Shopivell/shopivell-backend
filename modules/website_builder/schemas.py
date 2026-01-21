# modules/website_builder/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from .models import WebsiteStatus, GenerationStatus


# Theme schemas
class WebsiteTheme(BaseModel):
    primary_color: str = "#3B82F6"
    secondary_color: str = "#1F2937"
    accent_color: str = "#10B981"
    font_family: str = "Inter, sans-serif"
    logo_url: Optional[str] = None


class WebsiteIntegrations(BaseModel):
    stripe: bool = False
    paynow: bool = False
    google_analytics: bool = False
    adsense: bool = False
    twilio: bool = False
    # Integration config
    stripe_public_key: Optional[str] = None
    ga_tracking_id: Optional[str] = None
    paynow_integration_id: Optional[str] = None


# Website schemas
class WebsiteCreate(BaseModel):
    store_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class WebsiteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    theme: Optional[Dict[str, Any]] = None
    integrations: Optional[Dict[str, Any]] = None


class WebsiteResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    description: Optional[str]
    status: WebsiteStatus
    pages: Dict[str, str]
    theme: Dict[str, Any]
    integrations: Dict[str, Any]
    preview_html: Optional[str]
    deployed_url: Optional[str]
    custom_domain: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WebsiteListResponse(BaseModel):
    websites: List[WebsiteResponse]
    total: int


# Generation schemas
class GenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    selected_screens: List[str] = Field(default=["homepage"])


class GenerationStatusResponse(BaseModel):
    id: UUID
    website_id: UUID
    status: GenerationStatus
    progress: float
    current_step: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


# Chat schemas
class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    message: str
    updated_html: Optional[str] = None
    suggestions: Optional[List[str]] = None


# Preview schemas
class PreviewResponse(BaseModel):
    html: str
    pages: Dict[str, str]


# Code export schemas
class CodeFileResponse(BaseModel):
    filename: str
    content: str
    language: str


class CodeExportResponse(BaseModel):
    files: List[CodeFileResponse]
    readme: str


# Deploy schemas
class DeployRequest(BaseModel):
    custom_domain: Optional[str] = None


class DeployResponse(BaseModel):
    deployed_url: str
    status: str
    message: str

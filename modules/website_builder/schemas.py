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
    template_id: Optional[UUID] = None
    theme: Optional[Dict[str, Any]] = None


class WebsiteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    theme: Optional[Dict[str, Any]] = None
    integrations: Optional[Dict[str, Any]] = None
    preview_html: Optional[str] = None


class WebsiteTemplatePageResponse(BaseModel):
    id: UUID
    page_name: str
    route_path: str
    sort_order: float
    grapesjs_project_json: Dict[str, Any]

    class Config:
        from_attributes = True


class WebsiteTemplateResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    category: str
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    is_published: bool
    pages: List[WebsiteTemplatePageResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class WebsiteTemplatePageInput(BaseModel):
    page_name: str = Field(..., min_length=1, max_length=120)
    route_path: str = Field(..., min_length=1, max_length=255)
    sort_order: float = 0
    grapesjs_project_json: Dict[str, Any]


class WebsiteTemplateInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    slug: str = Field(..., min_length=1, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field("", max_length=5000)
    category: str = Field(..., min_length=1, max_length=80)
    thumbnail_url: Optional[str] = Field(None, max_length=1000)
    preview_url: Optional[str] = Field(None, max_length=1000)
    is_published: bool = True
    pages: Optional[List[WebsiteTemplatePageInput]] = None


class WebsiteProjectPageResponse(BaseModel):
    id: UUID
    website_id: UUID
    template_page_id: Optional[UUID] = None
    page_name: str
    route_path: str
    sort_order: float
    grapesjs_project_json: Dict[str, Any]
    updated_at: datetime

    class Config:
        from_attributes = True


class WebsiteProjectPageUpdate(BaseModel):
    page_name: Optional[str] = Field(None, min_length=1, max_length=120)
    route_path: Optional[str] = Field(None, min_length=1, max_length=255)
    sort_order: Optional[float] = None
    grapesjs_project_json: Optional[Dict[str, Any]] = None


class WebsitePageOrder(BaseModel):
    page_ids: List[UUID] = Field(..., min_length=1)


class WebsiteVersionCreate(BaseModel):
    notes: Optional[str] = Field(None, max_length=500)


class WebsiteChatMessageCreate(BaseModel):
    conversation_id: str = Field(..., min_length=8, max_length=80)
    sender_name: Optional[str] = Field(None, max_length=160)
    sender_email: Optional[str] = Field(None, max_length=255)
    message: str = Field(..., min_length=1, max_length=5000)


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

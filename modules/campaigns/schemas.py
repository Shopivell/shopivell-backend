# modules/campaigns/schemas.py
from pydantic import BaseModel, ConfigDict, HttpUrl
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from .models import CampaignStatus, CampaignGoal


class AdContentBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    headline: Optional[str] = None
    primary_text: Optional[str] = None
    description: Optional[str] = None
    call_to_action: Optional[str] = None
    destination_url: Optional[str] = None
    media_url: Optional[str] = None
    media_type: str = "image"


class AdContentCreate(AdContentBase):
    ad_set_id: uuid.UUID
    asset_id: Optional[uuid.UUID] = None


class AdContentResponse(AdContentBase):
    id: uuid.UUID
    ad_set_id: uuid.UUID
    asset_id: Optional[uuid.UUID] = None
    is_primary: bool = False
    is_active: bool = True
    generated_image_base64: Optional[str] = None  # AI-generated image
    created_at: datetime
    updated_at: datetime


class AdSetBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    title: Optional[str] = None
    age_range: Optional[Dict[str, int]] = None
    gender: Optional[str] = None
    audience_tags: List[str] = []
    hashtags: List[str] = []
    daily_budget: Optional[float] = None


class AdSetCreate(AdSetBase):
    campaign_id: uuid.UUID


class AdSetResponse(AdSetBase):
    id: uuid.UUID
    campaign_id: uuid.UUID
    total_spent: float = 0.0
    is_selected: bool = True
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    ad_contents: List[AdContentResponse] = []


class CampaignBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: Optional[str] = None
    source_url: Optional[str] = None
    source_type: str = "url"
    goal: CampaignGoal = CampaignGoal.SALES
    conversion_button: str = "Learn More"
    daily_budget: float = 100.0
    total_budget: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    countries: List[str] = []
    cities: List[str] = []
    age_range: Dict[str, int] = {"min": 18, "max": 65}
    gender: str = "all"
    interests: List[str] = []
    platforms: List[str] = ["facebook"]


class CampaignCreate(CampaignBase):
    store_id: uuid.UUID


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[CampaignGoal] = None
    conversion_button: Optional[str] = None
    daily_budget: Optional[float] = None
    total_budget: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    countries: Optional[List[str]] = None
    cities: Optional[List[str]] = None
    age_range: Optional[Dict[str, int]] = None
    gender: Optional[str] = None
    interests: Optional[List[str]] = None
    platforms: Optional[List[str]] = None
    status: Optional[CampaignStatus] = None


class CampaignResponse(CampaignBase):
    id: uuid.UUID
    store_id: uuid.UUID
    scraped_data: Optional[Dict[str, Any]] = None
    scraped_at: Optional[datetime] = None
    generated_headlines: List[str] = []
    generated_descriptions: List[str] = []
    status: CampaignStatus
    error_message: Optional[str] = None
    platform_campaign_ids: Dict[str, str] = {}
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    ad_sets: List[AdSetResponse] = []


class CampaignListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaigns: List[CampaignResponse]
    total: int
    page: int
    size: int


# URL Scraping Request/Response
class ScrapeUrlRequest(BaseModel):
    url: str
    store_id: uuid.UUID
    campaign_name: Optional[str] = None
    asset_ids: Optional[List[uuid.UUID]] = None  # User-provided assets to help AI agents


class ScrapeUrlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: uuid.UUID
    status: str
    message: str
    scraped_data: Optional[Dict[str, Any]] = None


# Ad Generation Request
class GenerateAdsRequest(BaseModel):
    campaign_id: uuid.UUID
    num_ad_sets: int = 5
    regenerate: bool = False

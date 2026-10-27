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
    # Per-variation delivery (Meta): placement, optimization goal and the targeting/
    # demographics/image-direction bundle that makes each Copy-A/B/C row a different test.
    placement: Optional[str] = None
    optimization_goal: Optional[str] = None
    creative_metadata: Optional[Dict[str, Any]] = None


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
    meta_ad_id: Optional[str] = None
    variation_label: Optional[str] = None
    copy_variation_index: int = 0
    image_variation_index: int = 0
    fatigue_score: float = 0.0
    last_refreshed_at: Optional[datetime] = None
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
    sales_type: Optional[str] = None
    destination_url: Optional[str] = None
    lead_form_fields: Optional[List[Dict[str, Any]]] = None
    # Meta Special Ad Category — must be declared for housing/employment/credit/
    # financial/social-issue/gambling ads. NONE for regular product ads.
    special_ad_category: str = "NONE"


class CampaignCreate(CampaignBase):
    store_id: uuid.UUID


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[CampaignGoal] = None
    special_ad_category: Optional[str] = None
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
    sales_type: Optional[str] = None
    destination_url: Optional[str] = None
    lead_form_fields: Optional[List[Dict[str, Any]]] = None


class CampaignResponse(CampaignBase):
    id: uuid.UUID
    store_id: uuid.UUID
    scraped_data: Optional[Dict[str, Any]] = None
    scraped_at: Optional[datetime] = None
    generated_headlines: List[str] = []
    generated_descriptions: List[str] = []
    status: CampaignStatus
    error_message: Optional[str] = None
    platform_campaign_ids: Dict[str, Any] = {}
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
    num_ad_sets: int = 1  # Default to 1 ad set to save tokens
    num_copies: int = 1  # Copy variations per ad set (1-5)
    num_images: int = 1  # Image variations per ad set (1-3)
    regenerate: bool = False


# Create Campaign from Store (no scraping - uses store data directly)
class CreateCampaignFromStoreRequest(BaseModel):
    store_id: uuid.UUID
    campaign_name: Optional[str] = None  # Optional custom name, defaults to store name
    asset_ids: Optional[List[uuid.UUID]] = None  # Optional user-provided assets


class CreateCampaignFromStoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: uuid.UUID
    status: str
    message: str
    store_data_used: Dict[str, Any]  # Shows what store data was used


# Quick Launch - paste URL → 5 ad sets live on Meta
class QuickLaunchRequest(BaseModel):
    url: str
    store_id: uuid.UUID
    ad_account_id: uuid.UUID
    daily_budget: float = 10.0  # USD per ad set (used when budget_type is "daily")
    budget_type: str = "lifetime"  # "daily" or "lifetime" — lifetime enables dayparting
    campaign_duration_days: int = 30  # Duration for lifetime budget campaigns
    countries: List[str] = ["ZW"]
    goal: CampaignGoal = CampaignGoal.TRAFFIC
    age_range: Dict[str, int] = {"min": 18, "max": 65}
    gender: str = "all"
    campaign_name: Optional[str] = None
    page_id: Optional[uuid.UUID] = None  # Facebook page for ads
    num_copies: int = 1  # Copy variations per ad set (1-5)
    num_images: int = 1  # Image variations per ad set (1-3)
    auto_start_scheduler: bool = True  # Auto-register with scheduler


class QuickLaunchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    campaign_id: uuid.UUID
    campaign_name: str
    meta_campaign_id: Optional[str] = None
    ad_sets_created: int = 0
    ads_created: int = 0
    scheduler_registered: bool = False
    dayparting_enabled: bool = False
    dayparting_schedule: Optional[List[Dict[str, Any]]] = None
    dayparting_reasoning: Optional[str] = None
    budget_type: str = "daily"
    pipeline_results: Optional[Dict[str, Any]] = None
    publish_results: Optional[Dict[str, Any]] = None
    errors: List[str] = []
    message: str


# --- Optimization & Fatigue Schemas ---

class OptimizeRequest(BaseModel):
    min_impressions: int = 1000
    dry_run: bool = False


class VariantEvaluation(BaseModel):
    ad_content_id: uuid.UUID
    variation_label: Optional[str] = None
    impressions: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    spend: float = 0.0
    status: str = "active"  # active, paused, winner, loser


class OptimizeResponse(BaseModel):
    campaign_id: uuid.UUID
    evaluated: bool = False
    reason: Optional[str] = None
    variants: List[VariantEvaluation] = []
    paused_count: int = 0
    scaled_count: int = 0
    budget_changes: List[Dict[str, Any]] = []
    dry_run: bool = False


class FatigueVariant(BaseModel):
    ad_content_id: uuid.UUID
    variation_label: Optional[str] = None
    fatigue_score: float = 0.0
    frequency: float = 0.0
    ctr_trend: str = "stable"  # stable, declining, dropped
    action: Optional[str] = None  # refresh_copy, refresh_both, none


class FatigueCheckResponse(BaseModel):
    campaign_id: uuid.UUID
    total_checked: int = 0
    fatigued_count: int = 0
    refreshed_count: int = 0
    variants: List[FatigueVariant] = []


class AdContentMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ad_content_id: uuid.UUID
    campaign_id: uuid.UUID
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    conversions: int = 0
    spend: float = 0.0
    ctr: float = 0.0
    cpc: float = 0.0
    cpm: float = 0.0
    frequency: float = 0.0
    roas: float = 0.0
    date: datetime
    collected_at: datetime

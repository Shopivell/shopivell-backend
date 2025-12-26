# schemas/marketing.py
from pydantic import BaseModel, ConfigDict, Field, validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, date
import uuid
from enum import Enum

# Enums
class CampaignObjective(str, Enum):
    OUTCOME_TRAFFIC = "OUTCOME_TRAFFIC"  # Replaces LINK_CLICKS
    OUTCOME_SALES = "OUTCOME_SALES"  # Replaces CONVERSIONS
    OUTCOME_LEADS = "OUTCOME_LEADS"  # Replaces LEAD_GENERATION
    OUTCOME_ENGAGEMENT = "OUTCOME_ENGAGEMENT"  # Replaces POST_ENGAGEMENT, PAGE_LIKES
    OUTCOME_AWARENESS = "OUTCOME_AWARENESS"  # Replaces BRAND_AWARENESS, REACH
    OUTCOME_APP_PROMOTION = "OUTCOME_APP_PROMOTION"  # Replaces APP_INSTALLS

class CampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"

class AdSetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"

class AdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"

class BillingEvent(str, Enum):
    IMPRESSIONS = "IMPRESSIONS"
    LINK_CLICKS = "LINK_CLICKS"
    THRUPLAY = "THRUPLAY"

class OptimizationGoal(str, Enum):
    LINK_CLICKS = "LINK_CLICKS"
    IMPRESSIONS = "IMPRESSIONS"
    CONVERSIONS = "CONVERSIONS"
    REACH = "REACH"
    THRUPLAY = "THRUPLAY"

class CreativeType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    CAROUSEL = "CAROUSEL"
    SLIDESHOW = "SLIDESHOW"

# Base Models
class MetaAdAccountBase(BaseModel):
    ad_account_id: str
    account_name: str
    account_status: int
    currency: str
    timezone_name: str
    business_id: Optional[str] = None
    business_name: Optional[str] = None
    is_connected: bool = True
    is_active: bool = True

class MetaCampaignBase(BaseModel):
    name: str
    objective: CampaignObjective
    status: CampaignStatus
    special_ad_categories: Optional[List[str]] = None
    buying_type: str = "AUCTION"
    daily_budget: Optional[int] = None
    lifetime_budget: Optional[int] = None
    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None
    bid_strategy: Optional[str] = None

class MetaAdSetBase(BaseModel):
    name: str
    status: AdSetStatus
    optimization_goal: OptimizationGoal
    billing_event: BillingEvent
    # daily_budget: Optional[int] = None
    lifetime_budget: Optional[int] = None
    bid_amount: Optional[int] = None
    bid_strategy: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    targeting: Optional[Dict[str, Any]] = None
    placement: Optional[Dict[str, Any]] = None
    # publisher_platforms: Optional[List[str]] = None

class MetaAdBase(BaseModel):
    name: str
    status: AdStatus
    ad_format: Optional[str] = None
    tracking_specs: Optional[Dict[str, Any]] = None

class MetaAdCreativeBase(BaseModel):
    creative_type: CreativeType
    object_story_spec: Optional[Dict[str, Any]] = None
    object_type: Optional[str] = None
    link_data: Optional[Dict[str, Any]] = None
    image_data: Optional[Dict[str, Any]] = None
    video_data: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    body: Optional[str] = None
    call_to_action_type: Optional[str] = None
    image_url: Optional[str] = None
    image_hash: Optional[str] = None
    video_url: Optional[str] = None
    video_id: Optional[str] = None
    url: Optional[str] = None

class MetaExperimentBase(BaseModel):
    name: str
    type: str = "A/B_TEST"
    status: str = "DRAFT"
    control_id: Optional[str] = None
    treatment_id: Optional[str] = None
    confidence_level: float = 0.95
    sample_size: Optional[int] = None
    duration_days: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

class MetaAutomatedRuleBase(BaseModel):
    name: str
    entity_type: str  # CAMPAIGN, ADSET, AD
    status: str = "ENABLED"
    conditions: List[Dict[str, Any]]
    action: Dict[str, Any]
    schedule_type: str = "DAILY"
    schedule_spec: Optional[Dict[str, Any]] = None

# Create Models
class MetaAdAccountCreate(MetaAdAccountBase):
    access_token: str
    user_id: str
    expires_at: Optional[datetime] = None
    business_account_id: Optional[uuid.UUID] = None

class MetaCampaignCreate(MetaCampaignBase):
    ad_account_id: uuid.UUID
    # Optional Meta ID if syncing existing
    campaign_id: Optional[str] = None

class MetaAdSetCreate(MetaAdSetBase):
    ad_account_id: uuid.UUID
    campaign_id: uuid.UUID
    # Optional Meta ID if syncing existing
    adset_id: Optional[str] = None

class MetaAdCreate(MetaAdBase):
    ad_account_id: uuid.UUID
    campaign_id: uuid.UUID
    adset_id: uuid.UUID
    creative_id: Optional[uuid.UUID] = None
    # Optional Meta ID if syncing existing
    ad_id: Optional[str] = None

class MetaAdCreativeCreate(MetaAdCreativeBase):
    ad_account_id: uuid.UUID
    # Optional Meta ID if syncing existing
    creative_id: Optional[str] = None

class MetaExperimentCreate(MetaExperimentBase):
    ad_account_id: uuid.UUID
    # Optional Meta ID if syncing existing
    experiment_id: Optional[str] = None

class MetaAutomatedRuleCreate(MetaAutomatedRuleBase):
    ad_account_id: uuid.UUID
    # Optional Meta ID if syncing existing
    rule_id: Optional[str] = None

# Update Models
class MetaAdAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    access_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_connected: Optional[bool] = None
    is_active: Optional[bool] = None

class MetaCampaignUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[CampaignStatus] = None
    daily_budget: Optional[int] = None
    lifetime_budget: Optional[int] = None
    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None

class MetaAdSetUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[AdSetStatus] = None
    daily_budget: Optional[int] = None
    bid_amount: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    targeting: Optional[Dict[str, Any]] = None

class MetaAdUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[AdStatus] = None
    creative_id: Optional[uuid.UUID] = None

# Response Models
class MetaAdAccountResponse(MetaAdAccountBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    user_id: str
    business_account_id: Optional[uuid.UUID] = None
    expires_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    # Statistics
    campaign_count: Optional[int] = 0
    active_campaign_count: Optional[int] = 0

class MetaCampaignResponse(MetaCampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: str
    ad_account_id: uuid.UUID

    # Draft support fields
    is_draft: Optional[bool] = Field(default=False)
    notes: Optional[str] = None
    draft_data: Optional[Dict[str, Any]] = None
    published_at: Optional[datetime] = None

    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    effective_status: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Statistics
    ad_set_count: Optional[int] = 0
    ad_count: Optional[int] = 0
    spend: Optional[float] = 0.0
    impressions: Optional[int] = 0
    clicks: Optional[int] = 0

class MetaAdSetResponse(MetaAdSetBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    adset_id: str
    ad_account_id: uuid.UUID
    campaign_id: uuid.UUID

    # Draft support fields
    is_draft: Optional[bool] = Field(default=False)
    notes: Optional[str] = None
    draft_data: Optional[Dict[str, Any]] = None
    published_at: Optional[datetime] = None

    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    effective_status: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Statistics
    ad_count: Optional[int] = 0
    spend: Optional[float] = 0.0
    impressions: Optional[int] = 0
    clicks: Optional[int] = 0

class MetaAdResponse(MetaAdBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    ad_id: str
    ad_account_id: uuid.UUID
    campaign_id: uuid.UUID
    adset_id: uuid.UUID
    creative_id: Optional[uuid.UUID] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    effective_status: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    
    # Statistics
    spend: Optional[float] = 0.0
    impressions: Optional[int] = 0
    clicks: Optional[int] = 0
    ctr: Optional[float] = 0.0

class MetaAdCreativeResponse(MetaAdCreativeBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    creative_id: str
    ad_account_id: uuid.UUID
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    
    # Usage
    ad_count: Optional[int] = 0

class MetaAdResponse(MetaAdBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    ad_id: str
    ad_account_id: uuid.UUID
    campaign_id: uuid.UUID
    adset_id: uuid.UUID
    creative_id: Optional[uuid.UUID] = None
    
    # Draft support fields - ADD THESE
    is_draft: Optional[bool] = Field(default=False)
    notes: Optional[str] = None
    draft_data: Optional[Dict[str, Any]] = None
    published_at: Optional[datetime] = None
    
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    effective_status: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    
    # Statistics
    spend: Optional[float] = 0.0
    impressions: Optional[int] = 0
    clicks: Optional[int] = 0
    ctr: Optional[float] = 0.0

class MetaExperimentResponse(MetaExperimentBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    experiment_id: str
    ad_account_id: uuid.UUID
    winner: Optional[str] = None
    confidence: Optional[float] = None
    metric_results: Optional[Dict[str, Any]] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

class MetaAutomatedRuleResponse(MetaAutomatedRuleBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    rule_id: str
    ad_account_id: uuid.UUID
    execution_count: int = 0
    last_execution_time: Optional[datetime] = None
    last_execution_result: Optional[Dict[str, Any]] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

class MetaAdInsightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    ad_id: uuid.UUID
    date: datetime
    impressions: int
    clicks: int
    spend: float
    cpm: float
    cpc: float
    ctr: float
    frequency: float
    reach: int
    conversions: int
    cost_per_conversion: float
    conversion_rate: float
    likes: int
    comments: int
    shares: int
    created_at: datetime
    updated_at: datetime

# List Response Models
class MetaAdAccountListResponse(BaseModel):
    ad_accounts: List[MetaAdAccountResponse]
    total_count: int

class MetaCampaignListResponse(BaseModel):
    campaigns: List[MetaCampaignResponse]
    total_count: int

class MetaAdSetListResponse(BaseModel):
    ad_sets: List[MetaAdSetResponse]
    total_count: int

class MetaAdListResponse(BaseModel):
    ads: List[MetaAdResponse]
    total_count: int

class MetaAdCreativeListResponse(BaseModel):
    ad_creatives: List[MetaAdCreativeResponse]
    total_count: int

class MetaExperimentListResponse(BaseModel):
    experiments: List[MetaExperimentResponse]
    total_count: int

class MetaAutomatedRuleListResponse(BaseModel):
    automated_rules: List[MetaAutomatedRuleResponse]
    total_count: int

class MetaAdInsightListResponse(BaseModel):
    insights: List[MetaAdInsightResponse]
    total_count: int

# API Request Models
class MetaSyncRequest(BaseModel):
    force: bool = False
    sync_all: bool = False

class MetaInsightsRequest(BaseModel):
    start_date: date
    end_date: date
    breakdowns: Optional[List[str]] = None
    level: str = "ad"
    fields: Optional[List[str]] = None

class MetaCreateCampaignRequest(BaseModel):
    name: str
    objective: CampaignObjective
    status: CampaignStatus = CampaignStatus.PAUSED
    special_ad_categories: Optional[List[str]] = None
    buying_type: str = "AUCTION"
    daily_budget: Optional[int] = None
    lifetime_budget: Optional[int] = None
    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None
    save_as_draft: Optional[bool] = False  # If true, save locally without publishing to Meta

class MetaCreateAdSetRequest(BaseModel):
    name: str
    status: AdSetStatus = AdSetStatus.PAUSED
    optimization_goal: OptimizationGoal
    billing_event: BillingEvent
    daily_budget: Optional[int] = None
    lifetime_budget: Optional[int] = None
    bid_amount: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    targeting: Optional[Dict[str, Any]] = None
    placement: Optional[Dict[str, Any]] = None
    save_as_draft: Optional[bool] = False  # If true, save locally without publishing to Meta

class MetaCreateAdRequest(BaseModel):
    name: str
    status: AdStatus = AdStatus.PAUSED
    
    # Creative identification options (choose one)
    creative_id: Optional[uuid.UUID] = None
    existing_post_id: Optional[str] = None
    
    # For creating simple link ads
    creative_link: Optional[str] = None
    creative_message: Optional[str] = None
    creative_description: Optional[str] = None
    image_url: Optional[str] = None
    call_to_action_type: Optional[str] = "LEARN_MORE"
    
    # General ad fields
    ad_format: Optional[str] = None
    tracking_specs: Optional[Dict[str, Any]] = None

class MetaCreateCreativeRequest(BaseModel):
    creative_type: CreativeType
    title: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    url: Optional[str] = None
    call_to_action_type: Optional[str] = None

class MetaCreateExperimentRequest(BaseModel):
    name: str
    type: str = "A/B_TEST"
    control_id: str
    treatment_id: str
    confidence_level: float = 0.95
    duration_days: int
    start_time: Optional[datetime] = None

class MetaBulkUpdateRequest(BaseModel):
    ids: List[uuid.UUID]
    status: Optional[str] = None
    budget: Optional[int] = None
    bid_amount: Optional[int] = None

# Success/Error Models
class SuccessMessage(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

class ErrorMessage(BaseModel):
    success: bool = False
    message: str
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

# Insights Models
class MetaInsightsSummary(BaseModel):
    spend: float
    impressions: int
    clicks: int
    ctr: float
    cpc: float
    cpm: float
    conversions: int
    cost_per_conversion: float
    conversion_rate: float
    reach: int
    frequency: float

class MetaPerformanceMetrics(BaseModel):
    date: date
    spend: float
    impressions: int
    clicks: int
    conversions: int
    ctr: float
    cpc: float

class MetaCampaignPerformance(BaseModel):
    campaign_id: str
    campaign_name: str
    objective: str
    status: str
    spend: float
    impressions: int
    clicks: int
    ctr: float
    conversions: int
    cost_per_conversion: float
    roas: Optional[float] = None

# Draft Models
class DraftItem(BaseModel):
    """Unified draft item for listing all drafts"""
    id: uuid.UUID
    type: str  # campaign, adset, ad
    name: str
    status: str
    notes: Optional[str] = None
    draft_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    # Additional context
    ad_account_id: Optional[uuid.UUID] = None
    campaign_id: Optional[uuid.UUID] = None
    campaign_name: Optional[str] = None
    adset_id: Optional[uuid.UUID] = None
    adset_name: Optional[str] = None

class DraftListResponse(BaseModel):
    drafts: List[DraftItem]
    total_count: int

class PublishDraftRequest(BaseModel):
    """Request to publish a draft"""
    notes: Optional[str] = None

class PublishDraftResponse(BaseModel):
    success: bool
    message: str
    meta_id: Optional[str] = None  # The ID returned from Meta API
    published_at: Optional[datetime] = None

# Update forward references if needed
MetaCampaignResponse.model_rebuild()
MetaAdSetResponse.model_rebuild()
MetaAdResponse.model_rebuild()
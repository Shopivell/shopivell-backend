# schemas.py - Pydantic models for Marketing Agents Module

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import uuid


class CampaignObjective(str, Enum):
    AWARENESS = "AWARENESS"
    TRAFFIC = "TRAFFIC"
    ENGAGEMENT = "ENGAGEMENT"
    LEAD_GENERATION = "LEAD_GENERATION"
    CONVERSIONS = "CONVERSIONS"


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


# ============ Campaign Schemas ============

class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    objective: CampaignObjective
    product_description: str = Field(..., min_length=10)
    keywords: List[str] = Field(default_factory=list)
    target_audience: Dict[str, Any] = Field(default_factory=dict)
    budget: int = Field(default=0, ge=0, description="Budget in cents")
    store_id: Optional[uuid.UUID] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[CampaignObjective] = None
    product_description: Optional[str] = None
    keywords: Optional[List[str]] = None
    target_audience: Optional[Dict[str, Any]] = None
    budget: Optional[int] = None
    status: Optional[CampaignStatus] = None


class CampaignResponse(BaseModel):
    id: uuid.UUID
    store_id: Optional[uuid.UUID]
    name: str
    objective: str
    product_description: Optional[str]
    keywords: Optional[List[str]]
    target_audience: Optional[Dict[str, Any]]
    status: str
    budget: int
    meta_campaign_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Market Research Schemas ============

class MarketResearchRequest(BaseModel):
    """Request to generate market research for a campaign"""
    campaign_id: uuid.UUID


class MarketResearchOutput(BaseModel):
    """Output from market research agent"""
    competitor_analysis: str
    audience_insights: str
    trend_data: str
    recommendations: str


class MarketResearchResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    competitor_analysis: Optional[str]
    audience_insights: Optional[str]
    trend_data: Optional[str]
    recommendations: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Creative Angle Schemas ============

class CreativeAngleRequest(BaseModel):
    """Request to generate creative angles for a campaign"""
    campaign_id: uuid.UUID
    num_angles: int = Field(default=3, ge=1, le=10)


class CreativeAngleOutput(BaseModel):
    """Single creative angle output"""
    angle_name: str
    value_proposition: str
    emotion_target: str
    visual_direction: str
    reasoning: str


class CreativeAngleResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    angle_name: str
    value_proposition: Optional[str]
    emotion_target: Optional[str]
    visual_direction: Optional[str]
    reasoning: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Ad Copy Schemas ============

class AdCopyRequest(BaseModel):
    """Request to generate ad copy"""
    campaign_id: uuid.UUID
    angle_id: Optional[uuid.UUID] = None
    num_variations: int = Field(default=3, ge=1, le=5)


class AdCopyOutput(BaseModel):
    """Ad copy output"""
    headline: str
    primary_text: str
    description: str
    call_to_action: str
    variations: List[Dict[str, str]] = Field(default_factory=list)


class AdCopyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    angle_id: Optional[uuid.UUID]
    headline: str
    primary_text: Optional[str]
    description: Optional[str]
    call_to_action: Optional[str]
    variations: Optional[List[Dict[str, str]]]
    is_active: bool
    meta_ad_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Performance Metrics Schemas ============

class PerformanceMetricsResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    ad_id: Optional[uuid.UUID]
    impressions: int
    clicks: int
    conversions: int
    spend: int
    ctr: float
    cpc: float
    cpa: float
    roas: float
    collected_at: datetime

    class Config:
        from_attributes = True


# ============ Optimization Schemas ============

class OptimizationPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OptimizationRecommendation(BaseModel):
    """AI-generated optimization recommendation"""
    action: str
    reasoning: str
    expected_impact: str
    priority: OptimizationPriority


class OptimizationRequest(BaseModel):
    """Request for campaign optimization analysis"""
    campaign_id: uuid.UUID


class OptimizationResponse(BaseModel):
    campaign_id: uuid.UUID
    recommendations: List[OptimizationRecommendation]
    generated_at: datetime

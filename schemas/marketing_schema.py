from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MarketingCampaignBaseSchema(BaseModel):
    name: str
    platform: str
    status: str
    objective: Optional[str] = None
    budget: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    channels: List[str] = Field(default_factory=list)
    metrics: Dict[str, float] = Field(default_factory=dict)
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MarketingCampaignCreateSchema(MarketingCampaignBaseSchema):
    pass


class MarketingCampaignUpdateSchema(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[str] = None
    objective: Optional[str] = None
    budget: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    channels: Optional[List[str]] = None
    metrics: Optional[Dict[str, float]] = None
    notes: Optional[str] = None


class MarketingCampaignResponseSchema(MarketingCampaignBaseSchema):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None


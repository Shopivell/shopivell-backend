"""
Pydantic schemas for Micro-Strategy and Pixel Readiness Tracker.
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


# ── Requests ───────────────────────────────────────────────


class CreateMicroStrategyRequest(BaseModel):
    ad_account_id: uuid.UUID
    store_id: uuid.UUID
    name: str
    source_url: str
    destination_url: Optional[str] = None
    winner_metric: str = "LOWEST_CPA"
    daily_budget_cents: int = 1000
    max_spend_per_phase_cents: int = 5000
    min_days_per_phase: int = 3
    max_days_per_phase: int = 7
    variations_per_phase: int = 5
    product_context: Optional[Dict[str, Any]] = None


class UpdateMicroStrategyRequest(BaseModel):
    name: Optional[str] = None
    winner_metric: Optional[str] = None
    daily_budget_cents: Optional[int] = None
    max_spend_per_phase_cents: Optional[int] = None
    min_days_per_phase: Optional[int] = None
    max_days_per_phase: Optional[int] = None


class DeclareWinnerRequest(BaseModel):
    variation_id: Optional[uuid.UUID] = None


class CreatePixelTrackerRequest(BaseModel):
    ad_account_id: uuid.UUID
    store_id: uuid.UUID
    pixel_id: str
    pixel_name: Optional[str] = None
    micro_strategy_id: Optional[uuid.UUID] = None
    required_events: int = 50
    required_days: int = 7
    event_window_days: int = 7


# ── Responses ──────────────────────────────────────────────


class PhaseVariationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variation_number: int
    variation_name: str
    variable_type: str
    variable_value: str
    variable_metadata: Optional[Dict[str, Any]] = None
    impressions: int = 0
    clicks: int = 0
    spend_cents: int = 0
    conversions: int = 0
    ctr: float = 0.0
    cpc: float = 0.0
    cpa: float = 0.0
    roas: float = 0.0
    is_winner: bool = False
    is_active: bool = True
    meta_adset_id: Optional[str] = None
    meta_ad_id: Optional[str] = None
    created_at: datetime


class PhaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phase_number: int
    phase_type: str
    status: str
    budget_per_variation_cents: Optional[int] = None
    total_spend_cents: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    winner_variation_id: Optional[uuid.UUID] = None
    winner_value: Optional[str] = None
    winner_metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    variations: List[PhaseVariationResponse] = []
    created_at: datetime


class MicroStrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    winner_metric: str
    daily_budget_cents: int
    max_spend_per_phase_cents: int
    min_days_per_phase: int
    max_days_per_phase: int
    variations_per_phase: int
    current_phase_number: int
    source_url: Optional[str] = None
    destination_url: Optional[str] = None
    winning_headline: Optional[str] = None
    winning_image_url: Optional[str] = None
    winning_audience: Optional[Dict[str, Any]] = None
    winning_offer: Optional[str] = None
    learnings: Optional[Dict[str, Any]] = None
    meta_campaign_id: Optional[str] = None
    phases: List[PhaseResponse] = []
    created_at: datetime
    updated_at: datetime


class MicroStrategyListResponse(BaseModel):
    strategies: List[MicroStrategyResponse]
    total: int


class PixelTrackerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pixel_id: str
    pixel_name: Optional[str] = None
    current_objective: str
    switch_status: str
    page_view_count: int = 0
    view_content_count: int = 0
    lead_count: int = 0
    add_to_cart_count: int = 0
    purchase_count: int = 0
    total_optimization_events: int = 0
    required_events: int
    required_days: int
    event_window_days: int
    traffic_campaign_id: Optional[str] = None
    leadgen_campaign_id: Optional[str] = None
    traffic_started_at: Optional[datetime] = None
    switch_triggered_at: Optional[datetime] = None
    leadgen_started_at: Optional[datetime] = None
    micro_strategy_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    @property
    def progress_percent(self) -> float:
        if self.required_events <= 0:
            return 100.0
        return min(100.0, (self.total_optimization_events / self.required_events) * 100)


class PixelTrackerListResponse(BaseModel):
    trackers: List[PixelTrackerResponse]
    total: int


class LearningsResponse(BaseModel):
    strategy_id: uuid.UUID
    strategy_name: str
    learnings: Optional[Dict[str, Any]] = None
    winning_headline: Optional[str] = None
    winning_image_url: Optional[str] = None
    winning_audience: Optional[Dict[str, Any]] = None
    winning_offer: Optional[str] = None
    phases_completed: int = 0
    phases_total: int = 4

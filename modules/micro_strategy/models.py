"""
Micro-Strategy models for Lexi isolated variable testing
and Pixel readiness tracking (Traffic -> Lead Gen auto-switch).
"""
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime,
    ForeignKey, Integer, JSON, Float,
)
from db_compat import UUID
from sqlalchemy.orm import relationship
import uuid
import enum
from datetime import datetime
from database import Base


# ── Enums ──────────────────────────────────────────────────


class StrategyStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PhaseType(str, enum.Enum):
    HEADLINE = "HEADLINE"
    IMAGE = "IMAGE"
    AUDIENCE = "AUDIENCE"
    OFFER = "OFFER"


class PhaseStatus(str, enum.Enum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    PUBLISHING = "PUBLISHING"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class WinnerMetric(str, enum.Enum):
    LOWEST_CPA = "LOWEST_CPA"
    HIGHEST_CTR = "HIGHEST_CTR"
    LOWEST_CPC = "LOWEST_CPC"
    HIGHEST_ROAS = "HIGHEST_ROAS"


class SwitchStatus(str, enum.Enum):
    TRAFFIC_PHASE = "TRAFFIC_PHASE"
    MONITORING = "MONITORING"
    READY_TO_SWITCH = "READY_TO_SWITCH"
    LEAD_GEN_PHASE = "LEAD_GEN_PHASE"
    COMPLETED = "COMPLETED"


# ── Models ─────────────────────────────────────────────────


class MicroStrategy(Base):
    """Top-level Lexi Micro-Strategy test plan."""
    __tablename__ = "micro_strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)

    # Config
    name = Column(String(255), nullable=False)
    status = Column(String(50), default=StrategyStatus.DRAFT.value)
    winner_metric = Column(String(50), default=WinnerMetric.LOWEST_CPA.value)
    daily_budget_cents = Column(Integer, default=1000)          # $10/day total
    max_spend_per_phase_cents = Column(Integer, default=5000)   # $50 max per phase
    min_days_per_phase = Column(Integer, default=3)
    max_days_per_phase = Column(Integer, default=7)
    variations_per_phase = Column(Integer, default=5)

    # Source context
    source_url = Column(Text, nullable=True)
    source_campaign_id = Column(UUID(as_uuid=True), nullable=True)
    product_context = Column(JSON, nullable=True)

    # Current phase tracking
    current_phase_number = Column(Integer, default=0)

    # Progressive winners (accumulated as phases complete)
    winning_headline = Column(Text, nullable=True)
    winning_image_url = Column(Text, nullable=True)
    winning_audience = Column(JSON, nullable=True)
    winning_offer = Column(Text, nullable=True)

    # Structured learning data
    learnings = Column(JSON, nullable=True)

    # Meta campaign ID for the live ads
    meta_campaign_id = Column(String(255), nullable=True)

    # Destination URL for ads
    destination_url = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    phases = relationship(
        "MicroStrategyPhase",
        back_populates="strategy",
        cascade="all, delete-orphan",
        order_by="MicroStrategyPhase.phase_number",
    )
    pixel_trackers = relationship(
        "PixelReadinessTracker",
        back_populates="micro_strategy",
        cascade="all, delete-orphan",
    )


class MicroStrategyPhase(Base):
    """One phase of the micro-strategy (e.g., headline testing)."""
    __tablename__ = "micro_strategy_phases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("micro_strategies.id", ondelete="CASCADE"), nullable=False)

    phase_number = Column(Integer, nullable=False)
    phase_type = Column(String(50), nullable=False)
    status = Column(String(50), default=PhaseStatus.PENDING.value)

    # Budget tracking
    budget_per_variation_cents = Column(Integer, nullable=True)
    total_spend_cents = Column(Integer, default=0)

    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Winner
    winner_variation_id = Column(UUID(as_uuid=True), nullable=True)
    winner_value = Column(Text, nullable=True)
    winner_metadata = Column(JSON, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    strategy = relationship("MicroStrategy", back_populates="phases")
    variations = relationship(
        "PhaseVariation",
        back_populates="phase",
        cascade="all, delete-orphan",
        order_by="PhaseVariation.variation_number",
    )


class PhaseVariation(Base):
    """One variation within a phase (e.g., Headline V1)."""
    __tablename__ = "phase_variations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    phase_id = Column(UUID(as_uuid=True), ForeignKey("micro_strategy_phases.id", ondelete="CASCADE"), nullable=False)

    variation_number = Column(Integer, nullable=False)
    variation_name = Column(String(255), nullable=False)

    # The variable being tested
    variable_type = Column(String(50), nullable=False)
    variable_value = Column(Text, nullable=False)
    variable_metadata = Column(JSON, nullable=True)

    # Meta entity references
    meta_adset_id = Column(String(255), nullable=True)
    meta_ad_id = Column(String(255), nullable=True)
    meta_creative_id = Column(String(255), nullable=True)

    # Performance metrics (synced from Meta Insights)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend_cents = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    cpa = Column(Float, default=0.0)
    roas = Column(Float, default=0.0)

    # Status
    is_winner = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    phase = relationship("MicroStrategyPhase", back_populates="variations")


class PixelReadinessTracker(Base):
    """Tracks pixel maturity and auto-switch from Traffic to Lead Gen."""
    __tablename__ = "pixel_readiness_trackers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    micro_strategy_id = Column(
        UUID(as_uuid=True),
        ForeignKey("micro_strategies.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Pixel info
    pixel_id = Column(String(255), nullable=False)
    pixel_name = Column(String(255), nullable=True)

    # Current state
    current_objective = Column(String(50), default="OUTCOME_TRAFFIC")
    switch_status = Column(String(50), default=SwitchStatus.TRAFFIC_PHASE.value)

    # Traffic campaign reference
    traffic_campaign_id = Column(String(255), nullable=True)

    # Lead gen campaign reference (created after switch)
    leadgen_campaign_id = Column(String(255), nullable=True)

    # Pixel event counts (synced periodically)
    page_view_count = Column(Integer, default=0)
    view_content_count = Column(Integer, default=0)
    lead_count = Column(Integer, default=0)
    add_to_cart_count = Column(Integer, default=0)
    purchase_count = Column(Integer, default=0)
    total_optimization_events = Column(Integer, default=0)

    # Switch thresholds (configurable)
    required_events = Column(Integer, default=50)
    required_days = Column(Integer, default=7)
    event_window_days = Column(Integer, default=7)

    # Timing
    traffic_started_at = Column(DateTime, nullable=True)
    switch_triggered_at = Column(DateTime, nullable=True)
    leadgen_started_at = Column(DateTime, nullable=True)

    # Audience data snapshot at switch time
    audience_snapshot = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    micro_strategy = relationship("MicroStrategy", back_populates="pixel_trackers")

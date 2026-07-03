# models.py - Marketing Agents Module

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Float, ForeignKey, UUID, Boolean
from sqlalchemy.orm import relationship
from db_compat import Vector
from datetime import datetime
import uuid
from database import Base


class Campaign(Base):
    """Marketing campaign for ad management"""
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True)
    name = Column(String(255), index=True, nullable=False)
    objective = Column(String(50), nullable=False)  # AWARENESS, TRAFFIC, CONVERSIONS, etc.
    product_description = Column(Text, nullable=True)
    keywords = Column(JSON, nullable=True)  # List of keywords
    target_audience = Column(JSON, nullable=True)  # Audience targeting config
    status = Column(String(50), default="draft")  # draft, active, paused, completed
    budget = Column(Integer, default=0)  # Budget in cents
    meta_campaign_id = Column(String(255), nullable=True)  # Meta Ads campaign ID

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    market_research = relationship("MarketResearch", back_populates="campaign", cascade="all, delete-orphan")
    creative_angles = relationship("CreativeAngle", back_populates="campaign", cascade="all, delete-orphan")
    ad_copies = relationship("AdCopy", back_populates="campaign", cascade="all, delete-orphan")
    performance_metrics = relationship("PerformanceMetrics", back_populates="campaign", cascade="all, delete-orphan")


class MarketResearch(Base):
    """AI-generated market research for campaigns"""
    __tablename__ = "market_research"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True)

    competitor_analysis = Column(Text, nullable=True)
    audience_insights = Column(Text, nullable=True)
    trend_data = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)  # Full AI response for reference

    embedding = Column(Vector(1536), nullable=True)  # OpenAI embedding dimension

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    campaign = relationship("Campaign", back_populates="market_research")


class CreativeAngle(Base):
    """AI-generated creative angles for ad campaigns"""
    __tablename__ = "creative_angles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True)

    angle_name = Column(String(255), nullable=False)
    value_proposition = Column(Text, nullable=True)
    emotion_target = Column(String(100), nullable=True)
    visual_direction = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)

    embedding = Column(Vector(1536), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    campaign = relationship("Campaign", back_populates="creative_angles")
    ad_copies = relationship("AdCopy", back_populates="creative_angle", cascade="all, delete-orphan")


class AdCopy(Base):
    """AI-generated ad copy variations"""
    __tablename__ = "ad_copies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True)
    angle_id = Column(UUID(as_uuid=True), ForeignKey("creative_angles.id"), nullable=True, index=True)

    headline = Column(String(255), nullable=False)
    primary_text = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    call_to_action = Column(String(50), nullable=True)
    variations = Column(JSON, nullable=True)  # List of alternative copy variations

    is_active = Column(Boolean, default=True)
    meta_ad_id = Column(String(255), nullable=True)  # Meta Ads ad ID

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    campaign = relationship("Campaign", back_populates="ad_copies")
    creative_angle = relationship("CreativeAngle", back_populates="ad_copies")
    performance_metrics = relationship("PerformanceMetrics", back_populates="ad_copy", cascade="all, delete-orphan")


class PerformanceMetrics(Base):
    """Performance tracking for ads"""
    __tablename__ = "performance_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True)
    ad_id = Column(UUID(as_uuid=True), ForeignKey("ad_copies.id"), nullable=True, index=True)

    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    spend = Column(Integer, default=0)  # Spend in cents

    ctr = Column(Float, default=0.0)  # Click-through rate as percentage
    cpc = Column(Float, default=0.0)  # Cost per click
    cpa = Column(Float, default=0.0)  # Cost per acquisition
    roas = Column(Float, default=0.0)  # Return on ad spend

    collected_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    campaign = relationship("Campaign", back_populates="performance_metrics")
    ad_copy = relationship("AdCopy", back_populates="performance_metrics")


class RuleExecutionLog(Base):
    """Persistent log of every automated rule evaluation and action"""
    __tablename__ = "rule_execution_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(String(255), nullable=False, index=True)
    rule_id = Column(String(255), nullable=False, index=True)
    rule_name = Column(String(255), nullable=False)
    entity_id = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)  # campaign, adset, ad
    action_taken = Column(String(50), nullable=False)  # scale_up, scale_down, pause, etc.
    old_value = Column(Float, nullable=True)  # Budget before change
    new_value = Column(Float, nullable=True)  # Budget after change
    success = Column(Boolean, default=False)
    message = Column(Text, nullable=True)

    # Simulation mode
    is_simulation = Column(Boolean, default=False)

    # Rollback mechanism
    rollback_eligible = Column(Boolean, default=False)
    rollback_checked = Column(Boolean, default=False)
    rollback_executed = Column(Boolean, default=False)
    rollback_check_at = Column(DateTime, nullable=True)  # When to check for rollback
    performance_at_action = Column(JSON, nullable=True)  # Snapshot of metrics at time of action

    executed_at = Column(DateTime, default=datetime.utcnow, index=True)


class OptimizationDecisionLog(Base):
    """Log of every MonitorOptimizer AI analysis"""
    __tablename__ = "optimization_decision_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    raw_analysis = Column(Text, nullable=True)
    recommendations = Column(JSON, nullable=True)  # Parsed recommendations list
    health_score = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)

    parse_method = Column(String(20), nullable=True)  # "json" or "string_fallback"
    model_used = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CircuitBreakerState(Base):
    """Persisted circuit breaker state per ad account"""
    __tablename__ = "circuit_breaker_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(String(255), nullable=False, unique=True, index=True)

    is_tripped = Column(Boolean, default=False)
    trip_reason = Column(String(255), nullable=True)
    tripped_at = Column(DateTime, nullable=True)
    auto_reset_at = Column(DateTime, nullable=True)  # Optional auto-reset time

    daily_spend_cap = Column(Float, default=10000.0)  # Configurable max daily spend
    volatility_threshold_pct = Column(Float, default=50.0)  # Max % change before blocking
    data_freshness_hours = Column(Integer, default=6)  # Max hours since last sync

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProposedRule(Base):
    """LLM-proposed optimization rules awaiting human approval"""
    __tablename__ = "proposed_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(String(255), nullable=True, index=True)
    campaign_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    source_decision_log_id = Column(UUID(as_uuid=True), ForeignKey("optimization_decision_logs.id"), nullable=True)

    name = Column(String(255), nullable=False)
    conditions = Column(JSON, nullable=False)  # Serialized condition list
    action_type = Column(String(50), nullable=False)
    adjustment_percent = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)

    status = Column(String(20), default="pending")  # pending, accepted, rejected
    accepted_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CreativeTest(Base):
    """Tracks a multi-variant creative test within an ad set"""
    __tablename__ = "creative_tests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(String(255), nullable=False, index=True)
    adset_id = Column(String(255), nullable=False, index=True)
    campaign_id = Column(String(255), nullable=True)
    original_ad_id = Column(String(255), nullable=False)  # Baseline ad

    status = Column(String(20), default="running")  # running, completed, failed
    num_variants = Column(Integer, default=4)
    min_impressions_per_variant = Column(Integer, default=500)
    prune_threshold = Column(Float, default=0.8)  # 80% of best CTR

    winner_ad_id = Column(String(255), nullable=True)
    results = Column(JSON, nullable=True)  # Summary of test outcomes

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)

    variants = relationship("CreativeTestVariant", back_populates="test", cascade="all, delete-orphan")


class CreativeTestVariant(Base):
    """Individual variant in a creative test"""
    __tablename__ = "creative_test_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    test_id = Column(UUID(as_uuid=True), ForeignKey("creative_tests.id"), nullable=False, index=True)
    ad_id = Column(String(255), nullable=False, index=True)  # Meta ad ID
    variant_number = Column(Integer, nullable=False)

    headline = Column(String(255), nullable=True)
    primary_text = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    is_original = Column(Boolean, default=False)  # Marks the baseline ad

    status = Column(String(20), default="active")  # active, paused, winner
    final_impressions = Column(Integer, nullable=True)
    final_ctr = Column(Float, nullable=True)
    final_cpc = Column(Float, nullable=True)
    final_conversions = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    test = relationship("CreativeTest", back_populates="variants")


class MarketingEvent(Base):
    """User-configured marketing events for a store"""
    __tablename__ = "marketing_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    event_type = Column(String(50), default="custom")  # sale, launch, seasonal, holiday, custom
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    budget_multiplier = Column(Float, default=1.0)  # e.g., 1.3 = suggest +30% budget
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoreCalendarOverride(Base):
    """Per-store overrides for built-in retail calendar events"""
    __tablename__ = "store_calendar_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    event_key = Column(String(100), nullable=False, index=True)  # e.g. "black_friday"

    is_enabled = Column(Boolean, default=True)  # Toggle event on/off
    custom_name = Column(String(255), nullable=True)  # Override name
    custom_start_month = Column(Integer, nullable=True)  # Override start month
    custom_start_day = Column(Integer, nullable=True)  # Override start day
    custom_duration_days = Column(Integer, nullable=True)  # Override duration
    custom_budget_multiplier = Column(Float, nullable=True)  # Override budget impact
    custom_impact = Column(String(20), nullable=True)  # Override impact level

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIDecisionLog(Base):
    """Comprehensive audit trail of every AI decision for fine-tuning"""
    __tablename__ = "ai_decision_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(String(255), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    decision_type = Column(String(50), nullable=False, index=True)
    # rule_proposal, rule_execution, creative_refresh, performance_analysis,
    # backtest, threshold_tune, rule_retire, rule_auto_accept
    agent_name = Column(String(50), nullable=False, index=True)
    # monitor_optimizer, rule_proposer, meta_learner, creative_agent, rules_engine

    # What the AI saw
    input_context = Column(JSON, nullable=True)

    # What the AI decided
    decision = Column(JSON, nullable=True)
    reasoning = Column(Text, nullable=True)

    # What happened after
    outcome_measured = Column(Boolean, default=False, index=True)
    outcome_data = Column(JSON, nullable=True)
    outcome_score = Column(Float, nullable=True)  # -1 to 1

    # Meta
    confidence = Column(Float, nullable=True)  # 0 to 1
    data_maturity_level = Column(String(20), nullable=True)
    model_used = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    outcome_measured_at = Column(DateTime, nullable=True)


class BacktestResult(Base):
    """Results of backtesting a rule against historical data"""
    __tablename__ = "backtest_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    rule_id = Column(String(255), nullable=False, index=True)
    ad_account_id = Column(String(255), nullable=True)
    entity_id = Column(String(255), nullable=True)

    days_tested = Column(Integer, nullable=False)
    total_triggers = Column(Integer, default=0)

    good_outcomes = Column(Integer, default=0)
    bad_outcomes = Column(Integer, default=0)
    neutral_outcomes = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    avg_roas_change = Column(Float, nullable=True)
    avg_cpa_change = Column(Float, nullable=True)

    verdict = Column(String(20), nullable=False)  # accepted, tightened, rejected
    adjusted_conditions = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SchedulerTierState(Base):
    """Persists last-run time of scheduler tiers so daily/weekly tasks
    survive restarts and frequent deploys (run-count gating reset on boot)."""
    __tablename__ = "scheduler_tier_state"

    tier_name = Column(String(50), primary_key=True)
    last_run_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RulePerformanceTracker(Base):
    """Tracks lifetime performance of each rule for auto-tuning and retirement"""
    __tablename__ = "rule_performance_trackers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    rule_id = Column(String(255), nullable=False, unique=True, index=True)
    rule_name = Column(String(255), nullable=False)

    total_triggers = Column(Integer, default=0)
    good_outcomes = Column(Integer, default=0)
    bad_outcomes = Column(Integer, default=0)
    neutral_outcomes = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    avg_roas_impact = Column(Float, nullable=True)
    avg_cpa_impact = Column(Float, nullable=True)

    times_tightened = Column(Integer, default=0)
    times_loosened = Column(Integer, default=0)
    original_conditions = Column(JSON, nullable=True)
    current_conditions = Column(JSON, nullable=True)

    auto_disabled = Column(Boolean, default=False)
    disabled_reason = Column(String(255), nullable=True)
    last_triggered_at = Column(DateTime, nullable=True)
    last_evaluated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

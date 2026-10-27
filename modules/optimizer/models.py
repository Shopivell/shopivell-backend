from sqlalchemy import Column, String, Float, Boolean, Text, Date, DateTime, JSON, UUID, Index, UniqueConstraint
from datetime import datetime
import uuid
from database import Base


class OptimizerConfig(Base):
    """Per-store ad-optimizer settings: targets, rule overrides, and the dry-run switch.

    Nothing changes on Meta unless dry_run is False here AND OPTIMIZER_DRY_RUN=false
    AND store.ads_enabled — the safe default is to only log decisions.
    """
    __tablename__ = "ad_optimizer_configs"

    store_id = Column(UUID(as_uuid=True), primary_key=True)
    dry_run = Column(Boolean, nullable=False, default=True)
    target_roas = Column(Float, nullable=True)
    target_cpa = Column(Float, nullable=True)
    rules = Column(JSON, nullable=True)  # {"scale_winner": {...overrides}, ...}
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Model-driven target calibration (opt-in). When True, target_roas/target_cpa above
    # are periodically re-proposed by a model grounded in this store's real niche and
    # performance, instead of staying whatever was last typed in manually.
    auto_calibrate = Column(Boolean, nullable=False, default=False)
    last_calibrated_at = Column(DateTime, nullable=True)
    calibration_reasoning = Column(Text, nullable=True)


class OptimizerDecision(Base):
    """One rule firing for one ad set: dry_run (logged only), applied, or failed."""
    __tablename__ = "ad_optimizer_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(String(64), nullable=True)
    campaign_name = Column(String(255), nullable=True)
    ad_set_id = Column(String(64), nullable=False)
    ad_set_name = Column(String(255), nullable=True)
    rule = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)  # budget_increase | budget_decrease | pause
    status = Column(String(20), nullable=False)  # dry_run | applied | failed
    metrics = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Cooldown lookup: latest decision per (ad set, rule).
    __table_args__ = (
        Index("ix_ad_optimizer_decisions_cooldown", "ad_set_id", "rule", "created_at"),
    )


class OptimizerSnapshot(Base):
    """Last-7-day metrics per ad set, one row per day — the history multi-day rules need."""
    __tablename__ = "ad_optimizer_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id = Column(String(64), nullable=True)
    ad_set_id = Column(String(64), nullable=False)
    active = Column(Boolean, nullable=False, default=False)
    day = Column(Date, nullable=False)
    metrics = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ad_set_id", "day", name="uq_ad_optimizer_snapshots_day"),
    )

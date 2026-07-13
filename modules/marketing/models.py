# modules/marketing/models.py
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, UUID, Integer, JSON, Float
from db_compat import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from database import Base
from utils.crypto import EncryptedString

class MetaAdAccount(Base):
    __tablename__ = "meta_ad_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_account_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta Ad Account ID
    account_name = Column(String(255), nullable=False)
    account_status = Column(Integer, nullable=False)  # 1=ACTIVE, 2=DISABLED, etc.
    currency = Column(String(10), nullable=False)
    timezone_name = Column(String(100), nullable=False)
    business_id = Column(String(255), nullable=True)  # Associated business ID
    business_name = Column(String(255), nullable=True)
    
    # Access and permissions
    access_token = Column(EncryptedString, nullable=False)  # encrypted at rest
    user_id = Column(String(255), nullable=False)  # Meta user ID
    expires_at = Column(DateTime, nullable=True)

    # Ownership (client-owned model): which Shopivell account/store this ad account
    # belongs to. Set at connect time so every ad write acts on the right client's
    # own account, never a shared one (Meta requires one advertiser per ad account).
    shopivell_user_id = Column(String(255), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)

    # Relationships
    business_account_id = Column(UUID(as_uuid=True), ForeignKey("facebook_business_accounts.id"), nullable=True)
    business_account = relationship("FacebookBusinessAccount", backref="ad_accounts")
    
    # Status tracking
    is_connected = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    # Autopilot master switch. When False (default), automated rules run in
    # advise-only/dry-run mode: the engine evaluates and logs what it WOULD do
    # but makes no spend-affecting Meta changes. Must be explicitly enabled for
    # live autonomous execution (pausing ads, changing budgets).
    autopilot_enabled = Column(Boolean, default=False, nullable=False)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    campaigns = relationship("MetaCampaign", back_populates="ad_account", cascade="all, delete-orphan")
    ad_sets = relationship("MetaAdSet", back_populates="ad_account", cascade="all, delete-orphan")
    ads = relationship("MetaAd", back_populates="ad_account", cascade="all, delete-orphan")
    ad_creatives = relationship("MetaAdCreative", back_populates="ad_account", cascade="all, delete-orphan")
    automated_rules = relationship("MetaAutomatedRule", back_populates="ad_account", cascade="all, delete-orphan")
    experiments = relationship("MetaExperiment", back_populates="ad_account", cascade="all, delete-orphan")

class MetaCampaign(Base):
    __tablename__ = "meta_campaigns"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    campaign_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta Campaign ID
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    
    # Basic info
    name = Column(String(255), nullable=False)
    objective = Column(String(100), nullable=False)  # LINK_CLICKS, CONVERSIONS, etc.
    status = Column(String(50), nullable=False)  # ACTIVE, PAUSED, DELETED, etc.
    
    # Campaign settings
    special_ad_categories = Column(JSON, nullable=True)  # Array of special ad categories
    buying_type = Column(String(50), default="AUCTION")  # AUCTION or RESERVED
    
    # Budget and schedule
    daily_budget = Column(Integer, nullable=True)  # In cents
    lifetime_budget = Column(Integer, nullable=True)  # In cents
    start_time = Column(DateTime, nullable=True)
    stop_time = Column(DateTime, nullable=True)
    
    # Optimization
    bid_strategy = Column(String(100), nullable=True)  # LOWEST_COST_WITHOUT_CAP, etc.

    # Draft support fields
    is_draft = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    draft_data = Column(JSON, nullable=True)  # Store original request data for drafts
    published_at = Column(DateTime, nullable=True)  # When draft was published

    # Metadata
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    effective_status = Column(String(50), nullable=True)

    # Sync info
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ad_account = relationship("MetaAdAccount", back_populates="campaigns")
    ad_sets = relationship("MetaAdSet", back_populates="campaign", cascade="all, delete-orphan")
    ads = relationship("MetaAd", back_populates="campaign", cascade="all, delete-orphan")

class MetaAdSet(Base):
    __tablename__ = "meta_ad_sets"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    adset_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta AdSet ID
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("meta_campaigns.id"), nullable=False)
    
    # Basic info
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)  # ACTIVE, PAUSED, etc.
    
    # Targeting
    targeting = Column(JSON, nullable=True)  # Detailed targeting spec
    optimization_goal = Column(String(100), nullable=False)  # LINK_CLICKS, CONVERSIONS, etc.
    billing_event = Column(String(100), nullable=False)  # IMPRESSIONS, LINK_CLICKS
    
    # Budget and bids
    daily_budget = Column(Integer, nullable=True)
    lifetime_budget = Column(Integer, nullable=True)
    bid_amount = Column(Integer, nullable=True)
    bid_strategy = Column(String(100), nullable=True)
    
    # Schedule
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    
    # Placement
    placement = Column(JSON, nullable=True)
    publisher_platforms = Column(JSON, nullable=True)

    # Draft support fields
    is_draft = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    draft_data = Column(JSON, nullable=True)  # Store original request data for drafts
    published_at = Column(DateTime, nullable=True)  # When draft was published

    # Metadata
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    effective_status = Column(String(50), nullable=True)

    # Sync info
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ad_account = relationship("MetaAdAccount", back_populates="ad_sets")
    campaign = relationship("MetaCampaign", back_populates="ad_sets")
    ads = relationship("MetaAd", back_populates="ad_set", cascade="all, delete-orphan")

class MetaAd(Base):
    __tablename__ = "meta_ads"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta Ad ID
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("meta_campaigns.id"), nullable=False)
    adset_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_sets.id"), nullable=False)
    creative_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_creatives.id"), nullable=True)
    
    # Basic info
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)  # ACTIVE, PAUSED, etc.
    
    # Ad content
    ad_format = Column(String(100), nullable=True)  # IMAGE, VIDEO, CAROUSEL, etc.
    
    # Tracking
    tracking_specs = Column(JSON, nullable=True)
    
    # Draft support fields - ADD THESE
    is_draft = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    draft_data = Column(JSON, nullable=True)  # Store original request data
    published_at = Column(DateTime, nullable=True)  # When draft was published
    
    # Metadata
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    effective_status = Column(String(50), nullable=True)
    
    # Sync info
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    ad_account = relationship("MetaAdAccount", back_populates="ads")
    campaign = relationship("MetaCampaign", back_populates="ads")
    ad_set = relationship("MetaAdSet", back_populates="ads")
    creative = relationship("MetaAdCreative", back_populates="ads")
    insights = relationship("MetaAdInsight", back_populates="ad", cascade="all, delete-orphan")

class MetaAdCreative(Base):
    __tablename__ = "meta_ad_creatives"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    creative_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta Creative ID
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    
    # Creative type
    creative_type = Column(String(50), nullable=False)  # IMAGE, VIDEO, CAROUSEL, etc.
    
    # Content
    object_story_spec = Column(JSON, nullable=True)  # For Page posts
    object_type = Column(String(50), nullable=True)  # PAGE, DOMAIN, etc.
    link_data = Column(JSON, nullable=True)  # For link ads
    image_data = Column(JSON, nullable=True)  # For image ads
    video_data = Column(JSON, nullable=True)  # For video ads
    
    # Creative details
    title = Column(String(255), nullable=True)
    body = Column(Text, nullable=True)
    call_to_action_type = Column(String(100), nullable=True)
    image_url = Column(Text, nullable=True)
    image_hash = Column(String(255), nullable=True)
    video_url = Column(Text, nullable=True)
    video_id = Column(String(255), nullable=True)
    url = Column(Text, nullable=True)
    
    # Metadata
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    
    # Sync info
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    ad_account = relationship("MetaAdAccount", back_populates="ad_creatives")
    ads = relationship("MetaAd", back_populates="creative")

class MetaExperiment(Base):
    __tablename__ = "meta_experiments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    experiment_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta Experiment ID
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    
    # Basic info
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # A/B_TEST, SPLIT_TEST, etc.
    status = Column(String(50), nullable=False)  # DRAFT, RUNNING, COMPLETED
    
    # Experiment design
    control_id = Column(String(255), nullable=True)  # Control campaign/adset ID
    treatment_id = Column(String(255), nullable=True)  # Treatment campaign/adset ID
    
    # Settings
    confidence_level = Column(Float, default=0.95)  # 95% confidence level
    sample_size = Column(Integer, nullable=True)  # Desired sample size
    duration_days = Column(Integer, nullable=True)
    
    # Results
    winner = Column(String(50), nullable=True)  # CONTROL, TREATMENT, NO_WINNER
    confidence = Column(Float, nullable=True)  # Statistical confidence
    metric_results = Column(JSON, nullable=True)
    
    # Schedule
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    
    # Metadata
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    
    # Sync info
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    ad_account = relationship("MetaAdAccount", back_populates="experiments")

class MetaAutomatedRule(Base):
    __tablename__ = "meta_automated_rules"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    rule_id = Column(String(255), unique=True, index=True, nullable=False)  # Meta Rule ID
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id"), nullable=False)
    
    # Rule details
    name = Column(String(255), nullable=False)
    entity_type = Column(String(50), nullable=False)  # CAMPAIGN, ADSET, AD
    status = Column(String(50), nullable=False)  # ENABLED, DISABLED
    
    # Conditions and actions
    conditions = Column(JSON, nullable=False)  # Array of condition objects
    action = Column(JSON, nullable=False)  # Action object
    
    # Schedule
    schedule_type = Column(String(50), nullable=False)  # DAILY, CUSTOM
    schedule_spec = Column(JSON, nullable=True)
    
    # Stats
    execution_count = Column(Integer, default=0)
    last_execution_time = Column(DateTime, nullable=True)
    last_execution_result = Column(JSON, nullable=True)
    
    # Metadata
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    
    # Sync info
    last_synced_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    ad_account = relationship("MetaAdAccount", back_populates="automated_rules")

class MetaAdInsight(Base):
    __tablename__ = "meta_ad_insights"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ad_id = Column(UUID(as_uuid=True), ForeignKey("meta_ads.id"), nullable=False)
    date = Column(DateTime, nullable=False)
    
    # Metrics
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    cpm = Column(Float, default=0.0)  # Cost per 1000 impressions
    cpc = Column(Float, default=0.0)  # Cost per click
    ctr = Column(Float, default=0.0)  # Click-through rate
    frequency = Column(Float, default=0.0)  # Average impressions per user
    reach = Column(Integer, default=0)
    
    # Conversion metrics
    conversions = Column(Integer, default=0)
    cost_per_conversion = Column(Float, default=0.0)
    conversion_rate = Column(Float, default=0.0)
    revenue = Column(Float, default=0.0)  # Purchase conversion value (for ROAS)
    
    # Engagement metrics
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    
    # Raw data
    raw_data = Column(JSON, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    ad = relationship("MetaAd", back_populates="insights")
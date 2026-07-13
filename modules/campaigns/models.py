# modules/campaigns/models.py
from sqlalchemy import Column, String, Text, Float, Integer, Boolean, DateTime, ForeignKey, Enum as SQLAlchemyEnum, JSON
from db_compat import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from database import Base

# Note: Store and Asset models are imported in main.py before this module
# to ensure SQLAlchemy can resolve the relationships properly


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class CampaignGoal(str, enum.Enum):
    TRAFFIC = "traffic"
    LEADS = "leads"
    SALES = "sales"
    AWARENESS = "awareness"
    ENGAGEMENT = "engagement"


class UrlCampaign(Base):
    """URL-based marketing campaigns with scraping and ad generation"""
    __tablename__ = "url_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)

    # Basic Info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Source
    source_url = Column(String(512), nullable=True)
    source_type = Column(String(50), default="url")  # url, store, manual

    # Scraped Data
    scraped_data = Column(JSON, nullable=True)  # Stores Tavily results
    scraped_at = Column(DateTime, nullable=True)

    # Campaign Settings
    goal = Column(SQLAlchemyEnum(CampaignGoal), default=CampaignGoal.SALES)
    conversion_button = Column(String(100), default="Learn More")
    daily_budget = Column(Float, default=100.0)
    total_budget = Column(Float, nullable=True)

    # Schedule
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    # Targeting
    countries = Column(JSON, default=list)  # List of country codes
    cities = Column(JSON, default=list)
    age_range = Column(JSON, default={"min": 18, "max": 65})
    gender = Column(String(20), default="all")
    interests = Column(JSON, default=list)

    # Generated Content
    generated_headlines = Column(JSON, default=list)
    generated_descriptions = Column(JSON, default=list)

    # Goal-specific
    sales_type = Column(String(20), nullable=True)  # product or service
    destination_url = Column(String(512), nullable=True)  # Sales: storefront link, Traffic: custom URL
    lead_form_fields = Column(JSON, nullable=True)  # Leads: [{label, type, required}]

    # Status
    status = Column(SQLAlchemyEnum(CampaignStatus), default=CampaignStatus.DRAFT)
    error_message = Column(Text, nullable=True)

    # Platform Settings
    platforms = Column(JSON, default=["facebook"])  # facebook, instagram, google
    platform_campaign_ids = Column(JSON, default=dict)  # Store external platform IDs

    # Meta Special Ad Category. Must be declared correctly for ads about housing,
    # employment, credit/financial services, social issues, or gambling — declaring
    # NONE for those is a policy violation. Defaults to NONE (regular products).
    special_ad_category = Column(String(50), default="NONE", nullable=False)

    # Fatigue auto-refresh safety gate. When False (default), fatigue-refreshed
    # replacement ads are created PAUSED so a human approves them before they spend.
    # When True, replacements go live ACTIVE automatically.
    auto_publish_refresh = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    # Relationships
    store = relationship("Store", back_populates="url_campaigns")
    ad_sets = relationship("UrlAdSet", back_populates="campaign", cascade="all, delete-orphan")


class UrlAdSet(Base):
    """Ad sets for URL-based campaigns"""
    __tablename__ = "url_ad_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("url_campaigns.id", ondelete="CASCADE"), nullable=False)

    # Basic Info
    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)

    # Targeting (can override campaign settings)
    age_range = Column(JSON, nullable=True)
    gender = Column(String(20), nullable=True)
    audience_tags = Column(JSON, default=list)  # Interest/behavior tags
    hashtags = Column(JSON, default=list)  # Social media hashtags

    # Budget
    daily_budget = Column(Float, nullable=True)
    total_spent = Column(Float, default=0.0)

    # Status
    is_selected = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    campaign = relationship("UrlCampaign", back_populates="ad_sets")
    ad_contents = relationship("UrlAdContent", back_populates="ad_set", cascade="all, delete-orphan")


class UrlAdContent(Base):
    """Ad content for URL-based campaigns"""
    __tablename__ = "url_ad_contents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ad_set_id = Column(UUID(as_uuid=True), ForeignKey("url_ad_sets.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)

    # Content
    headline = Column(String(255), nullable=True)
    primary_text = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    call_to_action = Column(String(100), nullable=True)
    destination_url = Column(String(512), nullable=True)

    # Media (can link to asset or store URL directly)
    media_url = Column(String(512), nullable=True)
    media_type = Column(String(50), default="image")  # image, video, carousel
    generated_image_base64 = Column(Text, nullable=True)  # Base64 encoded generated image

    # A/B Variation tracking
    meta_ad_id = Column(String(255), nullable=True)  # Meta platform ad ID for insights
    variation_label = Column(String(100), nullable=True)  # e.g. "Copy-A_Image-1"
    copy_variation_index = Column(Integer, default=0)
    image_variation_index = Column(Integer, default=0)

    # Fatigue tracking
    fatigue_score = Column(Float, default=0.0)  # 0-100, >60 = fatigued
    last_refreshed_at = Column(DateTime, nullable=True)
    parent_content_id = Column(UUID(as_uuid=True), ForeignKey("url_ad_contents.id", ondelete="SET NULL"), nullable=True)

    # Status
    is_primary = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ad_set = relationship("UrlAdSet", back_populates="ad_contents")
    asset = relationship("Asset", back_populates="url_ad_contents")
    parent_content = relationship("UrlAdContent", remote_side=[id], foreign_keys=[parent_content_id])
    metrics = relationship("AdContentMetrics", back_populates="ad_content", cascade="all, delete-orphan")


class AdContentMetrics(Base):
    """Daily performance metrics for ad content variants, synced from Meta Insights"""
    __tablename__ = "ad_content_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ad_content_id = Column(UUID(as_uuid=True), ForeignKey("url_ad_contents.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("url_campaigns.id", ondelete="CASCADE"), nullable=False)

    # Core metrics
    impressions = Column(Integer, default=0)
    reach = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    spend = Column(Float, default=0.0)

    # Calculated metrics
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    cpm = Column(Float, default=0.0)
    frequency = Column(Float, default=0.0)
    roas = Column(Float, default=0.0)

    # Time window
    date = Column(DateTime, nullable=False)
    collected_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    ad_content = relationship("UrlAdContent", back_populates="metrics")
    campaign = relationship("UrlCampaign")

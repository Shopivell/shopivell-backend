# models.py - Marketing Agents Module

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Float, ForeignKey, UUID, Boolean
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
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

from typing import Optional, List, Dict, Any
from sqlalchemy import String, Float, DateTime, Date, ForeignKey, Text, Integer, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, date
import uuid
from database import Base

class AnalyticsPlatform(Base):
    __tablename__ = "analytics_platforms"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # Google Analytics, Facebook, Instagram, etc.
    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)  # web_analytics, social_media, advertising, ecommerce
    api_config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)  # API configuration
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_sync: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default='inactive')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class PlatformData(Base):
    __tablename__ = "platform_data"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analytics_platforms.id"), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)  # sessions, pageviews, conversions, impressions, etc.
    data_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # Flexible metric storage
    dimensions: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)  # Flexible dimension storage
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    platform: Mapped["AnalyticsPlatform"] = relationship("AnalyticsPlatform")

class AnalyticsReport(Base):
    __tablename__ = "analytics_reports"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # Acquisition, Behavior, Conversions, etc.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default='Shopify')
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, default='standard')  # standard, custom, exploration
    data_source: Mapped[str] = mapped_column(String(50), nullable=False, default='internal')  # internal, google_analytics, facebook, etc.
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)  # Report configuration/filters
    last_viewed: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    has_info: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ReportView(Base):
    __tablename__ = "report_views"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analytics_reports.id"), nullable=False)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    viewed_by: Mapped[str] = mapped_column(String(100), nullable=True)
    
    # Relationship
    report: Mapped["AnalyticsReport"] = relationship("AnalyticsReport")

class DataSyncLog(Base):
    __tablename__ = "data_sync_logs"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analytics_platforms.id"), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)  # full, incremental, realtime
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success, failed, partial
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationship
    platform: Mapped["AnalyticsPlatform"] = relationship("AnalyticsPlatform")
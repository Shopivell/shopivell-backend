# modules/social/models.py
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SQLEnum, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base
import enum

class SocialPlatform(str, enum.Enum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    PINTEREST = "pinterest"

class SocialConnectionStatus(str, enum.Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"

class FacebookPageConnection(Base):
    __tablename__ = "facebook_page_connections"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shopivell_user_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    store_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)
    
    # Facebook Page Details
    facebook_page_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    facebook_page_name: Mapped[str] = mapped_column(String(255), nullable=False)
    facebook_page_token: Mapped[str] = mapped_column(Text, nullable=False)
    facebook_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Token Management
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_token_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Connection Status
    status: Mapped[SocialConnectionStatus] = mapped_column(SQLEnum(SocialConnectionStatus), default=SocialConnectionStatus.CONNECTED)
    
    # Permissions
    granted_permissions: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # String-based relationships
    user = relationship("User", back_populates="facebook_connections")
    store = relationship("Store", back_populates="facebook_connections")

class SocialPost(Base):
    __tablename__ = "social_posts"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shopivell_user_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    store_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)
    page_connection_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("facebook_page_connections.id"), nullable=False)
    
    # Post Content
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Facebook Post Reference
    facebook_post_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    
    # Scheduling
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Status
    status: Mapped[str] = mapped_column(String(50), default="draft")
    
    # Metadata
    platform: Mapped[SocialPlatform] = mapped_column(SQLEnum(SocialPlatform), default=SocialPlatform.FACEBOOK)
    insights: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # String-based relationships
    user = relationship("User", back_populates="social_posts")
    store = relationship("Store", back_populates="social_posts")
    page_connection = relationship("FacebookPageConnection")
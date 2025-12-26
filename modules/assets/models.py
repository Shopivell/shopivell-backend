# modules/assets/models.py
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, Enum as SQLAlchemyEnum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from database import Base


class AssetType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)

    # File Info
    name = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=True)
    file_type = Column(SQLAlchemyEnum(AssetType), default=AssetType.IMAGE)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)  # in bytes

    # Cloudinary Info
    cloudinary_public_id = Column(String(255), nullable=True)
    cloudinary_url = Column(String(512), nullable=True)
    cloudinary_secure_url = Column(String(512), nullable=True)
    thumbnail_url = Column(String(512), nullable=True)

    # Dimensions (for images/videos)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)  # for videos, in seconds

    # Content Info (for generated assets)
    headline = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    features = Column(JSON, default=list)
    call_to_action = Column(String(100), nullable=True)

    # Source
    source = Column(String(50), default="upload")  # upload, generated, scraped
    source_campaign_id = Column(UUID(as_uuid=True), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    is_generated = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", back_populates="assets")
    url_ad_contents = relationship("UrlAdContent", back_populates="asset")

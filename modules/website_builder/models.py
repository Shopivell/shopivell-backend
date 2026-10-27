# modules/website_builder/models.py
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Boolean, Enum as SQLEnum
from db_compat import UUID
from sqlalchemy import JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from database import Base


class WebsiteStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    DEPLOYED = "deployed"
    FAILED = "failed"


class GenerationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Website(Base):
    """Generated website for a store"""
    __tablename__ = 'websites'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey('stores.id'), nullable=False, index=True)

    # Basic info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Status
    status = Column(SQLEnum(WebsiteStatus), default=WebsiteStatus.DRAFT, nullable=False)

    # Generated content
    pages = Column(JSON, default=dict)  # {"homepage": "<html>...", "products": "<html>..."}
    theme = Column(JSON, default=dict)  # {"primary_color": "#...", "font": "..."}
    integrations = Column(JSON, default=dict)  # {"stripe": true, "analytics": false}

    # Full compiled website
    preview_html = Column(Text, nullable=True)  # Combined HTML for preview
    generated_code = Column(Text, nullable=True)  # Full exportable code

    # Deployment
    deployed_url = Column(String(500), nullable=True)
    custom_domain = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    generations = relationship("WebsiteGeneration", back_populates="website", cascade="all, delete-orphan")


class WebsiteGeneration(Base):
    """Tracks website generation jobs"""
    __tablename__ = 'website_generations'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    website_id = Column(UUID(as_uuid=True), ForeignKey('websites.id'), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey('stores.id'), nullable=False, index=True)

    # Generation request
    prompt = Column(Text, nullable=False)
    selected_screens = Column(JSON, default=list)  # ["homepage", "products", "contact"]

    # Status tracking
    status = Column(SQLEnum(GenerationStatus), default=GenerationStatus.PENDING, nullable=False)
    progress = Column(Float, default=0)  # 0-100
    current_step = Column(String(100), nullable=True)  # "Generating homepage..."
    error_message = Column(Text, nullable=True)

    # Results
    generated_pages = Column(JSON, default=dict)  # Pages generated in this job

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    website = relationship("Website", back_populates="generations")

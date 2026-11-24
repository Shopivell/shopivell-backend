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


class WebsiteTemplate(Base):
    """Immutable, admin-managed GrapesJS starter template."""
    __tablename__ = "website_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(160), nullable=False)
    slug = Column(String(180), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False, default="")
    category = Column(String(80), nullable=False, index=True)
    thumbnail_url = Column(String(1000), nullable=True)
    preview_url = Column(String(1000), nullable=True)
    is_published = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    pages = relationship("WebsiteTemplatePage", back_populates="template", cascade="all, delete-orphan", order_by="WebsiteTemplatePage.sort_order")


class WebsiteTemplatePage(Base):
    """A page in an immutable template. Its GrapesJS JSON is copied on project creation."""
    __tablename__ = "website_template_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("website_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    page_name = Column(String(120), nullable=False)
    route_path = Column(String(255), nullable=False)
    sort_order = Column(Float, nullable=False, default=0)
    grapesjs_project_json = Column(JSON, nullable=False, default=dict)
    template = relationship("WebsiteTemplate", back_populates="pages")


class WebsiteProjectPage(Base):
    """Project-owned editable page. Never references mutable template JSON for editing."""
    __tablename__ = "website_project_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    website_id = Column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    template_page_id = Column(UUID(as_uuid=True), ForeignKey("website_template_pages.id", ondelete="SET NULL"), nullable=True)
    page_name = Column(String(120), nullable=False)
    route_path = Column(String(255), nullable=False)
    sort_order = Column(Float, nullable=False, default=0)
    grapesjs_project_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebsiteProjectVersion(Base):
    """Named immutable snapshot created by manual saves and before publishing."""
    __tablename__ = "website_project_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    website_id = Column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Float, nullable=False)
    project_json = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(Text, nullable=True)


class WebsiteMediaAsset(Base):
    """Uploaded site media metadata; file storage remains replaceable."""
    __tablename__ = "website_media_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    website_id = Column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    storage_name = Column(String(255), nullable=False, unique=True)
    file_url = Column(String(1000), nullable=False)
    mime_type = Column(String(120), nullable=False)
    file_size = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WebsiteInboxMessage(Base):
    """Visitor messages collected by the embedded storefront assistant."""
    __tablename__ = "website_inbox_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    website_id = Column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(80), nullable=False, index=True)
    sender_name = Column(String(160), nullable=True)
    sender_email = Column(String(255), nullable=True)
    sender_type = Column(String(20), nullable=False, default="visitor")
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

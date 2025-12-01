# modules/stores/models.py
from typing import Optional, List, Dict, Any
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SQLEnum, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base
import enum

# NO import from users module!

# modules/stores/models.py
# modules/stores/models.py
class StoreSetupStep(str, enum.Enum):
    CREATE_STORE = "create_store"  # Add the new one
    BASIC_INFO = "basic_info"
    BUSINESS_TYPE = "business_type"
    DELIVERY_SETTINGS = "delivery_settings"
    PAYMENT_METHODS = "payment_methods"
    FEATURES = "features"
    GOALS = "goals"
    DOMAIN = "domain"
    WHATSAPP = "whatsapp"
    COMPLETED = "completed"

class Store(Base):
    __tablename__ = "stores"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    # Basic Info
    store_name: Mapped[str] = mapped_column(String(255), nullable=False)
    store_phone: Mapped[str] = mapped_column(String(50), nullable=False)
    store_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    color_theme: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Business Type
    business_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Delivery Settings
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pickup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dine_in_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_fee: Mapped[str] = mapped_column(String(50), default='0')
    free_delivery_minimum: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Domain & Features
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled_features: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    business_goals: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    payment_methods: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    
    # Setup Progress - UPDATED DEFAULT
    current_step: Mapped[StoreSetupStep] = mapped_column(SQLEnum(StoreSetupStep), default=StoreSetupStep.CREATE_STORE)
    is_setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships using string references
    owner = relationship("User", back_populates="stores")
    facebook_connections = relationship("FacebookPageConnection", back_populates="store", cascade="all, delete-orphan")
    social_posts = relationship("SocialPost", back_populates="store", cascade="all, delete-orphan")

# modules/stores/models.py - FIX THIS LINE
class StoreSetupSession(Base):
    __tablename__ = "store_setup_sessions"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # FIXED: Remove nullable=False and add default=dict
    session_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # UPDATED: Remove nullable=False and add default
    current_step: Mapped[StoreSetupStep] = mapped_column(SQLEnum(StoreSetupStep), default=StoreSetupStep.CREATE_STORE)
    completed_steps: Mapped[List[str]] = mapped_column(JSON, default=list)
    setup_progress: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    user = relationship("User", back_populates="setup_sessions")
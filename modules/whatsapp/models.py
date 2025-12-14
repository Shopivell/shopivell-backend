# models.py

from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, UUID, JSON
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from database import Base

class WhatsAppAccount(Base):
    __tablename__ = "whatsapp_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    business_account_id = Column(UUID(as_uuid=True), ForeignKey("facebook_business_accounts.id"), nullable=False)
    waba_id = Column(String(255), unique=True, index=True, nullable=False)
    phone_number_id = Column(String(255), unique=True, index=True, nullable=False)
    phone_number = Column(String(50), nullable=False)
    display_name = Column(String(255), nullable=True)
    verified_name = Column(String(255), nullable=True)
    quality_rating = Column(String(50), nullable=True)
    is_enabled = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    webhook_url = Column(Text, nullable=True)
    webhook_verify_token = Column(String(255), nullable=True)
    permanent_access_token = Column(Text, nullable=True)
    
    # --- NEW FIELDS FOR CONVERSIONS API ---
    capi_dataset_id = Column(String(50), nullable=True, comment="Meta Conversions API Dataset ID (Pixel ID)")
    capi_access_token = Column(Text, nullable=True, comment="Meta CAPI Access Token - STORE ENCRYPTED IN PRODUCTION")
    # --- END NEW FIELDS ---
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    business_account = relationship("FacebookBusinessAccount", back_populates="whatsapp_accounts")
    messages = relationship("WhatsAppMessage", back_populates="whatsapp_account", cascade="all, delete-orphan")

class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    whatsapp_account_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_accounts.id"), nullable=False)
    message_id = Column(String(255), nullable=False, index=True)
    wamid = Column(String(500), nullable=True)
    from_number = Column(String(50), nullable=False)
    to_number = Column(String(50), nullable=False)
    message_type = Column(String(50), nullable=False)
    direction = Column(String(10), nullable=False)
    status = Column(String(50), nullable=False, default="sent")
    template_name = Column(String(255), nullable=True)
    message_text = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)
    media_id = Column(String(500), nullable=True)
    
    meta_data = Column(JSON, nullable=True) 
    
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    whatsapp_account = relationship("WhatsAppAccount", back_populates="messages")
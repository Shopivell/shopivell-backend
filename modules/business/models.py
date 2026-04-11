from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, UUID
from db_compat import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from database import Base

class FacebookBusinessAccount(Base):
    __tablename__ = "facebook_business_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    business_account_id = Column(String(255), unique=True, index=True, nullable=False)
    business_name = Column(String(255), nullable=False)
    access_token = Column(Text, nullable=False)
    user_id = Column(String(255), nullable=False)  # Facebook user ID
    shopivell_user_id = Column(String(255), nullable=True, index=True)  # Shopivell user ID for filtering
    expires_at = Column(DateTime, nullable=True)
    is_connected = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship with Facebook Pages
    pages = relationship("FacebookPage", back_populates="business_account", cascade="all, delete-orphan")

    # ADDED: Relationship with WhatsApp Accounts
    # This assumes there is a WhatsAppAccount model with a foreign key to this table
    # and a back_populates='business_account'.
    whatsapp_accounts = relationship("WhatsAppAccount", back_populates="business_account", cascade="all, delete-orphan")


class FacebookPage(Base):
    __tablename__ = "facebook_pages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    business_account_id = Column(UUID(as_uuid=True), ForeignKey("facebook_business_accounts.id"), nullable=False)
    page_id = Column(String(255), nullable=False, index=True)
    page_name = Column(String(255), nullable=False)
    page_access_token = Column(Text, nullable=False)
    category = Column(String(255), nullable=True)
    category_list = Column(Text, nullable=True)  # Comma-separated categories
    about = Column(Text, nullable=True)
    cover_photo_url = Column(Text, nullable=True)
    profile_picture_url = Column(Text, nullable=True)
    website = Column(String(500), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    location = Column(String(500), nullable=True)
    tasks = Column(Text, nullable=True)  # Comma-separated tasks
    is_connected = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship with business account
    business_account = relationship("FacebookBusinessAccount", back_populates="pages")


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    business_account_id = Column(UUID(as_uuid=True), ForeignKey("facebook_business_accounts.id"), nullable=False)
    instagram_id = Column(String(255), nullable=False, index=True)  # Instagram Business Account ID
    username = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    profile_picture_url = Column(Text, nullable=True)
    biography = Column(Text, nullable=True)
    followers_count = Column(String(50), nullable=True)
    follows_count = Column(String(50), nullable=True)
    media_count = Column(String(50), nullable=True)
    website = Column(String(500), nullable=True)
    category = Column(String(255), nullable=True)
    # The page access token is used to make IG API calls
    page_access_token = Column(Text, nullable=False)
    facebook_page_id = Column(String(255), nullable=True)  # Linked Facebook Page ID
    is_connected = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship with business account
    business_account = relationship("FacebookBusinessAccount", backref="instagram_accounts")
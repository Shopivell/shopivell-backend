# modules/stores/schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from .models import StoreSetupStep

class StoreBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    store_name: str
    store_phone: str
    store_email: Optional[EmailStr] = None  # ADDED
    store_link: Optional[str] = None
    color_theme: Optional[str] = None
    logo_url: Optional[str] = None  # ADDED
    screenshot_url: Optional[str] = None
    facebook_pixel_id: Optional[str] = None
    banner_url: Optional[str] = None
    business_type: Optional[str] = None
    store_voice: Optional[str] = None
    # Brand kit (Auto-Fill store page)
    brand_description: Optional[str] = None
    secondary_colors: Optional[List[str]] = None
    font_heading: Optional[str] = None
    font_body: Optional[str] = None
    brand_dna: Optional[Dict[str, Any]] = None  # Voice&Style + About + Buyer Profiles
    products_or_services: Optional[List[str]] = None
    delivery_enabled: bool = True
    pickup_enabled: bool = False
    dine_in_enabled: bool = False
    delivery_fee: str = '0'
    free_delivery_minimum: bool = False
    store_address: Optional[str] = None
    store_city: Optional[str] = None
    store_country: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    unit_system: Optional[str] = None
    domain: Optional[str] = None
    enabled_features: Optional[Dict[str, Any]] = None
    business_goals: Optional[List[str]] = None
    payment_methods: Optional[Dict[str, Any]] = None
    ai_creative_prompt: Optional[str] = None
    ai_creative_auto_publish: Optional[bool] = None

class StoreCreate(StoreBase):
    owner_id: uuid.UUID
    agency_id: Optional[uuid.UUID] = None
    scraped_faqs: Optional[List[Dict[str, Any]]] = None  # FAQs from scraping
    extracted_images: Optional[List[Dict[str, Any]]] = None  # Images from scraping

class StoreUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    store_name: Optional[str] = None
    store_phone: Optional[str] = None
    store_email: Optional[EmailStr] = None  # ADDED
    store_link: Optional[str] = None
    color_theme: Optional[str] = None
    logo_url: Optional[str] = None  # ADDED
    screenshot_url: Optional[str] = None
    facebook_pixel_id: Optional[str] = None
    banner_url: Optional[str] = None
    business_type: Optional[str] = None
    store_voice: Optional[str] = None
    store_tone: Optional[str] = None
    # Brand kit (Auto-Fill store page)
    brand_description: Optional[str] = None
    secondary_colors: Optional[List[str]] = None
    font_heading: Optional[str] = None
    font_body: Optional[str] = None
    products_or_services: Optional[List[str]] = None  # ADDED
    delivery_enabled: Optional[bool] = None
    pickup_enabled: Optional[bool] = None
    dine_in_enabled: Optional[bool] = None
    delivery_fee: Optional[str] = None
    free_delivery_minimum: Optional[bool] = None
    store_address: Optional[str] = None
    store_city: Optional[str] = None
    store_country: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    unit_system: Optional[str] = None
    domain: Optional[str] = None
    enabled_features: Optional[Dict[str, Any]] = None
    business_goals: Optional[List[str]] = None
    payment_methods: Optional[Dict[str, Any]] = None
    ai_creative_prompt: Optional[str] = None
    ai_creative_auto_publish: Optional[bool] = None
    brand_dna: Optional[Dict[str, Any]] = None  # Voice&Style + About + Buyer Profiles
    current_step: Optional[StoreSetupStep] = None
    is_setup_completed: Optional[bool] = None

class StoreResponse(StoreBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    current_step: StoreSetupStep
    is_setup_completed: bool
    created_at: datetime
    updated_at: datetime

class StoreListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    stores: List[StoreResponse]
    total: int
    page: int
    size: int

class StoreSetupStepData(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    step: StoreSetupStep
    data: Dict[str, Any]

class StoreSetupStart(BaseModel):
    user_id: uuid.UUID

class StoreSetupSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    user_id: uuid.UUID
    session_data: Dict[str, Any]
    current_step: StoreSetupStep
    completed_steps: List[str]
    setup_progress: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

class StoreHashtagInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    store_id: uuid.UUID
    store_name: str
    business_type: Optional[str]
    hashtag_suggestions: Dict[str, Any]
    primary_hashtag: str
    business_hashtag: str

class StoreHashtagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    store_id: uuid.UUID
    store_name: str
    business_type: Optional[str]
    hashtag_suggestions: Dict[str, Any]
    primary_hashtag: str
    business_hashtag: str

class MultiStoreHashtagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    stores: List[StoreHashtagResponse]

class ScrapeRequest(BaseModel):
    url: str
    sessionId: Optional[str] = None
    userId: Optional[str] = None

class MessageSend(BaseModel):
    """Schema for incoming message data."""
    message_body: str

class SimpleMessage(BaseModel):
    message: str
# modules/stores/schemas.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from .models import StoreSetupStep

class StoreBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    store_name: str
    store_phone: str
    store_link: Optional[str] = None
    color_theme: Optional[str] = None
    business_type: Optional[str] = None
    delivery_enabled: bool = True
    pickup_enabled: bool = False
    dine_in_enabled: bool = False
    delivery_fee: str = '0'
    free_delivery_minimum: bool = False
    domain: Optional[str] = None
    enabled_features: Optional[Dict[str, Any]] = None
    business_goals: Optional[List[str]] = None
    payment_methods: Optional[Dict[str, Any]] = None

class StoreCreate(StoreBase):
    owner_id: uuid.UUID

class StoreUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    store_name: Optional[str] = None
    store_phone: Optional[str] = None
    store_link: Optional[str] = None
    color_theme: Optional[str] = None
    business_type: Optional[str] = None
    delivery_enabled: Optional[bool] = None
    pickup_enabled: Optional[bool] = None
    dine_in_enabled: Optional[bool] = None
    delivery_fee: Optional[str] = None
    free_delivery_minimum: Optional[bool] = None
    domain: Optional[str] = None
    enabled_features: Optional[Dict[str, Any]] = None
    business_goals: Optional[List[str]] = None
    payment_methods: Optional[Dict[str, Any]] = None
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
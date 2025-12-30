# modules/payments/schemas.py
from pydantic import BaseModel, ConfigDict, Field, validator, EmailStr
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from decimal import Decimal
from .models import PaymentMethod, PaymentStatus, SubscriptionPlan

class PackageFeatureBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    description: Optional[str] = None
    is_active: bool = True

class PackageFeatureCreate(PackageFeatureBase):
    pass

class PackageFeatureResponse(PackageFeatureBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

class PackagePricingBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    package_name: SubscriptionPlan
    description: Optional[str] = None
    monthly_price: float = Field(ge=0, default=0.10)
    annual_price: Optional[float] = Field(ge=0, default=None)
    currency: str = "USD"
    features: List[str] = []
    is_active: bool = True

class PackagePricingCreate(PackagePricingBase):
    pass

class PackagePricingUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    description: Optional[str] = None
    monthly_price: Optional[float] = Field(ge=0, default=None)
    annual_price: Optional[float] = Field(ge=0, default=None)
    currency: Optional[str] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None

class PackagePricingResponse(PackagePricingBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

class PaymentTransactionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    amount: float = Field(gt=0)
    currency: str = "USD"
    payment_method: PaymentMethod
    package_name: SubscriptionPlan
    billing_period: str = "monthly"
    mobile_number: Optional[str] = None

class PaymentTransactionCreate(PaymentTransactionBase):
    store_id: uuid.UUID
    user_id: uuid.UUID

# modules/payment/schemas.py
class PaymentTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    store_id: uuid.UUID
    user_id: uuid.UUID
    reference: str
    amount: float
    currency: str
    payment_method: PaymentMethod
    status: PaymentStatus
    poll_url: Optional[str] = None
    paynow_reference: Optional[str] = None
    mobile_number: Optional[str] = None
    package_name: SubscriptionPlan
    billing_period: str = "monthly"
    subscription_id: Optional[str] = None
    payment_metadata: Dict[str, Any] = {}  # CHANGED from 'metadata'
    error_message: Optional[str] = None
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

class PaymentInitiateRequest(BaseModel):
    store_id: uuid.UUID
    package_name: SubscriptionPlan
    payment_method: PaymentMethod
    billing_period: str = "monthly"
    mobile_number: Optional[str] = None
    tokens_to_redeem: int = 0  # Number of tokens to use for discount

class PaymentWebhookData(BaseModel):
    reference: str
    status: str
    paynow_reference: Optional[str] = None
    amount: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

class PaymentStatusUpdate(BaseModel):
    status: PaymentStatus
    paynow_reference: Optional[str] = None
    poll_url: Optional[str] = None
    error_message: Optional[str] = None

class StoreSubscriptionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    package_name: SubscriptionPlan
    billing_period: str = "monthly"
    is_active: bool = True
    auto_renew: bool = True
    enabled_features: Dict[str, Any] = {}
    usage_limits: Dict[str, Any] = {}

class StoreSubscriptionResponse(StoreSubscriptionBase):
    id: uuid.UUID
    store_id: uuid.UUID
    current_payment_id: Optional[uuid.UUID] = None
    last_payment_id: Optional[uuid.UUID] = None
    subscribed_at: datetime
    current_period_start: datetime
    current_period_end: datetime
    cancelled_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None

class PaymentSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: str
    current_package: str
    billing_period: str
    is_active: bool
    auto_renew: bool = False
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    next_payment_date: Optional[datetime] = None
    next_payment_amount: float = 0
    total_transactions: int = 0
    completed_payments: int = 0
    total_spent: float = 0
    enabled_features: Dict[str, Any] = {}
    usage_limits: Dict[str, Any] = {}
    package_features: List[str] = []

class PackageComparisonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    free: PackagePricingResponse
    premium: PackagePricingResponse
    business: PackagePricingResponse

class EcoCashPaymentRequest(BaseModel):
    mobile_number: str = Field(..., pattern=r'^07[78]\d{7}$', description="Ecocash number format: 077xxxxxxx or 078xxxxxxx")
    amount: float = Field(gt=0, description="Payment amount")
    email: EmailStr
    description: str = "Store subscription payment"
# modules/pos/schemas.py
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from .models import (
    POSRegisterStatus, POSSessionStatus, POSTransactionStatus,
    POSPaymentMethod, ExternalPOSProvider
)


# ============== Register Schemas ==============

class POSRegisterBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., max_length=100)
    device_id: Optional[str] = None
    status: POSRegisterStatus = POSRegisterStatus.ACTIVE
    default_payment_method: POSPaymentMethod = POSPaymentMethod.CASH
    receipt_header: Optional[str] = None
    receipt_footer: Optional[str] = None
    settings: Dict[str, Any] = {}
    external_provider: Optional[ExternalPOSProvider] = None
    external_register_id: Optional[str] = None


class POSRegisterCreate(BaseModel):
    store_id: UUID
    name: str = Field(..., max_length=100)
    device_id: Optional[str] = None
    status: POSRegisterStatus = POSRegisterStatus.ACTIVE
    default_payment_method: POSPaymentMethod = POSPaymentMethod.CASH
    receipt_header: Optional[str] = None
    receipt_footer: Optional[str] = None
    settings: Dict[str, Any] = {}


class POSRegisterUpdate(BaseModel):
    name: Optional[str] = None
    device_id: Optional[str] = None
    status: Optional[POSRegisterStatus] = None
    default_payment_method: Optional[POSPaymentMethod] = None
    receipt_header: Optional[str] = None
    receipt_footer: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class POSRegisterResponse(POSRegisterBase):
    id: UUID
    store_id: UUID
    created_at: datetime
    updated_at: datetime


# ============== Session Schemas ==============

class POSSessionCreate(BaseModel):
    store_id: UUID
    register_id: UUID
    opening_balance: float = Field(ge=0, default=0)
    notes: Optional[str] = None


class POSSessionClose(BaseModel):
    closing_balance: float = Field(ge=0)
    notes: Optional[str] = None


class POSSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    register_id: UUID
    user_id: UUID
    session_number: str
    status: POSSessionStatus
    opening_balance: float
    closing_balance: Optional[float]
    expected_balance: Optional[float]
    cash_difference: Optional[float]
    total_sales: float
    total_refunds: float
    total_transactions: int
    cash_total: float
    card_total: float
    mobile_money_total: float
    opened_at: datetime
    closed_at: Optional[datetime]
    notes: Optional[str]


class POSSessionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sessions: List[POSSessionResponse]
    total: int


# ============== Transaction/Cart Schemas ==============

class CartItem(BaseModel):
    product_id: UUID
    sku: str
    name: str
    quantity: int = Field(gt=0)
    price: float = Field(ge=0)
    discount: float = Field(ge=0, default=0)


class CartItemWithTotal(BaseModel):
    product_id: str
    sku: str
    name: str
    quantity: int
    price: float
    discount: float
    total: float


class POSTransactionCreate(BaseModel):
    session_id: UUID
    items: List[CartItem]
    payment_method: POSPaymentMethod
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    discount_amount: float = Field(ge=0, default=0)
    amount_tendered: Optional[float] = None
    notes: Optional[str] = None


class POSTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    session_id: UUID
    transaction_number: str
    status: POSTransactionStatus
    customer_id: Optional[UUID]
    customer_name: Optional[str]
    customer_phone: Optional[str]
    subtotal: float
    tax_amount: float
    discount_amount: float
    total_amount: float
    payment_method: POSPaymentMethod
    payment_reference: Optional[str]
    amount_tendered: Optional[float]
    change_given: Optional[float]
    items: List[Dict[str, Any]]
    created_at: datetime
    completed_at: Optional[datetime]


class POSTransactionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transactions: List[POSTransactionResponse]
    total: int


class ReceiptResponse(BaseModel):
    transaction_number: str
    store_name: str
    store_address: Optional[str]
    store_phone: Optional[str]
    cashier_name: str
    date: datetime
    items: List[CartItemWithTotal]
    subtotal: float
    tax_amount: float
    discount_amount: float
    total_amount: float
    payment_method: str
    amount_tendered: Optional[float]
    change_given: Optional[float]
    receipt_header: Optional[str]
    receipt_footer: Optional[str]


# ============== Product Lookup Schemas ==============

class ProductLookupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    sku: Optional[str]
    barcode: Optional[str]
    price: float
    available: int
    image_url: Optional[str]


# ============== External Integration Schemas ==============

class ExternalPOSIntegrationCreate(BaseModel):
    store_id: UUID
    provider: ExternalPOSProvider
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    merchant_id: Optional[str] = None
    location_id: Optional[str] = None
    auto_sync_orders: bool = True
    auto_sync_inventory: bool = False


class ExternalPOSIntegrationUpdate(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    merchant_id: Optional[str] = None
    location_id: Optional[str] = None
    auto_sync_orders: Optional[bool] = None
    auto_sync_inventory: Optional[bool] = None
    is_active: Optional[bool] = None


class ExternalPOSIntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    provider: ExternalPOSProvider
    merchant_id: Optional[str]
    location_id: Optional[str]
    auto_sync_orders: bool
    auto_sync_inventory: bool
    is_active: bool
    last_sync_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# ============== Webhook Payload Schemas ==============

class SquareWebhookPayload(BaseModel):
    merchant_id: str
    type: str
    event_id: str
    created_at: str
    data: Dict[str, Any]


class CloverWebhookPayload(BaseModel):
    appId: Optional[str] = None
    merchants: Dict[str, List[str]] = {}

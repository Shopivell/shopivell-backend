from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
import uuid


# --- Supplier ---

class SupplierBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    is_active: bool = True

class SupplierCreate(SupplierBase):
    pass

class SupplierUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None

class SupplierResponse(SupplierBase):
    id: uuid.UUID
    created_at: datetime


# --- CatalogProduct ---

class CatalogProductBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    supplier_id: uuid.UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    sku: str
    unit_price: float = 0.0
    wholesale_price: float = 0.0
    min_order_qty: int = 1
    max_order_qty: Optional[int] = None
    unit_of_measure: str = "unit"
    image_url: Optional[str] = None
    is_available: bool = True
    stock_level: int = 0

class CatalogProductCreate(CatalogProductBase):
    pass

class CatalogProductUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    sku: Optional[str] = None
    unit_price: Optional[float] = None
    wholesale_price: Optional[float] = None
    min_order_qty: Optional[int] = None
    max_order_qty: Optional[int] = None
    unit_of_measure: Optional[str] = None
    image_url: Optional[str] = None
    is_available: Optional[bool] = None
    stock_level: Optional[int] = None

class CatalogProductResponse(CatalogProductBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

class CatalogProductListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    products: List[CatalogProductResponse]
    total: int
    page: int
    size: int


# --- PurchaseOrderItem ---

class PurchaseOrderItemBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    catalog_product_id: uuid.UUID
    product_name: str
    sku: str
    quantity_ordered: int = 0
    unit_price: float = 0.0
    total_price: float = 0.0

class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    pass

class PurchaseOrderItemResponse(PurchaseOrderItemBase):
    id: uuid.UUID
    purchase_order_id: uuid.UUID
    quantity_received: int = 0
    quantity_pending: int = 0


# --- PurchaseOrder ---

class PurchaseOrderBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    store_id: uuid.UUID
    supplier_id: uuid.UUID
    payment_terms: Optional[str] = None
    currency: str = "USD"
    estimated_arrival: Optional[datetime] = None
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    destination: Optional[str] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[dict] = None
    shipping_cost: float = 0.0
    tax: float = 0.0

class PurchaseOrderCreate(PurchaseOrderBase):
    items: List[PurchaseOrderItemCreate] = []

class PurchaseOrderUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    supplier_id: Optional[uuid.UUID] = None
    payment_terms: Optional[str] = None
    currency: Optional[str] = None
    estimated_arrival: Optional[datetime] = None
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    destination: Optional[str] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[dict] = None
    shipping_cost: Optional[float] = None
    tax: Optional[float] = None
    items: Optional[List[PurchaseOrderItemCreate]] = None

class PurchaseOrderResponse(PurchaseOrderBase):
    id: uuid.UUID
    po_number: str
    status: str
    subtotal: float = 0.0
    total: float = 0.0
    payment_status: str = "pending"
    created_at: datetime
    updated_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    items: List[PurchaseOrderItemResponse] = []

class PurchaseOrderListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    orders: List[PurchaseOrderResponse]
    total: int
    page: int
    size: int

class POStatusUpdate(BaseModel):
    status: str
    tracking_number: Optional[str] = None
    shipping_carrier: Optional[str] = None
    notes: Optional[str] = None


# --- GoodsReceiptItem ---

class GoodsReceiptItemCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    purchase_order_item_id: uuid.UUID
    quantity_received: int = 0
    quantity_rejected: int = 0
    notes: Optional[str] = None

class GoodsReceiptItemResponse(GoodsReceiptItemCreate):
    id: uuid.UUID
    goods_receipt_id: uuid.UUID


# --- GoodsReceipt ---

class GoodsReceiptCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    received_by: Optional[str] = None
    notes: Optional[str] = None
    items: List[GoodsReceiptItemCreate] = []

class GoodsReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    purchase_order_id: uuid.UUID
    store_id: uuid.UUID
    receipt_number: str
    received_by: Optional[str] = None
    status: str
    received_at: datetime
    notes: Optional[str] = None
    items: List[GoodsReceiptItemResponse] = []


# --- ConsumptionRecord ---

class ConsumptionRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    store_id: uuid.UUID
    product_id: uuid.UUID
    catalog_product_id: Optional[uuid.UUID] = None
    quantity_consumed: float
    period_start: datetime
    period_end: datetime
    recorded_at: datetime


# --- ProcurementAlert ---

class ProcurementAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    store_id: uuid.UUID
    product_id: uuid.UUID
    alert_type: str
    message: str
    is_read: bool
    created_at: datetime


# --- Analytics ---

class ProcurementAnalyticsResponse(BaseModel):
    total_orders: int = 0
    total_spending: float = 0.0
    pending_orders: int = 0
    delivered_orders: int = 0
    avg_order_value: float = 0.0
    spending_by_month: List[dict] = []
    spending_by_category: List[dict] = []
    top_products: List[dict] = []

class ConsumptionTrendResponse(BaseModel):
    product_id: uuid.UUID
    product_name: str
    avg_daily_consumption: float = 0.0
    current_stock: int = 0
    estimated_days_remaining: Optional[float] = None
    consumption_history: List[dict] = []

class AdminAnalyticsResponse(BaseModel):
    total_orders_all: int = 0
    total_revenue: float = 0.0
    active_stores: int = 0
    orders_by_status: dict = {}
    monthly_trends: List[dict] = []

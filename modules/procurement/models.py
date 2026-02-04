from typing import Optional, List
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer, Boolean, JSON, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
import enum
import random
import string

from database import Base


# --- Enums ---

class POStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    PARTIAL = "partial"
    REFUNDED = "refunded"


class GoodsReceiptStatus(str, enum.Enum):
    PARTIAL = "partial"
    COMPLETE = "complete"


class AlertType(str, enum.Enum):
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    REORDER_SUGGESTION = "reorder_suggestion"


# --- Helpers ---

def generate_po_number() -> str:
    digits = ''.join(random.choices(string.digits, k=6))
    return f"PO-{digits}"


def generate_gr_number() -> str:
    digits = ''.join(random.choices(string.digits, k=6))
    return f"GR-{digits}"


# --- Models ---

class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    catalog_products: Mapped[List["CatalogProduct"]] = relationship("CatalogProduct", back_populates="supplier", cascade="all, delete-orphan")
    purchase_orders: Mapped[List["PurchaseOrder"]] = relationship("PurchaseOrder", back_populates="supplier")


class CatalogProduct(Base):
    __tablename__ = "catalog_products"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wholesale_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    min_order_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_order_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(String(50), nullable=False, default="unit")
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stock_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=datetime.utcnow, nullable=True)

    # Relationships
    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="catalog_products")
    order_items: Mapped[List["PurchaseOrderItem"]] = relationship("PurchaseOrderItem", back_populates="catalog_product")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    po_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, default=generate_po_number)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=POStatus.DRAFT.value)
    supplier_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shipping_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default=PaymentStatus.PENDING.value)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    estimated_arrival: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    shipping_carrier: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reference_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=datetime.utcnow, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    store = relationship("Store", backref="purchase_orders")
    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="purchase_orders")
    items: Mapped[List["PurchaseOrderItem"]] = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    goods_receipts: Mapped[List["GoodsReceipt"]] = relationship("GoodsReceipt", back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    catalog_product_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("catalog_products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="items")
    catalog_product: Mapped["CatalogProduct"] = relationship("CatalogProduct", back_populates="order_items")
    receipt_items: Mapped[List["GoodsReceiptItem"]] = relationship("GoodsReceiptItem", back_populates="purchase_order_item")


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    receipt_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, default=generate_gr_number)
    received_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=GoodsReceiptStatus.PARTIAL.value)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="goods_receipts")
    store = relationship("Store", backref="goods_receipts")
    items: Mapped[List["GoodsReceiptItem"]] = relationship("GoodsReceiptItem", back_populates="goods_receipt", cascade="all, delete-orphan")


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goods_receipt_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=False, index=True)
    purchase_order_item_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("purchase_order_items.id"), nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    goods_receipt: Mapped["GoodsReceipt"] = relationship("GoodsReceipt", back_populates="items")
    purchase_order_item: Mapped["PurchaseOrderItem"] = relationship("PurchaseOrderItem", back_populates="receipt_items")


class ConsumptionRecord(Base):
    __tablename__ = "consumption_records"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    catalog_product_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("catalog_products.id"), nullable=True)
    quantity_consumed: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    store = relationship("Store", backref="consumption_records")
    product = relationship("Product", backref="consumption_records")


class ProcurementAlert(Base):
    __tablename__ = "procurement_alerts"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    store = relationship("Store", backref="procurement_alerts")
    product = relationship("Product", backref="procurement_alerts")

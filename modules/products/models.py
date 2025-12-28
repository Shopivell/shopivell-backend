from typing import Optional, List
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Integer, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base

class Product(Base):
    __tablename__ = "products"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vendor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Keep quantity for backward compatibility
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Inventory fields
    sku: Mapped[str] = mapped_column(String(100), nullable=False, server_default='No SKU')
    barcode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Detailed inventory tracking
    unavailable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Product properties
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weight_unit: Mapped[str] = mapped_column(String(10), nullable=False, default='kg')
    status: Mapped[str] = mapped_column(String(50), nullable=False, default='Active')
    inventory_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    physical_product: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sell_when_out_of_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Image fields
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    store = relationship("Store", backref="products")
    collections: Mapped[List["Collection"]] = relationship(
        "Collection",
        secondary="collection_products",
        back_populates="products"
    )

class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    collection_type: Mapped[str] = mapped_column(String(50), nullable=False, default='manual')
    # Image fields
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    theme_template: Mapped[str] = mapped_column(String(100), nullable=False, default='default')
    sales_channels: Mapped[dict] = mapped_column(JSON, nullable=False, default=lambda: {"onlineStore": True, "pointOfSale": True})
    search_query: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sort_by: Mapped[str] = mapped_column(String(50), nullable=False, default='best-selling')
    conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    store = relationship("Store", backref="collections")
    products: Mapped[List["Product"]] = relationship(
        "Product",
        secondary="collection_products",
        back_populates="collections"
    )

class CollectionProduct(Base):
    __tablename__ = "collection_products"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("collections.id"), nullable=False)
    product_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
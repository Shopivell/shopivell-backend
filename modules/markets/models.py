# models.py
from typing import Optional
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Float
from db_compat import PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
from database import Base

class Market(Base):
    __tablename__ = "markets"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    flag: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    customizations: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(100), nullable=False, default="US Dollar (USD $)")
    catalogs: Mapped[str] = mapped_column(String(255), nullable=False, default="All products")
    domain: Mapped[str] = mapped_column(String(500), nullable=False)
    online_store: Mapped[str] = mapped_column(String(255), nullable=False, default="Horizon")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    market_includes = relationship("MarketInclude", back_populates="market", cascade="all, delete-orphan")
    market_customizations = relationship("MarketCustomization", back_populates="market", cascade="all, delete-orphan")
    catalog_markets = relationship("CatalogMarket", back_populates="market", cascade="all, delete-orphan")

class MarketInclude(Base):
    __tablename__ = "market_includes"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    condition: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    market = relationship("Market", back_populates="market_includes")

class MarketCustomization(Base):
    __tablename__ = "market_customizations"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    original_value: Mapped[str] = mapped_column(String(500), nullable=False)
    customized_value: Mapped[str] = mapped_column(String(500), nullable=False)
    
    market = relationship("Market", back_populates="market_customizations")

class Catalog(Base):
    __tablename__ = "catalogs"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="Draft")
    assigned_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    price_overrides: Mapped[int] = mapped_column(Integer, default=0)
    overall_adjustment: Mapped[str] = mapped_column(String(100), default="None")
    products_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_include_products: Mapped[bool] = mapped_column(Boolean, default=True)
    price_adjustment: Mapped[float] = mapped_column(Float, default=0)
    adjustment_type: Mapped[str] = mapped_column(String(20), default="Decrease")
    include_compare_price: Mapped[bool] = mapped_column(Boolean, default=True)
    currency: Mapped[str] = mapped_column(String(50), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    catalog_products = relationship("CatalogProduct", back_populates="catalog", cascade="all, delete-orphan")
    catalog_markets = relationship("CatalogMarket", back_populates="catalog", cascade="all, delete-orphan")

class CatalogProduct(Base):
    __tablename__ = "catalog_products"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalog_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("catalogs.id"), nullable=False)
    product_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    price_in_usd: Mapped[float] = mapped_column(Float, nullable=False)
    compare_at_price: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="included")
    product_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    catalog = relationship("Catalog", back_populates="catalog_products")

class CatalogMarket(Base):
    __tablename__ = "catalog_markets"
    
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalog_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("catalogs.id"), nullable=False)
    market_id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("markets.id"), nullable=False)
    
    catalog = relationship("Catalog", back_populates="catalog_markets")
    market = relationship("Market", back_populates="catalog_markets")



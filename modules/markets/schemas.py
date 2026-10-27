# schemas.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List
import uuid

# Market Schemas
class MarketIncludeBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: str
    value: str
    condition: Optional[str] = None

class MarketIncludeCreate(MarketIncludeBase):
    pass

class MarketIncludeResponse(MarketIncludeBase):
    id: uuid.UUID
    market_id: uuid.UUID

class MarketCustomizationBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: str
    original_value: str
    customized_value: str

class MarketCustomizationCreate(MarketCustomizationBase):
    pass

class MarketCustomizationResponse(MarketCustomizationBase):
    id: uuid.UUID
    market_id: uuid.UUID

class MarketBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    status: str = "active"
    flag: Optional[str] = None
    currency: str = "US Dollar (USD $)"
    catalogs: str = "All products"
    domain: str
    online_store: str = "Horizon"

class MarketCreate(MarketBase):
    includes: Optional[List[MarketIncludeCreate]] = None
    customizations: Optional[List[MarketCustomizationCreate]] = None

class MarketUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: Optional[str] = None
    status: Optional[str] = None
    flag: Optional[str] = None
    currency: Optional[str] = None
    catalogs: Optional[str] = None
    domain: Optional[str] = None
    online_store: Optional[str] = None

class MarketResponse(MarketBase):
    id: uuid.UUID
    customizations: int
    created_at: datetime
    updated_at: datetime
    market_includes: List[MarketIncludeResponse] = []
    market_customizations: List[MarketCustomizationResponse] = []

class MarketListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    markets: List[MarketResponse]
    total: int
    page: int
    size: int

# Catalog Schemas
class CatalogProductBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: uuid.UUID
    product_name: str
    price_in_usd: float
    compare_at_price: float = 0
    status: str = "included"
    product_image: Optional[str] = None

class CatalogProductCreate(CatalogProductBase):
    pass

class CatalogProductResponse(CatalogProductBase):
    id: uuid.UUID
    catalog_id: uuid.UUID

class CatalogMarketBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    market_id: uuid.UUID

class CatalogMarketCreate(CatalogMarketBase):
    pass

class CatalogMarketResponse(CatalogMarketBase):
    id: uuid.UUID
    catalog_id: uuid.UUID
    market: Optional[MarketResponse] = None

class CatalogBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str
    status: str = "Draft"
    assigned_to: Optional[str] = None
    auto_include_products: bool = True
    price_adjustment: float = 0
    adjustment_type: str = "Decrease"
    include_compare_price: bool = True
    currency: str = "USD"

class CatalogCreate(CatalogBase):
    products: Optional[List[CatalogProductCreate]] = None
    markets: Optional[List[CatalogMarketCreate]] = None

class CatalogUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    auto_include_products: Optional[bool] = None
    price_adjustment: Optional[float] = None
    adjustment_type: Optional[str] = None
    include_compare_price: Optional[bool] = None
    currency: Optional[str] = None

class CatalogResponse(CatalogBase):
    id: uuid.UUID
    price_overrides: int
    overall_adjustment: str
    products_count: int
    created_at: datetime
    updated_at: datetime
    catalog_products: List[CatalogProductResponse] = []
    catalog_markets: List[CatalogMarketResponse] = []

class CatalogListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    catalogs: List[CatalogResponse]
    total: int
    page: int
    size: int

# Product Schemas
class ProductBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    price_in_usd: float
    compare_at_price: float = 0
    status: str = "active"
    image: Optional[str] = None

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: Optional[str] = None
    price_in_usd: Optional[float] = None
    compare_at_price: Optional[float] = None
    status: Optional[str] = None
    image: Optional[str] = None

class ProductResponse(ProductBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

class ProductListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    products: List[ProductResponse]
    total: int
    page: int
    size: int
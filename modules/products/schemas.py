from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid

# Product Schemas
class ProductBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    branch: Optional[str] = None
    in_stock: Optional[bool] = None
    price: float = 0.0
    type: Optional[str] = None
    vendor: Optional[str] = None
    tags: Optional[str] = None
    # Keep quantity for backward compatibility
    quantity: int = 0
    # Inventory fields
    sku: str = 'No SKU'
    barcode: Optional[str] = None
    # Detailed inventory tracking
    unavailable: int = 0
    committed: int = 0
    available: int = 0
    on_hand: int = 0
    # Product properties
    weight: float = 0.0
    weight_unit: str = 'kg'
    status: str = 'Active'
    inventory_tracked: bool = True
    physical_product: bool = True
    sell_when_out_of_stock: bool = False
    # Image fields
    image_url: Optional[str] = None
    image_path: Optional[str] = None

class ProductCreate(ProductBase):
    store_id: uuid.UUID
    collections: List[uuid.UUID] = []

class ProductUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    branch: Optional[str] = None
    in_stock: Optional[bool] = None
    price: Optional[float] = None
    type: Optional[str] = None
    vendor: Optional[str] = None
    tags: Optional[str] = None
    # Keep quantity for backward compatibility
    quantity: Optional[int] = None
    # Inventory fields
    sku: Optional[str] = None
    barcode: Optional[str] = None
    # Detailed inventory tracking
    unavailable: Optional[int] = None
    committed: Optional[int] = None
    available: Optional[int] = None
    on_hand: Optional[int] = None
    # Product properties
    weight: Optional[float] = None
    weight_unit: Optional[str] = None
    status: Optional[str] = None
    inventory_tracked: Optional[bool] = None
    physical_product: Optional[bool] = None
    sell_when_out_of_stock: Optional[bool] = None
    # Image fields
    image_url: Optional[str] = None
    image_path: Optional[str] = None

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

# Inventory Schemas
class InventoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    name: str
    sku: str
    quantity: int
    unavailable: int
    committed: int
    available: int
    on_hand: int
    status: str
    inventory_tracked: bool

class InventoryListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    inventory_items: List[InventoryItemResponse]
    total: int
    page: int
    size: int

class InventoryUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    quantity: Optional[int] = None
    unavailable: Optional[int] = None
    committed: Optional[int] = None
    available: Optional[int] = None
    on_hand: Optional[int] = None

# Collection Schemas
class CollectionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    title: str
    description: Optional[str] = None
    collection_type: str = 'manual'
    # Image fields
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    theme_template: str = 'default'
    sales_channels: Dict[str, bool] = {"onlineStore": True, "pointOfSale": True}
    search_query: Optional[str] = None
    sort_by: str = 'best-selling'
    conditions: Optional[str] = None

class CollectionCreate(CollectionBase):
    store_id: uuid.UUID
    product_ids: List[uuid.UUID] = []

class CollectionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    title: Optional[str] = None
    description: Optional[str] = None
    collection_type: Optional[str] = None
    # Image fields
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    theme_template: Optional[str] = None
    sales_channels: Optional[Dict[str, bool]] = None
    search_query: Optional[str] = None
    sort_by: Optional[str] = None
    conditions: Optional[str] = None

class CollectionResponse(CollectionBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

class CollectionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    collections: List[CollectionResponse]
    total: int
    page: int
    size: int

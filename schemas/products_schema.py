# schemas/products_schema.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID

class ProductBase(BaseModel):
    # Common fields for all product operations
    name: str
    description: Optional[str] = None
    price: float
    category: str
    supplier_id: UUID

    # Config for Pydantic v2+ to enable ORM mode (from_attributes)
    model_config = ConfigDict(from_attributes=True)

class ProductCreate(ProductBase):
    # When creating a product, all base fields are required
    pass

class ProductUpdate(BaseModel):
    # For updating, all fields should be optional
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    # supplier_id should generally not be changed during an update
    # image_path is updated via a separate endpoint

    model_config = ConfigDict(from_attributes=True)


class ProductResponse(ProductBase):
    # When returning a product, include its ID and the image URL
    id: UUID
    image_path: Optional[str] = None # This will directly hold the DO Spaces URL

    model_config = ConfigDict(from_attributes=True)

class MessageResponse(BaseModel):
    message: str
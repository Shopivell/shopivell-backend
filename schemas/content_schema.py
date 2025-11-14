from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContentAttachmentSchema(BaseModel):
    name: str
    file_type: Optional[str] = None
    file_size: Optional[str] = None
    url: Optional[str] = None


class ContentItemBaseSchema(BaseModel):
    title: str
    content_type: str = Field(validation_alias="type")
    platform: str
    status: str
    author: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[str] = None
    engagement: Optional[str] = None
    scheduled_date: Optional[date] = None
    date_posted: Optional[date] = None
    thumbnail_url: Optional[str] = None
    attachments: List[ContentAttachmentSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ContentItemCreateSchema(ContentItemBaseSchema):
    pass


class ContentItemUpdateSchema(BaseModel):
    title: Optional[str] = None
    content_type: Optional[str] = Field(default=None, validation_alias="type")
    platform: Optional[str] = None
    status: Optional[str] = None
    author: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[str] = None
    engagement: Optional[str] = None
    scheduled_date: Optional[date] = None
    date_posted: Optional[date] = None
    thumbnail_url: Optional[str] = None
    attachments: Optional[List[ContentAttachmentSchema]] = None

    model_config = ConfigDict(populate_by_name=True)


class ContentItemResponseSchema(ContentItemBaseSchema):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None


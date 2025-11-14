import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import ContentItem
from schemas.content_schema import (
    ContentItemCreateSchema,
    ContentItemResponseSchema,
    ContentItemUpdateSchema,
)


logger = logging.getLogger(__name__)

content_router = APIRouter(prefix="/content", tags=["Content"])


@content_router.get("/", response_model=List[ContentItemResponseSchema])
def list_content_items(db: Session = Depends(get_db)) -> List[ContentItem]:
    return db.query(ContentItem).order_by(ContentItem.created_at.desc()).all()


@content_router.post("/", response_model=ContentItemResponseSchema, status_code=status.HTTP_201_CREATED)
def create_content_item(
    content_data: ContentItemCreateSchema, db: Session = Depends(get_db)
) -> ContentItem:
    payload = content_data.model_dump(by_alias=False)
    content_item = ContentItem(**payload)

    db.add(content_item)
    db.commit()
    db.refresh(content_item)
    return content_item


@content_router.put("/{content_id}", response_model=ContentItemResponseSchema)
def update_content_item(
    content_id: UUID,
    content_update: ContentItemUpdateSchema,
    db: Session = Depends(get_db),
) -> ContentItem:
    content_item = db.query(ContentItem).filter(ContentItem.id == content_id).first()
    if not content_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content item not found.")

    update_data = content_update.model_dump(exclude_unset=True, by_alias=False)
    if not update_data:
        return content_item

    for key, value in update_data.items():
        setattr(content_item, key, value)

    db.add(content_item)
    db.commit()
    db.refresh(content_item)
    return content_item


@content_router.delete("/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_content_item(content_id: UUID, db: Session = Depends(get_db)) -> None:
    content_item = db.query(ContentItem).filter(ContentItem.id == content_id).first()
    if not content_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content item not found.")

    db.delete(content_item)
    db.commit()


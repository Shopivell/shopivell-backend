from fastapi import APIRouter, Depends, HTTPException, Path, status, Query
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
from datetime import datetime

from database import get_db 
from .models import Content
from .schemas import (
    ContentCreate, 
    ContentUpdate,
    ContentResponse, 
    ContentListResponse,
    ContentStatsResponse
) 

content_router = APIRouter(prefix="/api/content", tags=["content"])

# --- Helper Functions ---

def calculate_engagement_rate(engagement: dict, metrics: dict) -> float:
    """Calculate engagement rate based on engagement metrics."""
    try:
        impressions = metrics.get('impressions', 0)
        if impressions == 0:
            return 0.0
        
        # Convert engagement counts to integers
        likes = int(engagement.get('likes', '0').replace('K', '000').replace('M', '000000'))
        shares = int(engagement.get('shares', '0').replace('K', '000').replace('M', '000000'))
        comments = int(engagement.get('comments', '0').replace('K', '000').replace('M', '000000'))
        
        total_engagement = likes + shares + comments
        return round((total_engagement / impressions) * 100, 2)
    except (ValueError, TypeError):
        return 0.0

# --- CRUD Endpoints ---

@content_router.post("/", response_model=ContentResponse, status_code=status.HTTP_201_CREATED)
def create_content(
    content_data: ContentCreate,
    db: Session = Depends(get_db)
):
    """Create new content"""
    
    # Calculate engagement rate if not provided
    metrics = content_data.metrics.copy()
    if 'engagementRate' not in metrics and content_data.engagement:
        metrics['engagementRate'] = calculate_engagement_rate(content_data.engagement, metrics)
    
    content_dict = content_data.model_dump()
    content_dict['metrics'] = metrics
    
    content = Content(**content_dict)
    db.add(content)
    db.commit()
    db.refresh(content)
    
    return content

@content_router.get("/{content_id}", response_model=ContentResponse)
def get_content(
    content_id: uuid.UUID = Path(..., description="The ID of the content to retrieve"),
    db: Session = Depends(get_db)
):
    """Retrieve specific content by ID"""
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content not found"
        )
    return content

@content_router.get("/", response_model=ContentListResponse)
def get_all_content(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    platform: Optional[str] = Query(None, description="Filter by platform"),
    status_filter: Optional[str] = Query(None, description="Filter by status", alias="status"),
    type_filter: Optional[str] = Query(None, description="Filter by content type", alias="type"),
    db: Session = Depends(get_db)
):
    """Get paginated list of content with optional filtering"""
    query = db.query(Content)
    
    # Apply filters
    if platform:
        query = query.filter(Content.platform == platform)
    if status_filter:
        query = query.filter(Content.status == status_filter)
    if type_filter:
        query = query.filter(Content.type == type_filter)
    
    total_count = query.count()
    content_items = query.order_by(Content.created_at.desc()).offset(skip).limit(limit).all()
    
    return ContentListResponse(
        content=content_items,
        total_count=total_count,
        page=skip // limit + 1,
        page_size=limit,
        total_pages=(total_count + limit - 1) // limit
    )

@content_router.put("/{content_id}", response_model=ContentResponse)
def update_content(
    content_id: uuid.UUID,
    content_data: ContentUpdate,
    db: Session = Depends(get_db)
):
    """Update existing content"""
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content not found"
        )
    
    # Update fields
    update_data = content_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(content, field, value)
    
    # Recalculate engagement rate if engagement or metrics changed
    if 'engagement' in update_data or 'metrics' in update_data:
        metrics = content.metrics.copy()
        metrics['engagementRate'] = calculate_engagement_rate(content.engagement, metrics)
        content.metrics = metrics
    
    content.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(content)
    
    return content

@content_router.delete("/{content_id}", status_code=status.HTTP_200_OK)
def delete_content(
    content_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete content"""
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content not found"
        )
    
    # Store info for response
    content_info = {
        "id": str(content.id),
        "title": content.title,
        "platform": content.platform
    }
    
    db.delete(content)
    db.commit()
    
    return {
        "message": "Content deleted successfully",
        "deleted_content": content_info
    }

# --- Specialized Endpoints ---

@content_router.get("/platform/{platform}", response_model=List[ContentResponse])
def get_content_by_platform(
    platform: str = Path(..., description="Platform to filter by"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get content by specific platform"""
    content_items = db.query(Content).filter(
        Content.platform == platform
    ).order_by(Content.created_at.desc()).offset(skip).limit(limit).all()
    
    return content_items

@content_router.get("/status/{status}", response_model=List[ContentResponse])
def get_content_by_status(
    status: str = Path(..., description="Status to filter by"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get content by specific status"""
    content_items = db.query(Content).filter(
        Content.status == status
    ).order_by(Content.created_at.desc()).offset(skip).limit(limit).all()
    
    return content_items

@content_router.get("/stats/summary", response_model=ContentStatsResponse)
def get_content_stats(db: Session = Depends(get_db)):
    """Get content statistics summary"""
    total_content = db.query(Content).count()
    published_count = db.query(Content).filter(Content.status == "published").count()
    scheduled_count = db.query(Content).filter(Content.status == "scheduled").count()
    draft_count = db.query(Content).filter(Content.status == "draft").count()
    
    # Platform statistics
    platforms = {}
    platform_results = db.query(Content.platform, db.func.count(Content.id)).group_by(Content.platform).all()
    for platform, count in platform_results:
        platforms[platform] = count
    
    # Content type statistics
    content_types = {}
    type_results = db.query(Content.type, db.func.count(Content.id)).group_by(Content.type).all()
    for content_type, count in type_results:
        content_types[content_type] = count
    
    return ContentStatsResponse(
        total_content=total_content,
        published_count=published_count,
        scheduled_count=scheduled_count,
        draft_count=draft_count,
        platforms=platforms,
        content_types=content_types
    )

@content_router.patch("/{content_id}/status", response_model=ContentResponse)
def update_content_status(
    content_id: uuid.UUID,
    status: str = Query(..., description="New status for the content"),
    db: Session = Depends(get_db)
):
    """Update content status"""
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content not found"
        )
    
    valid_statuses = ["draft", "scheduled", "published", "archived"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    content.status = status
    content.updated_at = datetime.utcnow()
    
    # If publishing, set date_posted to now if not already set
    if status == "published" and not content.date_posted:
        content.date_posted = datetime.utcnow()
    
    db.commit()
    db.refresh(content)
    
    return content

# --- Bulk Operations ---

@content_router.post("/bulk", response_model=List[ContentResponse], status_code=status.HTTP_201_CREATED)
def create_bulk_content(
    content_list: List[ContentCreate],
    db: Session = Depends(get_db)
):
    """Create multiple content items at once"""
    content_objects = []
    
    for content_data in content_list:
        # Calculate engagement rate if not provided
        metrics = content_data.metrics.copy()
        if 'engagementRate' not in metrics and content_data.engagement:
            metrics['engagementRate'] = calculate_engagement_rate(content_data.engagement, metrics)
        
        content_dict = content_data.model_dump()
        content_dict['metrics'] = metrics
        
        content = Content(**content_dict)
        content_objects.append(content)
    
    db.add_all(content_objects)
    db.commit()
    
    # Refresh all objects to get their IDs
    for content in content_objects:
        db.refresh(content)
    
    return content_objects
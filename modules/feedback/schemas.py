# modules/feedback/schemas.py
"""
Pydantic schemas for feedback endpoints.
"""

from enum import Enum
from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    FEEDBACK = "feedback"
    IMPROVEMENT = "improvement"
    QUESTION = "question"
    REVIEW = "review"


class FeedbackStatus(str, Enum):
    NEW = "new"
    IN_REVIEW = "in_review"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"
    WONT_FIX = "wont_fix"


class FeedbackPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class UserInfo(BaseModel):
    """Basic user information for feedback responses."""
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class FeedbackCreate(BaseModel):
    """Schema for creating new feedback."""
    type: FeedbackType
    title: str = Field(..., min_length=5, max_length=255)
    description: str = Field(..., min_length=10)
    page_url: Optional[str] = None
    browser_info: Optional[str] = None
    screenshot_url: Optional[str] = None
    error_message: Optional[str] = None
    steps_to_reproduce: Optional[str] = None
    priority: FeedbackPriority = FeedbackPriority.MEDIUM
    is_public: bool = False
    rating: Optional[int] = Field(None, ge=1, le=5, description="Star rating 1-5 for reviews")


class FeedbackUpdate(BaseModel):
    """Schema for users updating their own feedback."""
    title: Optional[str] = Field(None, min_length=5, max_length=255)
    description: Optional[str] = Field(None, min_length=10)
    page_url: Optional[str] = None
    browser_info: Optional[str] = None
    screenshot_url: Optional[str] = None
    error_message: Optional[str] = None
    steps_to_reproduce: Optional[str] = None
    is_public: Optional[bool] = None


class FeedbackAdminUpdate(BaseModel):
    """Schema for admin updating feedback."""
    status: Optional[FeedbackStatus] = None
    priority: Optional[FeedbackPriority] = None
    admin_response: Optional[str] = None
    is_public: Optional[bool] = None


class FeedbackResponse(BaseModel):
    """Schema for feedback response."""
    id: UUID
    type: str
    title: str
    description: str
    page_url: Optional[str] = None
    browser_info: Optional[str] = None
    screenshot_url: Optional[str] = None
    error_message: Optional[str] = None
    steps_to_reproduce: Optional[str] = None
    status: str
    priority: str
    admin_response: Optional[str] = None
    responded_at: Optional[datetime] = None
    rating: Optional[int] = None
    upvotes: int
    is_public: bool
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    user: Optional[UserInfo] = None
    comments_count: int = 0

    class Config:
        from_attributes = True


class FeedbackListResponse(BaseModel):
    """Schema for paginated feedback list."""
    feedback: List[FeedbackResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class FeedbackStatsResponse(BaseModel):
    """Schema for feedback statistics."""
    total: int
    by_type: Dict[str, int]
    by_status: Dict[str, int]
    by_priority: Dict[str, int]
    recent_count: int


class CommentCreate(BaseModel):
    """Schema for creating a comment."""
    comment: str = Field(..., min_length=1)


class CommentUpdate(BaseModel):
    """Schema for updating a comment."""
    comment: str = Field(..., min_length=1)


class FeedbackCommentResponse(BaseModel):
    """Schema for comment response."""
    id: UUID
    comment: str
    is_admin: bool
    created_at: datetime
    user: Optional[UserInfo] = None

    class Config:
        from_attributes = True

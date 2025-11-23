# Social Post Schemas
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class PlatformResult(BaseModel):
    platform: str
    success: bool
    post_id: Optional[str] = None
    error: Optional[str] = None

class SocialPostBase(BaseModel):
    caption: str
    hashtags: List[str]
    cta: str
    image_url: str
    platforms: List[PlatformResult]

class SocialPostCreate(SocialPostBase):
    business_id: int

class SocialPost(SocialPostBase):
    id: int
    business_id: int
    status: str
    created_at: datetime
    approved_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Workflow Log Schemas
class WorkflowLogBase(BaseModel):
    workflow_id: str
    execution_id: str
    status: str
    success_count: int = 0
    failure_count: int = 0
    message: Optional[str] = None

class WorkflowLogCreate(WorkflowLogBase):
    business_id: int

class WorkflowLog(WorkflowLogBase):
    id: int
    business_id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# Error Log Schemas
class ErrorLogBase(BaseModel):
    workflow_id: Optional[str] = None
    execution_id: Optional[str] = None
    error_type: str
    error_message: str
    stack_trace: Optional[str] = None
    request_data: Optional[Dict[str, Any]] = None

class ErrorLogCreate(ErrorLogBase):
    business_id: Optional[int] = None

class ErrorLog(ErrorLogBase):
    id: int
    business_id: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# API Response Schemas
class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None

class WebhookResponse(BaseModel):
    businessId: int
    trigger: str = "social_automation"

class MessageSend(BaseModel):
    """Schema for incoming message data."""
    message_body: str

class MessageSendResponse(BaseModel):
    """Schema for the message send response."""
    success: bool
    message: str
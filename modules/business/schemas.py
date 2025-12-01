from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

# Base schemas with common fields
class FacebookBusinessAccountBase(BaseModel):
    business_account_id: str
    business_name: str
    user_id: str
    is_connected: bool = True
    is_active: bool = True

class FacebookPageBase(BaseModel):
    page_id: str
    page_name: str
    category: Optional[str] = None
    category_list: Optional[str] = None
    about: Optional[str] = None
    cover_photo_url: Optional[str] = None
    profile_picture_url: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    tasks: Optional[str] = None
    is_connected: bool = True
    is_active: bool = True

# Create schemas
class FacebookBusinessAccountCreate(FacebookBusinessAccountBase):
    access_token: str
    expires_at: Optional[datetime] = None

class FacebookPageCreate(FacebookPageBase):
    business_account_id: uuid.UUID
    page_access_token: str

# Update schemas
class FacebookBusinessAccountUpdate(BaseModel):
    business_name: Optional[str] = None
    access_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_connected: Optional[bool] = None
    is_active: Optional[bool] = None

class FacebookPageUpdate(BaseModel):
    page_name: Optional[str] = None
    page_access_token: Optional[str] = None
    category: Optional[str] = None
    category_list: Optional[str] = None
    about: Optional[str] = None
    cover_photo_url: Optional[str] = None
    profile_picture_url: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    tasks: Optional[str] = None
    is_connected: Optional[bool] = None
    is_active: Optional[bool] = None

# Response schemas
class FacebookBusinessAccountResponse(FacebookBusinessAccountBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    pages: List["FacebookPageResponse"] = []

class FacebookPageResponse(FacebookPageBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    business_account_id: uuid.UUID
    page_access_token: str  # Consider removing this for security in some endpoints
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

# OAuth schemas
class FacebookOAuthRequest(BaseModel):
    access_token: str

class FacebookOAuthResponse(BaseModel):
    success: bool
    message: str
    business_account_id: uuid.UUID
    pages: List[FacebookPageResponse]

# List response schemas
class FacebookBusinessAccountListResponse(BaseModel):
    business_accounts: List[FacebookBusinessAccountResponse]
    total_count: int

class FacebookPageListResponse(BaseModel):
    pages: List[FacebookPageResponse]
    total_count: int

# Success message schema
class SuccessMessage(BaseModel):
    message: str

# Post creation schemas
class FacebookPostCreate(BaseModel):
    message: str
    link: Optional[str] = None
    published: bool = True
    scheduled_publish_time: Optional[datetime] = None

class FacebookPostResponse(BaseModel):
    success: bool
    message: str
    post_id: Optional[str] = None
    post_url: Optional[str] = None

# New schemas for posts and analytics
class FacebookPost(BaseModel):
    id: str
    message: Optional[str] = None
    created_time: str
    updated_time: Optional[str] = None
    permalink_url: Optional[str] = None
    type: Optional[str] = None
    status_type: Optional[str] = None
    is_published: Optional[bool] = None
    is_hidden: Optional[bool] = None
    is_expired: Optional[bool] = None
    likes: Optional[Dict] = None
    comments: Optional[Dict] = None
    shares: Optional[Dict] = None

class FacebookPostInsights(BaseModel):
    post_id: str
    insights: Dict
    created_time: Optional[str] = None
    message: Optional[str] = None
    permalink_url: Optional[str] = None

class FacebookPostsResponse(BaseModel):
    posts: List[FacebookPost]
    total_count: int

class FacebookPostInsightsResponse(BaseModel):
    success: bool
    post_id: str
    insights: Dict
    message: Optional[str] = None
    permalink_url: Optional[str] = None

class FacebookCallbackRequest(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None  # Add this

# Pydantic model for OAuth URL request
class FacebookOAuthUrlRequest(BaseModel):
    redirect_uri: Optional[str] = None


# Update forward references for nested models
FacebookBusinessAccountResponse.model_rebuild()
FacebookPageResponse.model_rebuild()
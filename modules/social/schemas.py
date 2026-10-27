# modules/social/schemas.py
from pydantic import BaseModel, ConfigDict, HttpUrl
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from .models import SocialPlatform, SocialConnectionStatus

class FacebookPageBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    name: str
    access_token: str
    category: Optional[str] = None
    perms: Optional[List[str]] = None

class FacebookPageList(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    pages: List[FacebookPageBase]
    user_id: str

class FacebookPageConnectionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    facebook_page_id: str
    facebook_page_name: str
    store_id: Optional[uuid.UUID] = None

class FacebookPageConnectionCreate(FacebookPageConnectionBase):
    facebook_page_token: str
    facebook_user_id: str
    granted_permissions: List[str]

class FacebookPageConnectionResponse(FacebookPageConnectionBase):
    id: uuid.UUID
    shopivell_user_id: uuid.UUID
    status: SocialConnectionStatus
    is_token_valid: bool
    created_at: datetime
    updated_at: datetime

class SocialPostBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    message: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    link: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    store_id: Optional[uuid.UUID] = None
    page_connection_id: uuid.UUID

class SocialPostCreate(SocialPostBase):
    pass

class SocialPostResponse(SocialPostBase):
    id: uuid.UUID
    shopivell_user_id: uuid.UUID
    facebook_post_id: Optional[str] = None
    status: str
    platform: SocialPlatform
    posted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class OAuthCallback(BaseModel):
    code: str
    state: Optional[str] = None

class FacebookOAuthURL(BaseModel):
    auth_url: str

class PostToFacebook(BaseModel):
    message: str
    media_file: Optional[str] = None  # Base64 encoded or URL
    media_type: Optional[str] = None  # image, video
    link: Optional[str] = None
    page_id: str
    store_id: Optional[uuid.UUID] = None

class FacebookPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    success: bool
    facebook_post_id: Optional[str] = None
    message: str
    posted_at: Optional[datetime] = None

class FacebookOAuthURL(BaseModel):
    # This must match the field name returned by your endpoint function
    auth_url: str 
    # Add any other fields if your endpoint returns them
    # For example, to pass the state parameter:
    # state: Optional[str] = None
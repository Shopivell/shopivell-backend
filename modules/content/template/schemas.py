from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

# --- A. Request Input Schemas (Unchanged) ---

class TextToImageCreate(BaseModel):
    """Schema for T2I requests (JSON body)."""
    prompt_text: str
    
    model_config = ConfigDict(extra='allow')

class TemplateRequestCreate(BaseModel):
    """Schema for Template-based requests (JSON body)."""
    # This ID now acts as a simple identifier/name for a predefined set of internal instructions.
    template_name: str 
    # The user can still provide a small prompt to customize the template
    user_prompt: str
    
    model_config = ConfigDict(extra='allow')

# --- B. Response and List Schemas ---

class ImageGenerationRequestResponse(BaseModel):
    """Schema for returning a completed or pending request."""
    id: UUID
    request_type: str  # e.g., 'template_i2i', 'prompt_t2i', 'prompt_i2i'
    template_name: Optional[str] = None # NEW FIELD ADDED HERE
    input_image_urls: List[str] 
    prompt_text: str
    output_image_url: Optional[str] = None
    status: str
    model_name: Optional[str] = None
    generation_time_ms: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

class ImageGenerationRequestListResponse(BaseModel):
    """Schema for listing multiple requests with pagination info."""
    requests: List[ImageGenerationRequestResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int

# Update Schema
class TemplateUpdate(BaseModel):
    base_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    base_image_url: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(prompt_t2i|prompt_i2i)$")
    
    model_config = ConfigDict(extra='forbid')

# Response Schema
class TemplateResponse(BaseModel):
    id: UUID
    template_name: str
    base_prompt: str
    negative_prompt: Optional[str] = None
    base_image_url: Optional[str] = None
    type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
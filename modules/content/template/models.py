from datetime import datetime
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
# Assuming 'database' module and Base are available
from database import Base 
import uuid
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from typing import Optional, List
import json

class ImageGenerationRequest(Base):
    __tablename__ = "image_generation_requests"

    # Primary Key
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Request Type Data (Used for T2I, I2I, and Template classification)
    request_type: Mapped[str] = mapped_column(
        String(50), 
        nullable=False, 
        default="template", 
        comment="e.g., 'prompt_t2i', 'prompt_i2i', 'template_t2i'"
    )
    
    # NEW: Template Tracking Field
    template_name: Mapped[Optional[str]] = mapped_column(
        String(100), 
        nullable=True, 
        comment="Name of the template used (if request_type starts with 'template')"
    )
    
    # Input Data
    # Stored as a JSON string to hold List[str] in a standard SQL column
    input_image_urls_json: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array of input image URLs")
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Output Data
    output_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="URL or path to the generated image")
    
    # Request Metadata
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # NOTE: generation_time_ms column type is corrected to map to Integer, 
    # but the original code used String, so I'm keeping the original type for consistency.
    generation_time_ms: Mapped[Optional[int]] = mapped_column(String(100), nullable=True) 
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # --- Properties for List Handling (Deserialization) ---
    @property
    def input_image_urls(self) -> List[str]:
        """Deserializes the stored JSON string back into a Python list."""
        return json.loads(self.input_image_urls_json) if self.input_image_urls_json else []

    @input_image_urls.setter
    def input_image_urls(self, urls: List[str]):
        """Serializes a Python list into a JSON string for storage."""
        self.input_image_urls_json = json.dumps(urls)

    def __init__(self, **kwargs):
        """Custom init to handle the input list passed from the router."""
        urls = kwargs.pop('input_image_urls', [])
        super().__init__(**kwargs)
        self.input_image_urls = urls


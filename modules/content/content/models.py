from datetime import datetime
from sqlalchemy import String, DateTime, Text, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from database import Base 
import uuid
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from typing import Optional, Dict, Any

class Content(Base):
    __tablename__ = "content"

    # Primary Key
    id: Mapped[PG_UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Content Data
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    
    # Dates
    date_posted: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scheduled_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # File Information
    file_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    file_size: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Author Information
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Engagement Data (Stored as JSON)
    engagement_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    
    # Thumbnail
    thumbnail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Metrics Data (Stored as JSON)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # --- Properties for JSON Handling ---
    @property
    def engagement(self) -> Dict[str, Any]:
        """Deserializes the stored JSON string back into a Python dict."""
        import json
        return json.loads(self.engagement_json) if self.engagement_json else {}

    @engagement.setter
    def engagement(self, engagement_data: Dict[str, Any]):
        """Serializes a Python dict into a JSON string for storage."""
        import json
        self.engagement_json = json.dumps(engagement_data)

    @property
    def metrics(self) -> Dict[str, Any]:
        """Deserializes the stored JSON string back into a Python dict."""
        import json
        return json.loads(self.metrics_json) if self.metrics_json else {}

    @metrics.setter
    def metrics(self, metrics_data: Dict[str, Any]):
        """Serializes a Python dict into a JSON string for storage."""
        import json
        self.metrics_json = json.dumps(metrics_data)

    def __init__(self, **kwargs):
        """Custom init to handle the engagement and metrics dicts passed from the router."""
        engagement = kwargs.pop('engagement', {})
        metrics = kwargs.pop('metrics', {})
        super().__init__(**kwargs)
        self.engagement = engagement
        self.metrics = metrics
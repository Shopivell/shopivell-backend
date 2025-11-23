from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from database import Base


class SocialMediaConfig(Base):
    __tablename__ = "social_media_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # facebook, instagram, twitter
    
    # Platform-specific settings
    enabled = Column(Boolean, default=False)
    page_id = Column(String(255))
    account_id = Column(String(255))
    access_token = Column(Text)
    api_key = Column(String(255))
    api_secret = Column(String(255))
    
    # Additional settings
    auto_post = Column(Boolean, default=True)
    posting_schedule = Column(JSON)  # {"time": "14:00", "days": ["mon", "wed", "fri"]}
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class SocialPost(Base):
    __tablename__ = "social_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    
    # Content
    caption = Column(Text)
    hashtags = Column(JSON)  # Array of hashtags
    cta = Column(String(500))
    image_url = Column(String(500))
    
    # Platforms where posted
    platforms = Column(JSON)  # Array of platform results
    
    # Status
    status = Column(String(50), default="draft")  # draft, approved, published, rejected
    approved_at = Column(DateTime(timezone=True))
    published_at = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WorkflowLog(Base):
    __tablename__ = "workflow_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    workflow_id = Column(String(255))
    execution_id = Column(String(255))
    
    # Results
    status = Column(String(50))  # success, failed, rejected
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    message = Column(Text)
    
    # Timing
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

class ErrorLog(Base):
    __tablename__ = "error_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"))
    workflow_id = Column(String(255))
    execution_id = Column(String(255))
    
    # Error details
    error_type = Column(String(255))
    error_message = Column(Text)
    stack_trace = Column(Text)
    
    # Context
    request_data = Column(JSON)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
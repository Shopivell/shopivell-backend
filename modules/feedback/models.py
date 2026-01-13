# modules/feedback/models.py
"""
SQLAlchemy models for feedback, bug reports, and feature requests.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class Feedback(Base):
    """Model for user feedback, bug reports, and feature requests."""
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True)

    type = Column(String(50), nullable=False)  # bug, feature, feedback, improvement, question
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)

    # Optional context
    page_url = Column(String(500), nullable=True)
    browser_info = Column(Text, nullable=True)
    screenshot_url = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    steps_to_reproduce = Column(Text, nullable=True)

    # Status and priority
    status = Column(String(50), default="new")  # new, in_review, in_progress, completed, closed, wont_fix
    priority = Column(String(50), default="medium")  # low, medium, high, critical

    # Admin response
    admin_response = Column(Text, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    responded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Public voting
    upvotes = Column(Integer, default=0)
    is_public = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="feedback_items")
    store = relationship("Store", backref="feedback_items")
    comments = relationship("FeedbackComment", back_populates="feedback", cascade="all, delete-orphan")
    votes = relationship("FeedbackVote", back_populates="feedback", cascade="all, delete-orphan")


class FeedbackComment(Base):
    """Model for comments on feedback items."""
    __tablename__ = "feedback_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id = Column(UUID(as_uuid=True), ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    comment = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    feedback = relationship("Feedback", back_populates="comments")
    user = relationship("User", backref="feedback_comments")


class FeedbackVote(Base):
    """Model for tracking user votes on public feedback."""
    __tablename__ = "feedback_votes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id = Column(UUID(as_uuid=True), ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    feedback = relationship("Feedback", back_populates="votes")
    user = relationship("User", backref="feedback_votes")

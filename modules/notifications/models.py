"""
Notification Models for Shopivell Platform

Handles notifications for:
- Hot leads (lead score >= 80)
- Handoff requests (bot can't answer)
- Unanswered queries (no knowledge match)
- New messages
- System notifications
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


class Notification(Base):
    """
    Notification model for store owners and users.

    Types:
    - hot_lead: Lead score >= 80, high priority
    - handoff: Bot can't answer, needs human, urgent priority
    - unanswered: No knowledge match, high priority
    - new_message: New inbound message, normal priority
    - system: System notifications, varies
    """
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    recipient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    # Notification content
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50), nullable=False, index=True)  # hot_lead, handoff, unanswered, new_message, system
    priority = Column(String(20), default="normal")  # low, normal, high, urgent

    # Related entity for navigation
    related_entity_type = Column(String(50), nullable=True)  # lead, conversation, task, product
    related_entity_id = Column(UUID(as_uuid=True), nullable=True)

    # Additional context data
    phone_number = Column(String(50), nullable=True)  # For lead/conversation notifications
    lead_score = Column(Integer, nullable=True)  # For hot lead notifications
    query_text = Column(Text, nullable=True)  # For unanswered query notifications

    # Status
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)

    # Action
    action_url = Column(String(500), nullable=True)  # Link to related page in frontend
    action_data = Column(JSON, nullable=True)  # Extra data for frontend actions

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", backref="notifications")
    recipient = relationship("User", backref="notifications")

    def __repr__(self):
        return f"<Notification {self.id} - {self.type}: {self.title[:30]}>"

    def to_dict(self):
        """Convert to dictionary for API response"""
        return {
            "id": str(self.id),
            "store_id": str(self.store_id),
            "recipient_id": str(self.recipient_id) if self.recipient_id else None,
            "title": self.title,
            "message": self.message,
            "type": self.type,
            "priority": self.priority,
            "related_entity_type": self.related_entity_type,
            "related_entity_id": str(self.related_entity_id) if self.related_entity_id else None,
            "phone_number": self.phone_number,
            "lead_score": self.lead_score,
            "is_read": self.is_read,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "action_url": self.action_url,
            "action_data": self.action_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class NotificationPreferences(Base):
    """
    User notification preferences.
    Controls how and when notifications are sent.
    """
    __tablename__ = "notification_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True)

    # In-app notifications
    in_app_enabled = Column(Boolean, default=True)

    # Email notifications
    email_enabled = Column(Boolean, default=True)
    email_address = Column(String(255), nullable=True)

    # SMS/WhatsApp notifications
    sms_enabled = Column(Boolean, default=False)
    sms_phone = Column(String(50), nullable=True)

    # Notification type preferences
    notify_hot_leads = Column(Boolean, default=True)
    notify_handoffs = Column(Boolean, default=True)
    notify_unanswered = Column(Boolean, default=True)
    notify_new_messages = Column(Boolean, default=False)  # Can be noisy
    notify_system = Column(Boolean, default=True)

    # Quiet hours (optional)
    quiet_hours_enabled = Column(Boolean, default=False)
    quiet_hours_start = Column(String(5), nullable=True)  # "22:00"
    quiet_hours_end = Column(String(5), nullable=True)  # "08:00"

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", backref="notification_preferences")

    def __repr__(self):
        return f"<NotificationPreferences user={self.user_id}>"

"""
Notification Schemas for API validation and serialization.
"""

from datetime import datetime
from typing import Optional, List, Any, Dict
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum


class NotificationType(str, Enum):
    """Notification types"""
    HOT_LEAD = "hot_lead"
    HANDOFF = "handoff"
    UNANSWERED = "unanswered"
    NEW_MESSAGE = "new_message"
    SYSTEM = "system"


class NotificationPriority(str, Enum):
    """Notification priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationCreate(BaseModel):
    """Schema for creating a notification"""
    store_id: UUID
    recipient_id: Optional[UUID] = None
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[UUID] = None
    phone_number: Optional[str] = None
    lead_score: Optional[int] = None
    query_text: Optional[str] = None
    action_url: Optional[str] = None
    action_data: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class NotificationResponse(BaseModel):
    """Schema for notification response"""
    id: UUID
    store_id: UUID
    recipient_id: Optional[UUID] = None
    title: str
    message: str
    type: str
    priority: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[UUID] = None
    phone_number: Optional[str] = None
    lead_score: Optional[int] = None
    is_read: bool
    read_at: Optional[datetime] = None
    action_url: Optional[str] = None
    action_data: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationList(BaseModel):
    """Schema for paginated notification list"""
    notifications: List[NotificationResponse]
    unread_count: int
    total: int
    page: int = 1
    page_size: int = 20


class NotificationUnreadCount(BaseModel):
    """Schema for unread count response"""
    unread_count: int
    by_type: Dict[str, int] = {}  # Count per notification type


class NotificationMarkRead(BaseModel):
    """Schema for marking notification as read"""
    notification_ids: Optional[List[UUID]] = None  # If None, mark all as read


class NotificationFilter(BaseModel):
    """Schema for filtering notifications"""
    type: Optional[NotificationType] = None
    priority: Optional[NotificationPriority] = None
    is_read: Optional[bool] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


# Notification Preferences Schemas

class NotificationPreferencesUpdate(BaseModel):
    """Schema for updating notification preferences"""
    in_app_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    email_address: Optional[str] = None
    sms_enabled: Optional[bool] = None
    sms_phone: Optional[str] = None
    notify_hot_leads: Optional[bool] = None
    notify_handoffs: Optional[bool] = None
    notify_unanswered: Optional[bool] = None
    notify_new_messages: Optional[bool] = None
    notify_system: Optional[bool] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None


class NotificationPreferencesResponse(BaseModel):
    """Schema for notification preferences response"""
    id: UUID
    user_id: UUID
    in_app_enabled: bool = True
    email_enabled: bool = True
    email_address: Optional[str] = None
    sms_enabled: bool = False
    sms_phone: Optional[str] = None
    notify_hot_leads: bool = True
    notify_handoffs: bool = True
    notify_unanswered: bool = True
    notify_new_messages: bool = False
    notify_system: bool = True
    quiet_hours_enabled: bool = False
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None

    class Config:
        from_attributes = True


# WebSocket Event Schemas

class WebSocketNotificationEvent(BaseModel):
    """Schema for WebSocket notification events"""
    event: str = "notification"  # notification, read, delete
    notification: Optional[NotificationResponse] = None
    notification_id: Optional[UUID] = None
    unread_count: int = 0

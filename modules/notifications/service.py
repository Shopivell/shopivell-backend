"""
Notification Service for Shopivell Platform

Handles creation and management of notifications for:
- Hot leads (score >= 80)
- Handoff requests (bot can't answer)
- Unanswered queries (no knowledge match)
- New messages
- System notifications
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from .models import Notification, NotificationPreferences
from .schemas import NotificationType, NotificationPriority

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for creating and managing notifications"""

    def __init__(self, store_id: UUID):
        self.store_id = store_id

    async def create_notification(
        self,
        db: Session,
        title: str,
        message: str,
        notification_type: NotificationType,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        recipient_id: Optional[UUID] = None,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[UUID] = None,
        phone_number: Optional[str] = None,
        lead_score: Optional[int] = None,
        query_text: Optional[str] = None,
        action_url: Optional[str] = None,
        action_data: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        """Create a new notification"""
        notification = Notification(
            store_id=self.store_id,
            recipient_id=recipient_id,
            title=title,
            message=message,
            type=notification_type.value,
            priority=priority.value,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            phone_number=phone_number,
            lead_score=lead_score,
            query_text=query_text,
            action_url=action_url,
            action_data=action_data,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)

        logger.info(f"Created notification: {notification_type.value} - {title}")
        return notification

    async def create_hot_lead_notification(
        self,
        db: Session,
        phone_number: str,
        lead_score: int,
        interests: List[str] = None,
        lead_id: Optional[UUID] = None,
    ) -> Notification:
        """Create notification for hot lead (score >= 80)"""
        interests_str = ", ".join(interests) if interests else "Not specified"

        return await self.create_notification(
            db=db,
            title=f"Hot Lead Alert! Score: {lead_score}",
            message=f"Lead {phone_number} scored {lead_score}/100. Interests: {interests_str}. This lead is ready for follow-up!",
            notification_type=NotificationType.HOT_LEAD,
            priority=NotificationPriority.HIGH,
            phone_number=phone_number,
            lead_score=lead_score,
            related_entity_type="lead",
            related_entity_id=lead_id,
            action_url=f"/messaging?phone={phone_number}",
            action_data={
                "phone_number": phone_number,
                "lead_score": lead_score,
                "interests": interests,
            },
        )

    async def create_handoff_notification(
        self,
        db: Session,
        phone_number: str,
        reason: str,
        last_query: Optional[str] = None,
        conversation_id: Optional[UUID] = None,
    ) -> Notification:
        """Create notification for handoff request (bot can't answer)"""
        return await self.create_notification(
            db=db,
            title="Human Assistance Needed",
            message=f"Customer {phone_number} needs human assistance. Reason: {reason}",
            notification_type=NotificationType.HANDOFF,
            priority=NotificationPriority.URGENT,
            phone_number=phone_number,
            query_text=last_query,
            related_entity_type="conversation",
            related_entity_id=conversation_id,
            action_url=f"/messaging?phone={phone_number}",
            action_data={
                "phone_number": phone_number,
                "reason": reason,
                "last_query": last_query,
            },
        )

    async def create_unanswered_query_notification(
        self,
        db: Session,
        phone_number: str,
        query_text: str,
        conversation_id: Optional[UUID] = None,
    ) -> Notification:
        """Create notification for unanswered query (no knowledge match)"""
        return await self.create_notification(
            db=db,
            title="Unanswered Customer Query",
            message=f"Bot couldn't answer: \"{query_text[:100]}...\" from {phone_number}. Please respond or add to knowledge base.",
            notification_type=NotificationType.UNANSWERED,
            priority=NotificationPriority.HIGH,
            phone_number=phone_number,
            query_text=query_text,
            related_entity_type="conversation",
            related_entity_id=conversation_id,
            action_url=f"/messaging?phone={phone_number}",
            action_data={
                "phone_number": phone_number,
                "query_text": query_text,
                "suggestion": "Add relevant information to your product catalog or knowledge base",
            },
        )

    async def create_new_message_notification(
        self,
        db: Session,
        phone_number: str,
        message_preview: str,
        conversation_id: Optional[UUID] = None,
    ) -> Notification:
        """Create notification for new inbound message"""
        return await self.create_notification(
            db=db,
            title="New Message",
            message=f"New message from {phone_number}: \"{message_preview[:50]}...\"",
            notification_type=NotificationType.NEW_MESSAGE,
            priority=NotificationPriority.NORMAL,
            phone_number=phone_number,
            related_entity_type="conversation",
            related_entity_id=conversation_id,
            action_url=f"/messaging?phone={phone_number}",
            action_data={
                "phone_number": phone_number,
                "message_preview": message_preview,
            },
        )

    def get_unread_count(self, db: Session) -> Dict[str, int]:
        """Get unread notification count, total and by type"""
        # Total unread
        total = db.query(func.count(Notification.id)).filter(
            Notification.store_id == self.store_id,
            Notification.is_read == False
        ).scalar() or 0

        # Count by type
        by_type = {}
        type_counts = db.query(
            Notification.type,
            func.count(Notification.id)
        ).filter(
            Notification.store_id == self.store_id,
            Notification.is_read == False
        ).group_by(Notification.type).all()

        for notification_type, count in type_counts:
            by_type[notification_type] = count

        return {
            "unread_count": total,
            "by_type": by_type
        }

    def get_notifications(
        self,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        notification_type: Optional[str] = None,
        is_read: Optional[bool] = None,
        priority: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated notifications with filters"""
        query = db.query(Notification).filter(
            Notification.store_id == self.store_id
        )

        # Apply filters
        if notification_type:
            query = query.filter(Notification.type == notification_type)
        if is_read is not None:
            query = query.filter(Notification.is_read == is_read)
        if priority:
            query = query.filter(Notification.priority == priority)

        # Get total count
        total = query.count()

        # Get unread count
        unread_count = db.query(func.count(Notification.id)).filter(
            Notification.store_id == self.store_id,
            Notification.is_read == False
        ).scalar() or 0

        # Apply pagination and ordering
        notifications = query.order_by(
            Notification.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "notifications": notifications,
            "unread_count": unread_count,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def mark_as_read(
        self,
        db: Session,
        notification_ids: Optional[List[UUID]] = None
    ) -> int:
        """Mark notifications as read. If no IDs provided, mark all as read."""
        query = db.query(Notification).filter(
            Notification.store_id == self.store_id,
            Notification.is_read == False
        )

        if notification_ids:
            query = query.filter(Notification.id.in_(notification_ids))

        now = datetime.utcnow()
        updated = query.update(
            {"is_read": True, "read_at": now},
            synchronize_session=False
        )
        db.commit()

        logger.info(f"Marked {updated} notifications as read for store {self.store_id}")
        return updated

    def delete_notification(self, db: Session, notification_id: UUID) -> bool:
        """Delete a notification"""
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.store_id == self.store_id
        ).first()

        if notification:
            db.delete(notification)
            db.commit()
            logger.info(f"Deleted notification {notification_id}")
            return True
        return False

    def delete_old_notifications(self, db: Session, days: int = 30) -> int:
        """Delete notifications older than specified days"""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)

        deleted = db.query(Notification).filter(
            Notification.store_id == self.store_id,
            Notification.created_at < cutoff
        ).delete(synchronize_session=False)

        db.commit()
        logger.info(f"Deleted {deleted} old notifications for store {self.store_id}")
        return deleted


# WebSocket Connection Manager for real-time notifications
class NotificationConnectionManager:
    """Manages WebSocket connections for real-time notifications"""

    def __init__(self):
        # Store connections by store_id
        self.active_connections: Dict[str, List[Any]] = {}

    async def connect(self, websocket, store_id: str):
        """Accept WebSocket connection and add to store's connection list"""
        await websocket.accept()
        if store_id not in self.active_connections:
            self.active_connections[store_id] = []
        self.active_connections[store_id].append(websocket)
        logger.info(f"WebSocket connected for store {store_id}")

    def disconnect(self, websocket, store_id: str):
        """Remove WebSocket connection from store's connection list"""
        if store_id in self.active_connections:
            if websocket in self.active_connections[store_id]:
                self.active_connections[store_id].remove(websocket)
            if not self.active_connections[store_id]:
                del self.active_connections[store_id]
        logger.info(f"WebSocket disconnected for store {store_id}")

    async def broadcast_to_store(self, store_id: str, message: dict):
        """Broadcast message to all connections for a store"""
        if store_id in self.active_connections:
            import json
            message_str = json.dumps(message)
            for connection in self.active_connections[store_id]:
                try:
                    await connection.send_text(message_str)
                except Exception as e:
                    logger.error(f"Error broadcasting to store {store_id}: {e}")

    async def send_notification(
        self,
        store_id: str,
        notification: Notification,
        unread_count: int
    ):
        """Send a new notification to all store connections"""
        await self.broadcast_to_store(store_id, {
            "event": "notification",
            "notification": notification.to_dict(),
            "unread_count": unread_count
        })


# Global connection manager instance
notification_manager = NotificationConnectionManager()

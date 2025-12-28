"""
Notification Router for Shopivell Platform

API endpoints for managing notifications:
- List notifications (paginated, with filters)
- Get unread count
- Mark as read (single or all)
- Delete notifications
- WebSocket for real-time notifications
"""

import logging
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from modules.users.models import User

from .models import Notification, NotificationPreferences
from .schemas import (
    NotificationResponse,
    NotificationList,
    NotificationUnreadCount,
    NotificationMarkRead,
    NotificationPreferencesUpdate,
    NotificationPreferencesResponse,
    NotificationType,
    NotificationPriority,
)
from .service import NotificationService, notification_manager

logger = logging.getLogger(__name__)

notification_router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ============================================================================
# Notification Endpoints
# ============================================================================

@notification_router.get("/store/{store_id}", response_model=NotificationList)
async def get_notifications(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    notification_type: Optional[str] = None,
    is_read: Optional[bool] = None,
    priority: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get paginated notifications for a store.

    Filters:
    - notification_type: hot_lead, handoff, unanswered, new_message, system
    - is_read: true/false
    - priority: low, normal, high, urgent
    """
    # Verify user has access to this store
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store's notifications")

    service = NotificationService(store_id)
    result = service.get_notifications(
        db=db,
        page=page,
        page_size=page_size,
        notification_type=notification_type,
        is_read=is_read,
        priority=priority,
    )

    # Convert ORM objects to response models
    notifications = [
        NotificationResponse(
            id=n.id,
            store_id=n.store_id,
            recipient_id=n.recipient_id,
            title=n.title,
            message=n.message,
            type=n.type,
            priority=n.priority,
            related_entity_type=n.related_entity_type,
            related_entity_id=n.related_entity_id,
            phone_number=n.phone_number,
            lead_score=n.lead_score,
            is_read=n.is_read,
            read_at=n.read_at,
            action_url=n.action_url,
            action_data=n.action_data,
            created_at=n.created_at,
        )
        for n in result["notifications"]
    ]

    return NotificationList(
        notifications=notifications,
        unread_count=result["unread_count"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@notification_router.get("/store/{store_id}/unread-count", response_model=NotificationUnreadCount)
async def get_unread_count(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get unread notification count for a store, total and by type."""
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store's notifications")

    service = NotificationService(store_id)
    result = service.get_unread_count(db)

    return NotificationUnreadCount(
        unread_count=result["unread_count"],
        by_type=result["by_type"],
    )


@notification_router.post("/store/{store_id}/mark-read")
async def mark_notifications_read(
    store_id: UUID,
    request: NotificationMarkRead,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark notifications as read.

    If notification_ids is provided, marks only those notifications.
    If notification_ids is None or empty, marks all notifications as read.
    """
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store's notifications")

    service = NotificationService(store_id)
    updated = service.mark_as_read(db, request.notification_ids)

    # Broadcast updated unread count via WebSocket
    new_count = service.get_unread_count(db)
    await notification_manager.broadcast_to_store(str(store_id), {
        "event": "read",
        "notification_ids": [str(nid) for nid in request.notification_ids] if request.notification_ids else None,
        "unread_count": new_count["unread_count"],
    })

    return {"message": f"Marked {updated} notifications as read", "updated": updated}


@notification_router.post("/{notification_id}/mark-read")
async def mark_single_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    # Get the notification to verify ownership
    notification = db.query(Notification).filter(Notification.id == notification_id).first()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if not current_user.store_id or str(current_user.store_id) != str(notification.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this notification")

    service = NotificationService(notification.store_id)
    updated = service.mark_as_read(db, [notification_id])

    # Broadcast updated unread count
    new_count = service.get_unread_count(db)
    await notification_manager.broadcast_to_store(str(notification.store_id), {
        "event": "read",
        "notification_ids": [str(notification_id)],
        "unread_count": new_count["unread_count"],
    })

    return {"message": "Notification marked as read", "updated": updated}


@notification_router.delete("/{notification_id}")
async def delete_notification(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a notification."""
    notification = db.query(Notification).filter(Notification.id == notification_id).first()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if not current_user.store_id or str(current_user.store_id) != str(notification.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to delete this notification")

    store_id = notification.store_id
    service = NotificationService(store_id)
    deleted = service.delete_notification(db, notification_id)

    if deleted:
        # Broadcast updated unread count
        new_count = service.get_unread_count(db)
        await notification_manager.broadcast_to_store(str(store_id), {
            "event": "delete",
            "notification_id": str(notification_id),
            "unread_count": new_count["unread_count"],
        })
        return {"message": "Notification deleted"}

    raise HTTPException(status_code=404, detail="Notification not found")


@notification_router.delete("/store/{store_id}/old")
async def delete_old_notifications(
    store_id: UUID,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete notifications older than specified days."""
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store's notifications")

    service = NotificationService(store_id)
    deleted = service.delete_old_notifications(db, days)

    return {"message": f"Deleted {deleted} old notifications", "deleted": deleted}


# ============================================================================
# Notification Preferences Endpoints
# ============================================================================

@notification_router.get("/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get notification preferences for the current user."""
    prefs = db.query(NotificationPreferences).filter(
        NotificationPreferences.user_id == current_user.id
    ).first()

    if not prefs:
        # Create default preferences if not exists
        prefs = NotificationPreferences(
            user_id=current_user.id,
            store_id=current_user.store_id,
        )
        db.add(prefs)
        db.commit()
        db.refresh(prefs)

    return prefs


@notification_router.put("/preferences", response_model=NotificationPreferencesResponse)
async def update_notification_preferences(
    request: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update notification preferences for the current user."""
    prefs = db.query(NotificationPreferences).filter(
        NotificationPreferences.user_id == current_user.id
    ).first()

    if not prefs:
        prefs = NotificationPreferences(
            user_id=current_user.id,
            store_id=current_user.store_id,
        )
        db.add(prefs)

    # Update only provided fields
    update_data = request.dict(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(prefs, field, value)

    db.commit()
    db.refresh(prefs)

    return prefs


# ============================================================================
# WebSocket Endpoint for Real-time Notifications
# ============================================================================

@notification_router.websocket("/ws/{store_id}")
async def notification_websocket(
    websocket: WebSocket,
    store_id: str,
    db: Session = Depends(get_db),
):
    """
    WebSocket endpoint for real-time notifications.

    Events sent to client:
    - notification: New notification created
    - read: Notification(s) marked as read
    - delete: Notification deleted

    Each event includes updated unread_count.
    """
    await notification_manager.connect(websocket, store_id)

    try:
        # Send initial unread count
        service = NotificationService(UUID(store_id))
        initial_count = service.get_unread_count(db)
        await websocket.send_json({
            "event": "connected",
            "unread_count": initial_count["unread_count"],
            "by_type": initial_count["by_type"],
        })

        # Keep connection alive
        while True:
            # Wait for any message (ping/pong or disconnect)
            data = await websocket.receive_text()

            # Handle ping
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        notification_manager.disconnect(websocket, store_id)
        logger.info(f"WebSocket client disconnected from store {store_id}")
    except Exception as e:
        logger.error(f"WebSocket error for store {store_id}: {e}")
        notification_manager.disconnect(websocket, store_id)


# ============================================================================
# Helper function for creating notifications from other modules
# ============================================================================

async def create_and_broadcast_notification(
    db: Session,
    store_id: UUID,
    title: str,
    message: str,
    notification_type: NotificationType,
    priority: NotificationPriority = NotificationPriority.NORMAL,
    **kwargs
):
    """
    Helper function to create a notification and broadcast via WebSocket.

    Use this from other modules (e.g., WhatsApp bot) to create notifications.
    """
    service = NotificationService(store_id)
    notification = await service.create_notification(
        db=db,
        title=title,
        message=message,
        notification_type=notification_type,
        priority=priority,
        **kwargs
    )

    # Get updated unread count
    unread_count = service.get_unread_count(db)

    # Broadcast to WebSocket clients
    await notification_manager.send_notification(
        store_id=str(store_id),
        notification=notification,
        unread_count=unread_count["unread_count"]
    )

    return notification

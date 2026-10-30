"""
CRM Service for AI Sales Bot

Handles:
- Follow-up task creation
- Hot lead notifications
- Handoff workflow
- Lead management
"""

import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy.orm import Session

from .models import (
    CRMTask, WhatsAppLead, WhatsAppConversation,
    StoreBotConfig, WhatsAppConversationMessage
)
from modules.notifications.service import NotificationService, notification_manager
from modules.notifications.models import Notification
from modules.notifications.schemas import NotificationType, NotificationPriority

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    FOLLOW_UP = "follow_up"
    HANDOFF = "handoff"
    CALLBACK = "callback"
    MEETING = "meeting"
    QUOTE = "quote"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CRMService:
    """
    CRM service for managing leads, tasks, and notifications.
    """

    def __init__(self, store_id: UUID, db: Session):
        self.store_id = store_id
        self.db = db
        self.notification_service = NotificationService(store_id=store_id)

    # =========================================================================
    # Task Management
    # =========================================================================

    def create_task(
        self,
        title: str,
        task_type: TaskType,
        priority: TaskPriority = TaskPriority.NORMAL,
        description: Optional[str] = None,
        phone_number: Optional[str] = None,
        lead_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        assigned_to: Optional[UUID] = None,
        due_date: Optional[datetime] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> CRMTask:
        """Create a new CRM task"""
        task = CRMTask(
            store_id=self.store_id,
            title=title,
            description=description,
            task_type=task_type.value,
            priority=priority.value,
            status=TaskStatus.PENDING.value,
            phone_number=phone_number,
            lead_id=lead_id,
            conversation_id=conversation_id,
            assigned_to=assigned_to,
            due_date=due_date or datetime.utcnow() + timedelta(hours=24),
            context=context
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

        logger.info(f"Created {task_type.value} task {task.id} for store {self.store_id}")
        return task

    def create_follow_up_task(
        self,
        phone_number: str,
        reason: str,
        lead_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        due_hours: int = 24
    ) -> CRMTask:
        """Create a follow-up task for a lead"""
        return self.create_task(
            title=f"Follow up with {phone_number}",
            task_type=TaskType.FOLLOW_UP,
            priority=priority,
            description=reason,
            phone_number=phone_number,
            lead_id=lead_id,
            conversation_id=conversation_id,
            due_date=datetime.utcnow() + timedelta(hours=due_hours),
            context={"reason": reason}
        )

    def create_handoff_task(
        self,
        phone_number: str,
        reason: str,
        conversation_id: Optional[UUID] = None,
        query_text: Optional[str] = None,
        assigned_to: Optional[UUID] = None
    ) -> CRMTask:
        """Create a handoff task when bot can't answer"""
        task = self.create_task(
            title=f"Human assistance needed for {phone_number}",
            task_type=TaskType.HANDOFF,
            priority=TaskPriority.URGENT,
            description=f"Bot couldn't answer: {query_text or reason}",
            phone_number=phone_number,
            conversation_id=conversation_id,
            assigned_to=assigned_to,
            due_date=datetime.utcnow() + timedelta(hours=1),  # Urgent - due in 1 hour
            context={
                "reason": reason,
                "query": query_text,
                "requires_human": True
            }
        )

        logger.info(f"Created handoff task {task.id} for {phone_number}")
        return task

    def create_callback_task(
        self,
        phone_number: str,
        requested_time: Optional[datetime] = None,
        conversation_id: Optional[UUID] = None,
        notes: Optional[str] = None
    ) -> CRMTask:
        """Create a callback request task"""
        return self.create_task(
            title=f"Callback requested by {phone_number}",
            task_type=TaskType.CALLBACK,
            priority=TaskPriority.HIGH,
            description=notes,
            phone_number=phone_number,
            conversation_id=conversation_id,
            due_date=requested_time or datetime.utcnow() + timedelta(hours=2),
            context={"callback_requested": True, "notes": notes}
        )

    def create_quote_task(
        self,
        phone_number: str,
        products_interested: List[str],
        conversation_id: Optional[UUID] = None,
        lead_id: Optional[UUID] = None
    ) -> CRMTask:
        """Create a quote request task"""
        return self.create_task(
            title=f"Quote requested by {phone_number}",
            task_type=TaskType.QUOTE,
            priority=TaskPriority.HIGH,
            description=f"Interested in: {', '.join(products_interested)}",
            phone_number=phone_number,
            lead_id=lead_id,
            conversation_id=conversation_id,
            due_date=datetime.utcnow() + timedelta(hours=4),
            context={"products": products_interested}
        )

    def complete_task(
        self,
        task_id: UUID,
        completed_by: UUID,
        notes: Optional[str] = None
    ) -> Optional[CRMTask]:
        """Mark a task as completed"""
        task = self.db.query(CRMTask).filter(
            CRMTask.id == task_id,
            CRMTask.store_id == self.store_id
        ).first()

        if not task:
            return None

        task.status = TaskStatus.COMPLETED.value
        task.completed_at = datetime.utcnow()
        task.completed_by = completed_by
        task.completion_notes = notes
        task.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(task)

        logger.info(f"Completed task {task_id}")
        return task

    def get_pending_tasks(
        self,
        task_type: Optional[TaskType] = None,
        priority: Optional[TaskPriority] = None,
        assigned_to: Optional[UUID] = None,
        limit: int = 20
    ) -> List[CRMTask]:
        """Get pending tasks with optional filters"""
        query = self.db.query(CRMTask).filter(
            CRMTask.store_id == self.store_id,
            CRMTask.status == TaskStatus.PENDING.value
        )

        if task_type:
            query = query.filter(CRMTask.task_type == task_type.value)
        if priority:
            query = query.filter(CRMTask.priority == priority.value)
        if assigned_to:
            query = query.filter(CRMTask.assigned_to == assigned_to)

        return query.order_by(CRMTask.due_date).limit(limit).all()

    # =========================================================================
    # Hot Lead Notifications
    # =========================================================================

    async def notify_hot_lead(
        self,
        lead: WhatsAppLead,
        score: float,
        config: Optional[StoreBotConfig] = None,
        conversation_id: Optional[UUID] = None
    ):
        """
        Send notification for a hot lead (score >= threshold).
        Creates in-app notification and optionally email/SMS.
        """
        threshold = config.hot_lead_threshold if config else 80

        if score < threshold:
            logger.debug(f"Score {score} below threshold {threshold}, skipping notification")
            return

        if not config or config.notify_on_hot_lead:
            # Create in-app notification
            notification = await self.notification_service.create_notification(
                db=self.db,
                title="Hot Lead Alert",
                message=f"Lead {lead.phone_number} has reached a score of {score:.0f}! Ready to convert.",
                notification_type=NotificationType.HOT_LEAD,
                priority=NotificationPriority.HIGH,
                related_entity_type="lead",
                related_entity_id=lead.id,
                action_url=f"/messaging/leads/{lead.id}",
                action_data={
                    "phone_number": lead.phone_number,
                    "score": score,
                    "interests": lead.interests,
                    "conversation_id": str(conversation_id) if conversation_id else None
                }
            )

            logger.info(f"Sent hot lead notification for {lead.phone_number} (score: {score})")

            # Create follow-up task
            self.create_follow_up_task(
                phone_number=lead.phone_number,
                reason=f"Hot lead with score {score:.0f}. Ready to convert!",
                lead_id=lead.id,
                conversation_id=conversation_id,
                priority=TaskPriority.HIGH,
                due_hours=1  # Due in 1 hour for hot leads
            )

    # =========================================================================
    # Handoff Notifications
    # =========================================================================

    async def notify_handoff(
        self,
        conversation: WhatsAppConversation,
        reason: str,
        query_text: Optional[str] = None,
        config: Optional[StoreBotConfig] = None
    ):
        """
        Notify store owner when bot can't answer and needs human intervention.
        """
        if not config or config.notify_on_handoff:
            notification = await self.notification_service.create_notification(
                db=self.db,
                title="Human Assistance Needed",
                message=f"Bot couldn't answer query from {conversation.phone_number}: {query_text or reason}",
                notification_type=NotificationType.HANDOFF,
                priority=NotificationPriority.URGENT,
                related_entity_type="conversation",
                related_entity_id=conversation.id,
                action_url=f"/messaging/conversations/{conversation.id}",
                action_data={
                    "phone_number": conversation.phone_number,
                    "reason": reason,
                    "query": query_text
                }
            )

            # Persisting the alert alone does not update connected notification
            # bells. Publish handoffs immediately; hot-lead alerts stay disabled.
            try:
                counts = self.notification_service.get_unread_count(self.db)
                await notification_manager.send_notification(
                    store_id=str(self.store_id),
                    notification=notification,
                    unread_count=counts["unread_count"],
                )
            except Exception:
                logger.exception("Failed to broadcast handoff notification")

            logger.info(f"Sent handoff notification for {conversation.phone_number}")

            # Create handoff task
            self.create_handoff_task(
                phone_number=conversation.phone_number,
                reason=reason,
                conversation_id=conversation.id,
                query_text=query_text
            )

    async def notify_unanswered_query(
        self,
        phone_number: str,
        query_text: str,
        conversation_id: Optional[UUID] = None,
        config: Optional[StoreBotConfig] = None
    ):
        """
        Notify when bot has no knowledge to answer a query.
        This is part of the NO HALLUCINATION policy - bot stays silent and alerts owner.
        """
        if not config or config.notify_on_unanswered:
            notification = await self.notification_service.create_notification(
                db=self.db,
                title="Unanswered Query",
                message=f"Bot couldn't find knowledge to answer: '{query_text[:100]}...' from {phone_number}",
                notification_type=NotificationType.UNANSWERED,
                priority=NotificationPriority.HIGH,
                related_entity_type="conversation",
                related_entity_id=conversation_id,
                action_url=f"/messaging/conversations/{conversation_id}" if conversation_id else "/messaging",
                action_data={
                    "phone_number": phone_number,
                    "query": query_text,
                    "action_needed": "Add to knowledge base or respond manually"
                }
            )

            logger.info(f"Sent unanswered query notification for {phone_number}")

            # Create handoff task for unanswered query
            self.create_handoff_task(
                phone_number=phone_number,
                reason="No knowledge match - needs manual response",
                conversation_id=conversation_id,
                query_text=query_text
            )

    # =========================================================================
    # Lead Management
    # =========================================================================

    def update_lead_score(
        self,
        lead: WhatsAppLead,
        new_score: float,
        scoring_reason: Optional[str] = None
    ) -> WhatsAppLead:
        """Update lead score and status"""
        lead.lead_score = new_score
        lead.scoring_reason = scoring_reason

        # Update status based on score
        if new_score <= 20:
            lead.lead_status = "cold"
        elif new_score <= 40:
            lead.lead_status = "cool"
        elif new_score <= 60:
            lead.lead_status = "warm"
        elif new_score <= 80:
            lead.lead_status = "hot"
        else:
            lead.lead_status = "very_hot"

        lead.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(lead)

        return lead

    def get_or_create_lead(
        self,
        phone_number: str,
        whatsapp_account_id: UUID
    ) -> WhatsAppLead:
        """Get existing lead or create new one"""
        lead = self.db.query(WhatsAppLead).filter(
            WhatsAppLead.whatsapp_account_id == whatsapp_account_id,
            WhatsAppLead.phone_number == phone_number
        ).first()

        if not lead:
            lead = WhatsAppLead(
                whatsapp_account_id=whatsapp_account_id,
                phone_number=phone_number,
                lead_score=0,
                lead_status="new"
            )
            self.db.add(lead)
            self.db.commit()
            self.db.refresh(lead)
            logger.info(f"Created new lead for {phone_number}")

        return lead

    def update_lead_interests(
        self,
        lead: WhatsAppLead,
        interests: List[str]
    ) -> WhatsAppLead:
        """Update lead interests from conversation"""
        current_interests = lead.interests or []

        # Merge and deduplicate
        all_interests = list(set(current_interests + interests))[:10]  # Keep max 10
        lead.interests = all_interests
        lead.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(lead)

        return lead

    # =========================================================================
    # Conversation Management
    # =========================================================================

    def get_or_create_conversation(
        self,
        phone_number: str,
        whatsapp_account_id: Optional[UUID] = None,
    ) -> WhatsAppConversation:
        """Get existing conversation or create new one.

        whatsapp_account_id is NOT NULL on the table; when the caller has it (the normal
        case - every real inbound message comes in on a specific connected account) it must
        be passed so a brand-new phone number doesn't hit an IntegrityError here. Callers
        that reach this before StoreRouter has already created the conversation (which does
        set it) need to pass it explicitly rather than relying on that ordering."""
        conversation = self.db.query(WhatsAppConversation).filter(
            WhatsAppConversation.store_id == self.store_id,
            WhatsAppConversation.phone_number == phone_number
        ).first()

        if not conversation:
            conversation = WhatsAppConversation(
                store_id=self.store_id,
                phone_number=phone_number,
                whatsapp_account_id=whatsapp_account_id,
                status="active"
            )
            self.db.add(conversation)
            self.db.commit()
            self.db.refresh(conversation)
            logger.info(f"Created new conversation for {phone_number}")

        return conversation

    def add_conversation_message(
        self,
        conversation: WhatsAppConversation,
        role: str,
        content: str,
        intent_detected: Optional[str] = None,
        confidence_score: Optional[float] = None,
        fallback_triggered: bool = False,
        message_id: Optional[str] = None
    ) -> WhatsAppConversationMessage:
        """Add a message to conversation history"""
        message = WhatsAppConversationMessage(
            conversation_id=conversation.id,
            role=role,
            content=content,
            intent_detected=intent_detected,
            confidence_score=confidence_score,
            fallback_triggered=fallback_triggered,
            message_id=message_id
        )
        self.db.add(message)

        # Update conversation stats
        conversation.total_messages += 1
        conversation.last_message_at = datetime.utcnow()

        if fallback_triggered:
            conversation.fallback_count += 1

        self.db.commit()
        self.db.refresh(message)

        return message

    def request_handoff(
        self,
        conversation: WhatsAppConversation,
        reason: str
    ) -> WhatsAppConversation:
        """Mark conversation as requiring human handoff"""
        conversation.handoff_requested = True
        conversation.handoff_reason = reason
        conversation.status = "handoff"
        conversation.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(conversation)

        logger.info(f"Handoff requested for conversation {conversation.id}: {reason}")
        return conversation

    def assign_conversation(
        self,
        conversation: WhatsAppConversation,
        user_id: UUID
    ) -> WhatsAppConversation:
        """Assign conversation to a human agent"""
        conversation.assigned_to = user_id
        conversation.status = "handoff"
        conversation.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(conversation)

        logger.info(f"Assigned conversation {conversation.id} to user {user_id}")
        return conversation

    def close_conversation(
        self,
        conversation: WhatsAppConversation
    ) -> WhatsAppConversation:
        """Close a conversation"""
        conversation.status = "closed"
        conversation.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(conversation)

        logger.info(f"Closed conversation {conversation.id}")
        return conversation

    def get_conversation_history(
        self,
        conversation_id: UUID,
        limit: int = 10
    ) -> List[Dict[str, str]]:
        """Get conversation history as list of messages"""
        messages = self.db.query(WhatsAppConversationMessage).filter(
            WhatsAppConversationMessage.conversation_id == conversation_id
        ).order_by(
            WhatsAppConversationMessage.created_at.desc()
        ).limit(limit).all()

        # Return in chronological order
        return [
            {"role": m.role, "content": m.content}
            for m in reversed(messages)
        ]

    # =========================================================================
    # Analytics
    # =========================================================================

    def get_task_stats(self) -> Dict[str, Any]:
        """Get task statistics for the store"""
        from sqlalchemy import func

        total = self.db.query(func.count(CRMTask.id)).filter(
            CRMTask.store_id == self.store_id
        ).scalar() or 0

        pending = self.db.query(func.count(CRMTask.id)).filter(
            CRMTask.store_id == self.store_id,
            CRMTask.status == TaskStatus.PENDING.value
        ).scalar() or 0

        overdue = self.db.query(func.count(CRMTask.id)).filter(
            CRMTask.store_id == self.store_id,
            CRMTask.status == TaskStatus.PENDING.value,
            CRMTask.due_date < datetime.utcnow()
        ).scalar() or 0

        by_type = {}
        type_counts = self.db.query(
            CRMTask.task_type,
            func.count(CRMTask.id)
        ).filter(
            CRMTask.store_id == self.store_id,
            CRMTask.status == TaskStatus.PENDING.value
        ).group_by(CRMTask.task_type).all()

        for task_type, count in type_counts:
            by_type[task_type] = count

        return {
            "total": total,
            "pending": pending,
            "overdue": overdue,
            "by_type": by_type
        }

    def get_lead_stats(self, whatsapp_account_id: UUID) -> Dict[str, Any]:
        """Get lead statistics"""
        from sqlalchemy import func

        total = self.db.query(func.count(WhatsAppLead.id)).filter(
            WhatsAppLead.whatsapp_account_id == whatsapp_account_id
        ).scalar() or 0

        by_status = {}
        status_counts = self.db.query(
            WhatsAppLead.lead_status,
            func.count(WhatsAppLead.id)
        ).filter(
            WhatsAppLead.whatsapp_account_id == whatsapp_account_id
        ).group_by(WhatsAppLead.lead_status).all()

        for status, count in status_counts:
            by_status[status] = count

        avg_score = self.db.query(func.avg(WhatsAppLead.lead_score)).filter(
            WhatsAppLead.whatsapp_account_id == whatsapp_account_id
        ).scalar() or 0

        return {
            "total": total,
            "by_status": by_status,
            "avg_score": round(avg_score, 1),
            "hot_leads": by_status.get("hot", 0) + by_status.get("very_hot", 0)
        }

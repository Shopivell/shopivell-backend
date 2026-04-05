"""
FAQ and Knowledge Base Router

API endpoints for managing:
- FAQs (Frequently Asked Questions)
- Knowledge Base entries
- Bot Configuration
- CRM Tasks
"""

import logging
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from dependencies import get_current_user
from modules.users.models import User
from modules.stores.models import Store

from .models import (
    FAQ, CompanyKnowledge, StoreBotConfig, CRMTask,
    WhatsAppConversation, WhatsAppConversationMessage
)
from .schemas import (
    # FAQ
    FAQCreate, FAQUpdate, FAQResponse, FAQListResponse, FAQFeedback,
    # Bot Config
    StoreBotConfigCreate, StoreBotConfigUpdate, StoreBotConfigResponse,
    # Knowledge
    KnowledgeEntryCreate, KnowledgeEntryUpdate, KnowledgeEntryResponse,
    KnowledgeListResponse, KnowledgeSearchResponse, KnowledgeSearchResult,
    # CRM Tasks
    CRMTaskCreate, CRMTaskUpdate, CRMTaskResponse, CRMTaskListResponse,
    TaskType, TaskPriority, TaskStatus,
    # Conversations
    ConversationResponse, ConversationListResponse, ConversationAssign,
    ConversationMessageResponse
)
from .knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

faq_router = APIRouter(prefix="/api/whatsapp", tags=["FAQ & Knowledge"])


def check_store_access(db: Session, user, store_id: UUID) -> bool:
    """Check if user has access to a store (owns it or owns the agency that owns it)"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return False

    # Convert user.id to UUID if it's a string (from CurrentUser JWT payload)
    user_id = UUID(user.id) if isinstance(user.id, str) else user.id

    # User owns the store directly
    if store.owner_id == user_id:
        return True
    # User owns the agency that owns the store
    if store.agency_id:
        from modules.agency.models import Agency
        agency = db.query(Agency).filter(Agency.id == store.agency_id).first()
        if agency and agency.owner_id == user_id:
            return True
    return False


# =============================================================================
# FAQ Endpoints
# =============================================================================

@faq_router.get("/stores/{store_id}/faqs", response_model=FAQListResponse)
async def get_faqs(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated FAQs for a store with optional filters"""
    # Verify user has access to this store
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    query = db.query(FAQ).filter(FAQ.store_id == store_id)

    # Apply filters
    if category:
        query = query.filter(FAQ.category == category)
    if is_active is not None:
        query = query.filter(FAQ.is_active == is_active)
    if is_featured is not None:
        query = query.filter(FAQ.is_featured == is_featured)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (FAQ.question.ilike(search_term)) | (FAQ.answer.ilike(search_term))
        )

    # Get total
    total = query.count()

    # Apply pagination and ordering
    faqs = query.order_by(FAQ.display_order, FAQ.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return FAQListResponse(
        faqs=[FAQResponse.model_validate(faq) for faq in faqs],
        total=total,
        page=page,
        page_size=page_size
    )


@faq_router.post("/stores/{store_id}/faqs", response_model=FAQResponse, status_code=201)
async def create_faq(
    store_id: UUID,
    faq_data: FAQCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new FAQ and sync to knowledge base"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    # Create FAQ
    faq = FAQ(
        store_id=store_id,
        question=faq_data.question,
        answer=faq_data.answer,
        category=faq_data.category,
        display_order=faq_data.display_order,
        is_active=faq_data.is_active,
        is_featured=faq_data.is_featured
    )
    db.add(faq)
    db.commit()
    db.refresh(faq)

    # Sync to knowledge base if active
    if faq.is_active:
        try:
            knowledge_service = KnowledgeService(store_id)
            knowledge_service.sync_faq_to_knowledge(db, faq)
        except Exception as e:
            logger.error(f"Failed to sync FAQ to knowledge base: {e}")
            # Don't fail the request, just log the error

    logger.info(f"Created FAQ {faq.id} for store {store_id}")
    return FAQResponse.model_validate(faq)


@faq_router.get("/faqs/{faq_id}", response_model=FAQResponse)
async def get_faq(
    faq_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single FAQ by ID"""
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()

    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    if not check_store_access(db, current_user, faq.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this FAQ")

    # Increment view count
    faq.view_count += 1
    db.commit()

    return FAQResponse.model_validate(faq)


@faq_router.put("/faqs/{faq_id}", response_model=FAQResponse)
async def update_faq(
    faq_id: UUID,
    faq_data: FAQUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a FAQ and re-sync to knowledge base"""
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()

    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    if not check_store_access(db, current_user, faq.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to update this FAQ")

    # Update fields
    update_data = faq_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(faq, field, value)

    faq.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(faq)

    # Re-sync to knowledge base
    if faq.is_active:
        try:
            knowledge_service = KnowledgeService(faq.store_id)
            knowledge_service.sync_faq_to_knowledge(db, faq)
        except Exception as e:
            logger.error(f"Failed to sync FAQ to knowledge base: {e}")
    else:
        # Deactivate knowledge entry
        try:
            knowledge_service = KnowledgeService(faq.store_id)
            knowledge_service.delete_faq_knowledge(db, faq)
        except Exception as e:
            logger.error(f"Failed to delete FAQ knowledge: {e}")

    logger.info(f"Updated FAQ {faq_id}")
    return FAQResponse.model_validate(faq)


@faq_router.delete("/faqs/{faq_id}")
async def delete_faq(
    faq_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a FAQ and its knowledge base entry"""
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()

    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    if not check_store_access(db, current_user, faq.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to delete this FAQ")

    # Delete knowledge entry first
    try:
        knowledge_service = KnowledgeService(faq.store_id)
        knowledge_service.delete_faq_knowledge(db, faq)
    except Exception as e:
        logger.error(f"Failed to delete FAQ knowledge: {e}")

    # Delete FAQ
    db.delete(faq)
    db.commit()

    logger.info(f"Deleted FAQ {faq_id}")
    return {"message": "FAQ deleted successfully"}


@faq_router.post("/faqs/{faq_id}/feedback")
async def submit_faq_feedback(
    faq_id: UUID,
    feedback: FAQFeedback,
    db: Session = Depends(get_db),
):
    """Submit feedback on whether a FAQ was helpful (public endpoint)"""
    faq = db.query(FAQ).filter(FAQ.id == faq_id).first()

    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    if feedback.helpful:
        faq.helpful_count += 1
    else:
        faq.not_helpful_count += 1

    db.commit()
    return {"message": "Feedback recorded"}


@faq_router.post("/stores/{store_id}/faqs/sync-all")
async def sync_all_faqs(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync all active FAQs to knowledge base"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    knowledge_service = KnowledgeService(store_id)
    synced_count = knowledge_service.sync_all_faqs_to_knowledge(db)

    return {"message": f"Synced {synced_count} FAQs to knowledge base"}


# =============================================================================
# Bot Configuration Endpoints
# =============================================================================

@faq_router.get("/stores/{store_id}/bot-config", response_model=StoreBotConfigResponse)
async def get_bot_config(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get bot configuration for a store"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store_id).first()

    if not config:
        # Create default config
        config = StoreBotConfig(store_id=store_id)
        db.add(config)
        db.commit()
        db.refresh(config)

    return StoreBotConfigResponse.model_validate(config)


@faq_router.put("/stores/{store_id}/bot-config", response_model=StoreBotConfigResponse)
async def update_bot_config(
    store_id: UUID,
    config_data: StoreBotConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update bot configuration for a store"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store_id).first()

    if not config:
        config = StoreBotConfig(store_id=store_id)
        db.add(config)

    # Update fields
    update_data = config_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(config, field, value)

    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)

    logger.info(f"Updated bot config for store {store_id}")
    return StoreBotConfigResponse.model_validate(config)


# =============================================================================
# Knowledge Base Endpoints
# =============================================================================

@faq_router.get("/stores/{store_id}/knowledge", response_model=KnowledgeListResponse)
async def get_knowledge_entries(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    content_type: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated knowledge base entries"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    query = db.query(CompanyKnowledge).filter(CompanyKnowledge.store_id == store_id)

    if content_type:
        query = query.filter(CompanyKnowledge.content_type == content_type)
    if category:
        query = query.filter(CompanyKnowledge.category == category)
    if is_active is not None:
        query = query.filter(CompanyKnowledge.is_active == is_active)

    total = query.count()
    entries = query.order_by(CompanyKnowledge.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return KnowledgeListResponse(
        entries=[KnowledgeEntryResponse.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size
    )


@faq_router.post("/stores/{store_id}/knowledge", response_model=KnowledgeEntryResponse, status_code=201)
async def create_knowledge_entry(
    store_id: UUID,
    entry_data: KnowledgeEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a manual knowledge base entry"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    knowledge_service = KnowledgeService(store_id)
    knowledge = knowledge_service.add_manual_knowledge(
        db=db,
        content=entry_data.content,
        title=entry_data.title,
        category=entry_data.category,
        tags=entry_data.tags,
        priority=entry_data.priority
    )

    return KnowledgeEntryResponse.model_validate(knowledge)


@faq_router.put("/knowledge/{knowledge_id}", response_model=KnowledgeEntryResponse)
async def update_knowledge_entry(
    knowledge_id: UUID,
    entry_data: KnowledgeEntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a knowledge base entry"""
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.id == knowledge_id).first()

    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    if not check_store_access(db, current_user, knowledge.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to update this entry")

    knowledge_service = KnowledgeService(knowledge.store_id)
    updated = knowledge_service.update_knowledge(
        db=db,
        knowledge_id=knowledge_id,
        **entry_data.model_dump(exclude_unset=True)
    )

    return KnowledgeEntryResponse.model_validate(updated)


@faq_router.delete("/knowledge/{knowledge_id}")
async def delete_knowledge_entry(
    knowledge_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft delete a knowledge base entry"""
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.id == knowledge_id).first()

    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    if not check_store_access(db, current_user, knowledge.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to delete this entry")

    knowledge_service = KnowledgeService(knowledge.store_id)
    knowledge_service.delete_knowledge(db, knowledge_id)

    return {"message": "Knowledge entry deleted"}


@faq_router.post("/stores/{store_id}/knowledge/sync-products")
async def sync_products_to_knowledge(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync all products to knowledge base"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    knowledge_service = KnowledgeService(store_id)
    synced_count = knowledge_service.sync_products_to_knowledge(db)

    return {"message": f"Synced {synced_count} products to knowledge base"}


@faq_router.post("/stores/{store_id}/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    store_id: UUID,
    query: str = Query(..., min_length=3),
    limit: int = Query(5, ge=1, le=20),
    threshold: float = Query(0.4, ge=0, le=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Semantic search in knowledge base"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    knowledge_service = KnowledgeService(store_id)
    results = knowledge_service.search_knowledge(
        db=db,
        query=query,
        threshold=threshold,
        limit=limit
    )

    return KnowledgeSearchResponse(
        query=query,
        results=[
            KnowledgeSearchResult(
                id=k.id,
                title=k.title,
                content=k.content,
                category=k.category,
                content_type=k.content_type,
                similarity_score=score
            )
            for k, score in results
        ],
        total_results=len(results)
    )


@faq_router.get("/stores/{store_id}/knowledge/stats")
async def get_knowledge_stats(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get knowledge base statistics"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    knowledge_service = KnowledgeService(store_id)
    stats = knowledge_service.get_knowledge_stats(db)

    return stats


# =============================================================================
# CRM Task Endpoints
# =============================================================================

@faq_router.get("/stores/{store_id}/tasks", response_model=CRMTaskListResponse)
async def get_crm_tasks(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated CRM tasks"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    query = db.query(CRMTask).filter(CRMTask.store_id == store_id)

    if task_type:
        query = query.filter(CRMTask.task_type == task_type)
    if status:
        query = query.filter(CRMTask.status == status)
    if priority:
        query = query.filter(CRMTask.priority == priority)
    if assigned_to:
        query = query.filter(CRMTask.assigned_to == assigned_to)

    total = query.count()
    tasks = query.order_by(CRMTask.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return CRMTaskListResponse(
        tasks=[CRMTaskResponse.model_validate(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size
    )


@faq_router.post("/stores/{store_id}/tasks", response_model=CRMTaskResponse, status_code=201)
async def create_crm_task(
    store_id: UUID,
    task_data: CRMTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new CRM task"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    task = CRMTask(
        store_id=store_id,
        **task_data.model_dump()
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    logger.info(f"Created CRM task {task.id} for store {store_id}")
    return CRMTaskResponse.model_validate(task)


@faq_router.put("/tasks/{task_id}", response_model=CRMTaskResponse)
async def update_crm_task(
    task_id: UUID,
    task_data: CRMTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a CRM task"""
    task = db.query(CRMTask).filter(CRMTask.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not check_store_access(db, current_user, task.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    update_data = task_data.model_dump(exclude_unset=True)

    # Handle completion
    if update_data.get("status") == "completed" and task.status != "completed":
        update_data["completed_at"] = datetime.utcnow()
        update_data["completed_by"] = current_user.id

    for field, value in update_data.items():
        setattr(task, field, value)

    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    logger.info(f"Updated CRM task {task_id}")
    return CRMTaskResponse.model_validate(task)


@faq_router.delete("/tasks/{task_id}")
async def delete_crm_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a CRM task"""
    task = db.query(CRMTask).filter(CRMTask.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not check_store_access(db, current_user, task.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to delete this task")

    db.delete(task)
    db.commit()

    return {"message": "Task deleted successfully"}


# =============================================================================
# Conversation Endpoints
# =============================================================================

@faq_router.get("/stores/{store_id}/conversations", response_model=ConversationListResponse)
async def get_conversations(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    handoff_requested: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated conversations with optional filters"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    query = db.query(WhatsAppConversation).filter(WhatsAppConversation.store_id == store_id)

    if status:
        query = query.filter(WhatsAppConversation.status == status)
    if handoff_requested is not None:
        query = query.filter(WhatsAppConversation.handoff_requested == handoff_requested)

    total = query.count()
    conversations = query.order_by(WhatsAppConversation.last_message_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(c) for c in conversations],
        total=total,
        page=page,
        page_size=page_size
    )


@faq_router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single conversation by ID"""
    conversation = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_store_access(db, current_user, conversation.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this conversation")

    return ConversationResponse.model_validate(conversation)


@faq_router.get("/conversations/{conversation_id}/messages", response_model=List[ConversationMessageResponse])
async def get_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get messages for a conversation"""
    conversation = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_store_access(db, current_user, conversation.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this conversation")

    messages = db.query(WhatsAppConversationMessage).filter(
        WhatsAppConversationMessage.conversation_id == conversation_id
    ).order_by(WhatsAppConversationMessage.created_at.desc()).limit(limit).all()

    return [ConversationMessageResponse.model_validate(m) for m in reversed(messages)]


@faq_router.post("/conversations/{conversation_id}/assign")
async def assign_conversation(
    conversation_id: UUID,
    assignment: ConversationAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign a conversation to a user for human takeover"""
    conversation = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_store_access(db, current_user, conversation.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this conversation")

    conversation.assigned_to = assignment.assigned_to
    conversation.status = "handoff"
    conversation.updated_at = datetime.utcnow()
    db.commit()

    logger.info(f"Assigned conversation {conversation_id} to user {assignment.assigned_to}")
    return {"message": "Conversation assigned successfully"}


@faq_router.post("/conversations/{conversation_id}/close")
async def close_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close a conversation"""
    conversation = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.id == conversation_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_store_access(db, current_user, conversation.store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this conversation")

    conversation.status = "closed"
    conversation.updated_at = datetime.utcnow()
    db.commit()

    logger.info(f"Closed conversation {conversation_id}")
    return {"message": "Conversation closed successfully"}


# ============ AI FAQ Generation ============

@faq_router.post("/stores/{store_id}/faqs/generate")
async def generate_faqs_with_ai(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate FAQs using AI based on the store's data (products, services, business type, etc.)."""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Build store context for AI
    context_parts = []
    context_parts.append(f"Business Name: {store.store_name}")
    if store.business_type:
        context_parts.append(f"Business Type: {store.business_type}")
    if store.store_voice:
        context_parts.append(f"About: {store.store_voice}")
    if store.products_or_services:
        services = store.products_or_services if isinstance(store.products_or_services, list) else [store.products_or_services]
        context_parts.append(f"Products/Services: {', '.join(services)}")
    if store.store_link:
        context_parts.append(f"Website: {store.store_link}")
    if store.store_address:
        context_parts.append(f"Address: {store.store_address}")
    if store.store_city:
        context_parts.append(f"City: {store.store_city}")
    if store.store_country:
        context_parts.append(f"Country: {store.store_country}")
    if store.store_phone:
        context_parts.append(f"Phone: {store.store_phone}")
    if store.store_email:
        context_parts.append(f"Email: {store.store_email}")

    # Get existing products from DB
    try:
        from modules.products.models import Product
        products = db.query(Product).filter(Product.store_id == store_id).limit(20).all()
        if products:
            product_names = [p.title for p in products if p.title]
            if product_names:
                context_parts.append(f"Products in store: {', '.join(product_names)}")
    except Exception:
        pass

    # Get existing FAQs to avoid duplicates
    existing_faqs = db.query(FAQ).filter(FAQ.store_id == store_id).all()
    existing_questions = [faq.question.lower() for faq in existing_faqs]

    store_context = "\n".join(context_parts)

    import os
    import json
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="AI service not configured")

    client = OpenAI(api_key=api_key)

    prompt = f"""You are an FAQ generator for a business. Based on the store information below, generate 8-12 relevant FAQs that customers would commonly ask.

STORE INFORMATION:
{store_context}

EXISTING FAQ QUESTIONS (do NOT duplicate these):
{chr(10).join(existing_questions[:20]) if existing_questions else 'None'}

Generate FAQs in these categories: general, services, pricing, shipping, returns, support, account, products.
Focus on questions relevant to this specific business type.
For service businesses, focus on how services work, pricing, booking, availability.
For product businesses, focus on shipping, returns, product details.

Return ONLY a JSON array of objects with "question", "answer", and "category" fields.
Each answer should be 1-3 sentences, helpful and professional.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )

        content = response.choices[0].message.content.strip()
        # Clean markdown if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        faqs_data = json.loads(content)
        if not isinstance(faqs_data, list):
            raise ValueError("Expected JSON array")

    except Exception as e:
        logger.error(f"AI FAQ generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")

    # Create FAQ records
    created = []
    existing_count = len(existing_faqs)
    for i, faq_data in enumerate(faqs_data):
        question = faq_data.get("question", "").strip()
        answer = faq_data.get("answer", "").strip()
        category = faq_data.get("category", "general").strip().lower()

        if not question or not answer:
            continue
        if question.lower() in existing_questions:
            continue

        faq = FAQ(
            store_id=store_id,
            question=question,
            answer=answer,
            category=category,
            display_order=existing_count + i,
            is_active=True,
            is_featured=(i < 3),
        )
        db.add(faq)
        created.append({"question": question, "answer": answer, "category": category})

    db.commit()

    # Sync new FAQs to knowledge base
    try:
        from .knowledge_service import KnowledgeService
        ks = KnowledgeService(db)
        new_faqs = db.query(FAQ).filter(
            FAQ.store_id == store_id,
            FAQ.is_active == True,
            FAQ.knowledge_id == None
        ).all()
        for faq in new_faqs:
            ks.sync_faq_to_knowledge(faq)
    except Exception as e:
        logger.warning(f"Knowledge sync after generation failed: {e}")

    return {
        "message": f"Generated {len(created)} new FAQs",
        "generated": len(created),
        "faqs": created,
    }

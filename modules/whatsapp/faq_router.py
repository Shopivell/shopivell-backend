"""
FAQ and Knowledge Base Router

API endpoints for managing:
- FAQs (Frequently Asked Questions)
- Knowledge Base entries
- Bot Configuration
- CRM Tasks
"""

import logging
import re
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
    ConversationMessageResponse, PharmacyBotGuidanceUpdate
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

    # Sync to knowledge base off the request path (durable + retried) so a slow
    # or transiently-failing embedding call never blocks or silently drops.
    if faq.is_active:
        from modules.jobs.queue import enqueue
        enqueue("sync_store_knowledge", {"store_id": str(store_id), "faq_id": str(faq.id)})

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

    # Re-sync to knowledge base off the request path (durable + retried).
    if faq.is_active:
        from modules.jobs.queue import enqueue
        enqueue("sync_store_knowledge", {"store_id": str(faq.store_id), "faq_id": str(faq.id)})
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


@faq_router.get("/stores/{store_id}/assistant-guidance")
@faq_router.get("/stores/{store_id}/pharmacy-bot-guidance")
async def get_pharmacy_bot_guidance(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return this store's assistant rules and reply templates."""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    markers = ("pharmacy", "pharmacist", "chemist", "dispensary", "drugstore")
    store_description = getattr(store, "store_description", "") or ""
    identity = " ".join((
        getattr(store, "store_name", "") or "",
        getattr(store, "store_category", "") or "",
        getattr(store, "business_type", "") or "",
        store_description,
    )).lower()
    is_pharmacy = any(marker in identity for marker in markers)

    from modules.openclaw.pharmacy_rules import (
        PHARMACY_BOT_INSTRUCTIONS,
        PHARMACY_REPLY_TEMPLATES,
    )

    config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store_id).first()
    instructions = (config.pharmacy_instructions if config and config.pharmacy_instructions is not None
                    else PHARMACY_BOT_INSTRUCTIONS if is_pharmacy else [])
    templates = (config.reply_templates if config and config.reply_templates is not None
                 else PHARMACY_REPLY_TEMPLATES if is_pharmacy else [])
    return {
        "is_pharmacy": is_pharmacy,
        "instructions": instructions,
        "reply_templates": templates,
    }


@faq_router.put("/stores/{store_id}/assistant-guidance")
@faq_router.put("/stores/{store_id}/pharmacy-bot-guidance")
async def update_pharmacy_bot_guidance(
    store_id: UUID,
    guidance: PharmacyBotGuidanceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save this store's assistant instructions and reusable reply templates."""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    markers = ("pharmacy", "pharmacist", "chemist", "dispensary", "drugstore")
    identity = " ".join(str(getattr(store, field, "") or "") for field in
                         ("store_name", "store_category", "business_type", "store_description")).lower()
    is_pharmacy = any(marker in identity for marker in markers)

    instructions = [item.strip() for item in guidance.instructions]
    templates = []
    for template in guidance.reply_templates:
        label = (template.get("label") or "").strip()
        text = (template.get("text") or "").strip()
        if not label or len(label) > 120 or not text or len(text) > 5000:
            raise HTTPException(status_code=422, detail="Each template needs a name (up to 120 characters) and reply text (up to 5000 characters)")
        templates.append({"label": label, "text": text})
    if any(not item or len(item) > 1000 for item in instructions):
        raise HTTPException(status_code=422, detail="Each rule must contain 1 to 1000 characters")
    config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store_id).first()
    if not config:
        config = StoreBotConfig(store_id=store_id)
        db.add(config)
    config.pharmacy_instructions = instructions
    config.reply_templates = templates
    config.updated_at = datetime.utcnow()
    db.commit()
    return {"is_pharmacy": is_pharmacy, "instructions": instructions, "reply_templates": templates}


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
        # An explicit null clears the optional custom rules. Other optional
        # update fields retain their current value when sent as null.
        if value is not None or field == "bot_personality":
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


def _faq_llm_configured() -> bool:
    """True when any model provider this app already uses has a key."""
    import os
    return bool(os.getenv("OPENROUTER_API_KEY")) or \
        os.getenv("OPENAI_API_KEY", "").startswith("sk-")


def _generate_faqs_text(prompt: str) -> str:
    """One FAQ-generation completion, returned as raw text.

    Provider order matches the rest of the app: OpenAI direct when an sk- key is
    configured, OpenRouter otherwise. The endpoint used to insist on
    OPENAI_API_KEY, so a deployment that runs everything through OpenRouter got
    "AI service not configured" from "create FAQ with AI" even though the model
    was available.
    """
    import os
    import requests

    messages = [{"role": "user", "content": prompt}]
    openai_key = os.getenv("OPENAI_API_KEY", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    attempts = []

    if openai_key.startswith("sk-"):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}",
                         "Content-Type": "application/json"},
                json={"model": os.getenv("FAQ_LLM_MODEL", "gpt-4o-mini"),
                      "messages": messages, "temperature": 0.3, "max_tokens": 3000},
                timeout=90,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"{resp.status_code} {resp.text[:160]}")
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            attempts.append(f"openai: {e}")
            logger.warning("[FAQ] OpenAI generation failed: %s", e)

    if openrouter_key:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {openrouter_key}",
                         "HTTP-Referer": "https://shopivell.com",
                         "X-Title": "Shopivell FAQs",
                         "Content-Type": "application/json"},
                json={"model": os.getenv("OPENROUTER_FAQ_MODEL", "openai/gpt-4o-mini"),
                      "messages": messages, "temperature": 0.3, "max_tokens": 3000},
                timeout=120,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"{resp.status_code} {resp.text[:160]}")
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            attempts.append(f"openrouter: {e}")
            logger.warning("[FAQ] OpenRouter generation failed: %s", e)

    if not attempts:
        raise HTTPException(status_code=503,
                            detail="AI service not configured: set OPENAI_API_KEY or OPENROUTER_API_KEY")
    raise HTTPException(status_code=502,
                        detail="AI generation failed: " + "; ".join(attempts))


def _parse_faqs_json(content: str) -> List[dict]:
    """The model's FAQ list, tolerating fences, prose around it or an object."""
    import json
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    data = None
    try:
        data = json.loads(text)
    except Exception:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except Exception:
                data = None
    if isinstance(data, dict):
        for key in ("faqs", "data", "items", "questions"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise HTTPException(status_code=502,
                            detail="AI generation failed: the model did not return a JSON array")
    return [item for item in data if isinstance(item, dict)]

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

    # Ground the FAQs in what customers actually search for: real Google
    # autocomplete + People-Also-Ask style questions, localized to the store's
    # market. Best-effort — if it fails, FAQ generation proceeds without it.
    real_searches = []
    try:
        from modules.agents.keyword_intelligence_agent import KeywordIntelligenceAgent
        kw_agent = KeywordIntelligenceAgent()

        seeds = []
        if store.products_or_services:
            svc = store.products_or_services if isinstance(store.products_or_services, list) else [store.products_or_services]
            seeds.extend([str(s).strip() for s in svc if s][:3])
        if not seeds and store.business_type:
            seeds.append(str(store.business_type))
        if not seeds and store.store_name:
            seeds.append(str(store.store_name))

        if seeds:
            primary = seeds[0]
            # PAA-style question seeds for the primary product/service.
            question_seeds = [f"how much is {primary}", f"how to {primary}", f"what is {primary}"]
            cc = (store.country_code or "ZW").upper()
            cities = [store.store_city] if store.store_city else None

            ac = kw_agent.research_keywords_autocomplete(seeds + question_seeds, cc, expand_alphabet=False)
            ranked = kw_agent._score_and_rank_keywords(ac.get("keywords", []), cc, cities)
            # Real, non-foreign searches, highest intent/local first.
            real_searches = [k["keyword"] for k in ranked if not k.get("is_foreign")][:12]
    except Exception as e:
        logger.warning(f"[FAQ] keyword grounding skipped: {e}")

    if not _faq_llm_configured():
        raise HTTPException(status_code=503,
                            detail="AI service not configured: set OPENAI_API_KEY or OPENROUTER_API_KEY")

    prompt = f"""You are an FAQ generator for a business. Based on the store information below, generate 8-12 relevant FAQs that customers would commonly ask.

STORE INFORMATION:
{store_context}

EXISTING FAQ QUESTIONS (do NOT duplicate these):
{chr(10).join(existing_questions[:20]) if existing_questions else 'None'}

REAL CUSTOMER SEARCHES (actual Google searches in this store's market — turn the
relevant ones into natural FAQ questions and answer them; prioritise these over
generic questions):
{chr(10).join(real_searches) if real_searches else 'None available'}

Generate FAQs in these categories: general, services, pricing, shipping, returns, support, account, products.
Focus on questions relevant to this specific business type.
For service businesses, focus on how services work, pricing, booking, availability.
For product businesses, focus on shipping, returns, product details.

Return ONLY a JSON array of objects with "question", "answer", and "category" fields.
Each answer should be 1-3 sentences, helpful and professional.
"""

    try:
        content = _generate_faqs_text(prompt)
        faqs_data = _parse_faqs_json(content)
    except HTTPException:
        raise
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


# =============================================================================
# Branch Management & Bulk Operations
# =============================================================================

@faq_router.get("/stores/{store_id}/branches")
async def get_store_branches(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all unique branches for a store"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    # Get distinct branches from knowledge entries
    branches = db.query(CompanyKnowledge.branch).filter(
        CompanyKnowledge.store_id == store_id,
        CompanyKnowledge.branch.isnot(None),
        CompanyKnowledge.branch != ""
    ).distinct().all()

    return {
        "branches": [b[0] for b in branches if b[0]],
        "total": len(branches)
    }


@faq_router.delete("/stores/{store_id}/knowledge/bulk")
async def bulk_delete_knowledge(
    store_id: UUID,
    branch: Optional[str] = Query(None, description="Delete only entries for this branch"),
    content_type: Optional[str] = Query(None, description="Delete only entries of this type (product, manual, faq)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk delete knowledge entries for a store, optionally filtered by branch or content type"""
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    query = db.query(CompanyKnowledge).filter(CompanyKnowledge.store_id == store_id)

    if branch:
        query = query.filter(CompanyKnowledge.branch == branch)
    if content_type:
        query = query.filter(CompanyKnowledge.content_type == content_type)

    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()

    return {
        "message": f"Deleted {count} knowledge entries",
        "deleted": count,
        "filters": {"branch": branch, "content_type": content_type}
    }


@faq_router.post("/stores/{store_id}/knowledge/upload")
async def upload_product_data(
    store_id: UUID,
    branch: str = Query(..., description="Branch name (e.g., 'Rezende', 'Angwa')"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload product data from CSV/Excel file.
    Expects a file upload with columns: stock_code, description, price
    """
    from fastapi import File, UploadFile
    # This is a placeholder - actual implementation below
    raise HTTPException(status_code=501, detail="Use the file upload endpoint instead")


from fastapi import File, UploadFile
import io

@faq_router.post("/stores/{store_id}/knowledge/upload-file")
async def upload_product_file(
    store_id: UUID,
    file: UploadFile = File(...),
    branch: str = Query(..., description="Branch name (e.g., 'Rezende', 'Angwa')"),
    replace_existing: bool = Query(False, description="Delete existing products for this branch before importing"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload product data from CSV or Excel file.

    Expected format:
    - Excel files (.xlsx, .xls): Should have columns for stock code, description, price
    - CSV files: Should have columns stock_code, description, price

    The file will be parsed and products imported to the knowledge base for the specified branch.
    """
    if not check_store_access(db, current_user, store_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this store")

    # Check file type
    filename = file.filename.lower()
    if not (filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv')):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Please upload a CSV or Excel file (.xlsx, .xls, .csv)"
        )

    try:
        import pandas as pd

        # Read file content
        content = await file.read()

        # Parse file based on type
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            # Excel file - try to detect header row (pharmacy exports often have header info)
            df_raw = pd.read_excel(io.BytesIO(content), header=None)

            # Find the header row (look for 'Stock Code' or 'Description')
            header_row = None
            for idx, row in df_raw.iterrows():
                row_str = ' '.join(str(v).lower() for v in row.values if pd.notna(v))
                if 'stock code' in row_str or 'description' in row_str:
                    header_row = idx
                    break

            if header_row is not None:
                df = pd.read_excel(io.BytesIO(content), skiprows=header_row + 1, header=None)
                # Use column names from header row
                headers = df_raw.iloc[header_row].values
                df.columns = [str(h).strip().lower().replace(' ', '_') for h in headers[:len(df.columns)]]
            else:
                df = pd.read_excel(io.BytesIO(content))
                df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

        # Normalize column names
        df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

        # Map common column variations
        col_mapping = {
            'stock_code': ['stock_code', 'stockcode', 'code', 'sku', 'item_code'],
            'description': ['description', 'name', 'product', 'product_name', 'item'],
            'price': ['price', 'stock_retail', 'retail', 'retail_price', 'selling_price', 'cost']
        }

        final_cols = {}
        for target, variants in col_mapping.items():
            for v in variants:
                if v in df.columns:
                    final_cols[target] = v
                    break

        if 'description' not in final_cols:
            raise HTTPException(
                status_code=400,
                detail="Could not find description/product name column in file"
            )

        # Delete existing if requested
        if replace_existing:
            deleted = db.query(CompanyKnowledge).filter(
                CompanyKnowledge.store_id == store_id,
                CompanyKnowledge.branch == branch,
                CompanyKnowledge.content_type.in_(['product', 'manual'])
            ).delete(synchronize_session=False)
            logger.info(f"Deleted {deleted} existing products for branch {branch}")

        # Import products
        imported = 0
        errors = []

        for idx, row in df.iterrows():
            try:
                description = str(row.get(final_cols.get('description', ''), '')).strip()
                if not description or description.lower() == 'nan' or description.lower() == 'description':
                    continue

                stock_code = str(row.get(final_cols.get('stock_code', ''), '')).strip()
                price = row.get(final_cols.get('price', ''), '')

                # Format price
                if pd.isna(price) or str(price).lower() == 'nan':
                    price_str = "Price on request"
                else:
                    try:
                        price_val = float(price)
                        price_str = f"${price_val:.2f}"
                    except:
                        price_str = str(price)

                # Create knowledge entry content
                content = f"Product: {description}\n"
                if stock_code and stock_code.lower() != 'nan':
                    content += f"Stock Code: {stock_code}\n"
                content += f"Price: {price_str}\n"
                content += f"Branch: {branch}"

                # Create knowledge entry
                entry = CompanyKnowledge(
                    store_id=store_id,
                    branch=branch,
                    title=description[:255] if len(description) > 255 else description,
                    content=content,
                    content_type="product",
                    category="product",
                    is_active=True,
                )
                db.add(entry)
                imported += 1

            except Exception as e:
                errors.append(f"Row {idx + 1}: {str(e)}")
                if len(errors) > 10:
                    break

        db.commit()

        return {
            "message": f"Successfully imported {imported} products for branch '{branch}'",
            "imported": imported,
            "branch": branch,
            "errors": errors[:10] if errors else None,
            "replaced_existing": replace_existing
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing product file: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing file: {str(e)}"
        )


@faq_router.post("/run-gweru-migration")
async def run_gweru_migration(
    db: Session = Depends(get_db),
):
    """One-time endpoint to import Gweru branch products. No auth for quick deployment."""
    import uuid
    from datetime import datetime
    from sqlalchemy import text

    STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"
    BRANCH = "Gweru"

    try:
        # Import products data
        from migrations.gweru_products_data import PRODUCTS

        # Check existing products
        result = db.execute(text("""
            SELECT COUNT(*) FROM company_knowledge
            WHERE store_id = :store_id AND branch = :branch
        """), {"store_id": STORE_ID, "branch": BRANCH})
        existing = result.fetchone()[0]

        if existing > 0:
            # Delete existing Gweru products
            db.execute(text("""
                DELETE FROM company_knowledge
                WHERE store_id = :store_id AND branch = :branch
            """), {"store_id": STORE_ID, "branch": BRANCH})
            db.commit()

        # Import new products
        imported = 0
        for name, price in PRODUCTS:
            content = f"Product: {name}\nPrice: ${price:.2f}"

            db.execute(text("""
                INSERT INTO company_knowledge (id, store_id, content_type, content, is_active, branch, created_at, updated_at)
                VALUES (:id, :store_id, :content_type, :content, :is_active, :branch, :created_at, :updated_at)
            """), {
                "id": str(uuid.uuid4()),
                "store_id": STORE_ID,
                "content_type": "product",
                "content": content,
                "is_active": True,
                "branch": BRANCH,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })
            imported += 1

        db.commit()

        # Get all branches count
        result = db.execute(text("""
            SELECT branch, COUNT(*) FROM company_knowledge
            WHERE store_id = :store_id AND branch IS NOT NULL
            GROUP BY branch ORDER BY branch
        """), {"store_id": STORE_ID})
        branches = {row[0]: row[1] for row in result.fetchall()}

        return {
            "success": True,
            "message": f"Successfully imported {imported} Gweru products",
            "imported": imported,
            "deleted_existing": existing,
            "branches": branches
        }

    except Exception as e:
        logger.error(f"Gweru migration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@faq_router.post("/run-bulawayo-migration")
async def run_bulawayo_migration(
    db: Session = Depends(get_db),
):
    """One-time endpoint to import Bulawayo branch products. No auth for quick deployment."""
    import uuid
    from datetime import datetime
    from sqlalchemy import text

    STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"
    BRANCH = "Bulawayo"

    try:
        # Import products data
        from migrations.bulawayo_products_data import PRODUCTS

        # Check existing products
        result = db.execute(text("""
            SELECT COUNT(*) FROM company_knowledge
            WHERE store_id = :store_id AND branch = :branch
        """), {"store_id": STORE_ID, "branch": BRANCH})
        existing = result.fetchone()[0]

        if existing > 0:
            # Delete existing Bulawayo products
            db.execute(text("""
                DELETE FROM company_knowledge
                WHERE store_id = :store_id AND branch = :branch
            """), {"store_id": STORE_ID, "branch": BRANCH})
            db.commit()

        # Import new products
        imported = 0
        for name, price in PRODUCTS:
            content = f"Product: {name}\nPrice: ${price:.2f}"

            db.execute(text("""
                INSERT INTO company_knowledge (id, store_id, content_type, content, is_active, branch, created_at, updated_at)
                VALUES (:id, :store_id, :content_type, :content, :is_active, :branch, :created_at, :updated_at)
            """), {
                "id": str(uuid.uuid4()),
                "store_id": STORE_ID,
                "content_type": "product",
                "content": content,
                "is_active": True,
                "branch": BRANCH,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })
            imported += 1

        db.commit()

        # Get all branches count
        result = db.execute(text("""
            SELECT branch, COUNT(*) FROM company_knowledge
            WHERE store_id = :store_id AND branch IS NOT NULL
            GROUP BY branch ORDER BY branch
        """), {"store_id": STORE_ID})
        branches = {row[0]: row[1] for row in result.fetchall()}

        return {
            "success": True,
            "message": f"Successfully imported {imported} Bulawayo products",
            "imported": imported,
            "deleted_existing": existing,
            "branches": branches
        }

    except Exception as e:
        logger.error(f"Bulawayo migration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@faq_router.post("/run-orders-migration")
async def run_orders_migration(
    db: Session = Depends(get_db),
):
    """One-time endpoint to create orders tables."""
    from sqlalchemy import text

    try:
        # Create whatsapp_orders table
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_orders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                store_id UUID NOT NULL REFERENCES stores(id),
                order_number VARCHAR(50) NOT NULL UNIQUE,
                customer_phone VARCHAR(50) NOT NULL,
                customer_name VARCHAR(255),
                customer_address TEXT,
                branch VARCHAR(100),
                items JSONB NOT NULL DEFAULT '[]',
                subtotal FLOAT DEFAULT 0.0,
                delivery_fee FLOAT DEFAULT 0.0,
                total_amount FLOAT DEFAULT 0.0,
                collection_method VARCHAR(50) DEFAULT 'delivery',
                delivery_distance_km FLOAT,
                payment_method VARCHAR(50) DEFAULT 'cod',
                payment_provider VARCHAR(50),
                payment_status VARCHAR(50) DEFAULT 'pending',
                payment_reference VARCHAR(255),
                payment_poll_url TEXT,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                confirmed_at TIMESTAMP,
                delivered_at TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_store_id ON whatsapp_orders(store_id);
            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_customer_phone ON whatsapp_orders(customer_phone);
            CREATE INDEX IF NOT EXISTS ix_whatsapp_orders_status ON whatsapp_orders(status);
        """))
        db.commit()

        # Create whatsapp_order_states table
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS whatsapp_order_states (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                store_id UUID NOT NULL REFERENCES stores(id),
                customer_phone VARCHAR(50) NOT NULL,
                current_state VARCHAR(50) DEFAULT 'idle',
                cart_items JSONB DEFAULT '[]',
                selected_branch VARCHAR(100),
                customer_name VARCHAR(255),
                customer_address TEXT,
                collection_method VARCHAR(50),
                payment_method VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,
                UNIQUE(store_id, customer_phone)
            );
            CREATE INDEX IF NOT EXISTS ix_whatsapp_order_states_store_phone
                ON whatsapp_order_states(store_id, customer_phone);
        """))
        db.commit()

        return {"success": True, "message": "Orders tables created successfully"}

    except Exception as e:
        logger.error(f"Orders migration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@faq_router.post("/orders/{order_number}/initiate-payment")
async def initiate_order_payment(
    order_number: str,
    payment_phone: str,
    db: Session = Depends(get_db),
):
    """
    Initiate mobile money payment for a WhatsApp order.

    Args:
        order_number: The order number (e.g., PP-20241014-ABCD)
        payment_phone: Customer's mobile number for payment (EcoCash/OneMoney/InnBucks)
    """
    from .payment_service import WhatsAppPaymentService, get_order_by_number

    try:
        # Get order details
        order = get_order_by_number(db, order_number)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order["payment_method"] == "cod":
            raise HTTPException(status_code=400, detail="Order is set to Cash on Delivery")

        if order["payment_status"] in ("paid", "completed"):
            return {"success": True, "already_paid": True, "message": "Payment already completed"}

        # Initialize payment service
        payment_service = WhatsAppPaymentService(db)

        # Initiate payment
        result, error = payment_service.initiate_mobile_payment(
            order_id=order["id"],
            order_number=order_number,
            amount=order["total_amount"],
            customer_phone=payment_phone,
            payment_provider=order["payment_provider"] or "ecocash"
        )

        if error:
            raise HTTPException(status_code=400, detail=error)

        return {
            "success": True,
            "order_number": order_number,
            "amount": order["total_amount"],
            "reference": result.get("reference"),
            "instructions": result.get("instructions"),
            "simulated": result.get("simulated", False)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Payment initiation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@faq_router.get("/orders/{order_number}/payment-status")
async def check_order_payment_status(
    order_number: str,
    db: Session = Depends(get_db),
):
    """Check payment status for a WhatsApp order."""
    from .payment_service import WhatsAppPaymentService, get_order_by_number

    try:
        order = get_order_by_number(db, order_number)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        payment_service = WhatsAppPaymentService(db)
        status = payment_service.check_payment_status(order["id"])

        return {
            "order_number": order_number,
            "payment_status": status.get("status"),
            "paid": status.get("paid", False),
            "reference": status.get("reference")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Payment status check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

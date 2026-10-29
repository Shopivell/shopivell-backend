# whatsapp_router.py

import hashlib
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import uuid
import requests
import os
import json
from datetime import datetime, time, timedelta
import logging 
from sqlalchemy import text
from database import get_db
from utils.jwt_auth import get_current_user
from modules.whatsapp.chatbot_engine import SalesBot, LeadScorer, MultiTenantSalesBot
from modules.whatsapp.flow_completion import handle_flow_completion
from modules.whatsapp.flow_token import encode_flow_token
from modules.whatsapp.interactive_messages import build_flow_message, build_text_message, build_button_message
from .models import CompanyKnowledge, WhatsAppAccount, WhatsAppMessage, WhatsAppLead, AdCampaign, WhatsAppConversation, WhatsAppConversationMessage, CRMTask
from .store_router import StoreRouter
from .profile_service import get_customer_name_from_contacts, generate_avatar_url, should_update_profile_picture
from . import consent
from .system_contacts import is_whatsapp_service_number
from .schemas import (
    ChatRequest, ConversionsAPISettingsUpdate, KnowledgeCreateRequest, KnowledgeResponse, WhatsAppAccountCreate, WhatsAppAccountUpdate, WhatsAppAccountResponse, WhatsAppConversionEvent, WhatsAppMessageResponse,
    WhatsAppMessageSendResponse, WhatsAppTextMessage,
    WhatsAppAccountsListResponse, WhatsAppMessagesListResponse,
    WhatsAppWebhookVerification, WhatsAppWebhookPayload,
    BulkMessageRequest, BulkMessageResponse, BulkMessageResult,
    AdCampaignCreate, AdCampaignUpdate, AdCampaignResponse, AdCampaignListResponse,
    AvailableStoresResponse, StoreSelectionOption,
    ConversationResponse, ConversationListResponse
)
from modules.business.models import FacebookBusinessAccount

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_capi_lead_event(
    pixel_id: str,
    access_token: str,
    phone_number: str,
    lead_score: float,
    event_id: str = None
) -> dict:
    """Send Lead event to Meta Conversions API"""
    import hashlib
    import time

    # Hash phone number for privacy
    phone_hash = hashlib.sha256(phone_number.encode()).hexdigest()
    event_id = event_id or f"lead_{int(time.time())}_{phone_number[-4:]}"

    url = f"https://graph.facebook.com/v23.0/{pixel_id}/events"
    headers = {"Content-Type": "application/json"}

    payload = {
        "data": [{
            "event_name": "Lead",
            "event_time": int(time.time()),
            "event_id": event_id,
            "event_source_url": "https://wa.me/",
            "action_source": "chat",
            "user_data": {
                "ph": [phone_hash],
                "client_user_agent": "WhatsApp"
            },
            "custom_data": {
                "lead_score": lead_score,
                "source": "whatsapp_bot",
                "currency": "USD",
                "value": lead_score  # Use score as value for optimization
            }
        }],
        "access_token": access_token
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        result = response.json()
        logger.info(f"CAPI Lead event sent: {result}")
        return {"success": True, "event_id": event_id, "response": result}
    except Exception as e:
        logger.error(f"CAPI error: {e}")
        return {"success": False, "error": str(e)}


HOT_LEAD_CAPI_THRESHOLD = 80.0


def maybe_send_capi_for_lead(db, whatsapp_account, phone_number: str) -> None:
    """Links lead scoring -> Conversions API.

    When a WhatsApp lead's score crosses the hot threshold, send Meta a Lead
    conversion event (once) so ad campaigns can optimize toward real leads.
    Fires only if the account has CAPI configured, the lead has marketing consent,
    and it hasn't already been sent. COMPLIANCE: customer data is shared with Meta
    only with marketing opt-in (Meta Business Tools Terms).
    """
    if not (whatsapp_account.capi_dataset_id and whatsapp_account.capi_access_token):
        return
    try:
        from .consent import clean_phone
        phone = clean_phone(phone_number)
    except Exception:
        phone = phone_number.replace(" ", "").replace("+", "").strip()

    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.whatsapp_account_id == whatsapp_account.id,
        WhatsAppLead.phone_number == phone,
    ).first()
    if not lead or lead.conversion_sent:
        return
    if (lead.lead_score or 0) < HOT_LEAD_CAPI_THRESHOLD:
        return
    if not (lead.marketing_opt_in and lead.opted_out_at is None):
        logger.info(f"Hot lead {phone} NOT sent to CAPI: no marketing consent on record")
        return

    result = send_capi_lead_event(
        pixel_id=whatsapp_account.capi_dataset_id,
        access_token=whatsapp_account.capi_access_token,
        phone_number=phone,
        lead_score=lead.lead_score or HOT_LEAD_CAPI_THRESHOLD,
    )
    if result.get("success"):
        lead.conversion_sent = True
        lead.conversion_event_id = result.get("event_id")
        lead.conversion_sent_at = datetime.utcnow()
        db.commit()
        logger.info(f"CAPI Lead event sent for {phone} (score {lead.lead_score})")


whatsapp_router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# WhatsApp Graph API base URL
WHATSAPP_API_BASE = "https://graph.facebook.com/v23.0"

# WebSocket Connection Manager
class ConnectionManager:
    """Manages active WebSocket connections for real-time updates."""
    def __init__(self):
        # Dictionary to hold active connections, keyed by WhatsApp Account ID (str)
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, account_id: str, accepted: bool = False):
        if not accepted:
            await websocket.accept()
        if account_id not in self.active_connections:
            self.active_connections[account_id] = []
        self.active_connections[account_id].append(websocket)
        logger.info(f"WebSocket connected for account ID: {account_id}. Total connections: {len(self.active_connections[account_id])}")

    def disconnect(self, websocket: WebSocket, account_id: str):
        if account_id in self.active_connections:
            self.active_connections[account_id].remove(websocket)
            if not self.active_connections[account_id]:
                del self.active_connections[account_id]
        logger.info(f"WebSocket disconnected for account ID: {account_id}")

    async def broadcast_message(self, account_id: str, message: Dict[str, Any]):
        """Broadcasts a new message or status update to all clients watching a specific account."""
        if account_id in self.active_connections:
            # Use a list of tasks for parallel sending
            send_tasks = []
            for connection in self.active_connections[account_id]:
                send_tasks.append(connection.send_json(message))
            
            # Run all send tasks concurrently
            await asyncio.gather(*send_tasks)
            logger.info(f"Broadcasted message to {len(self.active_connections[account_id])} clients for account {account_id}")

manager = ConnectionManager()

# Helper functions
def get_whatsapp_client(whatsapp_account_id: uuid.UUID, db: Session):
    """Get WhatsApp account with access token"""
    whatsapp_account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == whatsapp_account_id
    ).first()
    
    if not whatsapp_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp account not found"
        )
    
    if not whatsapp_account.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp account is not enabled"
        )
    
    # Try to use permanent access token, fall back to business account token, then env var
    access_token = whatsapp_account.permanent_access_token
    if not access_token:
        business_account = whatsapp_account.business_account
        if business_account:
            access_token = business_account.access_token
    if not access_token:
        access_token = os.getenv("WHATSAPP_PERMANENT_TOKEN")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No access token available for WhatsApp account"
        )

    return whatsapp_account, access_token

def send_whatsapp_message_request(
    phone_number_id: str,
    access_token: str,
    to: str,
    message_type: str,
    message_data: Dict[str, Any]
):
    """Send message to WhatsApp API"""
    url = f"{WHATSAPP_API_BASE}/{phone_number_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": message_type,
        **message_data
    }
    
    logger.info(f"Sending WhatsApp message to {to}")
    logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"WhatsApp API response: {json.dumps(result, indent=2)}")
        return result
        
    except requests.exceptions.HTTPError as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
            logger.error(f"WhatsApp API error: {error_detail}")
        except:
            error_detail = str(e)
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send WhatsApp message: {error_detail}"
        )
    except Exception as e:
        logger.error(f"Unexpected error sending WhatsApp message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send WhatsApp message: {str(e)}"
        )

def save_message_to_db(
    db: Session,
    whatsapp_account_id: uuid.UUID,
    message_id: str,
    from_number: str,
    to_number: str,
    message_type: str,
    direction: str,
    status: str,
    message_text: Optional[str] = None,
    wamid: Optional[str] = None,
    meta_data: Optional[Dict[str, Any]] = None
):
    """Save message to database"""
    try:
        message = WhatsAppMessage(
            whatsapp_account_id=whatsapp_account_id,
            message_id=message_id,
            wamid=wamid,
            from_number=from_number,
            to_number=to_number,
            message_type=message_type,
            direction=direction,
            status=status,
            message_text=message_text,
            meta_data=meta_data,
            timestamp=datetime.utcnow()
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save message to database: {str(e)}")
        raise

# WhatsApp Account Management Endpoints
@whatsapp_router.post("/accounts", response_model=WhatsAppAccountResponse)
def create_whatsapp_account(
    account_data: WhatsAppAccountCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new WhatsApp account configuration using Business Account Token"""
    # This legacy endpoint lacks a store association; use the scoped connection flow.
    raise HTTPException(status_code=403, detail="Connect WhatsApp from store settings")
    
    # 1. Check if business account exists
    business_account = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.id == account_data.business_account_id
    ).first()
    
    if not business_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business account not found"
        )

    # 2. Check if the Business Account has a valid token
    if not business_account.access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected Business Account does not have an access token linked."
        )
    
    # 3. Check whether this phone number is already connected
    existing_account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.phone_number_id == account_data.phone_number_id
    ).first()
    
    if existing_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp account with this phone number ID already exists"
        )
    
    try:
        # 4. Create WhatsApp account
        # Auto-generate webhook verify token if not provided
        import secrets
        verify_token = account_data.webhook_verify_token or secrets.token_urlsafe(32)
        webhook_url = account_data.webhook_url or "https://api.shopivell.com/v1/api/whatsapp/webhook"

        whatsapp_account = WhatsAppAccount(
            business_account_id=account_data.business_account_id,
            waba_id=account_data.waba_id,
            phone_number_id=account_data.phone_number_id,
            phone_number=account_data.phone_number,
            display_name=account_data.display_name,
            permanent_access_token=business_account.access_token,
            webhook_url=webhook_url,
            webhook_verify_token=verify_token,
            is_enabled=True
        )
        
        db.add(whatsapp_account)
        db.commit()
        db.refresh(whatsapp_account)
        
        return WhatsAppAccountResponse.model_validate(whatsapp_account)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create WhatsApp account: {str(e)}"
        )

@whatsapp_router.get("/accounts", response_model=WhatsAppAccountsListResponse)
def get_whatsapp_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    business_account_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all WhatsApp accounts"""
    if not current_user.store_id:
        raise HTTPException(status_code=403, detail="Select a store")
    _authorize_message_store(db, current_user, uuid.UUID(current_user.store_id))
    query = db.query(WhatsAppAccount).filter(WhatsAppAccount.is_enabled == True,
                                              WhatsAppAccount.store_id == uuid.UUID(current_user.store_id))
    
    if business_account_id:
        query = query.filter(WhatsAppAccount.business_account_id == business_account_id)
    
    accounts = query.offset(skip).limit(limit).all()
    total_count = query.count()
    
    return WhatsAppAccountsListResponse(
        accounts=[WhatsAppAccountResponse.model_validate(acc) for acc in accounts],
        total_count=total_count
    )

@whatsapp_router.get("/store/{store_id}/accounts", response_model=WhatsAppAccountsListResponse)
def get_store_whatsapp_accounts(
    store_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all WhatsApp accounts for a specific store"""
    _authorize_message_store(db, current_user, store_id)
    accounts = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.store_id == store_id,
        WhatsAppAccount.is_enabled == True
    ).all()

    return WhatsAppAccountsListResponse(
        accounts=[WhatsAppAccountResponse.model_validate(acc) for acc in accounts],
        total_count=len(accounts)
    )

@whatsapp_router.get("/store/{store_id}/unread-count")
def get_store_unread_message_count(
    store_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Get the count of unread inbound messages for a store.
    Unread messages are inbound messages that have not been marked as read by the store owner.
    """
    _authorize_message_store(db, current_user, store_id)
    try:
        # Get all WhatsApp accounts for this store
        accounts = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.store_id == store_id,
            WhatsAppAccount.is_enabled == True
        ).all()

        if not accounts:
            return {"unread_count": 0, "store_id": str(store_id)}

        account_ids = [acc.id for acc in accounts]

        # Count inbound messages that haven't been read (read_at is NULL)
        unread_count = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.whatsapp_account_id.in_(account_ids),
            WhatsAppMessage.direction == "inbound",
            WhatsAppMessage.read_at == None  # Not yet read by store owner
        ).count()

        return {
            "unread_count": unread_count,
            "store_id": str(store_id)
        }

    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get unread count: {str(e)}"
        )

@whatsapp_router.post("/messages/{message_id}/mark-read")
def mark_message_as_read(
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark a message as read by the store owner"""
    try:
        message = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.id == message_id
        ).first()

        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == message.whatsapp_account_id).first()
        if not account or not account.store_id:
            raise HTTPException(status_code=404, detail="WhatsApp account not found")
        member = _authorize_message_store(db, current_user, account.store_id)
        if member is not None and member.branch_names is not None:
            conversation = db.query(WhatsAppConversation).filter(
                WhatsAppConversation.whatsapp_account_id == account.id,
                WhatsAppConversation.phone_number.in_([message.from_number, message.to_number])).first()
            if not conversation:
                raise HTTPException(status_code=403, detail="Conversation is not assigned to an accessible branch")
            _authorize_message_branch(db, current_user, conversation)

        message.read_at = datetime.utcnow()
        db.commit()

        return {"success": True, "message_id": str(message_id)}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error marking message as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark message as read: {str(e)}"
        )

@whatsapp_router.post("/conversations/{phone_number}/mark-read")
def mark_conversation_as_read(
    phone_number: str,
    account_id: uuid.UUID = Query(..., description="WhatsApp account ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark all messages in a conversation as read"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account or not account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    member = _authorize_message_store(db, current_user, account.store_id)
    try:
        phone_clean = phone_number.replace(" ", "").replace("+", "").strip()
        if member is not None and member.branch_names is not None:
            conversation = db.query(WhatsAppConversation).filter(
                WhatsAppConversation.whatsapp_account_id == account_id,
                WhatsAppConversation.phone_number.in_([phone_clean, "+" + phone_clean])).first()
            if not conversation:
                raise HTTPException(status_code=403, detail="Conversation is not assigned to an accessible branch")
            _authorize_message_branch(db, current_user, conversation)

        # Inbound messages are always stored with a "+" prefix on from_number
        # (see _persist_sandbox_message) - matching only the bare digits here
        # meant this filter never matched anything, so unread counts never
        # actually decreased. Match both forms to be safe either way.
        updated = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.whatsapp_account_id == account_id,
            WhatsAppMessage.from_number.in_([phone_clean, f"+{phone_clean}"]),
            WhatsAppMessage.direction == "inbound",
            WhatsAppMessage.read_at == None
        ).update({"read_at": datetime.utcnow()}, synchronize_session=False)

        db.commit()

        return {
            "success": True,
            "phone_number": phone_clean,
            "messages_marked_read": updated
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error marking conversation as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark conversation as read: {str(e)}"
        )

@whatsapp_router.get("/accounts/{account_id}", response_model=WhatsAppAccountResponse)
def get_whatsapp_account(account_id: uuid.UUID, db: Session = Depends(get_db),
                         current_user=Depends(get_current_user)):
    """Get a specific WhatsApp account"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp account not found"
        )

    if not account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    _authorize_message_store(db, current_user, account.store_id)
    return WhatsAppAccountResponse.model_validate(account)

@whatsapp_router.put("/accounts/{account_id}", response_model=WhatsAppAccountResponse)
def update_whatsapp_account(
    account_id: uuid.UUID,
    account_data: WhatsAppAccountUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update WhatsApp account configuration"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp account not found"
        )
    from modules.users.auth_router import _require_store_owner
    _require_store_owner(db, account.store_id, current_user)
    
    try:
        update_data = account_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(account, key, value)
        
        account.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(account)
        
        return WhatsAppAccountResponse.model_validate(account)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update WhatsApp account: {str(e)}"
        )

@whatsapp_router.delete("/accounts/{account_id}")
def delete_whatsapp_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a WhatsApp account and all related data"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp account not found")
    from modules.users.auth_router import _require_store_owner
    _require_store_owner(db, account.store_id, current_user)

    try:
        # Delete related records - order matters for FK constraints
        # 1. Nullify CRM task references to leads and conversations
        lead_ids = [l.id for l in db.query(WhatsAppLead).filter(WhatsAppLead.whatsapp_account_id == account_id).all()]
        conv_ids = [c.id for c in db.query(WhatsAppConversation).filter(WhatsAppConversation.whatsapp_account_id == account_id).all()]

        if lead_ids:
            db.query(CRMTask).filter(CRMTask.lead_id.in_(lead_ids)).update({"lead_id": None}, synchronize_session=False)
        if conv_ids:
            db.query(CRMTask).filter(CRMTask.conversation_id.in_(conv_ids)).update({"conversation_id": None}, synchronize_session=False)
            db.query(WhatsAppConversationMessage).filter(WhatsAppConversationMessage.conversation_id.in_(conv_ids)).delete(synchronize_session=False)

        # 2. Delete child records
        db.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_account_id == account_id).delete()
        db.query(WhatsAppLead).filter(WhatsAppLead.whatsapp_account_id == account_id).delete()
        db.query(WhatsAppConversation).filter(WhatsAppConversation.whatsapp_account_id == account_id).delete()
        db.query(AdCampaign).filter(AdCampaign.whatsapp_account_id == account_id).delete()

        db.delete(account)
        db.commit()
        return {"detail": "Account deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")

# WhatsApp Messaging Endpoints
# NOTE: Template messaging has been removed entirely — WABA accounts were
# blocked by Meta for template-message quality (2 accounts blocked June 2026).
# Only text messages within the 24-hour customer service window are supported.

@whatsapp_router.post("/accounts/{account_id}/send-bulk", response_model=BulkMessageResponse)
def send_bulk_whatsapp_messages(
    account_id: uuid.UUID,
    bulk_data: BulkMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Send bulk WhatsApp text messages to multiple recipients
    (within the 24-hour customer service window).

    Policy compliance (WhatsApp Business Messaging Policy):
    - Opted-out (STOP) numbers are never messaged.
    - Sends are throttled to avoid spike-sending patterns that damage quality
      rating (delay configurable via WHATSAPP_BULK_SEND_DELAY_SECONDS).
    """
    import time as _time

    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    if not whatsapp_account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    _authorize_message_store(db, current_user, whatsapp_account.store_id)

    send_delay = float(os.getenv("WHATSAPP_BULK_SEND_DELAY_SECONDS", "1.0"))
    # Bulk sends are marketing: require explicit opt-in per the WhatsApp Business
    # Messaging Policy. On by default; only relax with another lawful basis.
    require_opt_in = os.getenv(
        "WHATSAPP_REQUIRE_MARKETING_OPT_IN", "true"
    ).strip().lower() in ("1", "true", "yes")

    results: List[BulkMessageResult] = []
    successful = 0
    failed = 0
    skipped = 0
    seen_numbers = set()

    for recipient in bulk_data.recipients:
        try:
            # Clean phone number
            to_clean = recipient.phone_number.replace(" ", "").replace("+", "").strip()

            if is_whatsapp_service_number(to_clean):
                results.append(BulkMessageResult(phone_number=to_clean, success=False,
                                                 error="skipped: WhatsApp service number"))
                skipped += 1
                continue

            # Deduplicate within this batch
            if to_clean in seen_numbers:
                results.append(BulkMessageResult(
                    phone_number=to_clean,
                    success=False,
                    error="skipped: duplicate recipient in batch"
                ))
                skipped += 1
                continue
            seen_numbers.add(to_clean)

            # COMPLIANCE: never message opted-out numbers
            if consent.is_suppressed(db, account_id, to_clean):
                results.append(BulkMessageResult(
                    phone_number=to_clean,
                    success=False,
                    error="skipped: recipient has opted out (STOP)"
                ))
                skipped += 1
                continue

            # COMPLIANCE: marketing bulk sends require an explicit opt-in on file.
            if require_opt_in and not consent.has_marketing_opt_in(db, account_id, to_clean):
                results.append(BulkMessageResult(
                    phone_number=to_clean,
                    success=False,
                    error="skipped: recipient has not opted in to marketing messages"
                ))
                skipped += 1
                continue

            # COMPLIANCE: free-form text may only be sent inside an OPEN 24-hour window
            # (recipient messaged us within the last 24h). Outside it, WhatsApp allows only
            # approved templates, which we don't use — so skip rather than let Meta reject.
            window_open = db.query(WhatsAppMessage).filter(
                WhatsAppMessage.whatsapp_account_id == account_id,
                WhatsAppMessage.from_number == to_clean,
                WhatsAppMessage.direction == "inbound",
                WhatsAppMessage.timestamp >= datetime.utcnow() - timedelta(hours=24),
            ).first()
            if not window_open:
                results.append(BulkMessageResult(
                    phone_number=to_clean,
                    success=False,
                    error="skipped: no open 24-hour window (customer must message first)"
                ))
                skipped += 1
                continue

            # Throttle between sends (skip delay before the first send)
            if successful + failed > 0 and send_delay > 0:
                _time.sleep(send_delay)

            # Send text message (requires active 24-hour window)
            if not bulk_data.text_message:
                raise ValueError("text_message is required")

            result = send_whatsapp_message_request(
                phone_number_id=whatsapp_account.phone_number_id,
                access_token=access_token,
                to=to_clean,
                message_type="text",
                message_data={
                    "text": {
                        "body": bulk_data.text_message,
                        "preview_url": False
                    }
                }
            )

            # Extract message IDs
            message_id = result.get("messages", [{}])[0].get("id")
            wamid = result.get("messages", [{}])[0].get("wamid")

            # Save to database
            save_message_to_db(
                db=db,
                whatsapp_account_id=account_id,
                message_id=message_id or f"bulk_{datetime.utcnow().timestamp()}",
                from_number=whatsapp_account.phone_number,
                to_number=to_clean,
                message_type="text",
                direction="outbound",
                status="sent",
                message_text=bulk_data.text_message,
                wamid=wamid,
                meta_data=result
            )

            results.append(BulkMessageResult(
                phone_number=to_clean,
                success=True,
                message_id=message_id,
                wamid=wamid
            ))
            successful += 1

        except HTTPException as e:
            results.append(BulkMessageResult(
                phone_number=recipient.phone_number,
                success=False,
                error=e.detail
            ))
            failed += 1
            logger.error(f"Bulk message failed for {recipient.phone_number}: {e.detail}")

        except Exception as e:
            results.append(BulkMessageResult(
                phone_number=recipient.phone_number,
                success=False,
                error=str(e)
            ))
            failed += 1
            logger.error(f"Bulk message failed for {recipient.phone_number}: {str(e)}")

    if skipped:
        logger.info(
            f"Bulk send on account {account_id}: {skipped} recipient(s) skipped "
            f"for compliance (opt-out / missing opt-in / duplicate)"
        )

    return BulkMessageResponse(
        success=failed == 0,
        total_recipients=len(bulk_data.recipients),
        successful=successful,
        failed=failed,
        skipped=skipped,
        results=results,
        message=(
            f"Sent {successful}/{len(bulk_data.recipients)} messages successfully"
            + (f" ({skipped} skipped for compliance)" if skipped else "")
        )
    )


# WebSocket Endpoint
@whatsapp_router.websocket("/accounts/{account_id}/ws")
async def websocket_endpoint(websocket: WebSocket, account_id: uuid.UUID):
    """WebSocket endpoint for real-time message updates for a specific account."""
    from database import SessionLocal
    from fastapi.security import HTTPAuthorizationCredentials
    str_account_id = str(account_id)
    await websocket.accept()
    db = SessionLocal()
    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=auth.get('token', ''))
        user = await get_current_user(credentials)
        account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
        if not account or not account.store_id:
            raise HTTPException(status_code=404, detail='Account not found')
        _authorize_message_store(db, user, account.store_id)
        await manager.connect(websocket, str_account_id, accepted=True)
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                pass
            user = await get_current_user(credentials)
            db.expire_all()
            _authorize_message_store(db, user, account.store_id)
    except WebSocketDisconnect:
        pass
    except (HTTPException, asyncio.TimeoutError, ValueError):
        await websocket.close(code=1008)
    except Exception as e:
        logger.error(f"WebSocket error for account {account_id}: {str(e)}")
    finally:
        if websocket in manager.active_connections.get(str_account_id, []):
            manager.disconnect(websocket, str_account_id)
        db.close()

# Webhook Endpoints
async def _notify_payment_result(db: Session, order, result_status: str):
    """Send a verified result to the same store's WhatsApp conversation."""
    from modules.openclaw.router import _zernio, ZERNIO_SANDBOX_ACCOUNT_ID
    from modules.stores.models import Store
    conversation = (db.query(WhatsAppConversation)
        .filter(WhatsAppConversation.store_id == order.store_id,
                WhatsAppConversation.phone_number.in_([order.customer_phone, order.customer_phone.lstrip('+')]))
        .order_by(WhatsAppConversation.last_message_at.desc()).first())
    if not conversation:
        raise RuntimeError('Customer conversation not found')
    wa = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == conversation.whatsapp_account_id,
                                         WhatsAppAccount.store_id == order.store_id).first()
    store = db.query(Store).filter(Store.id == order.store_id).first()
    if not wa or not store:
        raise RuntimeError('Store WhatsApp account not found')
    account_id = None
    if wa.waba_id.startswith('zernio-sandbox-'):
        account_id = ZERNIO_SANDBOX_ACCOUNT_ID
    elif store.zernio_profile_id:
        accounts = await _zernio('GET', '/accounts', params={'profileId': store.zernio_profile_id})
        for account in accounts.get('accounts') or []:
            meta = account.get('metadata') or {}
            if account.get('platform') == 'whatsapp' and meta.get('phoneNumberId') == wa.phone_number_id:
                account_id = account.get('_id') or account.get('id')
                break
    if not account_id:
        raise RuntimeError('Store WhatsApp connection not found')
    data = await _zernio('GET', '/inbox/conversations', params={'platform': 'whatsapp', 'limit': 50, 'accountId': account_id})
    phone = order.customer_phone.lstrip('+').replace(' ', '')
    target = next((c for c in (data.get('data') or []) if str(c.get('participantId') or c.get('participantUsername') or '').lstrip('+').replace(' ', '') == phone), None)
    if not target:
        raise RuntimeError('Customer conversation not found in connected inbox')
    messages = {
        'paid': 'Your payment has been confirmed as successful.',
        'failed': 'Your payment failed. Please contact the store to retry or choose another payment method.',
        'cancelled': 'Your payment was cancelled. Please contact the store to retry or choose another payment method.',
        'refunded': 'Your payment has been refunded.',
    }
    await _zernio('POST', f"/inbox/conversations/{target['id']}/messages",
                  json_body={'accountId': account_id, 'message': f"Order {order.order_number}: {messages[result_status]}"})


@whatsapp_router.post('/paynow-callback')
async def whatsapp_paynow_callback(request: Request, db: Session = Depends(get_db)):
    """Record verified Paynow updates for bot orders; never trust the status alone."""
    import hashlib
    import hmac
    from decimal import Decimal, InvalidOperation
    from urllib.parse import parse_qsl
    from modules.orders.models import CustomerOrder
    from modules.whatsapp.models import WhatsAppOrder

    key = os.getenv('PAYNOW_INTEGRATION_KEY', '')
    if not key:
        raise HTTPException(status_code=503, detail='Payment verification is unavailable')
    try:
        raw = (await request.body()).decode('utf-8')
        fields = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail='Invalid payment update')
    names = [name.lower() for name, _ in fields]
    if len(names) != len(set(names)) or names.count('hash') != 1:
        raise HTTPException(status_code=400, detail='Invalid payment update')
    data = {name.lower(): value for name, value in fields}
    expected = hashlib.sha512((''.join(value for name, value in fields if name.lower() != 'hash') + key).encode()).hexdigest().upper()
    if not hmac.compare_digest(expected, data.get('hash', '').upper()):
        raise HTTPException(status_code=403, detail='Invalid payment signature')
    reference = data.get('reference', '')
    if not reference.startswith(('Order ', 'Order+')):
        raise HTTPException(status_code=400, detail='Unknown order reference')
    order_number = reference[len('Order '):].strip()
    order = db.query(WhatsAppOrder).filter(WhatsAppOrder.order_number == order_number).with_for_update().first()
    if not order:
        raise HTTPException(status_code=404, detail='Order not found')
    try:
        amount = Decimal(data.get('amount', ''))
        expected_amount = Decimal(str(order.total_amount)).quantize(Decimal('0.01'))
    except InvalidOperation:
        raise HTTPException(status_code=400, detail='Invalid payment amount')
    if not amount.is_finite() or amount != expected_amount:
        raise HTTPException(status_code=400, detail='Payment amount does not match the order')
    paynow_reference = data.get('paynowreference', '')
    saved_reference = str(order.payment_reference or '')
    if not paynow_reference:
        raise HTTPException(status_code=400, detail='Payment reference does not match the order')
    if saved_reference.startswith('PNW-'):
        if not order.payment_poll_url or data.get('pollurl') != order.payment_poll_url:
            raise HTTPException(status_code=400, detail='Payment reference does not match the order')
        order.payment_reference = paynow_reference
    elif not saved_reference or saved_reference != paynow_reference:
        raise HTTPException(status_code=400, detail='Payment reference does not match the order')
    status_value = data.get('status', '').strip().lower()
    previous_status = order.payment_status
    if status_value in ('paid', 'awaiting delivery', 'delivered') and order.payment_status != 'refunded':
        order.payment_status = 'paid'
        if order.status == 'pending':
            order.status = 'confirmed'
        customer_order = db.query(CustomerOrder).filter(CustomerOrder.id == order.id).first()
        if customer_order:
            customer_order.payment_status = 'paid'
            if customer_order.status == 'pending':
                customer_order.status = 'confirmed'
        db.commit()  # Never lose a confirmed payment if customer linking fails.
        if customer_order:
            try:
                from modules.customers.paid_order import link_paid_order_customer
                link_paid_order_customer(db, customer_order)
                db.commit()
                from utils.cache import cache
                cache.invalidate_pattern('cust:*')
            except Exception:
                db.rollback()
                logger.exception('Payment recorded but customer linking failed for order %s', order_number)
                raise HTTPException(status_code=500, detail='Customer linking will be retried')
    elif status_value in ('failed', 'cancelled', 'canceled') and order.payment_status not in ('paid', 'completed', 'refunded'):
        # A provider rejection is not a successful payment. Keep both order
        # views in sync, and do not let a late failure overwrite a paid order.
        order.payment_status = 'failed' if status_value == 'failed' else 'cancelled'
        customer_order = db.query(CustomerOrder).filter(CustomerOrder.id == order.id).first()
        if customer_order:
            customer_order.payment_status = order.payment_status
        db.commit()
    elif status_value == 'refunded':
        order.payment_status = 'refunded'
        customer_order = db.query(CustomerOrder).filter(CustomerOrder.id == order.id).first()
        if customer_order:
            customer_order.payment_status = 'refunded'
        db.commit()
    if order.payment_status in ('paid', 'failed', 'cancelled', 'refunded') and order.payment_status != previous_status:
        from modules.jobs.queue import enqueue
        if not enqueue('notify_whatsapp_payment', {'order_id': str(order.id), 'status': order.payment_status}, max_attempts=8):
            logger.error('Could not schedule payment notification for order %s', order_number)
    return {'received': True}


@whatsapp_router.get("/webhook")
def whatsapp_webhook_verification(
    request: Request,
    db: Session = Depends(get_db)
):
    """WhatsApp webhook verification endpoint (GET)"""
    params = dict(request.query_params)
    logger.info(f"Webhook verification request: {params}")
    
    hub_mode = params.get("hub.mode")
    hub_challenge = params.get("hub.challenge")
    hub_verify_token = params.get("hub.verify_token")
    
    if not all([hub_mode, hub_challenge, hub_verify_token]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing verification parameters"
        )
    
    # Verify token against stored tokens
    accounts = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.webhook_verify_token == hub_verify_token
    ).all()
    
    if hub_mode == "subscribe" and accounts:
        logger.info(f"Webhook verified for {len(accounts)} accounts")
        return PlainTextResponse(content=hub_challenge)
    else:
        logger.warning(f"Webhook verification failed. Mode: {hub_mode}, Token matches: {len(accounts)} accounts")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verification failed"
        )

@whatsapp_router.post("/webhook")
async def whatsapp_webhook_receive(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Receive WhatsApp webhook events (POST)"""
    try:
        import hmac as _hmac, hashlib as _hashlib, os as _os
        raw = await request.body()
        # Verify Meta's X-Hub-Signature-256 (Meta Platform Terms request integrity).
        # Verify-and-log by default; only REJECT forged payloads when
        # WHATSAPP_VERIFY_WEBHOOK_SIGNATURE=true, so enabling it can't accidentally
        # silence the bot if the configured app secret doesn't match. Confirm the
        # log shows "signature OK" first, then turn enforcement on.
        app_secret = _os.getenv("WHATSAPP_APP_SECRET") or _os.getenv("FACEBOOK_APP_SECRET") or ""
        if app_secret:
            sig = request.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + _hmac.new(app_secret.encode("utf-8"), raw, _hashlib.sha256).hexdigest()
            valid = bool(sig) and _hmac.compare_digest(sig, expected)
            enforce = _os.getenv("WHATSAPP_VERIFY_WEBHOOK_SIGNATURE", "false").strip().lower() in ("1", "true", "yes")
            if not valid:
                logger.warning(f"[whatsapp webhook] X-Hub-Signature-256 INVALID/absent (enforce={enforce})")
                if enforce:
                    return {"status": "ignored"}
            else:
                logger.info("[whatsapp webhook] signature OK")
        else:
            logger.warning("[whatsapp webhook] no app secret configured - signature NOT verified")

        payload = json.loads(raw.decode("utf-8") or "{}")
        logger.info(f"Received webhook payload: {json.dumps(payload, indent=2)}")

        # Process webhook using a thread to avoid async context issues
        import threading
        def run_in_thread():
            try:
                process_webhook_payload(payload)
            except Exception as e:
                logger.error(f"Thread error processing webhook: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())

        thread = threading.Thread(target=run_in_thread)
        thread.start()

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "ok"}

def process_webhook_payload(payload: Dict[str, Any]):
    """Process webhook payload and update message statuses"""
    # Create a NEW database session for this background task
    from database import SessionLocal
    db = SessionLocal()

    try:
        entries = payload.get("entry", [])

        for entry in entries:
            changes = entry.get("changes", [])

            for change in changes:
                value = change.get("value", {})

                # Handle incoming messages
                messages = value.get("messages", [])
                if messages:
                    process_incoming_messages(value, db)

                # Handle message status updates
                statuses = value.get("statuses", [])
                if statuses:
                    process_message_statuses(statuses, db)

        logger.info("Webhook processed successfully")

    except Exception as e:
        logger.error(f"Error in webhook processing: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        db.close()

def process_incoming_messages(value: Dict[str, Any], db: Session):
    """
    Process incoming messages from webhook with multi-store routing.

    Routing Flow:
    1. Check for Click-to-WhatsApp ad referral data -> route to campaign's store
    2. Check for existing conversation -> route to same store
    3. Check for default store on WhatsApp account -> route there
    4. No routing found -> ask customer to select a store
    """
    # Extract metadata
    meta_data = value.get("metadata", {})
    phone_number_id = meta_data.get("phone_number_id")

    logger.info(f"Processing message for phone_number_id: {phone_number_id}")

    contacts = value.get("contacts", [])
    messages = value.get("messages", [])

    # Find WhatsApp account by phone_number_id
    whatsapp_account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.phone_number_id == phone_number_id
    ).first()

    if not whatsapp_account:
        logger.warning(f"No WhatsApp account found for phone_number_id: {phone_number_id}")
        return

    # Get access token for sending replies
    access_token = whatsapp_account.permanent_access_token
    logger.info(f"Access token from permanent_access_token: {'SET' if access_token else 'NONE'}")
    if not access_token:
        # Try to get from business account relationship
        business_account = whatsapp_account.business_account
        if business_account:
            access_token = business_account.access_token
            logger.info(f"Access token from business_account: {'SET' if access_token else 'NONE'}")
        else:
            # Direct query fallback
            logger.info("Business account relationship not loaded, trying direct query")
            fb_account = db.query(FacebookBusinessAccount).filter(
                FacebookBusinessAccount.id == whatsapp_account.business_account_id
            ).first()
            if fb_account:
                access_token = fb_account.access_token
                logger.info(f"Access token from direct query: {'SET' if access_token else 'NONE'}")
    if not access_token:
        access_token = os.getenv("WHATSAPP_PERMANENT_TOKEN")
        if access_token:
            logger.info("Access token from WHATSAPP_PERMANENT_TOKEN env var")

    # Initialize the store router
    router = StoreRouter(whatsapp_account_id=whatsapp_account.id, db=db)

    for message in messages:
        from_number_raw = message.get("from")
        from_number_clean = from_number_raw.replace(" ", "").replace("+", "").strip()

        message_id = message.get("id")
        message_type = message.get("type")
        timestamp = message.get("timestamp")
        if is_whatsapp_service_number(from_number_clean):
            logger.info("Skipping auto-response to WhatsApp service notification")
            continue

        # Extract message text
        message_text = None
        if message_type == "text":
            text_data = message.get("text", {})
            message_text = text_data.get("body")
        elif message_type == "interactive":
            interactive_data = message.get("interactive", {})
            interactive_type = interactive_data.get("type")
            if interactive_type == "list_reply":
                message_text = interactive_data["list_reply"]["title"]
            elif interactive_type == "button_reply":
                message_text = interactive_data["button_reply"]["title"]
            elif interactive_type == "nfm_reply":
                # WhatsApp Flow completed — handle order submission
                nfm_data = interactive_data.get("nfm_reply", {})
                response_json_str = nfm_data.get("response_json", "{}")
                nfm_flow_token = nfm_data.get("body", "")
                try:
                    response_json = json.loads(response_json_str) if isinstance(response_json_str, str) else response_json_str
                    # Save message first
                    save_message_to_db(
                        db=db, whatsapp_account_id=whatsapp_account.id,
                        message_id=message_id, from_number=from_number_clean,
                        to_number=whatsapp_account.phone_number,
                        message_type="interactive", direction="inbound",
                        status="received", message_text="[Flow completed]",
                        meta_data=message,
                    )
                    result_messages = handle_flow_completion(
                        response_json=response_json,
                        flow_token=nfm_flow_token,
                        whatsapp_account=whatsapp_account,
                        from_number=from_number_clean,
                        db=db,
                        access_token=access_token,
                    )
                    if result_messages:
                        for resp in result_messages:
                            send_whatsapp_message_request(
                                phone_number_id=whatsapp_account.phone_number_id,
                                access_token=access_token,
                                to=from_number_clean,
                                message_type=resp["type"],
                                message_data=resp["data"],
                            )
                            save_message_to_db(
                                db=db, whatsapp_account_id=whatsapp_account.id,
                                message_id=f"flow_confirm_{datetime.utcnow().timestamp()}",
                                from_number=whatsapp_account.phone_number,
                                to_number=from_number_clean,
                                message_type=resp["type"], direction="outbound",
                                status="sent",
                                message_text=resp["data"].get("text", {}).get("body") or "[interactive message]",
                            )
                except Exception as nfm_err:
                    logger.error(f"nfm_reply processing error: {nfm_err}")
                    import traceback
                    logger.error(traceback.format_exc())
                continue  # Skip further processing for nfm_reply

        # Save incoming message to database
        new_message_db = save_message_to_db(
            db=db,
            whatsapp_account_id=whatsapp_account.id,
            message_id=message_id,
            from_number=from_number_clean,
            to_number=whatsapp_account.phone_number,
            message_type=message_type,
            direction="inbound",
            status="received",
            message_text=message_text,
            meta_data=message
        )

        # REAL-TIME PUSH: Broadcast the new message to the frontend
        if new_message_db:
            try:
                message_response = WhatsAppMessageResponse.model_validate(new_message_db)
                # Use thread-safe broadcast - don't block if it fails
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(manager.broadcast_message(
                        str(whatsapp_account.id),
                        message_response.model_dump()
                    ))
                    loop.close()
                except Exception as broadcast_err:
                    logger.warning(f"Broadcast failed (non-critical): {broadcast_err}")
            except Exception as e:
                logger.warning(f"Failed to prepare broadcast (non-critical): {e}")

        logger.info(f"Incoming message from {from_number_clean}: {message_text}")
        logger.info(f"Message saved successfully, proceeding to auto-respond check")

        # OPT-OUT / OPT-IN HANDLING (WhatsApp Business Messaging Policy):
        # STOP must be honored immediately and permanently. Handle before any
        # bot/flow logic so an opted-out user never gets an AI reply instead.
        if message_type == "text" and consent.is_opt_out_message(message_text):
            consent.record_opt_out(db, whatsapp_account.id, from_number_clean)
            if access_token:
                try:
                    send_whatsapp_message_request(
                        phone_number_id=whatsapp_account.phone_number_id,
                        access_token=access_token,
                        to=from_number_clean,
                        message_type="text",
                        message_data={"text": {"body": consent.OPT_OUT_CONFIRMATION, "preview_url": False}},
                    )
                except Exception as opt_err:
                    logger.error(f"Failed to send opt-out confirmation: {opt_err}")
            continue  # Never run bot/flow logic for an opt-out message

        if message_type == "text" and consent.is_opt_in_message(message_text):
            consent.record_opt_in(db, whatsapp_account.id, from_number_clean, source="inbound_message")
            if access_token:
                try:
                    send_whatsapp_message_request(
                        phone_number_id=whatsapp_account.phone_number_id,
                        access_token=access_token,
                        to=from_number_clean,
                        message_type="text",
                        message_data={"text": {"body": consent.OPT_IN_CONFIRMATION, "preview_url": False}},
                    )
                except Exception as opt_err:
                    logger.error(f"Failed to send opt-in confirmation: {opt_err}")
            continue

        # POST-FLOW PAYMENT: Handle EcoCash payment polling after Flow completes
        if message_text and access_token and message_type in ("text", "interactive"):
            try:
                active_conv = db.query(WhatsAppConversation).filter(
                    WhatsAppConversation.whatsapp_account_id == whatsapp_account.id,
                    WhatsAppConversation.phone_number == from_number_clean,
                    WhatsAppConversation.order_flow_active == True,
                ).first()
                if active_conv and active_conv.order_flow_state:
                    state = active_conv.order_flow_state

                    # Handle order choice: "Order on Website" vs "Order in WhatsApp"
                    if state.get("awaiting_order_choice"):
                        btn_id = None
                        if message_type == "interactive":
                            idata = message.get("interactive", {})
                            if idata.get("type") == "button_reply":
                                btn_id = idata["button_reply"].get("id")

                        if btn_id == "order_website":
                            # Send storefront link
                            order_link = state.get("order_link", "")
                            active_conv.order_flow_state = None
                            active_conv.order_flow_active = False
                            db.commit()
                            send_whatsapp_message_request(
                                phone_number_id=whatsapp_account.phone_number_id,
                                access_token=access_token, to=from_number_clean,
                                message_type="text",
                                message_data={"text": {"body": f"Here's your order link 🛒\n{order_link}\n\nBrowse our products and place your order!", "preview_url": True}},
                            )
                            continue

                        elif btn_id == "order_whatsapp":
                            # Launch WhatsApp Flow
                            from .models import WhatsAppFlow
                            wa_flow = db.query(WhatsAppFlow).filter(
                                WhatsAppFlow.store_id == store_id,
                                WhatsAppFlow.status == "published",
                            ).first()

                            if wa_flow:
                                flow_token = encode_flow_token(
                                    store_id=str(store_id),
                                    phone=from_number_clean,
                                    conv_id=str(active_conv.id),
                                )
                                flow_msg = build_flow_message(
                                    flow_id=wa_flow.flow_id,
                                    flow_token=flow_token,
                                )
                                send_whatsapp_message_request(
                                    phone_number_id=whatsapp_account.phone_number_id,
                                    access_token=access_token, to=from_number_clean,
                                    message_type=flow_msg["type"], message_data=flow_msg["data"],
                                )
                                active_conv.order_flow_active = True
                                active_conv.order_flow_state = {"flow_sent": True}
                                db.commit()
                            else:
                                # No flow — fall back to storefront link
                                order_link = state.get("order_link", "")
                                active_conv.order_flow_state = None
                                active_conv.order_flow_active = False
                                db.commit()
                                send_whatsapp_message_request(
                                    phone_number_id=whatsapp_account.phone_number_id,
                                    access_token=access_token, to=from_number_clean,
                                    message_type="text",
                                    message_data={"text": {"body": f"WhatsApp ordering isn't set up yet, but you can order here 🛒\n{order_link}", "preview_url": True}},
                                )
                            continue

                        elif btn_id == "get_more_info":
                            # Clear state so bot resumes normal chat
                            active_conv.order_flow_state = None
                            active_conv.order_flow_active = False
                            db.commit()
                            send_whatsapp_message_request(
                                phone_number_id=whatsapp_account.phone_number_id,
                                access_token=access_token, to=from_number_clean,
                                message_type="text",
                                message_data={"text": {"body": "Sure! What would you like to know? I can tell you about our products, services, pricing, or anything else. Just ask! 😊", "preview_url": False}},
                            )
                            continue

                        else:
                            # Unrecognized reply while awaiting choice — resend buttons
                            choice_msg = build_button_message(
                                body="Please choose how I can help you:",
                                buttons=[
                                    {"id": "order_website", "title": "Order on Website"},
                                    {"id": "order_whatsapp", "title": "Order in WhatsApp"},
                                    {"id": "get_more_info", "title": "Get More Info"},
                                ],
                            )
                            send_whatsapp_message_request(
                                phone_number_id=whatsapp_account.phone_number_id,
                                access_token=access_token, to=from_number_clean,
                                message_type=choice_msg["type"], message_data=choice_msg["data"],
                            )
                            continue

                    if state.get("awaiting_payment"):
                        # Handle "Check Payment" or "Cancel" button replies
                        btn_id = None
                        if message_type == "interactive":
                            idata = message.get("interactive", {})
                            if idata.get("type") == "button_reply":
                                btn_id = idata["button_reply"].get("id")

                        if btn_id == "cancel_payment" or (message_text and message_text.lower() == "cancel"):
                            active_conv.order_flow_active = False
                            active_conv.order_flow_state = None
                            db.commit()
                            send_whatsapp_message_request(
                                phone_number_id=whatsapp_account.phone_number_id,
                                access_token=access_token, to=from_number_clean,
                                message_type="text",
                                message_data={"text": {"body": "Payment cancelled. Your order is saved — contact us to arrange payment.", "preview_url": False}},
                            )
                            continue

                        if btn_id == "check_payment" or (message_text and "check" in message_text.lower()):
                            # Poll PayNow for status
                            poll_url = state.get("payment_poll_url")
                            order_number = state.get("order_number", "")
                            if poll_url:
                                try:
                                    from utils.payment_service import PaymentService
                                    ps = PaymentService()
                                    result = ps.check_payment_status(poll_url)
                                    if result and result.get("paid"):
                                        # Update order
                                        from modules.orders.models import CustomerOrder
                                        order_id = state.get("order_id")
                                        if order_id:
                                            order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
                                            if order:
                                                order.payment_status = "paid"
                                                db.commit()
                                                try:
                                                    from modules.customers.paid_order import link_paid_order_customer
                                                    link_paid_order_customer(db, order)
                                                    db.commit()
                                                except Exception:
                                                    db.rollback()
                                                    logger.exception("Payment succeeded but customer linking failed for order %s", order_id)
                                        active_conv.order_flow_active = False
                                        active_conv.order_flow_state = None
                                        db.commit()
                                        send_whatsapp_message_request(
                                            phone_number_id=whatsapp_account.phone_number_id,
                                            access_token=access_token, to=from_number_clean,
                                            message_type="text",
                                            message_data={"text": {"body": f"Payment confirmed! ✅\nOrder *{order_number}* is now paid.\nThank you! 🙏", "preview_url": False}},
                                        )
                                    else:
                                        # Still pending
                                        resp = build_button_message(
                                            body=f"Payment for order {order_number} is still pending. Please approve the EcoCash prompt on your phone.",
                                            buttons=[
                                                {"id": "check_payment", "title": "Check Again"},
                                                {"id": "cancel_payment", "title": "Cancel"},
                                            ],
                                        )
                                        send_whatsapp_message_request(
                                            phone_number_id=whatsapp_account.phone_number_id,
                                            access_token=access_token, to=from_number_clean,
                                            message_type=resp["type"], message_data=resp["data"],
                                        )
                                except Exception as pay_err:
                                    logger.error(f"Payment check error: {pay_err}")
                            continue
                        # Any other message while awaiting payment — remind them
                        resp = build_button_message(
                            body="You have a pending payment. Please check your payment or cancel.",
                            buttons=[
                                {"id": "check_payment", "title": "Check Payment"},
                                {"id": "cancel_payment", "title": "Cancel"},
                            ],
                        )
                        send_whatsapp_message_request(
                            phone_number_id=whatsapp_account.phone_number_id,
                            access_token=access_token, to=from_number_clean,
                            message_type=resp["type"], message_data=resp["data"],
                        )
                        continue
            except Exception as of_err:
                logger.error(f"Post-flow payment error: {of_err}")
                import traceback
                logger.error(traceback.format_exc())

        # ALWAYS create/update conversation for ANY incoming message (not just text)
        # This ensures all phone numbers show up in the conversations list
        try:
            store_id_for_conv, _, conversation = router.route_message(
                phone_number=from_number_clean,
                message_data=message
            )
            if conversation:
                customer_name = get_customer_name_from_contacts(contacts)
                if customer_name and not conversation.customer_name:
                    conversation.customer_name = customer_name
                if should_update_profile_picture(conversation.profile_picture_updated_at):
                    conversation.profile_picture_url = generate_avatar_url(
                        name=conversation.customer_name or customer_name,
                        phone_number=from_number_clean
                    )
                    conversation.profile_picture_updated_at = datetime.utcnow()
                conversation.last_message_at = datetime.utcnow()
                db.commit()
                logger.info(f"Conversation created/updated for {from_number_clean}")
        except Exception as conv_err:
            logger.error(f"Failed to create conversation: {conv_err}")

        # AUTO-RESPOND: If it's a text message, use AI chatbot to respond
        logger.info(f"AUTO-RESPOND CHECK: message_type={message_type}, message_text={bool(message_text)}, access_token={bool(access_token)}")
        logger.info(f"Access token value (first 20 chars): {access_token[:20] if access_token else 'NONE'}")
        if message_type in ("text", "interactive") and message_text and access_token:
            logger.info("AUTO-RESPOND: Conditions met, starting response generation")
            try:
                # === MULTI-STORE ROUTING ===
                store_id, routing_method, conversation = router.route_message(
                    phone_number=from_number_clean,
                    message_data=message
                )

                logger.info(f"Routing result: store_id={store_id}, method={routing_method}")

                # Update conversation with customer name and profile picture
                if conversation:
                    # Extract customer name from contacts
                    customer_name = get_customer_name_from_contacts(contacts)
                    if customer_name and not conversation.customer_name:
                        conversation.customer_name = customer_name
                    
                    # Set profile picture (generate avatar if not from Meta)
                    if should_update_profile_picture(conversation.profile_picture_updated_at):
                        profile_url = generate_avatar_url(
                            name=conversation.customer_name or customer_name,
                            phone_number=from_number_clean
                        )
                        conversation.profile_picture_url = profile_url
                        conversation.profile_picture_updated_at = datetime.utcnow()
                    
                    db.commit()

                # Handle case where no store is routed (needs selection)
                if store_id is None:
                    # Check if this is a store selection response
                    if conversation and conversation.routing_status == "awaiting_selection":
                        selected_store_id = router.parse_store_selection(message_text)
                        if selected_store_id:
                            # Route to selected store
                            conversation = router.route_to_store(
                                phone_number=from_number_clean,
                                store_id=selected_store_id,
                                method="user_selection"
                            )
                            store_id = selected_store_id
                            logger.info(f"Customer selected store: {store_id}")

                            # Send welcome message for the selected store
                            from modules.stores.models import Store
                            store = db.query(Store).filter(Store.id == store_id).first()
                            if store:
                                welcome = f"Great! You're now connected to {store.store_name}. How can we help you today?"
                                send_whatsapp_message_request(
                                    phone_number_id=whatsapp_account.phone_number_id,
                                    access_token=access_token,
                                    to=from_number_clean,
                                    message_type="text",
                                    message_data={"text": {"body": welcome, "preview_url": False}}
                                )
                                save_message_to_db(
                                    db=db,
                                    whatsapp_account_id=whatsapp_account.id,
                                    message_id=f"welcome_{datetime.utcnow().timestamp()}",
                                    from_number=whatsapp_account.phone_number,
                                    to_number=from_number_clean,
                                    message_type="text",
                                    direction="outbound",
                                    status="sent",
                                    message_text=welcome
                                )
                            continue
                        else:
                            # Invalid selection, send selection menu again
                            selection_message = router.build_store_selection_message()
                            if selection_message:
                                invalid_response = f"Sorry, I didn't understand that. {selection_message}"
                                send_whatsapp_message_request(
                                    phone_number_id=whatsapp_account.phone_number_id,
                                    access_token=access_token,
                                    to=from_number_clean,
                                    message_type="text",
                                    message_data={"text": {"body": invalid_response, "preview_url": False}}
                                )
                                save_message_to_db(
                                    db=db,
                                    whatsapp_account_id=whatsapp_account.id,
                                    message_id=f"selection_{datetime.utcnow().timestamp()}",
                                    from_number=whatsapp_account.phone_number,
                                    to_number=from_number_clean,
                                    message_type="text",
                                    direction="outbound",
                                    status="sent",
                                    message_text=invalid_response
                                )
                            continue

                    # First contact - send store selection menu
                    selection_message = router.build_store_selection_message()
                    if selection_message:
                        send_whatsapp_message_request(
                            phone_number_id=whatsapp_account.phone_number_id,
                            access_token=access_token,
                            to=from_number_clean,
                            message_type="text",
                            message_data={"text": {"body": selection_message, "preview_url": False}}
                        )
                        save_message_to_db(
                            db=db,
                            whatsapp_account_id=whatsapp_account.id,
                            message_id=f"selection_{datetime.utcnow().timestamp()}",
                            from_number=whatsapp_account.phone_number,
                            to_number=from_number_clean,
                            message_type="text",
                            direction="outbound",
                            status="sent",
                            message_text=selection_message
                        )
                        continue
                    else:
                        logger.warning(f"No stores available for WhatsApp account {whatsapp_account.id}")
                        continue

                # === GENERATE AI RESPONSE ===
                # Use MultiTenantSalesBot with store-specific configuration
                logger.info(f"AUTO-RESPOND: Creating bot for store {store_id}")
                bot = MultiTenantSalesBot(
                    store_id=store_id,
                    db=db
                )
                logger.info(f"AUTO-RESPOND: Bot created, generating response")

                # Run the bot - handle async properly
                logger.info(f"AUTO-RESPOND: Running generate_response")
                try:
                    # Try to get existing event loop, or create new one
                    try:
                        loop = asyncio.get_running_loop()
                        # If we're already in an async context, use run_coroutine_threadsafe
                        import concurrent.futures
                        future = asyncio.run_coroutine_threadsafe(
                            bot.generate_response(
                                user_message=message_text,
                                phone_number=from_number_clean,
                                whatsapp_account_id=whatsapp_account.id
                            ),
                            loop
                        )
                        ai_response = future.result(timeout=60)
                    except RuntimeError:
                        # No running loop, create a new one
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            ai_response = loop.run_until_complete(
                                bot.generate_response(
                                    user_message=message_text,
                                    phone_number=from_number_clean,
                                    whatsapp_account_id=whatsapp_account.id
                                )
                            )
                        finally:
                            loop.close()
                    logger.info(f"AUTO-RESPOND: Got response: {ai_response[:50] if ai_response else 'None'}...")
                except Exception as loop_error:
                    logger.error(f"AUTO-RESPOND: Event loop error: {str(loop_error)}")
                    raise

                # NO HALLUCINATION POLICY: If bot returns None, stay silent
                if ai_response is None:
                    logger.info(f"Bot has no knowledge match for query from {from_number_clean}, staying silent")
                    continue

                # WHATSAPP FLOWS: If chatbot detects purchase intent, ask how they want to order
                if "ORDER_FLOW_START" in ai_response:
                    logger.info(f"ORDER CHOICE: Purchase intent detected for {from_number_clean}, asking preference")
                    try:
                        storefront_url = os.getenv('STOREFRONT_URL', 'https://shopivell.com')
                        order_link = f"{storefront_url}/store/{store_id}/order"

                        # Send button message asking what they'd like to do
                        choice_msg = build_button_message(
                            body="Great! How can I help you today?",
                            buttons=[
                                {"id": "order_website", "title": "Order on Website"},
                                {"id": "order_whatsapp", "title": "Order in WhatsApp"},
                                {"id": "get_more_info", "title": "Get More Info"},
                            ],
                        )
                        send_whatsapp_message_request(
                            phone_number_id=whatsapp_account.phone_number_id,
                            access_token=access_token,
                            to=from_number_clean,
                            message_type=choice_msg["type"],
                            message_data=choice_msg["data"],
                        )
                        save_message_to_db(
                            db=db, whatsapp_account_id=whatsapp_account.id,
                            message_id=f"order_choice_{datetime.utcnow().timestamp()}",
                            from_number=whatsapp_account.phone_number,
                            to_number=from_number_clean,
                            message_type="interactive", direction="outbound",
                            status="sent", message_text="[Order choice buttons sent]",
                        )
                        # Mark conversation as awaiting order choice
                        if conversation:
                            conversation.order_flow_state = {"awaiting_order_choice": True, "order_link": order_link}
                            db.commit()
                        continue
                    except Exception as flow_err:
                        logger.error(f"Order choice error: {flow_err}")
                        import traceback
                        logger.error(traceback.format_exc())
                        ai_response = "I'd love to help you order! Let me check our products for you."

                logger.info(f"AI Response for {from_number_clean}: {ai_response[:100]}...")

                # Link lead scoring -> CAPI: fire a Meta Lead event if this inbound
                # message pushed the lead over the hot threshold (consent-gated, once).
                try:
                    maybe_send_capi_for_lead(db, whatsapp_account, from_number_clean)
                except Exception as capi_err:
                    logger.error(f"CAPI lead link error for {from_number_clean}: {capi_err}")

                # Save the outgoing AI response to database FIRST
                msg_id = f"ai_reply_{datetime.utcnow().timestamp()}"
                save_message_to_db(
                    db=db,
                    whatsapp_account_id=whatsapp_account.id,
                    message_id=msg_id,
                    from_number=whatsapp_account.phone_number,
                    to_number=from_number_clean,
                    message_type="text",
                    direction="outbound",
                    status="pending",
                    message_text=ai_response
                )
                logger.info(f"Saved outbound message to DB: {msg_id}")

                # Send the AI response back via WhatsApp
                try:
                    logger.info(f"Sending WhatsApp message with token: {access_token[:20]}...")
                    send_result = send_whatsapp_message_request(
                        phone_number_id=whatsapp_account.phone_number_id,
                        access_token=access_token,
                        to=from_number_clean,
                        message_type="text",
                        message_data={
                            "text": {
                                "body": ai_response,
                                "preview_url": False
                            }
                        }
                    )
                    logger.info(f"WhatsApp send result: {send_result}")

                    # Update message status to sent
                    sent_msg = db.query(WhatsAppMessage).filter(WhatsAppMessage.message_id == msg_id).first()
                    if sent_msg:
                        sent_msg.status = "sent"
                        db.commit()
                except Exception as send_error:
                    logger.error(f"Failed to send WhatsApp message: {str(send_error)}")
                    import traceback
                    logger.error(traceback.format_exc())

                logger.info(f"AI response sent to {from_number_clean}")

            except Exception as e:
                logger.error(f"Failed to generate/send AI response: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())

def process_message_statuses(statuses: List[Dict[str, Any]], db: Session):
    """Update message statuses in database"""
    for status_data in statuses:
        message_id = status_data.get("id")
        status = status_data.get("status")
        timestamp = status_data.get("timestamp")
        
        # Find message by ID
        message = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.message_id == message_id
        ).first()
        
        if message:
            old_status = message.status # Capture current status
            
            message.status = status
            message.updated_at = datetime.utcnow()
            
            # Update timestamps based on status
            if status == "delivered":
                message.delivered_at = datetime.fromtimestamp(int(timestamp))
            elif status == "read":
                message.read_at = datetime.fromtimestamp(int(timestamp))
            
            db.commit()
            db.refresh(message) # Refresh to get updated object
            
            logger.info(f"Updated message {message_id} status to {status}")
            
            # 🔔 REAL-TIME PUSH: Broadcast the status update
            # Only broadcast if the status has actually changed
            if old_status != status:
                message_response = WhatsAppMessageResponse.model_validate(message)
                asyncio.run(manager.broadcast_message(
                    str(message.whatsapp_account_id),
                    message_response.model_dump()
                ))

# Message History Endpoints
@whatsapp_router.get("/accounts/{account_id}/conversation-summaries")
def get_conversation_summaries(account_id: uuid.UUID, db: Session = Depends(get_db),
                               current_user=Depends(get_current_user)):
    """Return the latest message and unread count per contact for this account."""
    from sqlalchemy import case, func
    account = _authorize_message_account(db, current_user, account_id)
    from modules.whatsapp.models import WhatsAppConversation
    member = _authorize_message_store(db, current_user, account.store_id)
    phone = case((WhatsAppMessage.direction == 'inbound', WhatsAppMessage.from_number),
                 else_=WhatsAppMessage.to_number)
    # Stored numbers may have a leading plus or formatting separators.
    phone = func.replace(func.replace(func.replace(phone, '+', ''), ' ', ''), '-', '')
    unread = case((WhatsAppMessage.direction == 'inbound',
                   case((WhatsAppMessage.read_at.is_(None), 1), else_=0)), else_=0)
    ranked = db.query(
        phone.label('phone_number'), WhatsAppMessage.message_text.label('message_text'),
        WhatsAppMessage.timestamp.label('timestamp'),
        func.row_number().over(partition_by=phone, order_by=(WhatsAppMessage.timestamp.desc(), WhatsAppMessage.id.desc())).label('rank'),
        func.sum(unread).over(partition_by=phone).label('unread_count'),
    ).filter(WhatsAppMessage.whatsapp_account_id == account_id,
             WhatsAppMessage.direction.in_(['inbound', 'outbound']),
             phone.isnot(None), phone != '').subquery()
    rows = db.query(ranked).filter(ranked.c.rank == 1).order_by(ranked.c.timestamp.desc()).all()
    rows = [row for row in rows if member is None or member.branch_names is None or
            db.query(WhatsAppConversation.id).filter(WhatsAppConversation.whatsapp_account_id == account_id,
                WhatsAppConversation.phone_number.in_([row.phone_number, '+' + row.phone_number]),
                WhatsAppConversation.branch.in_(member.branch_names)).first()]
    return {'conversations': [{'phone_number': row.phone_number, 'last_message': row.message_text,
                               'last_message_at': row.timestamp, 'unread_count': int(row.unread_count or 0)}
                              for row in rows]}


@whatsapp_router.get("/accounts/{account_id}/messages", response_model=WhatsAppMessagesListResponse)
def get_whatsapp_messages(
    account_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    direction: Optional[str] = Query(None, regex="^(inbound|outbound)$"),
    status: Optional[str] = None,
    phone_number: Optional[str] = Query(None, description="Filter by phone number (conversation)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get WhatsApp message history"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account or not account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    member = _authorize_message_store(db, current_user, account.store_id)
    from sqlalchemy import or_
    query = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.whatsapp_account_id == account_id
    )

    # Filter by phone number if provided
    if phone_number:
        from sqlalchemy import func
        phone_clean = phone_number.replace(" ", "").replace("+", "").replace("-", "").strip()
        variants = [phone_clean]
        if phone_clean.startswith('263') and len(phone_clean) == 12:
            variants.extend(['0' + phone_clean[3:], phone_clean[3:]])
        def stripped(column):
            return func.replace(func.replace(func.replace(column, '+', ''), ' ', ''), '-', '')
        query = query.filter(or_(stripped(WhatsAppMessage.from_number).in_(variants),
                                 stripped(WhatsAppMessage.to_number).in_(variants)))
        if member is not None and member.branch_names is not None:
            from modules.whatsapp.models import WhatsAppConversation
            conversation = db.query(WhatsAppConversation).filter(
                WhatsAppConversation.whatsapp_account_id == account_id,
                WhatsAppConversation.phone_number.in_(variants)).first()
            if not conversation:
                raise HTTPException(status_code=403, detail="Conversation is not assigned to an accessible branch")
            _authorize_message_branch(db, current_user, conversation)

    if direction:
        query = query.filter(WhatsAppMessage.direction == direction)

    if status:
        query = query.filter(WhatsAppMessage.status == status)

    messages = query.order_by(WhatsAppMessage.timestamp.desc()).offset(skip).limit(limit).all()
    total_count = query.count()
    
    return WhatsAppMessagesListResponse(
        messages=[WhatsAppMessageResponse.model_validate(msg) for msg in messages],
        total_count=total_count
    )


@whatsapp_router.get("/accounts/{account_id}/conversations/{phone_number}/messages", response_model=WhatsAppMessagesListResponse)
def get_conversation_messages(
    account_id: uuid.UUID,
    phone_number: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get messages for a specific conversation (phone number)"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account or not account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    member = _authorize_message_store(db, current_user, account.store_id)
    # Clean phone number
    phone_clean = phone_number.replace(" ", "").replace("+", "").replace("-", "").strip()
    if member is not None and member.branch_names is not None:
        conv = db.query(WhatsAppConversation).filter(
            WhatsAppConversation.whatsapp_account_id == account_id,
            WhatsAppConversation.phone_number.in_([phone_clean, "+" + phone_clean])).first()
        if not conv:
            raise HTTPException(status_code=403, detail="Conversation is not assigned to an accessible branch")
        _authorize_message_branch(db, current_user, conv)

    # Get messages where this phone is either sender or recipient
    from sqlalchemy import or_
    query = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.whatsapp_account_id == account_id,
        or_(
            WhatsAppMessage.from_number == phone_clean,
            WhatsAppMessage.from_number == f"+{phone_clean}",
            WhatsAppMessage.to_number == phone_clean,
            WhatsAppMessage.to_number == f"+{phone_clean}"
        )
    )

    total_count = query.count()
    messages = query.order_by(WhatsAppMessage.timestamp.asc()).offset(skip).limit(limit).all()

    return WhatsAppMessagesListResponse(
        messages=[WhatsAppMessageResponse.model_validate(msg) for msg in messages],
        total_count=total_count
    )


# Conversations Endpoints
@whatsapp_router.get("/accounts/{account_id}/conversations", response_model=ConversationListResponse)
def get_conversations(
    account_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status: active, handoff, closed"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all conversations for a WhatsApp account with profile pictures"""
    # Verify account exists
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account or not account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    member = _authorize_message_store(db, current_user, account.store_id)
    
    query = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.whatsapp_account_id == account_id
    )
    if member is not None and member.branch_names is not None:
        if not member.branch_names:
            return ConversationListResponse(conversations=[], total=0, page=page, page_size=page_size)
        query = query.filter(WhatsAppConversation.branch.in_(member.branch_names))
    
    if status_filter:
        query = query.filter(WhatsAppConversation.status == status_filter)
    
    total = query.count()
    
    conversations = query.order_by(
        WhatsAppConversation.last_message_at.desc().nullslast()
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    # Generate profile pictures for conversations that don't have one
    for conv in conversations:
        if not conv.profile_picture_url:
            conv.profile_picture_url = generate_avatar_url(
                name=conv.customer_name,
                phone_number=conv.phone_number
            )
            conv.profile_picture_updated_at = datetime.utcnow()
    
    db.commit()
    
    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(conv) for conv in conversations],
        total=total,
        page=page,
        page_size=page_size
    )


# WhatsApp Account Information Endpoints
@whatsapp_router.get("/accounts/{account_id}/info")
def get_whatsapp_account_info(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get WhatsApp account information from Facebook API"""
    _authorize_message_account(db, current_user, account_id)
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    
    try:
        # Get WhatsApp Business Account details
        waba_response = requests.get(
            f"{WHATSAPP_API_BASE}/{whatsapp_account.waba_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "fields": "id,name,timezone_id,message_template_namespace,onboarding_status"
            }
        )
        
        waba_data = {}
        if waba_response.status_code == 200:
            waba_data = waba_response.json()
        
        # Get phone number details
        phone_response = requests.get(
            f"{WHATSAPP_API_BASE}/{whatsapp_account.phone_number_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "fields": "verified_name,quality_rating,display_phone_number"
            }
        )
        
        phone_data = {}
        if phone_response.status_code == 200:
            phone_data = phone_response.json()
        
        # Update account with new information
        if phone_data.get("quality_rating"):
            whatsapp_account.quality_rating = phone_data.get("quality_rating")
        
        if phone_data.get("verified_name"):
            whatsapp_account.verified_name = phone_data.get("verified_name")
        
        db.commit()
        
        return {
            "success": True,
            "waba_info": waba_data,
            "phone_info": phone_data,
            "account": WhatsAppAccountResponse.model_validate(whatsapp_account)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get WhatsApp account info: {str(e)}"
        )

# Quick test endpoint
@whatsapp_router.post("/test/send-message")
def test_send_message(
    account_id: uuid.UUID,
    to: str = Query(..., description="Your phone number in E.164 format (no spaces, no +)"),
    message: str = Query("Hello from WhatsApp API!", description="Message text"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Improved test endpoint to send WhatsApp messages"""
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    _authorize_message_store(db, current_user, whatsapp_account.store_id)

    try:
        # Clean phone number (remove spaces, +)
        to_clean = to.replace(" ", "").replace("+", "").strip()

        # Check if we have an active conversation window (last 24 hours)
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)

        recent_message = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.whatsapp_account_id == account_id,
            WhatsAppMessage.from_number == to_clean,
            WhatsAppMessage.direction == "inbound",
            WhatsAppMessage.timestamp >= twenty_four_hours_ago
        ).first()

        if recent_message:
            # User has messaged in last 24 hours, send regular text
            result = send_text_message(whatsapp_account, access_token, to_clean, message, db)
        else:
            # No active 24-hour window — cannot initiate a conversation
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "24-hour window expired — message not sent. The customer must "
                    "message you first before you can reply."
                )
            )
        
        return {
            "success": True,
            "message": result.get("message"),
            "message_id": result.get("message_id"),
            "wamid": result.get("wamid"),
            "recipient": to_clean,
            "type": result.get("type"),
            "note": result.get("note")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test message error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send test message: {str(e)}"
        )

def send_text_message(whatsapp_account, access_token, to, message, db):
    """Send regular text message"""
    try:
        result = send_whatsapp_message_request(
            phone_number_id=whatsapp_account.phone_number_id,
            access_token=access_token,
            to=to,
            message_type="text",
            message_data={
                "text": {
                    "body": message,
                    "preview_url": False
                }
            }
        )
        
        message_id = result.get("messages", [{}])[0].get("id")
        wamid = result.get("messages", [{}])[0].get("wamid")
        
        # Save to database
        saved_message = save_message_to_db(
            db=db,
            whatsapp_account_id=whatsapp_account.id,
            message_id=message_id or f"temp_{datetime.utcnow().timestamp()}",
            from_number=whatsapp_account.phone_number,
            to_number=to,
            message_type="text",
            direction="outbound",
            status="sent",
            message_text=message,
            wamid=wamid,
            meta_data=result
        )
        
        # 🔔 REAL-TIME PUSH: Broadcast the new outgoing message
        if saved_message:
            message_response = WhatsAppMessageResponse.model_validate(saved_message)
            asyncio.run(manager.broadcast_message(
                str(whatsapp_account.id),
                message_response.model_dump()
            ))
        
        return {
            "success": True,
            "message": "Text message sent successfully",
            "message_id": message_id,
            "wamid": wamid,
            "recipient": to,
            "type": "text",
            "note": "Text message sent (24-hour window is active). Check your WhatsApp."
        }
        
    except HTTPException as e:
        # No template fallback — template messaging has been removed.
        logger.error(f"Text message failed: {e.detail}")
        raise

# Conversions API Base URL (Used for Conversions)
META_GRAPH_URL = "https://graph.facebook.com/v18.0" 

# --- NEW HELPER FUNCTIONS FOR CONVERSIONS API ---

def normalize_and_hash_pii(value: str, is_phone: bool = False) -> Optional[str]:
    """Normalizes PII (removes symbols/spaces, lowercases) and returns SHA256 hash."""
    if not value:
        return None
    
    normalized = str(value).lower()
    
    if is_phone:
        # Normalize Phone: Remove all non-digit characters (keeping the country code numbers)
        normalized = ''.join(filter(str.isdigit, normalized))
    else:
        # General normalization: remove spaces, trim, etc. (for email, name)
        normalized = normalized.strip().replace(' ', '')
        
    if not normalized:
        return None
        
    # Hash with SHA256
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

# --- NEW BACKGROUND TASK FOR CONVERSIONS API ---

def send_conversion_event_background(
    capi_access_token: str,
    capi_dataset_id: str,
    event_data: WhatsAppConversionEvent
):
    """
    Background task to send the conversion event to Meta's Conversions API.
    """
    CAPI_API_BASE = "https://graph.facebook.com/v20.0" # Use a stable version

    # --- 1. Prepare User Data (PII Hashing) ---
    user_data = {}
    
    # HASH REQUIRED: phone_number (E.164 format)
    if event_data.phone_number:
        user_data['ph'] = [normalize_and_hash_pii(event_data.phone_number)]
        
    # HASH OPTIONAL: email
    if event_data.email:
        user_data['em'] = [normalize_and_hash_pii(event_data.email)]
        
    # HASH OPTIONAL: names
    if event_data.first_name:
        user_data['fn'] = [normalize_and_hash_pii(event_data.first_name)]
    if event_data.last_name:
        user_data['ln'] = [normalize_and_hash_pii(event_data.last_name)]

    # --- 2. Prepare Custom Data (Value, Currency, Order ID) ---
    custom_data = {}
    if event_data.value is not None:
        custom_data['value'] = event_data.value
    if event_data.currency:
        custom_data['currency'] = event_data.currency
    if event_data.order_id:
        custom_data['order_id'] = event_data.order_id

    # --- 3. Build the Final CAPI Event Payload ---
    # The CAPI accepts a list of events
    event_time = int(datetime.utcnow().timestamp())
    
    event = {
        'event_name': event_data.event_name,
        'event_time': event_time,
        'action_source': event_data.action_source.value,
        'user_data': user_data,
        'custom_data': custom_data if custom_data else None,
        # 'event_source_url' is optional but helpful for debugging
    }

    capi_payload = {
        'data': [event],
        'access_token': capi_access_token
    }

    # --- 4. Send Request to Meta CAPI ---
    url = f"{CAPI_API_BASE}/{capi_dataset_id}/events"
    
    try:
        response = requests.post(url, json=capi_payload, timeout=10)
        response.raise_for_status()
        logger.info(f"CAPI Success for {event_data.event_name}. Meta response: {response.json()}")
    
    except requests.exceptions.RequestException as e:
        error_detail = "CAPI Unknown Error"
        try:
            error_detail = e.response.json().get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
            
        logger.error(f"Failed to send CAPI event {event_data.event_name}. Error: {error_detail}")
        # Note: Do not raise HTTPException here, as this is a background task.
        # Log the error for later review.
        
@whatsapp_router.post("/debug/send-test")
def debug_send_test_message(
    account_id: uuid.UUID,
    to: str = Query(..., description="Recipient phone number"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Debug endpoint to test WhatsApp message sending (text only)"""
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    _authorize_message_store(db, current_user, whatsapp_account.store_id)

    try:
        message_type = "text"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "body": "Test message from WhatsApp API",
                "preview_url": False
            }
        }

        url = f"{WHATSAPP_API_BASE}/{whatsapp_account.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"Sending {message_type} message to {to}")
        logger.info(f"URL: {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        # Log full response
        logger.info(f"Response Status: {response.status_code}")
        logger.info(f"Response Headers: {dict(response.headers)}")
        logger.info(f"Response Body: {response.text}")
        
        if response.status_code >= 400:
            error_data = response.json()
            logger.error(f"WhatsApp API Error: {error_data}")
            
            return {
                "success": False,
                "error": error_data.get("error", {}),
                "status_code": response.status_code,
                "note": "Message failed to send. See logs for details."
            }
        
        result = response.json()
        
        return {
            "success": True,
            "message_type": message_type,
            "response": result,
            "note": f"{message_type.capitalize()} message sent. Check logs for details."
        }
        
    except Exception as e:
        logger.error(f"Debug endpoint error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Debug error: {str(e)}"
        )
    
# --- CONVERSIONS API ENDPOINT ---

# Insert this endpoint after your existing messaging endpoints

@whatsapp_router.post("/accounts/{account_id}/send-conversion", status_code=status.HTTP_202_ACCEPTED)
def send_whatsapp_conversion_event(
    account_id: uuid.UUID,
    event_data: WhatsAppConversionEvent,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Sends an offline conversion event to Meta's Conversions API (CAPI) 
    using the configured Dataset ID and Access Token for the WhatsApp Account.
    The task is executed in the background.
    """
    
    # 1. Retrieve the WhatsApp Account and CAPI Credentials from the database
    whatsapp_account, _ = get_whatsapp_client(account_id, db)
    from modules.users.access import require_store_capability
    require_store_capability(db, current_user, whatsapp_account.store_id, 'ads')

    # COMPLIANCE: customer data (even hashed) may only be shared with Meta if
    # the customer has consent on record and has not opted out.
    if event_data.phone_number:
        if consent.is_suppressed(db, account_id, event_data.phone_number):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer has opted out — conversion event not sent to Meta."
            )
        if not consent.has_marketing_opt_in(db, account_id, event_data.phone_number):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Customer has no marketing consent on record — conversion "
                    "event not sent to Meta (Business Tools Terms require consent)."
                )
            )

    capi_dataset_id = whatsapp_account.capi_dataset_id
    capi_access_token = whatsapp_account.capi_access_token # NOTE: DECRYPT HERE IF ENCRYPTED IN DB!

    if not capi_dataset_id or not capi_access_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversions API configuration is missing (Dataset ID or Access Token). Please configure via the /capi-settings endpoint."
        )

    # 2. Add the conversion task to the background queue
    background_tasks.add_task(
        send_conversion_event_background,
        capi_access_token=capi_access_token,
        capi_dataset_id=capi_dataset_id,
        event_data=event_data
    )

    return {
        "status": "Conversion event accepted and is being processed in the background.",
        "event_name": event_data.event_name,
        "recipient_phone_number": event_data.phone_number
    }

@whatsapp_router.post("/accounts/{account_id}/capi-settings", status_code=status.HTTP_200_OK)
def update_capi_settings(
    account_id: uuid.UUID,
    settings: ConversionsAPISettingsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Saves the Meta Conversions API Dataset ID and Access Token for the account.
    This data is required for the /send-conversion endpoint.
    """
    
    # 1. Find the WhatsApp Account
    whatsapp_account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id
    ).first()

    if not whatsapp_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"WhatsApp Account with ID {account_id} not found."
        )
    from modules.users.auth_router import _require_store_owner
    _require_store_owner(db, whatsapp_account.store_id, current_user)

    # 2. Update the fields
    # *****************************************************************
    # NOTE: In a real system, you would ENCRYPT the access token here 
    # before assigning it to the model property!
    # *****************************************************************
    whatsapp_account.capi_dataset_id= settings.capi_dataset_id
    whatsapp_account.capi_access_token = settings.capi_access_token
    
    # 3. Commit the changes
    db.add(whatsapp_account)
    db.commit()
    db.refresh(whatsapp_account)

    return {
        "message": "Conversions API settings updated successfully.",
        "dataset_id": whatsapp_account.capi_dataset_id,
        "note": "Access Token was saved securely (should be encrypted in production)."
    }

# --- IMPORTANT CHANGE TO PREVIOUS /send-conversion ENDPOINT ---

# You must also update your /send-conversion endpoint to use the 
# database-saved capi_dataset_id instead of relying on the environment variable:

class SavedReplyInput(BaseModel):
    title: str
    body: str


def _authorize_message_store(db, user, store_id):
    from modules.whatsapp.faq_router import check_store_access
    if check_store_access(db, user, store_id):
        return
    from modules.users.models import StoreMember
    member = db.query(StoreMember).filter(
        StoreMember.store_id == store_id,
        StoreMember.user_id == uuid.UUID(str(user.id)),
        StoreMember.is_active.is_(True)).first()
    if not member or 'messages' not in (member.permissions or []):
        raise HTTPException(status_code=403, detail="Not authorized to access messages for this store")
    return member


def _authorize_message_branch(db, user, conversation):
    member = _authorize_message_store(db, user, conversation.store_id)
    # Owners and legacy members (branch_names is NULL) retain their existing scope.
    if member is not None and member.branch_names is not None and conversation.branch not in (member.branch_names or []):
        raise HTTPException(status_code=403, detail="This conversation belongs to a branch you cannot manage")
    return member


@whatsapp_router.get("/stores/{store_id}/pharmacy/branches")
def pharmacy_branches(store_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _authorize_message_store(db, current_user, store_id)
    from modules.whatsapp.models import WhatsAppConversation
    from sqlalchemy import distinct, or_
    values = {row[0] for row in db.query(distinct(CompanyKnowledge.branch)).filter(
        CompanyKnowledge.store_id == store_id, CompanyKnowledge.branch.isnot(None), CompanyKnowledge.branch != "").all()}
    values.update(row[0] for row in db.query(distinct(WhatsAppConversation.branch)).filter(
        WhatsAppConversation.store_id == store_id, WhatsAppConversation.branch.isnot(None), WhatsAppConversation.branch != "").all())
    return {"branches": sorted(values)}


class ConversationBranchInput(BaseModel):
    branch: Optional[str] = None


@whatsapp_router.patch("/stores/{store_id}/conversations/{conversation_id}/branch")
def assign_conversation_branch(store_id: uuid.UUID, conversation_id: uuid.UUID, data: ConversationBranchInput,
                               db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from modules.whatsapp.models import WhatsAppConversation
    member = _authorize_message_store(db, current_user, store_id)
    row = db.query(WhatsAppConversation).filter(WhatsAppConversation.id == conversation_id,
                                                WhatsAppConversation.store_id == store_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if member is not None:
        raise HTTPException(status_code=403, detail="Only the store owner can route conversations between branches")
    branch = data.branch.strip() if data.branch else None
    if branch:
        available = {item[0] for item in db.query(CompanyKnowledge.branch).filter(
            CompanyKnowledge.store_id == store_id, CompanyKnowledge.branch == branch).distinct().all()}
        if branch not in available:
            raise HTTPException(status_code=400, detail="Choose a branch registered for this store")
    row.branch = branch
    db.commit()
    return {"conversation_id": str(row.id), "branch": row.branch}


@whatsapp_router.get("/stores/{store_id}/pharmacy/prescriptions")
def pharmacy_prescription_queue(store_id: uuid.UUID, branch: Optional[str] = None,
                                db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from modules.whatsapp.models import WhatsAppConversation
    member = _authorize_message_store(db, current_user, store_id)
    query = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.store_id == store_id,
        WhatsAppConversation.handoff_requested.is_(True),
        WhatsAppConversation.handoff_reason.ilike("%prescription%"))
    if member is not None and member.branch_names is not None:
        if not member.branch_names:
            return {"prescriptions": []}
        query = query.filter(WhatsAppConversation.branch.in_(member.branch_names))
    if branch:
        query = query.filter(WhatsAppConversation.branch == branch)
    rows = query.order_by(WhatsAppConversation.last_message_at.desc().nullslast()).limit(200).all()
    return {"prescriptions": [{"id": str(row.id), "phone_number": row.phone_number,
                                "customer_name": row.customer_name, "branch": row.branch,
                                "last_message_at": row.last_message_at, "status": row.status,
                                "handoff_reason": row.handoff_reason} for row in rows]}


class PrescriptionStatusInput(BaseModel):
    status: str


@whatsapp_router.patch("/stores/{store_id}/pharmacy/prescriptions/{conversation_id}/status")
def update_pharmacy_prescription_status(store_id: uuid.UUID, conversation_id: uuid.UUID,
                                        data: PrescriptionStatusInput, db: Session = Depends(get_db),
                                        current_user=Depends(get_current_user)):
    if data.status not in {"handoff", "closed"}:
        raise HTTPException(status_code=400, detail="Status must be handoff or closed")
    row = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.id == conversation_id,
        WhatsAppConversation.store_id == store_id,
        WhatsAppConversation.handoff_requested.is_(True),
        WhatsAppConversation.handoff_reason.ilike("%prescription%")
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prescription request not found")
    _authorize_message_branch(db, current_user, row)
    row.status = data.status
    db.commit()
    return {"id": str(row.id), "status": row.status}


def _authorize_message_account(db, user, account_id):
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account or not account.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    _authorize_message_store(db, user, account.store_id)
    return account


@whatsapp_router.get("/stores/{store_id}/saved-replies")
def list_saved_replies(store_id: uuid.UUID, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    from modules.whatsapp.models import MessageTemplate
    _authorize_message_store(db, current_user, store_id)
    rows = db.query(MessageTemplate).filter(MessageTemplate.store_id == store_id).order_by(MessageTemplate.created_at).all()
    return [{"id": str(r.id), "title": r.title, "body": r.body} for r in rows]


@whatsapp_router.post("/stores/{store_id}/saved-replies", status_code=201)
def create_saved_reply(store_id: uuid.UUID, data: SavedReplyInput, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    from modules.whatsapp.models import MessageTemplate
    _authorize_message_store(db, current_user, store_id)
    title, body = data.title.strip(), data.body.strip()
    if not title or len(title) > 120 or not body or len(body) > 4096:
        raise HTTPException(status_code=400, detail="Enter a title and message (maximum 4,096 characters).")
    row = MessageTemplate(store_id=store_id, title=title, body=body)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": str(row.id), "title": row.title, "body": row.body}


@whatsapp_router.delete("/stores/{store_id}/saved-replies/{reply_id}")
def delete_saved_reply(store_id: uuid.UUID, reply_id: uuid.UUID, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    from modules.whatsapp.models import MessageTemplate
    _authorize_message_store(db, current_user, store_id)
    row = db.query(MessageTemplate).filter(MessageTemplate.id == reply_id, MessageTemplate.store_id == store_id).first()
    if not row: raise HTTPException(status_code=404, detail="Saved reply not found")
    db.delete(row); db.commit()
    return {"success": True}


@whatsapp_router.post("/accounts/{account_id}/send-attachment")
async def send_attachment(account_id: uuid.UUID, to: str = Form(...), caption: str = Form(""),
                          file: UploadFile = File(...), db: Session = Depends(get_db),
                          current_user=Depends(get_current_user)):
    import httpx
    from modules.openclaw.router import (_zernio, _zernio_account_id_for_wa,
        _persist_sandbox_message, ZERNIO_API_BASE, ZERNIO_API_KEY, ZERNIO_SANDBOX_ACCOUNT_ID)
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not account or not account.store_id: raise HTTPException(status_code=404, detail="WhatsApp account not found")
    member = _authorize_message_store(db, current_user, account.store_id)
    target = ''.join(c for c in to if c.isdigit())
    if member is not None and member.branch_names is not None:
        conversation = db.query(WhatsAppConversation).filter(
            WhatsAppConversation.whatsapp_account_id == account_id,
            WhatsAppConversation.phone_number.in_([target, '+' + target])).first()
        if not conversation:
            raise HTTPException(status_code=403, detail="Conversation is not assigned to an accessible branch")
        _authorize_message_branch(db, current_user, conversation)
    if is_whatsapp_service_number(target):
        raise HTTPException(status_code=403, detail='Replies to WhatsApp service notifications are disabled')
    if not target:
        raise HTTPException(status_code=400, detail="Customer phone number is required")
    if consent.is_suppressed(db, account_id, target):
        raise HTTPException(status_code=403, detail="This customer has opted out of messages")
    content = await file.read(25 * 1024 * 1024 + 1)
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Choose a file of up to 25 MB")
    account_id_z = await _zernio_account_id_for_wa(account)
    if (account_id_z == ZERNIO_SANDBOX_ACCOUNT_ID
            and not str(account.waba_id or '').startswith('zernio-sandbox-')):
        raise HTTPException(status_code=503, detail="Could not resolve the connected WhatsApp account. Please try again.")
    convs = await _zernio("GET", "/inbox/conversations", params={"platform":"whatsapp", "limit":50, "accountId":account_id_z})
    conv = next((c for c in (convs.get("data") or []) if ''.join(x for x in str(c.get("participantId") or c.get("participantUsername") or "") if x.isdigit()) == target), None)
    if not conv: raise HTTPException(status_code=400, detail="No open conversation with this customer")
    async with httpx.AsyncClient(timeout=60) as client:
        upload = await client.post(f"{ZERNIO_API_BASE}/media/upload-direct", headers={"Authorization":f"Bearer {ZERNIO_API_KEY}"}, files={"file":(file.filename or "attachment",content,file.content_type or "application/octet-stream")})
        if upload.status_code >= 400: raise HTTPException(status_code=502, detail="Could not upload attachment")
        url = upload.json().get("url")
    if not url: raise HTTPException(status_code=502, detail="Attachment upload returned no URL")
    kind = (file.content_type or '').split('/')[0]
    kind = kind if kind in ('image','video','audio') else 'file'
    result = await _zernio("POST", f"/inbox/conversations/{conv['id']}/messages", json_body={"accountId":account_id_z,"message":caption,"attachmentUrl":url,"attachmentType":kind,"attachmentName":file.filename or 'attachment'})
    mid = ((result or {}).get("data") or {}).get("messageId")
    history_url = url
    try:
        from modules.assets.service import AssetService
        saved, error = await asyncio.to_thread(
            AssetService(db).upload_to_minio, content,
            os.path.basename(file.filename or "attachment"), account.store_id,
            file.content_type or "application/octet-stream")
        if saved and saved.get("url"):
            history_url = saved["url"]
        elif error:
            logger.warning("Attachment history storage failed: %s", error)
    except Exception:
        logger.exception("Attachment was sent but permanent history storage failed")
    try:
        _persist_sandbox_message(db, account, target, None, "outbound", caption, mid, media_urls=[history_url])
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Attachment sent but could not be saved to message history")
    return {"success":True,"message_id":mid}


@whatsapp_router.post("/accounts/{account_id}/send-text", response_model=WhatsAppMessageSendResponse)
def send_whatsapp_direct_text_message(
    account_id: uuid.UUID,
    message_data: WhatsAppTextMessage, # Assuming this schema has 'to' and 'message_text'
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Send a direct text message within the 24-hour customer service window.
    """
    # Shopivell's own Meta App isn't approved for production WhatsApp access (App
    # Review rejected the permission request - see WORKLOG.md), so the direct-Meta
    # path below can't work for any tenant going forward, regardless of whether an
    # account happens to have a stored permanent_access_token. Every send for a
    # known account routes through Zernio, which holds its own approved Meta
    # access, and returns here on both success and failure. The direct-Meta code
    # below is unreachable except when account_id doesn't match any row at all.
    _sandbox_acct = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    if not _sandbox_acct or not _sandbox_acct.store_id:
        raise HTTPException(status_code=404, detail="WhatsApp account not found")
    member = _authorize_message_store(db, current_user, _sandbox_acct.store_id)
    to_clean = ''.join(c for c in message_data.to if c.isdigit())
    if member is not None and member.branch_names is not None:
        conversation = db.query(WhatsAppConversation).filter(
            WhatsAppConversation.whatsapp_account_id == account_id,
            WhatsAppConversation.phone_number.in_([to_clean, '+' + to_clean])).first()
        if not conversation:
            raise HTTPException(status_code=403, detail="Conversation is not assigned to an accessible branch")
        _authorize_message_branch(db, current_user, conversation)
    if is_whatsapp_service_number(to_clean):
        raise HTTPException(status_code=403, detail='Replies to WhatsApp service notifications are disabled')
    if consent.is_suppressed(db, account_id, to_clean):
        return WhatsAppMessageSendResponse(success=False, message_id=None, wamid=None,
                                           message="Recipient has opted out and cannot be messaged.")
    if _sandbox_acct is not None:
        from modules.openclaw.router import (
            sandbox_send_text_sync, _persist_sandbox_message, _zernio_account_id_for_wa,
        )
        import asyncio as _asyncio
        try:
            zernio_account_id = _asyncio.run(_zernio_account_id_for_wa(_sandbox_acct))
            mid = sandbox_send_text_sync(message_data.to, message_data.body, zernio_account_id)
            _persist_sandbox_message(
                db, _sandbox_acct, message_data.to, None,
                "outbound", message_data.body, mid,
            )
            db.commit()
            return WhatsAppMessageSendResponse(
                success=True, message_id=mid, wamid=mid, message="Sent via Zernio.",
            )
        except HTTPException as he:
            return WhatsAppMessageSendResponse(
                success=False, message_id=None, wamid=None,
                message=str(he.detail),
            )

    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    to_clean = message_data.to.replace(" ", "").replace("+", "").strip()

    # COMPLIANCE: opted-out (STOP) numbers may never be messaged, even within
    # the 24-hour customer service window.
    if consent.is_suppressed(db, account_id, to_clean):
        return WhatsAppMessageSendResponse(
            success=False,
            message_id=None,
            wamid=None,
            message="Recipient has opted out (STOP) and cannot be messaged."
        )

    # 1. Check for active 24-hour window
    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
    
    recent_message = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.whatsapp_account_id == account_id,
        WhatsAppMessage.from_number == to_clean,
        WhatsAppMessage.direction == "inbound",
        WhatsAppMessage.timestamp >= twenty_four_hours_ago
    ).first()
    
    if recent_message:
        # 2. Window is open: Attempt to send non-template text message
        logger.info(f"24-hour window active for {to_clean}. Sending direct text.")
        
        result = send_text_message(
            whatsapp_account, 
            access_token, 
            to_clean, 
            message_data.body, 
            db
        )
        
        # Map the utility dict result to the required Pydantic response model
        return WhatsAppMessageSendResponse(
            success=True,
            message_id=result.get("message_id"),
            wamid=result.get("wamid"),
            message=result.get("message")
        )
        
    else:
        # 3. Window is closed: conversations cannot be initiated by the
        # business. Initiating outside the 24h window contributed to WABA
        # quality blocks. Fail loudly instead.
        logger.warning(f"24-hour window closed for {to_clean}. Message NOT sent.")
        return WhatsAppMessageSendResponse(
            success=False,
            message_id=None,
            wamid=None,
            message=(
                "24-hour window expired — message not sent. The customer must "
                "message you first before you can reply."
            )
        )
    

@whatsapp_router.post("/accounts/{account_id}/chat")
async def chat_and_respond(
    account_id: uuid.UUID,
    message_data: WhatsAppTextMessage,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Process a message with AI, score the lead, and send response via WhatsApp.
    If lead score >= 70, sends conversion event to Meta CAPI.
    """
    try:
        whatsapp_account, access_token = get_whatsapp_client(account_id, db)
        if not whatsapp_account.store_id:
            raise HTTPException(status_code=404, detail="WhatsApp account not found")
        _authorize_message_store(db, current_user, whatsapp_account.store_id)
        to_clean = message_data.to.replace(" ", "").replace("+", "").strip()

        # 1. Get or create lead record
        lead = db.query(WhatsAppLead).filter(
            WhatsAppLead.whatsapp_account_id == account_id,
            WhatsAppLead.phone_number == to_clean
        ).first()

        if not lead:
            lead = WhatsAppLead(
                whatsapp_account_id=account_id,
                phone_number=to_clean,
                lead_score=0,
                lead_status="new",
                total_messages=0
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)

        # 2. Get store_id from WhatsApp account
        store_id = whatsapp_account.store_id

        if not store_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WhatsApp account is not linked to a store"
            )

        # 3. Generate AI response using MultiTenantSalesBot
        bot = MultiTenantSalesBot(
            store_id=store_id,
            db=db
        )

        ai_response = await bot.generate_response(
            user_message=message_data.body,
            phone_number=to_clean,
            whatsapp_account_id=account_id
        )

        # NO HALLUCINATION POLICY: If bot returns None, stay silent
        if ai_response is None:
            logger.info(f"Bot has no knowledge match for {to_clean}, staying silent")
            return {
                "success": False,
                "message": "No knowledge match - staying silent. Notification sent to store owner.",
                "lead": {
                    "phone_number": to_clean,
                    "score": lead.lead_score,
                    "status": lead.lead_status
                }
            }

        logger.info(f"AI Response for {to_clean}: {ai_response}")

        # Lead scoring and updates are now handled inside MultiTenantSalesBot
        # Refresh lead to get updated values
        db.refresh(lead)

        logger.info(f"LEAD SCORE: {to_clean} = {lead.lead_score} | Status: {lead.lead_status}")

        # 4. Send to Meta CAPI if hot lead and not already sent
        # COMPLIANCE: customer data (even hashed) is only shared with Meta if
        # the customer has marketing opt-in on record and has not opted out
        # (Meta Business Tools Terms require consent for shared data).
        capi_result = None
        is_hot_lead = lead.lead_score >= 80 if lead.lead_score else False
        has_consent = bool(lead.marketing_opt_in and lead.opted_out_at is None)
        if is_hot_lead and not lead.conversion_sent and not has_consent:
            logger.info(
                f"Hot lead {to_clean} NOT sent to CAPI: no marketing consent on record"
            )
        if is_hot_lead and not lead.conversion_sent and has_consent:
            if whatsapp_account.capi_dataset_id and whatsapp_account.capi_access_token:
                capi_result = send_capi_lead_event(
                    pixel_id=whatsapp_account.capi_dataset_id,
                    access_token=whatsapp_account.capi_access_token,
                    phone_number=to_clean,
                    lead_score=lead.lead_score or 80
                )
                if capi_result.get("success"):
                    lead.conversion_sent = True
                    lead.conversion_event_id = capi_result.get("event_id")
                    lead.conversion_sent_at = datetime.utcnow()
                    db.commit()
                    logger.info(f"CAPI Lead event sent for {to_clean}")

        # 7. Send via WhatsApp API
        send_result = send_whatsapp_message_request(
            phone_number_id=whatsapp_account.phone_number_id,
            access_token=access_token,
            to=to_clean,
            message_type="text",
            message_data={
                "text": {
                    "body": ai_response,
                    "preview_url": False
                }
            }
        )

        # 8. Save to database
        message_id = send_result.get("messages", [{}])[0].get("id")
        save_message_to_db(
            db=db,
            whatsapp_account_id=account_id,
            message_id=message_id or f"ai_chat_{datetime.utcnow().timestamp()}",
            from_number=whatsapp_account.phone_number,
            to_number=to_clean,
            message_type="text",
            direction="outbound",
            status="sent",
            message_text=ai_response
        )

        return {
            "success": True,
            "question": message_data.body,
            "response": ai_response,
            "sent_to": to_clean,
            "lead_score": lead.lead_score,
            "lead_status": lead.lead_status,
            "is_hot_lead": is_hot_lead,
            "interests": lead.interests,
            "reasoning": lead.scoring_reason,
            "capi_sent": capi_result.get("success") if capi_result else False
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@whatsapp_router.get("/leads")
def get_all_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    min_score: Optional[float] = Query(None, description="Minimum lead score"),
    status_filter: Optional[str] = Query(None, description="Filter by status: new, engaged, qualified, converted"),
    hot_leads_only: bool = Query(False, description="Only show hot leads (score >= 70)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get leads for the selected store's WhatsApp accounts."""
    if not current_user.store_id:
        raise HTTPException(status_code=403, detail="Select a store")
    store_id = uuid.UUID(current_user.store_id)
    _authorize_message_store(db, current_user, store_id)
    query = db.query(WhatsAppLead).join(WhatsAppAccount,
        WhatsAppLead.whatsapp_account_id == WhatsAppAccount.id).filter(WhatsAppAccount.store_id == store_id)

    if min_score is not None:
        query = query.filter(WhatsAppLead.lead_score >= min_score)

    if status_filter:
        query = query.filter(WhatsAppLead.lead_status == status_filter)

    if hot_leads_only:
        query = query.filter(WhatsAppLead.lead_score >= 70)

    total = query.count()
    leads = query.order_by(WhatsAppLead.lead_score.desc()).offset(skip).limit(limit).all()

    return {
        "success": True,
        "total": total,
        "leads": [
            {
                "id": str(lead.id),
                "whatsapp_account_id": str(lead.whatsapp_account_id),
                "phone_number": lead.phone_number,
                "lead_score": lead.lead_score,
                "lead_status": lead.lead_status,
                "is_hot_lead": lead.lead_score >= 70 if lead.lead_score else False,
                "scoring_reason": lead.scoring_reason,
                "total_messages": lead.total_messages,
                "last_message": lead.last_message,
                "interests": lead.interests,
                "conversion_sent": lead.conversion_sent,
                "conversion_event_id": lead.conversion_event_id,
                "conversion_sent_at": lead.conversion_sent_at.isoformat() if lead.conversion_sent_at else None,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
                "updated_at": lead.updated_at.isoformat() if lead.updated_at else None
            }
            for lead in leads
        ],
        "pagination": {
            "skip": skip,
            "limit": limit,
            "has_more": total > (skip + limit)
        }
    }


@whatsapp_router.get("/accounts/{account_id}/leads")
def get_leads(
    account_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    min_score: Optional[float] = Query(None, description="Minimum lead score"),
    status_filter: Optional[str] = Query(None, description="Filter by status: new, engaged, qualified, converted"),
    hot_leads_only: bool = Query(False, description="Only show hot leads (score >= 70)"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all leads for a WhatsApp account with their scores and details"""
    _authorize_message_account(db, current_user, account_id)
    query = db.query(WhatsAppLead).filter(
        WhatsAppLead.whatsapp_account_id == account_id
    )

    if min_score is not None:
        query = query.filter(WhatsAppLead.lead_score >= min_score)

    if status_filter:
        query = query.filter(WhatsAppLead.lead_status == status_filter)

    if hot_leads_only:
        query = query.filter(WhatsAppLead.lead_score >= 70)

    total = query.count()
    leads = query.order_by(WhatsAppLead.lead_score.desc()).offset(skip).limit(limit).all()

    return {
        "success": True,
        "total": total,
        "leads": [
            {
                "id": str(lead.id),
                "phone_number": lead.phone_number,
                "lead_score": lead.lead_score,
                "lead_status": lead.lead_status,
                "is_hot_lead": lead.lead_score >= 70 if lead.lead_score else False,
                "scoring_reason": lead.scoring_reason,
                "total_messages": lead.total_messages,
                "last_message": lead.last_message,
                "interests": lead.interests,
                "conversion_sent": lead.conversion_sent,
                "conversion_event_id": lead.conversion_event_id,
                "conversion_sent_at": lead.conversion_sent_at.isoformat() if lead.conversion_sent_at else None,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
                "updated_at": lead.updated_at.isoformat() if lead.updated_at else None
            }
            for lead in leads
        ],
        "pagination": {
            "skip": skip,
            "limit": limit,
            "has_more": total > (skip + limit)
        }
    }


@whatsapp_router.get("/accounts/{account_id}/leads/{phone_number}")
def get_lead_by_phone(
    account_id: uuid.UUID,
    phone_number: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get a specific lead by phone number"""
    _authorize_message_account(db, current_user, account_id)
    phone_clean = phone_number.replace(" ", "").replace("+", "").strip()

    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.whatsapp_account_id == account_id,
        WhatsAppLead.phone_number == phone_clean
    ).first()

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No lead found for phone number: {phone_clean}"
        )

    return {
        "success": True,
        "lead": {
            "id": str(lead.id),
            "phone_number": lead.phone_number,
            "lead_score": lead.lead_score,
            "lead_status": lead.lead_status,
            "is_hot_lead": lead.lead_score >= 70 if lead.lead_score else False,
            "scoring_reason": lead.scoring_reason,
            "total_messages": lead.total_messages,
            "last_message": lead.last_message,
            "interests": lead.interests,
            "conversion_sent": lead.conversion_sent,
            "conversion_event_id": lead.conversion_event_id,
            "conversion_sent_at": lead.conversion_sent_at.isoformat() if lead.conversion_sent_at else None,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None
        }
    }


class LeadStatusUpdate(BaseModel):
    lead_status: str


@whatsapp_router.patch("/accounts/{account_id}/leads/{lead_id}")
def update_lead_status(
    account_id: uuid.UUID,
    lead_id: uuid.UUID,
    payload: LeadStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Manually override a lead's status (e.g. from the Leads UI)."""
    _authorize_message_account(db, current_user, account_id)
    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.id == lead_id,
        WhatsAppLead.whatsapp_account_id == account_id
    ).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    lead.lead_status = payload.lead_status
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    return {
        "success": True,
        "lead": {
            "id": str(lead.id),
            "lead_status": lead.lead_status,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        }
    }


@whatsapp_router.delete("/accounts/{account_id}/leads/{lead_id}")
def delete_lead(
    account_id: uuid.UUID,
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a lead."""
    _authorize_message_account(db, current_user, account_id)
    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.id == lead_id,
        WhatsAppLead.whatsapp_account_id == account_id
    ).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    db.delete(lead)
    db.commit()
    return {"success": True}


@whatsapp_router.post("/ask")
async def ask_question(request: ChatRequest, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    """
    Test endpoint to ask questions to the AI Sales Bot.
    Uses the MultiTenantSalesBot with store-specific knowledge.
    """
    _authorize_message_store(db, current_user, request.store_id)
    try:
        # Initialize the multi-tenant bot
        bot = MultiTenantSalesBot(
            store_id=request.store_id,
            db=db
        )

        # Generate response
        ai_response = await bot.generate_response(
            user_message=request.question,
            phone_number=request.user_id
        )

        # Handle no knowledge match
        if ai_response is None:
            return {
                "user_id": request.user_id,
                "store_id": str(request.store_id),
                "response": None,
                "message": "No knowledge match - bot stays silent. Owner notified.",
                "fallback_triggered": True
            }

        return {
            "user_id": request.user_id,
            "store_id": str(request.store_id),
            "response": ai_response,
            "fallback_triggered": False
        }

    except Exception as e:
        logger.error(f"Ask endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
# ============ KNOWLEDGE MANAGEMENT ENDPOINTS ============


@whatsapp_router.post("/knowledge", response_model=KnowledgeResponse)
def create_knowledge_entry(
    request: KnowledgeCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Create a new knowledge entry with REAL OpenAI embedding
    """
    from modules.users.auth_router import _require_store_owner
    _require_store_owner(db, request.store_id, current_user)
    try:
        from utils.embeddings import embed_text, active_embedding_model

        print(f"📝 Creating knowledge: {request.content[:50]}...")

        # 1. Generate embedding via the central, resilient layer
        embedding = embed_text(request.content, agent_name="knowledge_embeddings")
        print(f"   ✅ Generated {len(embedding)}-dim embedding")

        # 2. Create knowledge entry
        from .models import CompanyKnowledge
        import uuid

        knowledge = CompanyKnowledge(
            id=uuid.uuid4(),
            store_id=request.store_id,
            content=request.content,
            embedding=embedding,
            embedding_model=active_embedding_model()
        )
        
        # 3. Save to database
        db.add(knowledge)
        db.commit()
        db.refresh(knowledge)
        
        print(f"   ✅ Saved to database (ID: {knowledge.id})")
        
        return KnowledgeResponse(
            id=knowledge.id,
            store_id=knowledge.store_id,
            content=knowledge.content,
            embedding_dimensions=len(embedding),
            created=True
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create knowledge: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create knowledge: {str(e)}"
        )

@whatsapp_router.get("/knowledge")
def get_knowledge_entries(
    store_id: uuid.UUID = Query(...),
    skip: int = Query(0, ge=0, description="Number of entries to skip"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all knowledge entries for a store"""
    from modules.users.auth_router import _require_store_owner
    _require_store_owner(db, store_id, current_user)
    # Get entries
    query = db.query(CompanyKnowledge).filter(
        CompanyKnowledge.store_id == store_id
    )
    
    entries = query.order_by(CompanyKnowledge.id).offset(skip).limit(limit).all()
    total = query.count()
    
    # Check if embeddings are real
    placeholder_count = db.execute(text("""
        SELECT COUNT(*) 
        FROM company_knowledge 
        WHERE store_id = :store_id AND embedding::text LIKE '[0.%'
    """), {"store_id": str(store_id)}).scalar()
    
    return {
        "entries": [
            {
                "id": str(entry.id),
                "content": entry.content,
                "content_preview": entry.content[:100] + "..." if len(entry.content) > 100 else entry.content,
                "has_embedding": entry.embedding is not None,
                "embedding_real": False if entry.embedding and str(entry.embedding).startswith('[0.') else True
            }
            for entry in entries
        ],
        "total": total,
        "placeholder_embeddings": placeholder_count,
        "store_id": str(store_id),
        "pagination": {
            "skip": skip,
            "limit": limit,
            "has_more": total > (skip + limit)
        }
    }

@whatsapp_router.post("/knowledge/fix-embeddings")
def fix_all_embeddings(
    store_id: uuid.UUID = Query(..., description="Store ID"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Fix all placeholder embeddings for a store.
    Regenerates embeddings for all entries (not just placeholders).
    """
    from modules.users.auth_router import _require_store_owner
    _require_store_owner(db, store_id, current_user)
    try:
        from utils.embeddings import embed_text, active_embedding_model
        from sqlalchemy import text

        logger.info(f"Fixing ALL embeddings for store: {store_id}")

        # Get ALL knowledge entries for this store (not just placeholders)
        rows = db.execute(text("""
            SELECT id, content
            FROM company_knowledge
            WHERE store_id = :store_id
        """), {"store_id": str(store_id)}).fetchall()

        if not rows:
            return {"message": "No knowledge entries found", "fixed": 0, "total_found": 0}

        logger.info(f"Found {len(rows)} knowledge entries to process")

        model_tag = active_embedding_model()
        fixed = 0
        errors = []

        for row in rows:
            row_id = row[0]  # Access by index for SQLAlchemy Row
            content = row[1]

            try:
                logger.info(f"Processing row {row_id}...")
                logger.info(f"  Content preview: {content[:50]}...")

                # Generate embedding via the central, resilient layer
                embedding = embed_text(content, agent_name="knowledge_embeddings")

                # Convert to PostgreSQL vector string format: "[0.1, 0.2, ...]"
                embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                logger.info(f"  Generated embedding with {len(embedding)} dimensions")

                # Update using string format that pgvector expects
                db.execute(text("""
                    UPDATE company_knowledge
                    SET embedding = CAST(:embedding AS vector),
                        embedding_model = :model
                    WHERE id = :id
                """), {
                    "embedding": embedding_str,
                    "model": model_tag,
                    "id": str(row_id)
                })

                fixed += 1
                logger.info(f"  Fixed row {row_id}")

            except Exception as e:
                error_msg = f"Row {row_id}: {type(e).__name__}: {e}"
                logger.error(f"Error: {error_msg}")
                errors.append(error_msg)

        db.commit()
        logger.info(f"Committed. Total fixed: {fixed}/{len(rows)}")

        return {
            "message": f"Fixed {fixed} embeddings",
            "total_found": len(rows),
            "fixed": fixed,
            "store_id": str(store_id),
            "errors": errors if errors else None
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Transaction rolled back due to error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fix embeddings: {str(e)}"
        )


# =============================================================================
# AD CAMPAIGN ENDPOINTS (Multi-Store Routing)
# =============================================================================

@whatsapp_router.post("/campaigns", response_model=AdCampaignResponse)
def create_ad_campaign(
    campaign_data: AdCampaignCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new ad campaign for multi-store routing.

    When customers click a Click-to-WhatsApp ad with this campaign's identifiers,
    they will be automatically routed to the associated store.
    """
    try:
        # Verify store exists
        from modules.stores.models import Store
        store = db.query(Store).filter(Store.id == campaign_data.store_id).first()
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Store not found: {campaign_data.store_id}"
            )

        # Verify WhatsApp account exists
        whatsapp_account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == campaign_data.whatsapp_account_id
        ).first()
        if not whatsapp_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"WhatsApp account not found: {campaign_data.whatsapp_account_id}"
            )

        # Create campaign
        campaign = AdCampaign(
            store_id=campaign_data.store_id,
            whatsapp_account_id=campaign_data.whatsapp_account_id,
            name=campaign_data.name,
            description=campaign_data.description,
            campaign_id=campaign_data.campaign_id,
            ad_id=campaign_data.ad_id,
            ctwa_clid=campaign_data.ctwa_clid,
            utm_source=campaign_data.utm_source,
            utm_medium=campaign_data.utm_medium,
            utm_campaign=campaign_data.utm_campaign,
            custom_ref=campaign_data.custom_ref,
            is_active=campaign_data.is_active
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        logger.info(f"Created ad campaign: {campaign.name} -> Store {campaign.store_id}")
        return AdCampaignResponse.model_validate(campaign)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign: {str(e)}"
        )


@whatsapp_router.get("/campaigns", response_model=AdCampaignListResponse)
def list_ad_campaigns(
    whatsapp_account_id: Optional[uuid.UUID] = Query(None, description="Filter by WhatsApp account"),
    store_id: Optional[uuid.UUID] = Query(None, description="Filter by store"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db)
):
    """List all ad campaigns with optional filters."""
    query = db.query(AdCampaign)

    if whatsapp_account_id:
        query = query.filter(AdCampaign.whatsapp_account_id == whatsapp_account_id)
    if store_id:
        query = query.filter(AdCampaign.store_id == store_id)
    if is_active is not None:
        query = query.filter(AdCampaign.is_active == is_active)

    campaigns = query.order_by(AdCampaign.created_at.desc()).all()

    return AdCampaignListResponse(
        campaigns=[AdCampaignResponse.model_validate(c) for c in campaigns],
        total=len(campaigns)
    )


@whatsapp_router.get("/campaigns/{campaign_id}", response_model=AdCampaignResponse)
def get_ad_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get a specific ad campaign by ID."""
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign not found: {campaign_id}"
        )
    return AdCampaignResponse.model_validate(campaign)


@whatsapp_router.put("/campaigns/{campaign_id}", response_model=AdCampaignResponse)
def update_ad_campaign(
    campaign_id: uuid.UUID,
    campaign_data: AdCampaignUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing ad campaign."""
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign not found: {campaign_id}"
        )

    try:
        update_data = campaign_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(campaign, key, value)

        campaign.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(campaign)

        logger.info(f"Updated ad campaign: {campaign.name}")
        return AdCampaignResponse.model_validate(campaign)

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update campaign: {str(e)}"
        )


@whatsapp_router.delete("/campaigns/{campaign_id}")
def delete_ad_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete an ad campaign."""
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign not found: {campaign_id}"
        )

    try:
        db.delete(campaign)
        db.commit()
        logger.info(f"Deleted ad campaign: {campaign_id}")
        return {"success": True, "message": f"Campaign {campaign_id} deleted"}

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete campaign: {str(e)}"
        )


@whatsapp_router.get("/accounts/{account_id}/available-stores", response_model=AvailableStoresResponse)
def get_available_stores_for_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get all stores that can be routed to from this WhatsApp account.
    Includes stores with active campaigns and the default store.
    """
    try:
        router = StoreRouter(whatsapp_account_id=account_id, db=db)
        stores = router.get_available_stores()

        return AvailableStoresResponse(
            stores=[StoreSelectionOption(**s) for s in stores],
            total=len(stores)
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to get available stores: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get available stores: {str(e)}"
        )


@whatsapp_router.post("/accounts/{account_id}/route-conversation")
def manually_route_conversation(
    account_id: uuid.UUID,
    phone_number: str = Query(..., description="Customer phone number"),
    store_id: uuid.UUID = Query(..., description="Store to route to"),
    db: Session = Depends(get_db)
):
    """
    Manually route a conversation to a specific store.
    Use this when a customer needs to be transferred to a different store.
    """
    try:
        phone_clean = phone_number.replace(" ", "").replace("+", "").strip()
        router = StoreRouter(whatsapp_account_id=account_id, db=db)
        conversation = router.route_to_store(
            phone_number=phone_clean,
            store_id=store_id,
            method="manual_assignment"
        )

        return {
            "success": True,
            "message": f"Conversation routed to store {store_id}",
            "conversation_id": str(conversation.id),
            "phone_number": phone_clean,
            "store_id": str(store_id)
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to route conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to route conversation: {str(e)}"
        )


@whatsapp_router.post("/test/simulate-ad-click")
def simulate_ad_click(
    whatsapp_account_id: uuid.UUID = Query(..., description="WhatsApp account ID"),
    phone_number: str = Query(..., description="Customer phone number to simulate"),
    custom_ref: str = Query(..., description="Campaign custom_ref (e.g., ZIMSECURE, SECURICO)"),
    message: str = Query("Hi, I saw your ad!", description="Initial message from customer"),
    db: Session = Depends(get_db)
):
    """
    TESTING ONLY: Simulate a Click-to-WhatsApp ad click.

    This mimics what happens when a customer clicks a Facebook/Instagram ad
    and sends a message via WhatsApp.
    """
    try:
        # Clean phone number
        phone_clean = phone_number.replace(" ", "").replace("+", "").strip()

        # Get the WhatsApp account
        whatsapp_account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == whatsapp_account_id
        ).first()
        if not whatsapp_account:
            raise HTTPException(status_code=404, detail="WhatsApp account not found")

        # Find the campaign by custom_ref
        campaign = db.query(AdCampaign).filter(
            AdCampaign.custom_ref == custom_ref,
            AdCampaign.whatsapp_account_id == whatsapp_account_id,
            AdCampaign.is_active == True
        ).first()

        if not campaign:
            raise HTTPException(
                status_code=404,
                detail=f"No active campaign found with custom_ref '{custom_ref}'"
            )

        # Get store info
        from modules.stores.models import Store
        store = db.query(Store).filter(Store.id == campaign.store_id).first()

        # Initialize router and route the message
        router = StoreRouter(whatsapp_account_id=whatsapp_account_id, db=db)

        # Simulate referral data that would come from Meta
        simulated_referral = {
            "source_url": f"https://wa.me/{whatsapp_account.phone_number}?text=ref_{custom_ref}",
            "source_type": "ad",
            "source_id": str(campaign.id),
            "headline": campaign.name,
            "ctwa_clid": None,
            "custom_ref": custom_ref
        }

        # Route the conversation
        conversation = router._get_or_create_conversation(
            phone_number=phone_clean,
            store_id=campaign.store_id,
            routing_status="routed",
            routed_via="ad_campaign",
            campaign_id=campaign.id,
            referral_data=simulated_referral
        )

        # Update campaign stats
        campaign.click_count += 1
        campaign.conversation_count += 1
        db.commit()

        # Now generate AI response using the store's bot
        bot = MultiTenantSalesBot(store_id=campaign.store_id, db=db)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ai_response = loop.run_until_complete(
                bot.generate_response(
                    user_message=message,
                    phone_number=phone_clean,
                    whatsapp_account_id=whatsapp_account_id
                )
            )
        finally:
            loop.close()

        return {
            "success": True,
            "simulation": {
                "customer_phone": phone_clean,
                "customer_message": message,
                "ad_clicked": custom_ref,
                "routed_to_store": store.store_name if store else str(campaign.store_id),
                "store_id": str(campaign.store_id),
                "campaign_name": campaign.name
            },
            "bot_response": ai_response if ai_response else "(Bot stayed silent - no knowledge match)",
            "conversation_id": str(conversation.id)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Simulation failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Simulation failed: {str(e)}"
        )


@whatsapp_router.get("/accounts/{account_id}/routing-stats")
def get_routing_stats(
    account_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get routing statistics for a WhatsApp account.
    Shows how conversations are being routed to different stores.
    """
    try:
        # Get all conversations for this account
        conversations = db.query(WhatsAppConversation).filter(
            WhatsAppConversation.whatsapp_account_id == account_id
        ).all()

        # Count by routing method
        routing_methods = {}
        store_counts = {}

        for conv in conversations:
            # Count by routing method
            method = conv.routed_via or "unknown"
            routing_methods[method] = routing_methods.get(method, 0) + 1

            # Count by store
            if conv.store_id:
                store_id_str = str(conv.store_id)
                store_counts[store_id_str] = store_counts.get(store_id_str, 0) + 1

        # Get campaign stats
        campaigns = db.query(AdCampaign).filter(
            AdCampaign.whatsapp_account_id == account_id
        ).all()

        campaign_stats = [
            {
                "id": str(c.id),
                "name": c.name,
                "store_id": str(c.store_id),
                "clicks": c.click_count,
                "conversations": c.conversation_count,
                "is_active": c.is_active
            }
            for c in campaigns
        ]

        return {
            "total_conversations": len(conversations),
            "routing_methods": routing_methods,
            "conversations_by_store": store_counts,
            "campaigns": campaign_stats
        }

    except Exception as e:
        logger.error(f"Failed to get routing stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get routing stats: {str(e)}"
        )


# Debug endpoint to test auto-respond logic
@whatsapp_router.post("/debug/test-autorespond")
def debug_test_autorespond(
    phone_number: str = Query(..., description="Customer phone number"),
    message: str = Query(..., description="Test message to respond to"),
    db: Session = Depends(get_db)
):
    """
    Debug endpoint to test the auto-respond logic synchronously.
    This helps diagnose why auto-respond might not be working.
    """
    import traceback

    try:
        # Find the WhatsApp account
        whatsapp_account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.phone_number_id == "826950020512691"
        ).first()

        if not whatsapp_account:
            return {"error": "WhatsApp account not found"}

        # Get access token
        access_token = whatsapp_account.permanent_access_token
        if not access_token:
            business_account = whatsapp_account.business_account
            if business_account:
                access_token = business_account.access_token
        if not access_token:
            access_token = os.getenv("WHATSAPP_PERMANENT_TOKEN")

        if not access_token:
            return {"error": "No access token available", "permanent_token": whatsapp_account.permanent_access_token is not None}

        # Initialize store router
        router = StoreRouter(whatsapp_account_id=whatsapp_account.id, db=db)

        # Route the message
        store_id, routing_method, conversation = router.route_message(
            phone_number=phone_number,
            message_data={"type": "text", "text": {"body": message}}
        )

        if not store_id:
            return {
                "error": "No store routed",
                "routing_method": routing_method,
                "conversation_status": conversation.routing_status if conversation else None
            }

        # Create the bot
        bot = MultiTenantSalesBot(store_id=store_id, db=db)

        # Generate response
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ai_response = loop.run_until_complete(
                bot.generate_response(
                    user_message=message,
                    phone_number=phone_number,
                    whatsapp_account_id=whatsapp_account.id
                )
            )
        finally:
            loop.close()

        return {
            "success": True,
            "store_id": str(store_id),
            "routing_method": routing_method,
            "ai_response": ai_response,
            "access_token_set": True
        }

    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }


# ==================== Lead Scoring Analytics ====================

@whatsapp_router.get("/leads/analytics")
def get_leads_analytics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Get lead scoring analytics — scores, categories, funnel data.

    Returns aggregated lead quality data for the dashboard.
    """
    from .models import WhatsAppLead
    from datetime import datetime, timedelta
    from sqlalchemy import func

    cutoff = datetime.utcnow() - timedelta(days=days)

    if not current_user.store_id:
        raise HTTPException(status_code=403, detail="Select a store")
    store_id = uuid.UUID(current_user.store_id)
    _authorize_message_store(db, current_user, store_id)

    leads = db.query(WhatsAppLead).join(WhatsAppAccount,
        WhatsAppLead.whatsapp_account_id == WhatsAppAccount.id).filter(
        WhatsAppAccount.store_id == store_id,
        WhatsAppLead.created_at >= cutoff
    ).order_by(WhatsAppLead.lead_score.desc()).all()

    hot = [l for l in leads if (l.lead_score or 0) >= 70]
    warm = [l for l in leads if 40 <= (l.lead_score or 0) < 70]
    cool = [l for l in leads if 20 <= (l.lead_score or 0) < 40]
    cold = [l for l in leads if (l.lead_score or 0) < 20]

    scores = [l.lead_score or 0 for l in leads]
    avg_score = sum(scores) / len(scores) if scores else 0

    return {
        "total_leads": len(leads),
        "hot_leads": len(hot),
        "warm_leads": len(warm),
        "cool_leads": len(cool),
        "cold_leads": len(cold),
        "average_score": round(avg_score, 1),
        "conversion_rate": round((len(hot) / len(leads) * 100), 1) if leads else 0,
        "leads": [
            {
                "id": str(l.id),
                "phone_number": l.phone_number,
                "lead_score": l.lead_score or 0,
                "lead_status": l.lead_status or "new",
                "scoring_reason": l.scoring_reason,
                "total_messages": l.total_messages or 0,
                "last_message": l.last_message,
                "interests": l.interests,
                "created_at": l.created_at.isoformat() if l.created_at else None,
                "updated_at": l.updated_at.isoformat() if l.updated_at else None
            }
            for l in leads[:100]  # Limit to 100 leads
        ]
    }

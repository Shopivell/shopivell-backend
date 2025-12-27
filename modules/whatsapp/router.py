# whatsapp_router.py

import hashlib
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks, WebSocket, WebSocketDisconnect
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
from modules.whatsapp.chatbot_engine import SalesBot, LeadScorer
from .models import CompanyKnowledge, WhatsAppAccount, WhatsAppMessage, WhatsAppLead
from .schemas import (
    ChatRequest, ConversionsAPISettingsUpdate, KnowledgeCreateRequest, KnowledgeResponse, WhatsAppAccountCreate, WhatsAppAccountUpdate, WhatsAppAccountResponse, WhatsAppConversionEvent, WhatsAppMessageResponse,
    WhatsAppMessageSendResponse, WhatsAppTextMessage, WhatsAppTemplateMessage,
    WhatsAppAccountsListResponse, WhatsAppMessagesListResponse,
    WhatsAppWebhookVerification, WhatsAppWebhookPayload,
    BulkMessageRequest, BulkMessageResponse, BulkMessageResult
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

whatsapp_router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# WhatsApp Graph API base URL
WHATSAPP_API_BASE = "https://graph.facebook.com/v23.0"

# WebSocket Connection Manager
class ConnectionManager:
    """Manages active WebSocket connections for real-time updates."""
    def __init__(self):
        # Dictionary to hold active connections, keyed by WhatsApp Account ID (str)
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, account_id: str):
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
    
    # Try to use permanent access token, fall back to business account token
    access_token = whatsapp_account.permanent_access_token
    if not access_token:
        business_account = whatsapp_account.business_account
        if business_account:
            access_token = business_account.access_token
    
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
    template_name: Optional[str] = None,
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
            template_name=template_name,
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
    db: Session = Depends(get_db)
):
    """Create a new WhatsApp account configuration using Business Account Token"""
    
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
    
    # 3. Check if WhatsApp account already exists for this WABA ID
    existing_account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.waba_id == account_data.waba_id
    ).first()
    
    if existing_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp account with this WABA ID already exists"
        )
    
    try:
        # 4. Create WhatsApp account
        # We use business_account.access_token instead of account_data.permanent_access_token
        whatsapp_account = WhatsAppAccount(
            business_account_id=account_data.business_account_id,
            waba_id=account_data.waba_id,
            phone_number_id=account_data.phone_number_id,
            phone_number=account_data.phone_number,
            display_name=account_data.display_name,
            
            # CHANGED: Use the token from the Business Model
            permanent_access_token=business_account.access_token, 
            
            webhook_url=account_data.webhook_url,
            webhook_verify_token=account_data.webhook_verify_token,
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
    db: Session = Depends(get_db)
):
    """Get all WhatsApp accounts"""
    query = db.query(WhatsAppAccount).filter(WhatsAppAccount.is_enabled == True)
    
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
    db: Session = Depends(get_db)
):
    """Get all WhatsApp accounts for a specific store"""
    accounts = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.store_id == store_id,
        WhatsAppAccount.is_enabled == True
    ).all()

    return WhatsAppAccountsListResponse(
        accounts=[WhatsAppAccountResponse.model_validate(acc) for acc in accounts],
        total_count=len(accounts)
    )

@whatsapp_router.get("/accounts/{account_id}", response_model=WhatsAppAccountResponse)
def get_whatsapp_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific WhatsApp account"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp account not found"
        )

    return WhatsAppAccountResponse.model_validate(account)

@whatsapp_router.put("/accounts/{account_id}", response_model=WhatsAppAccountResponse)
def update_whatsapp_account(
    account_id: uuid.UUID,
    account_data: WhatsAppAccountUpdate,
    db: Session = Depends(get_db)
):
    """Update WhatsApp account configuration"""
    account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp account not found"
        )
    
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

# WhatsApp Messaging Endpoints

@whatsapp_router.post("/accounts/{account_id}/send-template", response_model=WhatsAppMessageSendResponse)
def send_whatsapp_template_message(
    account_id: uuid.UUID,
    template_data: WhatsAppTemplateMessage,
    db: Session = Depends(get_db)
):
    """Send a template message via WhatsApp"""
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    
    try:
        # Prepare template payload
        template_payload = {
            "name": template_data.template_name,
            "language": {
                "code": template_data.language_code
            }
        }
        
        if template_data.components:
            template_payload["components"] = template_data.components
        
        # Send message via WhatsApp API
        result = send_whatsapp_message_request(
            phone_number_id=whatsapp_account.phone_number_id,
            access_token=access_token,
            to=template_data.to,
            message_type="template",
            message_data={
                "template": template_payload
            }
        )
        
        # Extract message IDs
        message_id = result.get("messages", [{}])[0].get("id")
        wamid = result.get("messages", [{}])[0].get("wamid")
        
        # Save to database
        saved_message = save_message_to_db(
            db=db,
            whatsapp_account_id=account_id,
            message_id=message_id or f"temp_{datetime.utcnow().timestamp()}",
            from_number=whatsapp_account.phone_number,
            to_number=template_data.to,
            message_type="template",
            direction="outbound",
            status="sent",
            template_name=template_data.template_name,
            wamid=wamid,
            meta_data=result
        )
        
        # 🔔 REAL-TIME PUSH: Broadcast the new outgoing message
        if saved_message:
            message_response = WhatsAppMessageResponse.model_validate(saved_message)
            asyncio.run(manager.broadcast_message(
                str(account_id),
                message_response.model_dump()
            ))
        
        return WhatsAppMessageSendResponse(
            success=True,
            message_id=message_id,
            wamid=wamid,
            message="Template message sent successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send template message: {str(e)}"
        )

@whatsapp_router.post("/accounts/{account_id}/send-bulk", response_model=BulkMessageResponse)
def send_bulk_whatsapp_messages(
    account_id: uuid.UUID,
    bulk_data: BulkMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Send bulk WhatsApp messages to multiple recipients.
    Supports both template messages and text messages (within 24-hour window).
    """
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)

    results: List[BulkMessageResult] = []
    successful = 0
    failed = 0

    for recipient in bulk_data.recipients:
        try:
            # Clean phone number
            to_clean = recipient.phone_number.replace(" ", "").replace("+", "").strip()

            if bulk_data.message_type == "template":
                # Send template message
                template_payload = {
                    "name": bulk_data.template_name or "hello_world",
                    "language": {
                        "code": bulk_data.language_code
                    }
                }

                if bulk_data.components:
                    template_payload["components"] = bulk_data.components

                result = send_whatsapp_message_request(
                    phone_number_id=whatsapp_account.phone_number_id,
                    access_token=access_token,
                    to=to_clean,
                    message_type="template",
                    message_data={"template": template_payload}
                )
            else:
                # Send text message (requires active 24-hour window)
                if not bulk_data.text_message:
                    raise ValueError("text_message is required for text messages")

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
                message_type=bulk_data.message_type,
                direction="outbound",
                status="sent",
                message_text=bulk_data.text_message if bulk_data.message_type == "text" else None,
                template_name=bulk_data.template_name if bulk_data.message_type == "template" else None,
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

    return BulkMessageResponse(
        success=failed == 0,
        total_recipients=len(bulk_data.recipients),
        successful=successful,
        failed=failed,
        results=results,
        message=f"Sent {successful}/{len(bulk_data.recipients)} messages successfully"
    )


@whatsapp_router.post("/accounts/{account_id}/send-hello-world")
def send_whatsapp_hello_world(
    account_id: uuid.UUID,
    to: str = Query(..., description="Recipient phone number"),
    db: Session = Depends(get_db)
):
    """Send hello_world template message (Step 2 from instructions)"""
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    
    try:
        # Send hello_world template
        result = send_whatsapp_message_request(
            phone_number_id=whatsapp_account.phone_number_id,
            access_token=access_token,
            to=to,
            message_type="template",
            message_data={
                "template": {
                    "name": "hello_world",
                    "language": {
                        "code": "en_US"
                    }
                }
            }
        )
        
        # Extract message IDs
        message_id = result.get("messages", [{}])[0].get("id")
        wamid = result.get("messages", [{}])[0].get("wamid")
        
        # Save to database
        saved_message = save_message_to_db(
            db=db,
            whatsapp_account_id=account_id,
            message_id=message_id or f"temp_{datetime.utcnow().timestamp()}",
            from_number=whatsapp_account.phone_number,
            to_number=to,
            message_type="template",
            direction="outbound",
            status="sent",
            template_name="hello_world",
            wamid=wamid,
            meta_data=result
        )
        
        # 🔔 REAL-TIME PUSH: Broadcast the new outgoing message
        if saved_message:
            message_response = WhatsAppMessageResponse.model_validate(saved_message)
            asyncio.run(manager.broadcast_message(
                str(account_id),
                message_response.model_dump()
            ))
        
        return {
            "success": True,
            "message": "Hello World template sent successfully",
            "message_id": message_id,
            "wamid": wamid,
            "recipient": to,
            "note": "Reply to this message to open customer service window for non-template messages"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send hello_world template: {str(e)}"
        )

# WebSocket Endpoint
@whatsapp_router.websocket("/accounts/{account_id}/ws")
async def websocket_endpoint(websocket: WebSocket, account_id: uuid.UUID):
    """WebSocket endpoint for real-time message updates for a specific account."""
    str_account_id = str(account_id)
    try:
        await manager.connect(websocket, str_account_id)
        # Keep the connection open indefinitely
        while True:
            # You can handle incoming client data here if needed (e.g., client is typing)
            # For now, just listen for disconnects or pings
            await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(websocket, str_account_id)
    except Exception as e:
        logger.error(f"WebSocket error for account {account_id}: {str(e)}")
        manager.disconnect(websocket, str_account_id)

# Webhook Endpoints
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
        payload = await request.json()
        logger.info(f"Received webhook payload: {json.dumps(payload, indent=2)}")

        # Process webhook in background with a NEW database session
        background_tasks.add_task(process_webhook_payload, payload)

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload"
        )

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
    """Process incoming messages from webhook and auto-respond using AI chatbot"""
    # FIX APPLIED: Using 'metadata' to correctly extract the object
    meta_data = value.get("metadata", {})
    phone_number_id = meta_data.get("phone_number_id")

    # Optional: Log the ID for debugging the account lookup
    logger.info(f"Attempting to find account with phone_number_id: {phone_number_id}")

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
    if not access_token:
        business_account = whatsapp_account.business_account
        if business_account:
            access_token = business_account.access_token

    for message in messages:
        from_number_raw = message.get("from")

        # CRITICAL FIX (Phone Number Cleaning)
        from_number_clean = from_number_raw.replace(" ", "").replace("+", "").strip()

        message_id = message.get("id")
        message_type = message.get("type")
        timestamp = message.get("timestamp")

        # Extract message text
        message_text = None
        if message_type == "text":
            text_data = message.get("text", {})
            message_text = text_data.get("body")

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
            # We convert the SQLAlchemy model to the Pydantic response schema for clean data
            message_response = WhatsAppMessageResponse.model_validate(new_message_db)
            asyncio.run(manager.broadcast_message(
                str(whatsapp_account.id),
                message_response.model_dump()
            ))

        logger.info(f"Incoming message from {from_number_clean}: {message_text}")

        # AUTO-RESPOND: If it's a text message, use AI chatbot to respond
        if message_type == "text" and message_text and access_token:
            try:
                # Generate AI response using SalesBot with token limit for very short WhatsApp messages
                bot = SalesBot(max_tokens=100).get_graph()
                config = {"configurable": {"thread_id": from_number_clean}}

                # Run the bot synchronously (we're already in a background task)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        bot.ainvoke(
                            {"messages": [("user", message_text)]},
                            config=config
                        )
                    )
                finally:
                    loop.close()

                ai_response = result["messages"][-1].content
                logger.info(f"AI Response for {from_number_clean}: {ai_response[:100]}...")

                # Send the AI response back via WhatsApp
                send_whatsapp_message_request(
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

                # Save the outgoing AI response to database
                save_message_to_db(
                    db=db,
                    whatsapp_account_id=whatsapp_account.id,
                    message_id=f"ai_reply_{datetime.utcnow().timestamp()}",
                    from_number=whatsapp_account.phone_number,
                    to_number=from_number_clean,
                    message_type="text",
                    direction="outbound",
                    status="sent",
                    message_text=ai_response
                )

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
@whatsapp_router.get("/accounts/{account_id}/messages", response_model=WhatsAppMessagesListResponse)
def get_whatsapp_messages(
    account_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    direction: Optional[str] = Query(None, regex="^(inbound|outbound)$"),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get WhatsApp message history"""
    query = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.whatsapp_account_id == account_id
    )
    
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

# WhatsApp Account Information Endpoints
@whatsapp_router.get("/accounts/{account_id}/info")
def get_whatsapp_account_info(
    account_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get WhatsApp account information from Facebook API"""
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
    force_template: bool = Query(False, description="Force template even if 24-hour window exists"),
    db: Session = Depends(get_db)
):
    """Improved test endpoint to send WhatsApp messages"""
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    
    try:
        # Clean phone number (remove spaces, +)
        to_clean = to.replace(" ", "").replace("+", "").strip()
        
        if force_template:
            # Always send template (for new conversations)
            result = send_template_message(whatsapp_account, access_token, to_clean, db)
        else:
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
                # No recent message, send template
                result = send_template_message(whatsapp_account, access_token, to_clean, db)
        
        return {
            "success": True,
            "message": result.get("message"),
            "message_id": result.get("message_id"),
            "wamid": result.get("wamid"),
            "recipient": to_clean,
            "type": result.get("type"),
            "note": result.get("note")
        }
        
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
        # If text fails, fall back to template
        logger.warning(f"Text message failed, falling back to template: {e.detail}")
        return send_template_message(whatsapp_account, access_token, to, db)

def send_template_message(whatsapp_account, access_token, to, db):
    """Send hello_world template message"""
    try:
        result = send_whatsapp_message_request(
            phone_number_id=whatsapp_account.phone_number_id,
            access_token=access_token,
            to=to,
            message_type="template",
            message_data={
                "template": {
                    "name": "hello_world",
                    "language": {
                        "code": "en_US"
                    }
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
            message_type="template",
            direction="outbound",
            status="sent",
            template_name="hello_world",
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
            "message": "Template message sent successfully",
            "message_id": message_id,
            "wamid": wamid,
            "recipient": to,
            "type": "template",
            "note": "Template message sent. Reply to it to open 24-hour customer service window."
        }
        
    except Exception as e:
        logger.error(f"Template message also failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Both text and template messages failed: {str(e)}"
        )

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
    message_type: str = Query("template", description="Message type: 'text' or 'template'"),
    db: Session = Depends(get_db)
):
    """Debug endpoint to test WhatsApp message sending"""
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    
    try:
        if message_type == "text":
            # Try to send regular text message
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
        else:
            # Send template message
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": {
                    "name": "hello_world",
                    "language": {
                        "code": "en_US"
                    }
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

# Insert this endpoint after your existing messaging endpoints (e.g., after send_whatsapp_template_message)

@whatsapp_router.post("/accounts/{account_id}/send-conversion", status_code=status.HTTP_202_ACCEPTED)
def send_whatsapp_conversion_event(
    account_id: uuid.UUID,
    event_data: WhatsAppConversionEvent,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Sends an offline conversion event to Meta's Conversions API (CAPI) 
    using the configured Dataset ID and Access Token for the WhatsApp Account.
    The task is executed in the background.
    """
    
    # 1. Retrieve the WhatsApp Account and CAPI Credentials from the database
    whatsapp_account, _ = get_whatsapp_client(account_id, db)
    
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
    db: Session = Depends(get_db)
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

@whatsapp_router.get("/accounts/{account_id}/templates")
def get_all_message_templates(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Retrieves all message templates associated with the WABA ID 
    using the Meta Graph API.
    """
    try:
        # Step 1: Get WABA ID and Access Token
        whatsapp_account, access_token = get_whatsapp_client(account_id, db)
        
        waba_id = whatsapp_account.waba_id
        url = f"{WHATSAPP_API_BASE}/{waba_id}/message_templates"
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        logger.info(f"Fetching message templates for WABA ID: {waba_id}")
        
        # Step 2: Make the API Request
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        
        result = response.json()
        
        logger.info(f"Successfully retrieved {len(result.get('data', []))} templates.")
        
        # Step 3: Return success response
        return {
            "success": True,
            "templates": result.get("data", []),
            "paging": result.get("paging")
        }
        
    except requests.exceptions.HTTPError as e:
        # Handle Meta API errors (4xx/5xx responses)
        error_detail = "Failed to communicate with Meta API."
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        
        try:
            error_data = e.response.json()
            error_message = error_data.get("error", {}).get("message")
            
            if error_message:
                error_detail = f"Meta API error: {error_message}"
            
            status_code = e.response.status_code
            
            logger.error(f"Meta API error fetching templates (Status {status_code}): {error_detail}")
        except:
            # Handle cases where the response is not valid JSON
            error_detail = f"Meta API returned status {e.response.status_code} but response body was unreadable."
            status_code = e.response.status_code
            logger.error(f"Unreadable Meta API error response: {error_detail}")
        
        raise HTTPException(
            status_code=status_code,
            detail=error_detail
        )
    
    except requests.exceptions.RequestException as e:
        # Handle network/connection errors (e.g., DNS error, timeout)
        logger.error(f"Network error during template fetch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Network error while connecting to Meta API: {str(e)}"
        )
        
    except Exception as e:
        # Handle other unexpected errors (e.g., issues with get_whatsapp_client)
        logger.error(f"Unexpected error fetching templates: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected internal error occurred: {str(e)}"
        )

# Add this new endpoint to whatsapp_router.py
@whatsapp_router.post("/accounts/{account_id}/send-text", response_model=WhatsAppMessageSendResponse)
def send_whatsapp_direct_text_message(
    account_id: uuid.UUID,
    message_data: WhatsAppTextMessage, # Assuming this schema has 'to' and 'message_text'
    db: Session = Depends(get_db)
):
    """
    Send a direct text message within the 24-hour window, or fall back to a template.
    """
    whatsapp_account, access_token = get_whatsapp_client(account_id, db)
    to_clean = message_data.to.replace(" ", "").replace("+", "").strip()
    
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
        
        # NOTE: send_text_message already handles a potential fallback if the API still rejects it
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
        # 3. Window is closed: Send template message (required by WhatsApp)
        logger.warning(f"24-hour window closed for {to_clean}. Falling back to template.")
        result = send_template_message(whatsapp_account, access_token, to_clean, db)
        
        # Map the utility dict result to the required Pydantic response model
        return WhatsAppMessageSendResponse(
            success=False, # Mark as failure to send requested text, but template sent
            message_id=result.get("message_id"),
            wamid=result.get("wamid"),
            message="24-hour window expired. Sent default template message instead."
        )
    

@whatsapp_router.post("/accounts/{account_id}/chat")
async def chat_and_respond(
    account_id: uuid.UUID,
    message_data: WhatsAppTextMessage,
    db: Session = Depends(get_db)
):
    """
    Process a message with AI, score the lead, and send response via WhatsApp.
    If lead score >= 70, sends conversion event to Meta CAPI.
    """
    try:
        whatsapp_account, access_token = get_whatsapp_client(account_id, db)
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

        # 2. Get conversation history for context
        recent_messages = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.whatsapp_account_id == account_id,
            WhatsAppMessage.from_number.contains(to_clean[-9:])
        ).order_by(WhatsAppMessage.timestamp.desc()).limit(5).all()

        conversation_history = "\n".join([
            f"{'Customer' if 'inbound' in m.direction else 'Bot'}: {m.message_text}"
            for m in reversed(recent_messages) if m.message_text
        ])

        # 3. Generate AI response
        bot = SalesBot(max_tokens=100).get_graph()
        config = {"configurable": {"thread_id": to_clean}}

        result = await bot.ainvoke(
            {"messages": [("user", message_data.body)]},
            config=config
        )

        ai_response = result["messages"][-1].content
        logger.info(f"AI Response for {to_clean}: {ai_response}")

        # 4. Score the lead
        scorer = LeadScorer()
        lead_result = scorer.score_lead(conversation_history, message_data.body)

        # Force flush to ensure logs appear immediately
        import sys
        print(f"\n{'='*50}", flush=True)
        print(f"LEAD SCORING RESULT for {to_clean}", flush=True)
        print(f"   Score: {lead_result.get('score')}", flush=True)
        print(f"   Status: {lead_result.get('status')}", flush=True)
        print(f"   Hot Lead: {lead_result.get('is_hot_lead')}", flush=True)
        print(f"   Interests: {lead_result.get('interests')}", flush=True)
        print(f"   Reason: {lead_result.get('reasoning')}", flush=True)
        print(f"{'='*50}\n", flush=True)
        sys.stdout.flush()

        # Also log via logger for backup
        logger.warning(f"LEAD SCORE: {to_clean} = {lead_result.get('score')} | Hot: {lead_result.get('is_hot_lead')} | Status: {lead_result.get('status')}")

        # 5. Update lead record
        lead.lead_score = lead_result.get("score", lead.lead_score)
        lead.lead_status = lead_result.get("status", lead.lead_status)
        lead.interests = lead_result.get("interests", lead.interests)
        lead.scoring_reason = lead_result.get("reasoning")
        lead.total_messages = (lead.total_messages or 0) + 1
        lead.last_message = message_data.body
        db.commit()

        # 6. Send to Meta CAPI if hot lead and not already sent
        capi_result = None
        if lead_result.get("is_hot_lead") and not lead.conversion_sent:
            if whatsapp_account.capi_dataset_id and whatsapp_account.capi_access_token:
                capi_result = send_capi_lead_event(
                    pixel_id=whatsapp_account.capi_dataset_id,
                    access_token=whatsapp_account.capi_access_token,
                    phone_number=to_clean,
                    lead_score=lead_result.get("score", 70)
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
            "lead_score": lead_result.get("score"),
            "lead_status": lead_result.get("status"),
            "is_hot_lead": lead_result.get("is_hot_lead"),
            "interests": lead_result.get("interests"),
            "reasoning": lead_result.get("reasoning"),
            "capi_sent": capi_result.get("success") if capi_result else False
        }

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
    db: Session = Depends(get_db)
):
    """Get all leads across all WhatsApp accounts"""
    query = db.query(WhatsAppLead)

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
    db: Session = Depends(get_db)
):
    """Get all leads for a WhatsApp account with their scores and details"""
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
    db: Session = Depends(get_db)
):
    """Get a specific lead by phone number"""
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


@whatsapp_router.post("/ask")
async def ask_question(request: ChatRequest):
    try:
        # 1. Initialize the Graph with token limit
        bot = SalesBot(max_tokens=100).get_graph()
        
        # 2. Set the configuration (thread_id enables memory)
        config = {"configurable": {"thread_id": request.user_id}}
        
        # 3. Invoke the logic
        # We use ainvoke (async) for the AI logic
        result = await bot.ainvoke(
            {"messages": [("user", request.question)]}, 
            config=config
        )
        
        # 4. Extract the last message from the AI
        ai_response = result["messages"][-1].content
        
        return {
            "user_id": request.user_id,
            "response": ai_response,
            "history_count": len(result["messages"])
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# ============ KNOWLEDGE MANAGEMENT ENDPOINTS ============


@whatsapp_router.post("/knowledge", response_model=KnowledgeResponse)
def create_knowledge_entry(
    request: KnowledgeCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Create a new knowledge entry with REAL OpenAI embedding
    """
    try:
        from langchain_openai import OpenAIEmbeddings
        
        print(f"📝 Creating knowledge: {request.content[:50]}...")
        
        # 1. Generate REAL embedding
        embeddings = OpenAIEmbeddings()
        embedding = embeddings.embed_query(request.content)
        print(f"   ✅ Generated {len(embedding)}-dim embedding")
        
        # 2. Create knowledge entry
        from .models import CompanyKnowledge
        import uuid
        
        knowledge = CompanyKnowledge(
            id=uuid.uuid4(),
            store_id=request.store_id,
            content=request.content,
            embedding=embedding  # REAL embedding
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
    store_id: uuid.UUID = Query("36689cad-4b73-4fea-802b-d3a4fbfa23ec"),
    skip: int = Query(0, ge=0, description="Number of entries to skip"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get all knowledge entries for a store"""
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
    store_id: uuid.UUID = Query("36689cad-4b73-4fea-802b-d3a4fbfa23ec", description="Store ID"),
    db: Session = Depends(get_db)
):
    """
    Fix all placeholder embeddings for a store.
    Regenerates embeddings for all entries (not just placeholders).
    """
    try:
        from langchain_openai import OpenAIEmbeddings
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

        embeddings = OpenAIEmbeddings()
        fixed = 0
        errors = []

        for row in rows:
            row_id = row[0]  # Access by index for SQLAlchemy Row
            content = row[1]

            try:
                logger.info(f"Processing row {row_id}...")
                logger.info(f"  Content preview: {content[:50]}...")

                # Generate real embedding using OpenAI
                embedding = embeddings.embed_query(content)

                # Convert to PostgreSQL vector string format: "[0.1, 0.2, ...]"
                embedding_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                logger.info(f"  Generated embedding with {len(embedding)} dimensions")

                # Update using string format that pgvector expects
                db.execute(text("""
                    UPDATE company_knowledge
                    SET embedding = CAST(:embedding AS vector)
                    WHERE id = :id
                """), {
                    "embedding": embedding_str,
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
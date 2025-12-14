# Add to your existing schemas.py or create a new whatsapp_schemas.py

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import uuid

from enum import Enum  # <--- FIX: Use the standard Python Enum class

# WhatsApp Account Schemas
class WhatsAppAccountBase(BaseModel):
    waba_id: str = Field(..., description="WhatsApp Business Account ID")
    phone_number_id: str = Field(..., description="Phone Number ID")
    phone_number: str = Field(..., description="WhatsApp phone number")
    display_name: Optional[str] = None
    verified_name: Optional[str] = None
    is_enabled: bool = True
    is_default: bool = False

class WhatsAppAccountCreate(WhatsAppAccountBase):
    business_account_id: uuid.UUID
    permanent_access_token: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_verify_token: Optional[str] = None

class WhatsAppAccountUpdate(BaseModel):
    display_name: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    permanent_access_token: Optional[str] = None

class WhatsAppAccountResponse(WhatsAppAccountBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    business_account_id: uuid.UUID
    quality_rating: Optional[str] = None
    created_at: datetime
    updated_at: datetime

# WhatsApp Message Schemas
class WhatsAppMessageBase(BaseModel):
    from_number: str
    to_number: str
    message_type: str
    direction: str
    status: str = "sent"

class WhatsAppMessageCreate(WhatsAppMessageBase):
    whatsapp_account_id: uuid.UUID
    message_id: str
    message_text: Optional[str] = None
    template_name: Optional[str] = None
    meta_data: Optional[Dict[str, Any]] = None

class WhatsAppMessageResponse(WhatsAppMessageBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    whatsapp_account_id: uuid.UUID
    message_id: str
    wamid: Optional[str] = None
    message_text: Optional[str] = None
    template_name: Optional[str] = None
    media_url: Optional[str] = None
    media_id: Optional[str] = None
    meta_data: Optional[Dict[str, Any]] = None
    timestamp: datetime
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime

# Message Request Schemas
class WhatsAppTextMessage(BaseModel):
    to: str = Field(..., description="Recipient phone number in international format")
    body: str = Field(..., description="Message text content")
    preview_url: bool = False

class WhatsAppTemplateMessage(BaseModel):
    to: str = Field(..., description="Recipient phone number in international format")
    template_name: str = Field(..., description="Template name")
    language_code: str = Field(default="en", description="Template language code")
    components: Optional[List[Dict[str, Any]]] = None

class WhatsAppMessageRequest(BaseModel):
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str
    text: Optional[WhatsAppTextMessage] = None
    template: Optional[WhatsAppTemplateMessage] = None

# Webhook Schemas
class WhatsAppWebhookPayload(BaseModel):
    object: str
    entry: List[Dict[str, Any]]

class WhatsAppWebhookVerification(BaseModel):
    hub_mode: str
    hub_challenge: str
    hub_verify_token: str

# Response Schemas
class WhatsAppMessageSendResponse(BaseModel):
    success: bool
    message_id: str
    wamid: Optional[str] = None
    message: str

class WhatsAppAccountsListResponse(BaseModel):
    accounts: List[WhatsAppAccountResponse]
    total_count: int

class WhatsAppMessagesListResponse(BaseModel):
    messages: List[WhatsAppMessageResponse]
    total_count: int

# Webhook event schemas
class WhatsAppWebhookContact(BaseModel):
    profile: Dict[str, str]
    wa_id: str

class WhatsAppWebhookMessage(BaseModel):
    from_field: str = Field(..., alias="from")
    id: str
    timestamp: str
    type: str
    text: Optional[Dict[str, str]] = None

class WhatsAppWebhookEvent(BaseModel):
    messaging_product: str
    meta_data: Dict[str, str]
    contacts: Optional[List[WhatsAppWebhookContact]] = None
    messages: Optional[List[WhatsAppWebhookMessage]] = None
    statuses: Optional[List[Dict[str, Any]]] = None

class ActionSource(str, Enum):
    """Enums for the action_source field (Meta CAPI requirement)."""
    # The 'system_generated' source is commonly used for server-to-server events.
    system_generated = "system_generated"
    email = "email"
    chat = "chat"
    app_in_app = "app_in_app"
    website = "website"

class WhatsAppConversionEvent(BaseModel):
    """
    Schema for sending an offline conversion event to Meta's Conversions API (CAPI) 
    via the WhatsApp module.
    
    Data fields are mapped to CAPI requirements (e.g., event_name, user_data, custom_data).
    """

    # --- REQUIRED FIELDS FOR THE PAYLOAD ---

    event_name: str = Field(
        ..., 
        description="The name of the conversion event (e.g., Purchase, Lead, InitiateCheckout). Must match Meta's standard events or custom events."
    )
    
    phone_number: str = Field(
        ...,
        description="The customer's phone number in E.164 format (e.g., 15551234567). This PII will be HASHED (SHA256) before sending and is crucial for WhatsApp event matching.",
        min_length=10
    )
    
    # --- CONTEXTUAL FIELDS ---
    
    action_source: ActionSource = Field(
        ActionSource.system_generated,
        description="Indicates where the action originated. 'system_generated' is the default for server-side offline events."
    )

    # --- CUSTOM DATA FIELDS (USED FOR 'custom_data' BLOCK in CAPI) ---
    
    value: Optional[float] = Field(
        None, 
        description="The monetary value of the conversion (e.g., 100.50). Required for 'Purchase' events."
    )
    
    currency: Optional[str] = Field(
        None,
        description="The currency of the value (e.g., USD, EUR). Use ISO 4217 standard."
    )
    
    order_id: Optional[str] = Field(
        None,
        description="Unique identifier for the transaction (e.g., an invoice number or order ID). Highly recommended for deduplication."
    )

    # --- OPTIONAL USER DATA FIELDS (FOR BETTER MATCHING) ---
    # These fields are included in the schema but require hashing logic 
    # (similar to phone_number) in the backend.

    email: Optional[str] = Field(
        None, 
        description="Customer's email address. Will be HASHED before sending."
    )
    
    first_name: Optional[str] = Field(
        None, 
        description="Customer's first name. Will be HASHED before sending."
    )
    
    last_name: Optional[str] = Field(
        None, 
        description="Customer's last name. Will be HASHED before sending."
    )

    class Config:
        """Example usage for documentation"""
        json_schema_extra = {
            "example": {
                "event_name": "Purchase",
                "phone_number": "15551234567",
                "value": 49.99,
                "currency": "USD",
                "order_id": "ORD-2025-54321",
                "action_source": "system_generated",
                "email": "customer@example.com"
            }
        }

class ConversionsAPISettingsUpdate(BaseModel):
    """
    Schema for updating the CAPI Dataset ID and Access Token 
    for a specific WhatsApp Account.
    """
    capi_dataset_id: str = Field(
        ...,
        description="The unique Dataset ID (Pixel ID) from Meta Events Manager.",
        min_length=10
    )
    capi_access_token: str = Field(
        ...,
        description="The Conversions API Access Token generated in Events Manager. This should be stored securely (encrypted) in your database.",
        min_length=30
    )
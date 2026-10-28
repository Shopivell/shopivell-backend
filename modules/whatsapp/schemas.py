# Add to your existing schemas.py or create a new whatsapp_schemas.py

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import uuid
from uuid import UUID
from enum import Enum

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
    store_id: Optional[uuid.UUID] = None
    permanent_access_token: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_verify_token: Optional[str] = None

class WhatsAppAccountUpdate(BaseModel):
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    display_name: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_default: Optional[bool] = None
    permanent_access_token: Optional[str] = None
    store_id: Optional[uuid.UUID] = None

class WhatsAppAccountResponse(WhatsAppAccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_account_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
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
    meta_data: Optional[Dict[str, Any]] = None

class WhatsAppMessageResponse(WhatsAppMessageBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    whatsapp_account_id: uuid.UUID
    message_id: str
    wamid: Optional[str] = None
    message_text: Optional[str] = None
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
    # None on a failed send (e.g. Zernio/Meta rejected it) - was required, which made a
    # failed send crash with a 500 Pydantic validation error instead of reporting the
    # actual failure reason in `message`. Confirmed live.
    message_id: Optional[str] = None
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

class ChatRequest(BaseModel):
    user_id: str  # Phone number to track conversations
    question: str
    store_id: UUID  # Required for multi-tenant bot

class KnowledgeResponse(BaseModel):
    """Response for knowledge creation"""
    id: UUID
    store_id: UUID
    content: str
    embedding_dimensions: int
    created: bool

    class Config:
        from_attributes = True

class KnowledgeCreateRequest(BaseModel):
    """Schema for creating knowledge entries"""
    content: str = Field(..., min_length=10, description="Knowledge content")
    store_id: UUID = Field(..., description="Store ID - required for multi-tenant support")


# Bulk Messaging Schemas
class BulkMessageRecipient(BaseModel):
    """Single recipient for bulk messaging"""
    phone_number: str = Field(..., description="Phone number in E.164 format (e.g., 263771234567)")
    name: Optional[str] = Field(None, description="Optional name for personalization")


class BulkMessageRequest(BaseModel):
    """Request schema for bulk text messaging (24-hour window only)"""
    recipients: List[BulkMessageRecipient] = Field(..., min_length=1, max_length=1000, description="List of recipients")
    text_message: str = Field(..., description="Text message content")

    class Config:
        json_schema_extra = {
            "example": {
                "recipients": [
                    {"phone_number": "263771234567", "name": "John"},
                    {"phone_number": "263772345678", "name": "Jane"}
                ],
                "text_message": "Hi! Thanks for reaching out — how can we help you today?"
            }
        }


class BulkMessageResult(BaseModel):
    """Result for a single recipient in bulk messaging"""
    phone_number: str
    success: bool
    message_id: Optional[str] = None
    wamid: Optional[str] = None
    error: Optional[str] = None


class BulkMessageResponse(BaseModel):
    """Response schema for bulk messaging"""
    success: bool
    total_recipients: int
    successful: int
    failed: int
    skipped: int = 0  # Recipients excluded for missing opt-in / opt-out (policy compliance)
    results: List[BulkMessageResult]
    message: str


# =============================================================================
# FAQ Schemas
# =============================================================================

class FAQCategory(str, Enum):
    """FAQ categories"""
    GENERAL = "general"
    SHIPPING = "shipping"
    RETURNS = "returns"
    PRICING = "pricing"
    PAYMENT = "payment"
    PRODUCTS = "products"
    SERVICES = "services"
    SUPPORT = "support"
    OTHER = "other"


class FAQBase(BaseModel):
    """Base FAQ schema"""
    question: str = Field(..., min_length=5, max_length=500, description="The question")
    answer: str = Field(..., min_length=10, description="The answer to the question")
    category: Optional[str] = Field(None, description="FAQ category")
    is_active: bool = Field(True, description="Whether the FAQ is active")
    is_featured: bool = Field(False, description="Whether to feature on website FAQ page")
    display_order: int = Field(0, description="Display order for sorting")


class FAQCreate(FAQBase):
    """Schema for creating a FAQ"""
    pass


class FAQUpdate(BaseModel):
    """Schema for updating a FAQ"""
    question: Optional[str] = Field(None, min_length=5, max_length=500)
    answer: Optional[str] = Field(None, min_length=10)
    category: Optional[str] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    display_order: Optional[int] = None


class FAQResponse(FAQBase):
    """Schema for FAQ response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    view_count: int = 0
    helpful_count: int = 0
    not_helpful_count: int = 0
    knowledge_id: Optional[UUID] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FAQListResponse(BaseModel):
    """Schema for paginated FAQ list"""
    faqs: List[FAQResponse]
    total: int
    page: int
    page_size: int


class FAQFeedback(BaseModel):
    """Schema for FAQ feedback (helpful/not helpful)"""
    helpful: bool = Field(..., description="Whether the FAQ was helpful")


# =============================================================================
# Store Bot Config Schemas
# =============================================================================

class StoreBotConfigBase(BaseModel):
    """Base schema for bot configuration"""
    bot_name: str = Field("Sales Assistant", max_length=100)
    bot_personality: Optional[str] = None
    greeting_message: str = Field("Hello! Welcome to our store. How can I help you today?")
    fallback_message: str = Field("I'll connect you with a team member who can help you better.")
    handoff_message: str = Field("A team member will be with you shortly.")
    temperature: float = Field(0.7, ge=0, le=1)
    max_response_tokens: int = Field(500, ge=50, le=2000)
    similarity_threshold: float = Field(0.4, ge=0, le=1)
    hot_lead_threshold: int = Field(80, ge=0, le=100)
    handoff_keywords: List[str] = Field(default=["speak to human", "talk to someone", "customer service", "manager"])
    max_fallbacks_before_handoff: int = Field(3, ge=1, le=10)
    notify_on_hot_lead: bool = True
    notify_on_handoff: bool = True
    notify_on_unanswered: bool = True
    is_enabled: bool = True
    auto_respond: bool = True


class StoreBotConfigCreate(StoreBotConfigBase):
    """Schema for creating bot configuration"""
    pass


class StoreBotConfigUpdate(BaseModel):
    """Schema for updating bot configuration"""
    bot_name: Optional[str] = None
    bot_personality: Optional[str] = None
    greeting_message: Optional[str] = None
    fallback_message: Optional[str] = None
    handoff_message: Optional[str] = None
    temperature: Optional[float] = None
    max_response_tokens: Optional[int] = None
    similarity_threshold: Optional[float] = None
    hot_lead_threshold: Optional[int] = None
    handoff_keywords: Optional[List[str]] = None
    max_fallbacks_before_handoff: Optional[int] = None
    notify_on_hot_lead: Optional[bool] = None
    notify_on_handoff: Optional[bool] = None
    notify_on_unanswered: Optional[bool] = None
    is_enabled: Optional[bool] = None
    auto_respond: Optional[bool] = None


class StoreBotConfigResponse(StoreBotConfigBase):
    """Schema for bot configuration response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    # Older store configurations may predate these timestamps.
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================================================
# Knowledge Base Schemas
# =============================================================================

class KnowledgeContentType(str, Enum):
    """Knowledge content types"""
    MANUAL = "manual"
    PRODUCT = "product"
    FAQ = "faq"
    POLICY = "policy"


class KnowledgeEntryBase(BaseModel):
    """Base schema for knowledge entry"""
    title: Optional[str] = Field(None, max_length=255)
    content: str = Field(..., min_length=10)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    priority: float = Field(1.0, ge=0, le=10)


class KnowledgeEntryCreate(KnowledgeEntryBase):
    """Schema for creating knowledge entry"""
    content_type: str = Field("manual", description="Content type: manual, product, faq, policy")


class KnowledgeEntryUpdate(BaseModel):
    """Schema for updating knowledge entry"""
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    priority: Optional[float] = None
    is_active: Optional[bool] = None


class KnowledgeEntryResponse(KnowledgeEntryBase):
    """Schema for knowledge entry response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    content_type: str
    source_id: Optional[UUID] = None
    is_active: bool
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class KnowledgeListResponse(BaseModel):
    """Schema for paginated knowledge list"""
    entries: List[KnowledgeEntryResponse]
    total: int
    page: int
    page_size: int


class KnowledgeSearchResult(BaseModel):
    """Schema for knowledge search result"""
    id: UUID
    title: Optional[str]
    content: str
    category: Optional[str]
    content_type: str
    similarity_score: float


class KnowledgeSearchResponse(BaseModel):
    """Schema for knowledge search response"""
    query: str
    results: List[KnowledgeSearchResult]
    total_results: int


# =============================================================================
# CRM Task Schemas
# =============================================================================

class TaskType(str, Enum):
    """Task types"""
    FOLLOW_UP = "follow_up"
    HANDOFF = "handoff"
    CALLBACK = "callback"
    MEETING = "meeting"
    QUOTE = "quote"


class TaskPriority(str, Enum):
    """Task priorities"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(str, Enum):
    """Task statuses"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CRMTaskBase(BaseModel):
    """Base schema for CRM task"""
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    task_type: TaskType
    priority: TaskPriority = TaskPriority.NORMAL
    phone_number: Optional[str] = None
    due_date: Optional[datetime] = None
    context: Optional[Dict[str, Any]] = None


class CRMTaskCreate(CRMTaskBase):
    """Schema for creating CRM task"""
    lead_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None


class CRMTaskUpdate(BaseModel):
    """Schema for updating CRM task"""
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    assigned_to: Optional[UUID] = None
    due_date: Optional[datetime] = None
    completion_notes: Optional[str] = None


class CRMTaskResponse(CRMTaskBase):
    """Schema for CRM task response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    status: TaskStatus
    lead_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    reminder_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[UUID] = None
    completion_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CRMTaskListResponse(BaseModel):
    """Schema for paginated CRM task list"""
    tasks: List[CRMTaskResponse]
    total: int
    page: int
    page_size: int


# =============================================================================
# Conversation Schemas
# =============================================================================

class ConversationStatus(str, Enum):
    """Conversation statuses"""
    ACTIVE = "active"
    HANDOFF = "handoff"
    CLOSED = "closed"


class ConversationResponse(BaseModel):
    """Schema for conversation response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: Optional[UUID] = None
    phone_number: str
    customer_name: Optional[str] = None
    profile_picture_url: Optional[str] = None
    conversation_summary: Optional[str] = None
    topics_discussed: Optional[List[str]] = None
    handoff_requested: Optional[bool] = False
    handoff_reason: Optional[str] = None
    assigned_to: Optional[UUID] = None
    total_messages: Optional[float] = 0
    fallback_count: Optional[float] = 0
    status: str
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Schema for paginated conversation list"""
    conversations: List[ConversationResponse]
    total: int
    page: int
    page_size: int


class ConversationAssign(BaseModel):
    """Schema for assigning conversation to user"""
    assigned_to: UUID = Field(..., description="User ID to assign the conversation to")


class ConversationMessageResponse(BaseModel):
    """Schema for conversation message response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    intent_detected: Optional[str] = None
    confidence_score: Optional[float] = None
    fallback_triggered: bool
    created_at: datetime


# =============================================================================
# Lead Schemas (Enhanced)
# =============================================================================

class LeadStatus(str, Enum):
    """Lead statuses"""
    NEW = "new"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    LOST = "lost"


class LeadResponse(BaseModel):
    """Schema for lead response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    whatsapp_account_id: UUID
    phone_number: str
    lead_score: float
    lead_status: str
    scoring_reason: Optional[str] = None
    total_messages: int
    last_message: Optional[str] = None
    interests: Optional[List[str]] = None
    conversion_sent: bool
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    """Schema for paginated lead list"""
    leads: List[LeadResponse]
    total: int
    page: int
    page_size: int


class LeadScoreUpdate(BaseModel):
    """Schema for manually updating lead score"""
    lead_score: float = Field(..., ge=0, le=100)
    lead_status: Optional[LeadStatus] = None
    scoring_reason: Optional[str] = None


# =============================================================================
# Ad Campaign Schemas (Multi-Store Routing)
# =============================================================================

class AdCampaignBase(BaseModel):
    """Base schema for ad campaign"""
    name: str = Field(..., min_length=1, max_length=255, description="Campaign name for reference")
    description: Optional[str] = None
    campaign_id: Optional[str] = Field(None, description="Meta campaign ID")
    ad_id: Optional[str] = Field(None, description="Meta ad ID")
    ctwa_clid: Optional[str] = Field(None, description="Click-to-WhatsApp Click ID")
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    custom_ref: Optional[str] = Field(None, description="Custom reference code for routing (e.g., STORE123)")
    is_active: bool = True


class AdCampaignCreate(AdCampaignBase):
    """Schema for creating ad campaign"""
    store_id: UUID = Field(..., description="Store ID to route to")
    whatsapp_account_id: UUID = Field(..., description="WhatsApp account this campaign is linked to")


class AdCampaignUpdate(BaseModel):
    """Schema for updating ad campaign"""
    name: Optional[str] = None
    description: Optional[str] = None
    campaign_id: Optional[str] = None
    ad_id: Optional[str] = None
    ctwa_clid: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    custom_ref: Optional[str] = None
    is_active: Optional[bool] = None


class AdCampaignResponse(AdCampaignBase):
    """Schema for ad campaign response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    whatsapp_account_id: UUID
    click_count: int = 0
    conversation_count: int = 0
    created_at: datetime
    updated_at: datetime


class AdCampaignListResponse(BaseModel):
    """Schema for paginated ad campaign list"""
    campaigns: List[AdCampaignResponse]
    total: int


class RoutingInfoResponse(BaseModel):
    """Schema for routing information"""
    store_id: Optional[UUID] = None
    store_name: Optional[str] = None
    routing_method: str
    campaign_id: Optional[UUID] = None
    campaign_name: Optional[str] = None


class StoreSelectionOption(BaseModel):
    """Schema for store selection option"""
    id: UUID
    name: str
    category: Optional[str] = None
    description: Optional[str] = None


class AvailableStoresResponse(BaseModel):
    """Schema for available stores response"""
    stores: List[StoreSelectionOption]
    total: int

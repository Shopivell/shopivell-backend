# models.py

# ✅ CORRECT: This is the SQLAlchemy column type
from db_compat import Vector, ARRAY, UUID
from sqlalchemy import Column, Float, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from database import Base
from utils.crypto import EncryptedString

class WhatsAppAccount(Base):
    __tablename__ = "whatsapp_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    business_account_id = Column(UUID(as_uuid=True), ForeignKey("facebook_business_accounts.id"), nullable=False)
    waba_id = Column(String(255), unique=True, index=True, nullable=False)
    phone_number_id = Column(String(255), unique=True, index=True, nullable=False)
    phone_number = Column(String(50), nullable=False)
    display_name = Column(String(255), nullable=True)
    verified_name = Column(String(255), nullable=True)
    quality_rating = Column(String(50), nullable=True)
    is_enabled = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    webhook_url = Column(Text, nullable=True)
    webhook_verify_token = Column(String(255), nullable=True)
    permanent_access_token = Column(EncryptedString, nullable=True)  # encrypted at rest

    # Store association for multi-store support
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True)
    store = relationship("Store")

    # --- NEW FIELDS FOR CONVERSIONS API ---
    capi_dataset_id = Column(String(50), nullable=True, comment="Meta Conversions API Dataset ID (Pixel ID)")
    capi_access_token = Column(EncryptedString, nullable=True, comment="Meta CAPI Access Token - encrypted at rest")
    # --- END NEW FIELDS ---
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    business_account = relationship("FacebookBusinessAccount", back_populates="whatsapp_accounts")
    messages = relationship("WhatsAppMessage", back_populates="whatsapp_account", cascade="all, delete-orphan")

class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    whatsapp_account_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_accounts.id"), nullable=False)
    message_id = Column(String(255), nullable=False, index=True)
    wamid = Column(String(500), nullable=True)
    from_number = Column(String(50), nullable=False)
    to_number = Column(String(50), nullable=False)
    message_type = Column(String(50), nullable=False)
    direction = Column(String(10), nullable=False)
    status = Column(String(50), nullable=False, default="sent")
    message_text = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)
    media_id = Column(String(500), nullable=True)
    
    meta_data = Column(JSON, nullable=True) 
    
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    whatsapp_account = relationship("WhatsAppAccount", back_populates="messages")

class WhatsAppLead(Base):
    """Track lead quality and conversion status for WhatsApp conversations"""
    __tablename__ = "whatsapp_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    whatsapp_account_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_accounts.id"), nullable=False)
    phone_number = Column(String(50), nullable=False, index=True)

    # Lead scoring
    lead_score = Column(Float, default=0.0)  # 0-100 score
    lead_status = Column(String(50), default="new")  # new, engaged, qualified, converted, lost
    scoring_reason = Column(Text, nullable=True)  # AI reasoning for the score

    # Conversation context
    total_messages = Column(Float, default=0)
    last_message = Column(Text, nullable=True)
    interests = Column(JSON, nullable=True)  # Products/services they asked about

    # Conversion tracking
    conversion_sent = Column(Boolean, default=False)  # Whether CAPI event was sent
    conversion_event_id = Column(String(255), nullable=True)
    conversion_sent_at = Column(DateTime, nullable=True)

    # Marketing consent (WhatsApp Business Messaging Policy requires opt-in
    # before sending marketing messages, and opt-outs must be honored)
    marketing_opt_in = Column(Boolean, default=False, nullable=False)
    opt_in_source = Column(String(100), nullable=True)  # checkout, inbound_message, manual, import
    opt_in_at = Column(DateTime, nullable=True)
    opted_out_at = Column(DateTime, nullable=True)  # Hard suppression: never message if set

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyKnowledge(Base):
    """
    Knowledge base for AI Sales Bot.
    Stores product info, FAQs, policies, and other content for RAG retrieval.
    """
    __tablename__ = "company_knowledge"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    # Content
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    category = Column(String(100), nullable=True, index=True)  # faq, product, policy, general
    tags = Column(ARRAY(String), nullable=True)

    # Content type and source
    content_type = Column(String(50), default="manual", index=True)  # manual, product, faq, policy
    source_id = Column(UUID(as_uuid=True), nullable=True)  # Link to product_id if synced from products

    # Vector embedding for semantic search. Dimension matches the active
    # embedding provider (utils.embeddings) — 384 for the self-hosted local
    # model (BAAI/bge-small-en-v1.5), the default. Switching to a 1536-dim
    # cloud provider is a migration (ALTER column + full re-embed).
    embedding = Column(Vector(384))
    # Which provider/model produced `embedding` (e.g. BAAI/bge-small-en-v1.5,
    # text-embedding-3-small). Vectors from different models are NOT comparable,
    # so this flags rows that need re-embedding after a provider switch.
    embedding_model = Column(String(100), nullable=True)

    # Status
    is_active = Column(Boolean, default=True, index=True)
    priority = Column(Float, default=1.0)  # Higher priority = more relevant

    # Sync tracking
    last_synced_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    store = relationship("Store", backref="knowledge_entries")

    def __repr__(self):
        return f"<CompanyKnowledge {self.id} - {self.title or self.content[:30]}>"


class StoreBotConfig(Base):
    """
    Per-store bot configuration for AI Sales Assistant.
    """
    __tablename__ = "store_bot_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, unique=True, index=True)

    # Bot identity
    bot_name = Column(String(100), default="Sales Assistant")
    bot_personality = Column(Text, nullable=True)  # Custom personality description

    # Messages
    greeting_message = Column(Text, default="Hello! Welcome to our store. How can I help you today?")
    fallback_message = Column(Text, default="I'll connect you with a team member who can help you better.")
    handoff_message = Column(Text, default="A team member will be with you shortly.")

    # AI Settings
    temperature = Column(Float, default=0.7)
    max_response_tokens = Column(Float, default=500)
    similarity_threshold = Column(Float, default=0.4)  # Minimum confidence for knowledge match

    # Lead scoring
    hot_lead_threshold = Column(Float, default=80)  # Score >= this triggers hot lead notification

    # Handoff triggers
    handoff_keywords = Column(ARRAY(String), default=["speak to human", "talk to someone", "customer service", "manager"])
    max_fallbacks_before_handoff = Column(Float, default=3)  # After N failed responses, trigger handoff

    # Notification settings
    notify_on_hot_lead = Column(Boolean, default=True)
    notify_on_handoff = Column(Boolean, default=True)
    notify_on_unanswered = Column(Boolean, default=True)

    # Feature toggles
    is_enabled = Column(Boolean, default=True)
    auto_respond = Column(Boolean, default=True)  # If false, just score leads, don't respond

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    store = relationship("Store", backref="bot_config")

    def __repr__(self):
        return f"<StoreBotConfig store={self.store_id}>"


class WhatsAppConversation(Base):
    """
    Conversation state per phone number for context memory.
    Supports multi-store routing via a shared WhatsApp number.
    """
    __tablename__ = "whatsapp_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True, index=True)  # Nullable until routed
    whatsapp_account_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_accounts.id"), nullable=False, index=True)
    phone_number = Column(String(50), nullable=False, index=True)

    # Routing information
    routing_status = Column(String(50), default="pending")  # pending, routed, awaiting_selection
    routed_via = Column(String(50), nullable=True)  # ad_campaign, previous_conversation, user_selection, default
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("ad_campaigns.id"), nullable=True)
    referral_data = Column(JSON, nullable=True)  # Raw referral data from Meta

    # Conversation summary (AI-generated)
    conversation_summary = Column(Text, nullable=True)
    topics_discussed = Column(ARRAY(String), nullable=True)
    customer_name = Column(String(255), nullable=True)

    # Profile picture from WhatsApp
    profile_picture_url = Column(Text, nullable=True)  # URL from Meta Graph API
    profile_picture_updated_at = Column(DateTime, nullable=True)  # When last fetched

    # Handoff status
    handoff_requested = Column(Boolean, default=False)
    handoff_reason = Column(Text, nullable=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Stats
    total_messages = Column(Float, default=0)
    fallback_count = Column(Float, default=0)  # Times bot couldn't answer
    last_message_at = Column(DateTime, nullable=True)

    # Status
    status = Column(String(50), default="active")  # active, handoff, closed

    # Order flow state machine
    order_flow_active = Column(Boolean, default=False)
    order_flow_state = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", backref="whatsapp_conversations")
    whatsapp_account = relationship("WhatsAppAccount", backref="conversations")
    assigned_user = relationship("User", backref="assigned_conversations")
    messages = relationship("WhatsAppConversationMessage", back_populates="conversation", cascade="all, delete-orphan")
    campaign = relationship("AdCampaign", backref="conversations")

    def __repr__(self):
        return f"<WhatsAppConversation {self.phone_number} - {self.routing_status}>"


class WhatsAppConversationMessage(Base):
    """
    Individual messages in a conversation for context/history.
    """
    __tablename__ = "whatsapp_conversation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_conversations.id"), nullable=False, index=True)

    # Message content
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)

    # AI analysis
    intent_detected = Column(String(100), nullable=True)  # pricing, availability, support, etc.
    confidence_score = Column(Float, nullable=True)  # Knowledge match confidence
    fallback_triggered = Column(Boolean, default=False)

    # Metadata
    message_id = Column(String(255), nullable=True)  # WhatsApp message ID
    meta_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    conversation = relationship("WhatsAppConversation", back_populates="messages")

    def __repr__(self):
        return f"<ConversationMessage {self.role}: {self.content[:30]}>"


class CRMTask(Base):
    """
    Follow-up and handoff tasks for CRM integration.
    """
    __tablename__ = "crm_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    # Task details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(String(50), nullable=False, index=True)  # follow_up, handoff, callback, meeting, quote
    priority = Column(String(20), default="normal")  # low, normal, high, urgent
    status = Column(String(50), default="pending", index=True)  # pending, in_progress, completed, cancelled

    # Related entities
    phone_number = Column(String(50), nullable=True, index=True)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_leads.id"), nullable=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_conversations.id"), nullable=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Scheduling
    due_date = Column(DateTime, nullable=True)
    reminder_at = Column(DateTime, nullable=True)

    # Context
    context = Column(JSON, nullable=True)  # Additional data about the task

    # Completion
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    completion_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", backref="crm_tasks")
    lead = relationship("WhatsAppLead", backref="tasks")
    conversation = relationship("WhatsAppConversation", backref="tasks")
    assignee = relationship("User", foreign_keys=[assigned_to], backref="assigned_tasks")
    completer = relationship("User", foreign_keys=[completed_by], backref="completed_tasks")

    def __repr__(self):
        return f"<CRMTask {self.task_type}: {self.title}>"


class AdCampaign(Base):
    """
    Links Click-to-WhatsApp ad campaigns to stores.
    Used for routing: when a customer clicks an ad, the referral data
    identifies which store they should be connected to.
    """
    __tablename__ = "ad_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    whatsapp_account_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_accounts.id"), nullable=False, index=True)

    # Campaign identifiers from Meta
    campaign_id = Column(String(255), nullable=True, index=True)  # Meta campaign ID
    ad_id = Column(String(255), nullable=True, index=True)  # Meta ad ID
    ctwa_clid = Column(String(255), nullable=True, index=True)  # Click-to-WhatsApp Click ID

    # Custom tracking
    utm_source = Column(String(100), nullable=True)
    utm_medium = Column(String(100), nullable=True)
    utm_campaign = Column(String(255), nullable=True, index=True)
    custom_ref = Column(String(255), nullable=True, index=True)  # Custom reference code

    # Campaign details
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Status
    is_active = Column(Boolean, default=True, index=True)

    # Stats
    click_count = Column(Float, default=0)
    conversation_count = Column(Float, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", backref="ad_campaigns")
    whatsapp_account = relationship("WhatsAppAccount", backref="ad_campaigns")

    def __repr__(self):
        return f"<AdCampaign {self.name} -> Store {self.store_id}>"


class FAQ(Base):
    """
    Frequently Asked Questions for the store.
    These are automatically synced to CompanyKnowledge for bot retrieval.
    """
    __tablename__ = "faqs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    # FAQ content
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(100), nullable=True, index=True)  # shipping, returns, pricing, general, etc.

    # Ordering and status
    display_order = Column(Float, default=0)
    is_active = Column(Boolean, default=True, index=True)
    is_featured = Column(Boolean, default=False)  # Show on website FAQ page

    # Usage tracking
    view_count = Column(Float, default=0)
    helpful_count = Column(Float, default=0)
    not_helpful_count = Column(Float, default=0)

    # Sync status with knowledge base
    knowledge_id = Column(UUID(as_uuid=True), ForeignKey("company_knowledge.id"), nullable=True)
    last_synced_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("Store", backref="faqs")
    knowledge_entry = relationship("CompanyKnowledge", backref="faq_source")

    def __repr__(self):
        return f"<FAQ {self.id} - {self.question[:50]}>"

    def to_knowledge_content(self):
        """Format FAQ for knowledge base embedding."""
        return f"Question: {self.question}\n\nAnswer: {self.answer}"


class WhatsAppFlow(Base):
    """Tracks WhatsApp Flows created for each store."""
    __tablename__ = "whatsapp_flows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    waba_id = Column(String(255), nullable=False)
    flow_id = Column(String(255), nullable=False, unique=True)
    flow_name = Column(String(255), nullable=False)
    status = Column(String(50), default="draft")  # draft, published, deprecated
    version = Column(Float, default=1)
    endpoint_uri = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", backref="whatsapp_flows")
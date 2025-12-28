# WhatsApp Module - AI Sales Assistant Bot

A multi-tenant AI-powered WhatsApp sales assistant for the Shopivell platform. The bot provides intelligent customer service, lead qualification, and conversion optimization based on store-specific knowledge.

## Overview

The AI Sales Assistant is designed to:
- **Understand store context**: Uses product catalog, store information, and FAQs as knowledge base
- **Track conversations**: Maintains conversation history per phone number with context memory
- **Score leads**: Intelligent lead scoring (0-100) based on engagement and intent signals
- **Convert leads**: Assists with sales conversion and scheduling
- **Alert store owners**: Notifies on hot leads and when human intervention is needed

## Features

### Core WhatsApp Features
- Message sending (text, image, document)
- Template messages (pre-approved)
- Interactive buttons
- Automated responses
- Order notifications
- Customer support

### AI Sales Bot Features
- Multi-tenant architecture (per-store configuration)
- RAG-based knowledge retrieval
- Conversation memory and context
- Lead scoring and qualification
- Hot lead notifications
- Human handoff workflow
- CRM task creation

## Critical Rule: No Hallucination Policy

The bot operates under strict rules to prevent misinformation:

1. **ONLY use information from the CONTEXT provided** (Products + Store info)
2. **If context doesn't have the answer: DO NOT RESPOND**
   - Stay silent (do not send "I don't know" messages)
   - Create notification alert for store owner
   - Let human handle the query
3. **NEVER invent product names, prices, features, or packages**
4. **All knowledge MUST come from Products catalogue** (services, packages, pricing)

## Architecture

```
modules/
└── whatsapp/
    ├── models.py              # Database models
    ├── schemas.py             # Pydantic schemas
    ├── router.py              # API endpoints & webhook handler
    ├── chatbot_engine.py      # MultiTenantSalesBot class
    ├── knowledge_service.py   # RAG knowledge management
    ├── lead_scorer.py         # Enhanced lead scoring
    ├── crm_service.py         # CRM task management
    └── README.md              # This file
```

## Database Models

### StoreBotConfig
Per-store bot configuration:
- `bot_name`: Display name for the bot
- `greeting_message`: Initial greeting template
- `fallback_message`: Message when handoff is triggered
- `hot_lead_threshold`: Score threshold for hot lead alerts (default: 80)
- `similarity_threshold`: Minimum confidence for knowledge match (default: 0.4)
- `temperature`: LLM creativity setting (0-1)
- `max_response_tokens`: Response length limit

### WhatsAppConversation
Conversation state per phone number:
- `store_id`: Associated store
- `phone_number`: Customer's WhatsApp number
- `conversation_summary`: AI-generated summary of conversation
- `topics_discussed`: Tracked topics/interests
- `handoff_requested`: Whether human assistance was requested
- `handoff_reason`: Reason for handoff
- `assigned_to`: Human agent assigned (if any)
- `total_messages`: Message count

### WhatsAppConversationMessage
Individual message history:
- `conversation_id`: Parent conversation
- `role`: "user" or "assistant"
- `content`: Message content
- `intent_detected`: Detected customer intent
- `confidence_score`: Knowledge match confidence
- `fallback_triggered`: Whether fallback was triggered

### CRMTask
Follow-up and handoff tasks:
- `store_id`: Associated store
- `task_type`: "follow_up", "handoff", "callback", "meeting", "quote"
- `priority`: "low", "normal", "high", "urgent"
- `status`: "pending", "in_progress", "completed", "cancelled"
- `phone_number`: Customer phone
- `lead_id`: Associated lead
- `due_date`: Task deadline
- `context`: Additional context data

## Knowledge Base System

### Knowledge Sources

1. **Products Catalogue** (Primary - MANDATORY)
   - Product names, descriptions, prices
   - Services and packages
   - Categories and variants
   - Auto-synced when products are updated

2. **Store Information**
   - Business name and type
   - Contact information
   - Operating hours
   - Location details

3. **Manual FAQs** (Optional)
   - Custom Q&A entries
   - Policy information
   - Process explanations

### Knowledge Sync Process

```python
# Auto-sync products to knowledge base
knowledge_service.sync_products_to_knowledge(db, store_id)

# Add manual knowledge entry
knowledge_service.add_manual_knowledge(
    db=db,
    store_id=store_id,
    content="Our refund policy is...",
    title="Refund Policy",
    category="policies"
)
```

### Semantic Search

The knowledge base uses pgvector for semantic similarity search:
- OpenAI embeddings (text-embedding-3-small, 1536 dimensions)
- HNSW index for fast approximate nearest neighbor search
- Configurable similarity threshold (default: 0.4)

## Lead Scoring

### Score Ranges

| Score | Status | Description |
|-------|--------|-------------|
| 0-20 | Cold | Just browsing |
| 21-40 | Cool | General questions |
| 41-60 | Warm | Interest in specific items |
| 61-80 | Hot | Serious interest, comparing |
| 81-100 | Very Hot | Ready to buy (HOT LEAD) |

### Scoring Signals

**Positive Signals (+points)**
- Asking about specific products/services
- Inquiring about pricing
- Asking about availability/scheduling
- Mentioning timeline ("this week", "soon")
- Budget discussions
- Comparison questions
- Request for quotes

**Negative Signals (-points)**
- Price objections
- "Just looking" statements
- Long response delays
- Vague questions

### Industry-Specific Scoring

The scorer adapts to store type:
- **Security**: Site surveys, installation timeline, payment plans
- **E-commerce**: Cart, shipping, returns
- **Services**: Consultations, scheduling, quotes

## Notification Integration

The bot triggers notifications via the Notifications module:

### Notification Types

| Type | Trigger | Priority | Action |
|------|---------|----------|--------|
| `hot_lead` | Lead score >= 80 | high | View lead, take over conversation |
| `handoff` | Bot can't answer | urgent | View conversation, respond manually |
| `unanswered` | No knowledge match | high | Add to knowledge base or respond |
| `new_message` | New inbound message | normal | View conversation |

### Notification Flow

```python
# When bot can't answer (fallback triggered)
async def handle_fallback(db, store_id, phone_number, query):
    # 1. Don't send any response to customer
    # 2. Create notification for store owner
    await notification_service.create_unanswered_query_notification(
        db=db,
        phone_number=phone_number,
        query_text=query,
        conversation_id=conversation.id
    )
    # 3. Create CRM task
    crm_service.create_follow_up_task(
        db=db,
        task_type="handoff",
        priority="urgent",
        phone_number=phone_number,
        context={"query": query, "reason": "No knowledge match"}
    )
```

## API Endpoints

### Core WhatsApp Endpoints
- `POST /v1/whatsapp/send` - Send message
- `POST /v1/whatsapp/template` - Send template message
- `GET /v1/whatsapp/conversations` - List conversations
- `POST /v1/whatsapp/webhook` - Incoming webhook handler
- `PUT /v1/whatsapp/settings` - Update settings

### Knowledge Management
- `POST /v1/whatsapp/stores/{store_id}/knowledge/sync-products` - Sync products to knowledge
- `POST /v1/whatsapp/stores/{store_id}/knowledge` - Add manual entry
- `GET /v1/whatsapp/stores/{store_id}/knowledge` - List entries
- `DELETE /v1/whatsapp/stores/{store_id}/knowledge/{id}` - Soft delete entry

### Bot Configuration
- `GET /v1/whatsapp/stores/{store_id}/bot-config` - Get configuration
- `PUT /v1/whatsapp/stores/{store_id}/bot-config` - Update configuration

### CRM Tasks
- `GET /v1/whatsapp/stores/{store_id}/tasks` - List tasks
- `PUT /v1/whatsapp/stores/{store_id}/tasks/{id}` - Update task status

### Conversations
- `GET /v1/whatsapp/stores/{store_id}/conversations` - List conversations
- `POST /v1/whatsapp/conversations/{id}/assign` - Assign to human agent

## Message Processing Flow

```
Incoming WhatsApp Message
         │
         ▼
┌─────────────────────┐
│  Get Store Config   │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Load Conversation   │
│ History & Context   │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Search Knowledge    │◄──── Products, Store Info, FAQs
│ Base (RAG)          │
└─────────────────────┘
         │
         ▼
    ┌────────────┐
    │ Confidence │
    │   Check    │
    └────────────┘
         │
    ┌────┴────┐
    │         │
   High      Low
    │         │
    ▼         ▼
┌────────┐  ┌──────────────────┐
│Generate│  │ DO NOT RESPOND   │
│Response│  │ Create Alert     │
└────────┘  │ Create CRM Task  │
    │       └──────────────────┘
    ▼
┌─────────────────────┐
│  Update Lead Score  │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Check Hot Lead      │──► If score >= 80, send notification
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Send Response via   │
│ WhatsApp API        │
└─────────────────────┘
```

## Configuration

### Environment Variables

```env
# OpenAI for embeddings and chat
OPENAI_API_KEY=sk-...

# Similarity threshold (0-1, higher = stricter matching)
KNOWLEDGE_SIMILARITY_THRESHOLD=0.4

# Hot lead threshold (0-100)
HOT_LEAD_THRESHOLD=80

# Max conversation history to include
MAX_CONVERSATION_HISTORY=10
```

### Store-Specific Settings

Each store can customize:
- Bot personality/tone
- Greeting messages
- Fallback behavior
- Notification preferences
- Lead scoring thresholds

## Message Types Supported

- **Text**: Plain text messages
- **Image**: Product images, catalogs
- **Document**: PDFs, price lists
- **Template**: Pre-approved WhatsApp templates
- **Interactive Buttons**: Quick reply options

## Scalability Considerations

### Performance Optimizations

1. **Pre-computed Embeddings**: Generate on product create/update, not at query time
2. **Batch Processing**: Products synced in batches of 100
3. **Incremental Sync**: Only re-embed changed products
4. **HNSW Index**: Fast approximate nearest neighbor for pgvector

### Caching Strategy

- **Redis Cache**:
  - Store configurations (TTL: 5 min)
  - Frequent product queries (TTL: 1 hour)
  - Conversation context (TTL: 24 hours)

### Database Indexes

```sql
CREATE INDEX idx_knowledge_store_id ON company_knowledge(store_id);
CREATE INDEX idx_knowledge_embedding ON company_knowledge
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_leads_store_phone ON whatsapp_leads(store_id, phone_number);
CREATE INDEX idx_conversations_store_phone ON whatsapp_conversations(store_id, phone_number);
```

## Best Practices

### For Store Owners

1. **Keep Products Updated**: The bot's knowledge is only as good as your catalog
2. **Add Complete Information**: Include prices, descriptions, availability
3. **Use Categories**: Help the bot organize product knowledge
4. **Add FAQs**: Common questions about policies, shipping, etc.
5. **Monitor Notifications**: Respond to unanswered queries promptly
6. **Review Lead Scores**: Follow up on hot leads quickly

### For Developers

1. **Test Knowledge Retrieval**: Verify semantic search returns relevant results
2. **Monitor Fallback Rate**: High fallback rate indicates knowledge gaps
3. **Log Confidence Scores**: Track match quality over time
4. **Handle Edge Cases**: Long messages, non-text content, etc.
5. **Rate Limit**: Respect WhatsApp API limits

## Troubleshooting

### Bot Not Responding

1. Check if knowledge base has relevant content
2. Verify similarity threshold isn't too high
3. Check for API errors in logs
4. Ensure store has valid WhatsApp account connected

### Low Match Confidence

1. Add more detailed product descriptions
2. Include common variations/synonyms
3. Consider lowering similarity threshold
4. Add manual FAQ entries for common queries

### Notification Not Received

1. Verify Notifications module is registered
2. Check WebSocket connection
3. Verify notification preferences
4. Check browser console for errors

## Integration

- WhatsApp Business API (Meta)
- Webhook for incoming messages
- OpenAI API (embeddings + chat completion)
- PostgreSQL with pgvector extension
- Redis for caching
- Notifications module for real-time alerts

---

## WhatsApp Embedded Signup

Store owners can connect their own WhatsApp Business phone numbers through Meta's Embedded Signup flow. This enables multi-tenant WhatsApp messaging where each store has its own dedicated WABA (WhatsApp Business Account) and phone number.

### How It Works

1. **Store owner initiates connection** from frontend settings
2. **Frontend loads Facebook SDK** and opens embedded signup popup
3. **User authenticates with Meta** and grants permissions
4. **Meta returns access token** with WABA and phone number selection
5. **Backend stores credentials** linked to the store
6. **Business Profile auto-filled** from store data

### Multi-Tenant Architecture

Each store gets:
- **Own WABA ID**: WhatsApp Business Account identifier
- **Own Phone Number ID**: Dedicated phone for sending/receiving
- **Permanent Access Token**: Long-lived token for API calls
- **Isolated Messages**: Messages stored with account linkage

### API Endpoints

```
GET  /v1/api/whatsapp/connect/info          # Get FB SDK config (public)
GET  /v1/api/whatsapp/connect/init          # Start OAuth flow
GET  /v1/api/whatsapp/connect/callback      # OAuth callback
POST /v1/api/whatsapp/connect/complete      # Complete signup
POST /v1/api/whatsapp/connect/sdk-callback  # FB SDK callback
GET  /v1/api/whatsapp/connect/accounts      # List connected accounts
POST /v1/api/whatsapp/connect/accounts/set-default  # Set default account
DELETE /v1/api/whatsapp/connect/accounts/{id}       # Disconnect account
```

### Environment Variables

```env
# Meta App Configuration
META_APP_ID=your_app_id
META_APP_SECRET=your_app_secret
META_WHATSAPP_CONFIG_ID=your_config_id

# URLs
FRONTEND_URL=http://localhost:5173
BACKEND_URL=http://localhost:8000
```

### Frontend Integration

```typescript
// Initialize Facebook SDK
FB.init({
  appId: 'YOUR_APP_ID',
  version: 'v21.0'
});

// Launch Embedded Signup
FB.login(response => {
  if (response.authResponse) {
    // Send to backend
    await fetch('/v1/api/whatsapp/connect/sdk-callback', {
      method: 'POST',
      body: JSON.stringify({
        accessToken: response.authResponse.accessToken,
        waba_id: selectedWabaId,
        phone_number_id: selectedPhoneId
      })
    });
  }
}, {
  config_id: 'YOUR_CONFIG_ID',
  response_type: 'code',
  override_default_response_type: true,
  extras: {
    setup: { /* embedded signup config */ }
  }
});
```

---

## WhatsApp Business Profile Auto-Fill

When a store owner connects their WhatsApp number, the system automatically populates their WhatsApp Business Profile using existing store information.

### Auto-Filled Fields

| WhatsApp Field | Source | Max Length |
|----------------|--------|------------|
| `address` | Store address/city/state/country | 256 chars |
| `description` | Store description | 512 chars |
| `vertical` | Mapped from business_type | - |
| `email` | Store email | 128 chars |
| `websites` | Store website URLs | 2 URLs max |

### Business Type to WhatsApp Vertical Mapping

The system maps Shopivell business types to WhatsApp's predefined verticals:

```python
BUSINESS_TYPE_TO_VERTICAL = {
    "retail": "RETAIL",
    "ecommerce": "RETAIL",
    "fashion": "RETAIL",
    "electronics": "RETAIL",
    "grocery": "RETAIL",
    "restaurant": "RESTAURANT",
    "food": "RESTAURANT",
    "cafe": "RESTAURANT",
    "catering": "RESTAURANT",
    "hotel": "HOTEL",
    "travel": "TRAVEL",
    "automotive": "AUTO",
    "car": "AUTO",
    "beauty": "BEAUTY",
    "salon": "BEAUTY",
    "spa": "BEAUTY",
    "health": "HEALTH",
    "medical": "HEALTH",
    "pharmacy": "HEALTH",
    "fitness": "HEALTH",
    "education": "EDU",
    "school": "EDU",
    "training": "EDU",
    "finance": "FINANCE",
    "insurance": "FINANCE",
    "entertainment": "ENTERTAIN",
    "events": "ENTERTAIN",
    "nonprofit": "NONPROFIT",
    "ngo": "NONPROFIT",
    "government": "GOVT",
    "security": "PROF_SERVICES",
    "consulting": "PROF_SERVICES",
    "legal": "PROF_SERVICES",
    "accounting": "PROF_SERVICES",
    "services": "PROF_SERVICES",
}
# Default: "OTHER" if no match
```

### Available WhatsApp Verticals

- `UNDEFINED` - Not specified
- `OTHER` - Other business type
- `AUTO` - Automotive
- `BEAUTY` - Beauty, Spa, Salon
- `APPAREL` - Clothing and Apparel
- `EDU` - Education
- `ENTERTAIN` - Entertainment
- `EVENT_PLAN` - Event Planning
- `FINANCE` - Financial Services
- `GROCERY` - Grocery
- `GOVT` - Government
- `HOTEL` - Hotels and Lodging
- `HEALTH` - Health
- `NONPROFIT` - Non-profit
- `PROF_SERVICES` - Professional Services
- `RETAIL` - Retail
- `TRAVEL` - Travel and Transportation
- `RESTAURANT` - Restaurant
- `NOT_A_BIZ` - Not a Business

### API Call

```python
# POST /v20.0/<PHONE_NUMBER_ID>/whatsapp_business_profile
payload = {
    "messaging_product": "whatsapp",
    "address": "123 Main St, City, State, Country",
    "description": "Your store description here...",
    "vertical": "RETAIL",
    "email": "store@example.com",
    "websites": ["https://example.com"]
}
```

### Implementation

The auto-fill happens in `embedded_signup.py`:

```python
class EmbeddedSignupService:
    async def update_business_profile(
        self,
        access_token: str,
        phone_number_id: str,
        store: Store
    ) -> Tuple[bool, Optional[str]]:
        """
        Update WhatsApp Business Profile with store information.
        Called automatically after successful signup.
        """
        # Build address from store location
        address = ", ".join(filter(None, [
            store.store_address,
            store.store_city,
            store.store_state,
            store.store_country
        ]))

        # Map business type to vertical
        vertical = BUSINESS_TYPE_TO_VERTICAL.get(
            (store.business_type or "").lower(),
            "OTHER"
        )

        # Build payload and call API
        payload = {
            "messaging_product": "whatsapp",
            "address": address[:256],
            "description": (store.store_description or "")[:512],
            "vertical": vertical,
            "email": (store.store_email or "")[:128],
            "websites": websites[:2]
        }
        # POST to Graph API
```

### Error Handling

- Profile update failures are logged but don't block account creation
- Missing store fields are omitted from the update
- Errors are returned to caller for logging/debugging

---

## Future Enhancements

- [ ] Multi-language support
- [ ] Voice message transcription
- [ ] Image/catalog sharing
- [ ] Appointment scheduling integration
- [ ] Payment link generation
- [ ] Order status tracking
- [ ] Customer sentiment analysis

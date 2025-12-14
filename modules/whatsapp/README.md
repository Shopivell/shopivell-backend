Overview
This module provides a comprehensive WhatsApp Business API integration system with real-time messaging, webhook handling, and Meta Conversions API support. It's built using FastAPI, SQLAlchemy, and integrates with Meta's WhatsApp Business Platform.

🚀 Quick Start
Prerequisites
Python 3.9+

PostgreSQL database

Meta Business Account with WhatsApp access

WhatsApp Business Account (WABA)

Facebook App configured for WhatsApp

env
DATABASE_URL=postgresql://user:password@localhost/whatsapp_db
SECRET_KEY=your-secret-key
WHATSAPP_API_VERSION=v23.0
📁 Project Structure
text
/modules/whatsapp/
├── models.py           # Database models
├── schemas.py          # Pydantic schemas
├── whatsapp_router.py  # API routes and business logic
└── README.md           # This file
🔧 Core Components
1. Database Models
WhatsAppAccount
Stores WhatsApp Business Account configurations:

WABA ID: WhatsApp Business Account ID

Phone Number ID: Unique ID for each phone number

Access Tokens: For API communication

Webhook Settings: For receiving messages

CAPI Settings: Conversions API credentials

WhatsAppMessage
Tracks all message interactions:

Message IDs: Both Meta and system IDs

Status Tracking: sent, delivered, read

Message Content: Text, templates, media

Metadata: Raw API responses

2. API Endpoints
Account Management
POST /api/whatsapp/accounts - Create WhatsApp account

GET /api/whatsapp/accounts - List all accounts

PUT /api/whatsapp/accounts/{id} - Update account

GET /api/whatsapp/accounts/{id}/info - Get account info from Meta

Message Sending
POST /api/whatsapp/accounts/{id}/send-template - Send template message

POST /api/whatsapp/accounts/{id}/send-text - Send text message

POST /api/whatsapp/accounts/{id}/send-hello-world - Send hello_world template

POST /api/whatsapp/test/send-message - Test endpoint

Message History
GET /api/whatsapp/accounts/{id}/messages - Get message history

GET /api/whatsapp/accounts/{id}/templates - Get available templates

Real-time Features
GET /api/whatsapp/webhook - Webhook verification

POST /api/whatsapp/webhook - Receive webhook events

WS /api/whatsapp/accounts/{id}/ws - WebSocket for real-time updates

Conversions API
POST /api/whatsapp/accounts/{id}/send-conversion - Send conversion event

POST /api/whatsapp/accounts/{id}/capi-settings - Configure CAPI settings

📱 WhatsApp Message Flow
1. Initial Setup
python
# Create WhatsApp account
POST /api/whatsapp/accounts
{
    "business_account_id": "uuid",
    "waba_id": "1234567890",
    "phone_number_id": "9876543210",
    "phone_number": "15551234567"
}
2. 24-Hour Message Window Rules
First Contact: Must use approved templates (e.g., hello_world)

Within 24 Hours: Can send free-form messages

After 24 Hours: Must use templates again

3. Sending Messages
Template Message (New Conversation)
python
POST /api/whatsapp/accounts/{id}/send-template
{
    "to": "15551234567",
    "template_name": "order_confirmation",
    "language_code": "en_US",
    "components": [...]
}
Text Message (Active Conversation)
python
POST /api/whatsapp/accounts/{id}/send-text
{
    "to": "15551234567",
    "body": "Your order has shipped!"
}
🔄 Webhook Configuration
1. Configure Webhook in Meta Dashboard
Callback URL: https://your-domain.com/api/whatsapp/webhook

Verify Token: Generate unique token

Subscribe Fields: messages, message_statuses

2. Update Account with Webhook Details
python
PUT /api/whatsapp/accounts/{id}
{
    "webhook_url": "https://your-domain.com/api/whatsapp/webhook",
    "webhook_verify_token": "your-verify-token"
}
3. Webhook Processing
Incoming Messages: Saved to DB, broadcast via WebSocket

Message Statuses: Updated in real-time

Error Handling: Logs errors, maintains message state

📊 Conversions API Integration
1. Setup
Create Dataset in Meta Events Manager

Generate Conversions API Access Token

Configure account:

python
POST /api/whatsapp/accounts/{id}/capi-settings
{
    "capi_dataset_id": "1234567890123456",
    "capi_access_token": "EAAG... (long-lived token)"
}
2. Sending Conversion Events
python
POST /api/whatsapp/accounts/{id}/send-conversion
{
    "event_name": "Purchase",
    "phone_number": "15551234567",
    "value": 99.99,
    "currency": "USD",
    "order_id": "ORD-12345"
}
3. PII Handling
Phone numbers hashed with SHA256

Emails normalized and hashed

Names processed for matching

All hashing done before sending to Meta

⚡ Real-time Features
WebSocket Connections
javascript
// Frontend WebSocket connection
const ws = new WebSocket(`wss://your-domain.com/api/whatsapp/accounts/${accountId}/ws`);

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    // Update UI with new message
};
Real-time Events
New Incoming Messages: Instantly appear in chat

Message Status Updates: Sent → Delivered → Read

System Notifications: Connection status, errors

🗄️ Database Schema
Key Relationships
text
FacebookBusinessAccount 1───* WhatsAppAccount 1───* WhatsAppMessage
          │                            │
          │                            *-- CAPI Settings
          │
          └───* Access Tokens
Indexes for Performance
whatsapp_accounts(waba_id, phone_number_id) - Fast lookups

whatsapp_messages(message_id, timestamp) - Message retrieval

whatsapp_messages(from_number, direction) - Conversation history

🔒 Security Considerations
1. Access Tokens
Store encrypted in production

Use environment variables for sensitive data

Rotate tokens regularly

2. Webhook Security
Validate verify tokens

Rate limit incoming requests

Log all webhook activities

3. PII Protection
Hash all personal data before storage

Never log raw phone numbers

Use parameterized queries

🐛 Common Issues & Solutions
1. Message Sending Failures
Error 131051: Phone number not registered with WABA

Error 131009: Template not approved

Error 132000: Rate limit exceeded

2. Webhook Issues
Verify token mismatch: Check stored token vs Meta config

Duplicate messages: Implement message ID deduplication

Missing fields: Ensure webhook is subscribed to all events

3. Database Issues
Connection pool exhausted: Increase pool size, add connection recycling

Slow queries: Add missing indexes, optimize joins

Duplicate entries: Implement unique constraints

📈 Monitoring & Logging
Key Metrics to Track
Message success/failure rates

Webhook response times

Database query performance

WebSocket connection counts

Logging Levels
python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Info: Business logic flow
# Warning: Non-critical issues
# Error: Critical failures
# Debug: Detailed tracing
🚀 Production Checklist
Enable SSL/TLS for all endpoints

Implement token encryption

Set up database backups

Configure monitoring alerts

Implement rate limiting

Set up error tracking (Sentry, etc.)

Create API documentation

Test failover scenarios

📚 Additional Resources
Meta WhatsApp Business API Docs

Conversions API Documentation

Webhook Best Practices

FastAPI Documentation

🆘 Getting Help
Check the logs for detailed error messages

Verify Meta Dashboard configuration

Test with WhatsApp test numbers first

Use the debug endpoints for troubleshooting

Consult Meta's API status page for outages

📄 License
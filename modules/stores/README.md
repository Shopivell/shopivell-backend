This module provides a comprehensive store management system with multi-step onboarding, store configuration, and integration with other platform features. It handles everything from initial store creation to ongoing management and customization.

🚀 Quick Start
Prerequisites
Python 3.9+

PostgreSQL database

User authentication system

Payment module (for subscriptions)

Social module (for Facebook integration)

Installation
Install dependencies:

bash
pip install fastapi sqlalchemy psycopg2-binary
Configure database connection:

env
DATABASE_URL=postgresql://user:password@localhost/ecommerce_db
📁 Project Structure
text
modules/stores/
├── models.py           # Database models (Store, StoreSetupSession)
├── schemas.py          # Pydantic schemas
├── api.py              # FastAPI endpoints
└── README.md           # This documentation
🔧 Core Components
1. Database Models
Store
Main store entity with comprehensive configuration:

Basic Info: Name, phone, email, logo

Business Details: Type, voice/tone, products/services

Delivery Settings: Multiple delivery options, fees

Features & Goals: Enabled features and business objectives

Setup Progress: Track onboarding completion

StoreSetupSession
Manages multi-step onboarding process:

Session Data: Stores temporary data during setup

Progress Tracking: Current step, completed steps, progress percentage

Step Persistence: Allows users to resume setup

Session Management: Active/inactive state management

2. Setup Steps Enum
Defines the 9-step onboarding process:

python
class StoreSetupStep(str, enum.Enum):
    CREATE_STORE = "create_store"      # Step 0: Session creation
    BASIC_INFO = "basic_info"          # Step 1: Basic store details
    BUSINESS_TYPE = "business_type"    # Step 2: Business categorization
    DELIVERY_SETTINGS = "delivery_settings"  # Step 3: Delivery options
    PAYMENT_METHODS = "payment_methods"      # Step 4: Payment setup
    FEATURES = "features"              # Step 5: Feature selection
    GOALS = "goals"                    # Step 6: Business objectives
    DOMAIN = "domain"                  # Step 7: Custom domain
    WHATSAPP = "whatsapp"              # Step 8: WhatsApp integration
    COMPLETED = "completed"            # Final: Store created
📱 API Endpoints
Store Setup (Multi-step Onboarding)
POST /api/stores/setup/start - Start new setup session

POST /api/stores/setup/{session_id}/step - Update step data

POST /api/stores/setup/{session_id}/complete - Complete & create store

POST /api/stores/setup/{session_id}/cancel - Cancel setup

GET /api/stores/setup/session/{session_id} - Get session data

POST /api/stores/setup/get-or-create - Get or create session

POST /api/stores/setup/force-restart - Force restart setup

Store Management
GET /api/stores/{store_id} - Get store details

GET /api/stores/owner/{owner_id} - Get all stores for owner

PATCH /api/stores/{store_id} - Update store

DELETE /api/stores/{store_id} - Delete store

Additional Features
GET /api/stores/{store_id}/hashtag-info - Get hashtag suggestions

GET /api/stores/owner/{owner_id}/hashtag-info - Get hashtags for all stores

POST /api/stores/scrape-website - Mock website scraping

POST /api/stores/business/send-message - Send messages (external service)

POST /api/stores/n8n/webhook/message - Simple webhook for n8n

🔄 Store Setup Flow
Phase 1: Session Creation
python
POST /api/stores/setup/start
{
    "user_id": "uuid"
}
Returns a StoreSetupSession with empty data and step 1.

Phase 2: Step-by-Step Data Collection
python
POST /api/stores/setup/{session_id}/step
{
    "step": "basic_info",
    "data": {
        "store_name": "My Awesome Store",
        "store_phone": "+1234567890",
        "store_email": "contact@store.com",
        "store_link": "https://store.com",
        "logo_url": "https://cdn.store.com/logo.png"
    }
}
Phase 3: Complete & Create Store
python
POST /api/stores/setup/{session_id}/complete
Validates all data and creates the actual Store record.

💡 Step-by-Step Guide
Step 1: Basic Information
Required Fields:

store_name: Business name

store_phone: Contact number

store_email: Email address

Optional Fields:

store_link: Website URL

color_theme: Brand color

logo_url: Logo image URL

Step 2: Business Type
Selection Options:

Restaurant, Cafe, Clothing, Electronics

Beauty, Fitness, Home Decor, etc.

Custom business types supported

Additional Fields:

store_voice: Brand voice description

store_tone: Communication tone

products_or_services: List of offerings

Step 3: Delivery Settings
Options:

Delivery enabled/disabled

Pickup enabled/disabled

Dine-in enabled/disabled

Delivery fee configuration

Free delivery minimum

Step 4: Payment Methods
Configuration:

Supported payment methods

Payment gateway settings

Currency preferences

Step 5: Features
Selectable Features:

WhatsApp integration

Social media posting

Analytics dashboard

Inventory management

Customer reviews

Email marketing

Step 6: Business Goals
Objective Options:

Increase online sales

Build customer loyalty

Expand product range

Improve customer service

Enhance brand awareness

Step 7: Domain Configuration
Options:

Custom domain setup

Subdomain generation

SSL certificate management

Step 8: WhatsApp Integration
Setup:

WhatsApp Business account

Template message approval

Webhook configuration

Step 9: Completion
Final Steps:

Data validation

Store creation

Session cleanup

Welcome email/setup

🏪 Store Features
Basic Configuration
Brand Identity: Name, logo, colors, voice

Contact Information: Phone, email, links

Business Type: Categorization and specialization

Service Options
Delivery: Multiple delivery methods

Pickup: In-store/curbside pickup

Dine-in: For physical locations

Fees: Configurable delivery fees

Integration Points
Payment: Multiple payment gateways

Social: Facebook Page connections

Communication: WhatsApp messaging

Analytics: Business insights

Management Tools
Setup Wizard: Guided onboarding

Progress Tracking: Step completion

Session Management: Resume capabilities

Data Validation: Input verification

🔒 Security & Validation
User Authorization
Users can only manage their own stores

Session ownership validation

API key/token authentication

Data Validation
python
# Pydantic validation in schemas
store_name: str = Field(min_length=3, max_length=255)
store_phone: str = Field(pattern=r'^\+?[1-9]\d{1,14}$')
store_email: EmailStr = Field(...)
Session Security
Session timeout handling

CSRF protection

Data encryption for sensitive info

Audit logging for changes

🗄️ Database Schema
Key Relationships
text
User 1───* Store
   │
   └───* StoreSetupSession (temporary)
Indexes for Performance
stores(owner_id, is_setup_completed) - User store lookups

stores(store_name) - Search optimization

store_setup_sessions(user_id, is_active) - Active session lookup

store_setup_sessions(updated_at) - Cleanup queries

Data Types
UUID: All primary keys

JSON: Flexible data storage

Enum: Controlled step values

DateTime: Timestamp tracking

🐛 Common Issues & Solutions
1. Setup Session Issues
Session not found: Verify session ID and active status

Step data not saving: Check JSON structure and field names

Progress not updating: Verify step completion logic

Session expired: Implement session timeout handling

2. Store Creation Issues
Missing required fields: Validate all required data

Duplicate store name: Implement name uniqueness check

Invalid phone/email: Use proper validation patterns

Permission denied: Verify user ownership

3. Integration Issues
WhatsApp setup failed: Check API credentials and permissions

Domain not working: Verify DNS configuration

Payment integration: Validate gateway settings

Social media connection: Check OAuth tokens

4. Debug Tools
python
# Check session data
GET /api/stores/setup/session/{session_id}

# Force restart if stuck
POST /api/stores/setup/force-restart

# Validate store data
GET /api/stores/{store_id}
📈 Monitoring & Analytics
Key Metrics
Setup completion rate

Average setup time per step

Drop-off points in onboarding

Store creation success rate

Feature adoption rates

Logging Strategy
python
# Info: Setup progression
logger.info(f"User {user_id} started store setup")

# Warning: Setup issues
logger.warning(f"User {user_id} stuck on step {step}")

# Error: Creation failures
logger.error(f"Failed to create store for {user_id}: {error}")

# Debug: Detailed data (development)
logger.debug(f"Session data: {session_data}")
Health Checks
Database connectivity: Verify model access

Session cleanup: Remove stale sessions

Data consistency: Validate store relationships

Integration health: Check external services

🚀 Production Checklist
Database indexes optimized

Session timeout configuration

Input validation comprehensive

Error messages user-friendly

Rate limiting implemented

Backup strategy for store data

Monitoring alerts configured

Documentation complete

API versioning planned

Migration scripts tested

📚 Integration Examples
Frontend Integration
javascript
// 1. Start setup
const startSetup = async (userId) => {
    const response = await fetch('/api/stores/setup/start', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId })
    });
    return await response.json();
};

// 2. Update step
const updateStep = async (sessionId, step, data) => {
    const response = await fetch(`/api/stores/setup/${sessionId}/step`, {
        method: 'POST',
        body: JSON.stringify({ step, data })
    });
    return await response.json();
};

// 3. Complete setup
const completeSetup = async (sessionId) => {
    const response = await fetch(`/api/stores/setup/${sessionId}/complete`, {
        method: 'POST'
    });
    return await response.json();
};

// 4. Resume setup
const resumeSetup = async (sessionId) => {
    const response = await fetch(`/api/stores/setup/session/${sessionId}`);
    return await response.json();
};
Hashtag Generation
python
# Automatically generate hashtags for social media
hashtags = generate_hashtag_suggestions(
    store_name="Coffee Corner",
    business_type="cafe"
)

# Returns categorized hashtag suggestions
{
    "store_specific": ["coffeecorner", "shopcoffeecorner", ...],
    "business_related": ["coffee", "cafe", "barista", ...],
    "general_business": ["smallbusiness", "supportlocal", ...],
    "platform_specific": { "instagram": [...], "facebook": [...] }
}
Website Scraping Simulation
python
# Mock endpoint for testing
POST /api/stores/scrape-website
{
    "url": "https://pizzapalace.com"
}

# Returns structured business data
{
    "store_name": "Pizza Palace",
    "store_email": "hello@pizzapalace.com",
    "store_phone": "555-0123",
    "store_voice": "Authentic Italian pizza since 1990...",
    "services_products": "Margherita Pizza, Pepperoni Special...",
    "color_theme": "#E53E3E",
    "logo_url": "https://cdn.example.com/pizza-logo.png"
}
🔄 Workflow Examples
New User Onboarding
User signs up for platform

System creates user record

User initiates store setup

Guided 9-step process begins

Data collected step by step

Store created upon completion

Welcome email and next steps

Store Management
Owner logs into dashboard

Views store analytics

Updates store information

Manages integrations

Views customer interactions

Generates reports
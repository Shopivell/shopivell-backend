Overview
This module provides a complete payment and subscription management system for the e-commerce platform. It supports multiple payment methods (EcoCash, InnBucks, Bank Transfer) with PayNow integration, package-based subscriptions, and comprehensive transaction tracking.

🚀 Quick Start
Prerequisites
Python 3.9+

PostgreSQL database

PayNow merchant account (for EcoCash/InnBucks payments)

Store and User modules configured

Configure environment variables:

env
DATABASE_URL=postgresql://user:password@localhost/ecommerce_db
PAYNOW_ID=your_paynow_id
PAYNOW_KEY=your_paynow_key
PAYNOW_INTEGRATION_KEY=your_paynow_integration_key
📁 Project Structure
text
modules/payments/
├── models.py           # Database models (PaymentTransaction, StoreSubscription, etc.)
├── schemas.py          # Pydantic schemas for request/response
├── api.py              # FastAPI endpoints and business logic
├── utils/
│   └── payment_service.py  # Payment processing logic
└── README.md           # This documentation
🔧 Core Components
1. Database Models
PackagePricing
Defines subscription packages and pricing:

FREE: $0.10/month (basic features)

PREMIUM: Custom pricing (advanced features)

BUSINESS: Custom pricing (enterprise features)

PaymentTransaction
Tracks all payment transactions:

Reference: Unique transaction ID

Payment Methods: EcoCash, InnBucks, Bank Transfer

Status Tracking: pending → processing → completed/failed

Metadata: Raw payment provider data

StoreSubscription
Manages store subscription states:

Package Assignment: Links store to package

Billing Period: Monthly/Annual

Feature Access: Enabled features and usage limits

Payment History: Links to payment transactions

2. Payment Service (utils/payment_service.py)
Key Functions
create_payment_transaction(): Creates and stores payment record

initiate_ecocash_payment(): Initiates EcoCash via PayNow

update_payment_status(): Updates transaction status

activate_subscription(): Activates subscription after payment

PayNow Integration Flow
Create payment request

Generate PayNow poll URL

Send SMS to user

Poll for payment status

Activate subscription on success

📱 API Endpoints
Package Management
GET /api/payments/packages - Get all available packages

GET /api/payments/packages/{package_name} - Get specific package

GET /api/payments/packages/compare - Compare packages

POST /api/payments/packages - Create new package (admin)

PATCH /api/payments/packages/{package_name} - Update package (admin)

Payment Processing
POST /api/payments/initiate - Initiate payment for subscription

POST /api/payments/ecocash/initiate - Direct EcoCash payment

GET /api/payments/transactions/{reference} - Get transaction details

GET /api/payments/store/{store_id}/transactions - Get store transactions

GET /api/payments/store/{store_id}/summary - Get payment summary

Subscription Management
GET /api/payments/store/{store_id}/subscription - Get subscription details

POST /api/payments/cancel-subscription/{store_id} - Cancel subscription

Webhook & Status
POST /api/payments/webhook/paynow - PayNow webhook endpoint

POST /api/payments/status/update - Manual status update (admin)

GET /api/payments/check-status/{reference} - Check payment status

POST /api/payments/simulate/{reference} - Simulate payment (testing)

💳 Payment Flow
1. Choose Package
python
GET /api/payments/packages/compare
Returns package comparison with pricing and features.

2. Initiate Payment
python
POST /api/payments/initiate
{
    "store_id": "uuid",
    "package_name": "premium",
    "payment_method": "ecocash",
    "billing_period": "monthly",
    "mobile_number": "0771234567"
}
3. Payment Processing
EcoCash Flow:
System creates PayNow request

User receives SMS with payment instructions

User pays via EcoCash menu

PayNow sends webhook confirmation

Subscription activated automatically

Bank Transfer Flow:
System generates bank details

User makes transfer with reference

Admin manually updates status via admin panel

4. Status Updates
Real-time: Webhook updates from PayNow

Polling: Client can check status via /check-status/{reference}

Manual: Admin can update via /status/update

🔄 Webhook Configuration
PayNow Webhook Setup
In PayNow merchant dashboard, set webhook URL:

text
https://your-domain.com/api/payments/webhook/paynow
PayNow will send POST requests with status updates:

json
{
    "reference": "PAY-2024-001",
    "status": "paid",
    "paynow_reference": "PN123456",
    "amount": 19.99
}
System automatically updates transaction and activates subscription

📊 Subscription Management
Package Features
Each package includes specific features:

python
{
    "free": ["basic_store", "10_products", "basic_analytics"],
    "premium": ["advanced_store", "100_products", "advanced_analytics", "whatsapp_integration"],
    "business": ["unlimited_products", "priority_support", "api_access", "custom_domain"]
}
Subscription States
Active: Subscription is active and paid

Cancelled: User cancelled, runs until period end

Expired: Period ended, downgraded to free

Auto-renewal
Enabled by default for paid packages

System attempts to charge 3 days before expiry

On failure, sends notification and retries

💰 Pricing Strategy
Default Pricing (USD)
Package	Monthly	Annual (Save 20%)
Free	$0.10	$1.00
Premium	$19.99	$191.90
Business	$49.99	$479.90
Currency Support
USD (default)

ZWL (Zimbabwean Dollar) via PayNow

Multi-currency support planned

🔒 Security Considerations
Payment Data Security
Never store full card details

Encrypt sensitive payment metadata

Use HTTPS for all endpoints

Validate webhook signatures

Access Control
Store owners can only see their transactions

Admin endpoints require authentication

Payment status updates require verification

Fraud Prevention
Transaction amount validation

Mobile number verification for EcoCash

Rate limiting on payment endpoints

Suspicious activity logging

🗄️ Database Schema
Key Relationships
text
Store 1───1 StoreSubscription
   │           │
   │           *───* PaymentTransaction (current/last)
   │
   └───* PaymentTransaction (history)
Indexes for Performance
payment_transactions(reference, store_id) - Fast lookups

payment_transactions(initiated_at, status) - Status queries

store_subscriptions(store_id, is_active) - Subscription checks

🐛 Common Issues & Solutions
1. Payment Failures
EcoCash timeout: Increase polling interval, check network

Insufficient balance: Validate user balance before charging

Expired transaction: Transactions expire after 24 hours

2. Webhook Issues
Missing webhooks: Verify PayNow configuration

Duplicate processing: Implement idempotency keys

Signature verification: Validate PayNow signatures

3. Subscription Issues
Feature not enabled: Check package assignment

Payment not linked: Verify transaction-subscription link

Auto-renewal failed: Check payment method validity

📈 Monitoring & Analytics
Key Metrics
Payment success rate by method

Average transaction value

Subscription churn rate

Revenue by package type

Logging
python
logger.info(f"Payment initiated: {reference}")  # Business flow
logger.warning(f"Payment pending: {reference}") # Non-critical issues
logger.error(f"Payment failed: {error}")        # Critical failures
Dashboard Metrics
Total revenue

Active subscriptions

Payment method distribution

Failed payment analysis

🧪 Testing
Test Payment Simulation
python
POST /api/payments/simulate/PAY-2024-001
Simulates successful payment for testing.

Test Data
Use test mobile numbers: 0777000000 - 0777000009

Test amounts: $0.10 - $100.00

Test packages: All packages available

🚀 Production Checklist
Configure SSL/TLS certificates

Set up PayNow production credentials

Implement payment data encryption

Configure automated backups

Set up monitoring alerts

Test webhook delivery

Implement rate limiting

Create admin dashboard

Document refund procedures

📚 Integration Examples
Frontend Integration
javascript
// 1. Get available packages
const packages = await fetch('/api/payments/packages');

// 2. Initiate payment
const payment = await fetch('/api/payments/initiate', {
    method: 'POST',
    body: JSON.stringify({
        store_id: storeId,
        package_name: 'premium',
        payment_method: 'ecocash',
        mobile_number: '0771234567'
    })
});

// 3. Poll for status
const checkStatus = async (reference) => {
    const response = await fetch(`/api/payments/check-status/${reference}`);
    const data = await response.json();
    
    if (data.status === 'completed') {
        // Redirect to success page
    } else if (data.status === 'failed') {
        // Show error message
    } else {
        // Continue polling
        setTimeout(() => checkStatus(reference), 5000);
    }
};
Admin Integration
python
# Get all pending transactions
pending = db.query(PaymentTransaction).filter(
    PaymentTransaction.status == PaymentStatus.PENDING,
    PaymentTransaction.initiated_at > datetime.utcnow() - timedelta(hours=24)
).all()

# Manual status update for bank transfers
transaction.status = PaymentStatus.COMPLETED
transaction.completed_at = datetime.utcnow()
db.commit()
🔄 Workflow Examples
New Store Subscription
User selects Premium package

System creates payment request ($19.99)

User pays via EcoCash

Webhook confirms payment

System activates Premium features

Store now has 100 products, WhatsApp integration, etc.

Subscription Renewal
3 days before expiry: System attempts auto-charge

If successful: Extends subscription period

If failed: Sends notification, retries next day

After expiry: Downgrades to Free package

Cancellation Flow
User requests cancellation

Subscription remains active until period end

Auto-renewal disabled

At period end: Downgraded to Free

📄 License & Compliance
PCI DSS Compliance
No credit card data storage

Payment redirects to secure providers

Regular security audits

Data Privacy
Transaction data encrypted at rest

User PII protected

Compliance with local regulations

Refund Policy
7-day money-back guarantee

Pro-rated refunds for annual plans

Refunds processed within 14 days

🆘 Support & Troubleshooting
Common Error Messages
"Store not found": Verify store exists and user has access

"Payment method not supported": Check available payment methods

"Mobile number required": EcoCash payments need mobile number

"Transaction expired": Initiate new payment (24h expiry)
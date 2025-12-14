Overview
This module provides a comprehensive customer relationship management (CRM) system for tracking, segmenting, and managing customer interactions. It includes customer profiles, segmentation, request management, and bulk operations with sample data for immediate use.

🚀 Quick Start
Prerequisites
Python 3.9+

PostgreSQL database

FastAPI application with database connection

Installation
Add the customer module to your project

Ensure database migrations are run for the customer models

Import and include the customer router in your main FastAPI app

📁 Project Structure
text
modules/customers/
├── models.py           # Database models (Customer, CustomerSegment, etc.)
├── schemas.py          # Pydantic schemas for validation
├── api.py              # FastAPI endpoints and business logic
└── README.md           # This documentation
🔧 Core Components
1. Database Models
Customer
Main customer entity with comprehensive profile tracking:

Personal Information: Name, email, phone, demographics

Address Details: Complete address information

Customer Profile: Type, status, loyalty points

Activity Tracking: Creation, updates, last activity

CustomerSegment
Dynamic customer grouping for targeted marketing:

Smart Segments: Pre-defined segments for common use cases

Manual Segments: Custom segments with specific criteria

Metrics: Customer count, percentage, activity tracking

CustomerRequest
Customer support and service request tracking:

Request Management: Track customer inquiries and issues

Priority System: High, medium, low priority levels

Status Tracking: Pending, in-progress, completed

CustomerSegmentMembership
Many-to-many relationship between customers and segments

2. Sample Segments
The module includes 24 pre-defined customer segments that are automatically created on startup:

Segment Type	Example Segments
Purchase Behavior	Customers who have purchased at least once, Repeat purchasers, Discount seekers
Engagement	Email subscribers, Product reviewers, Social media followers
Cart Behavior	Abandoned checkouts, Recently browsed
Loyalty	VIP Customers, Subscription members
Value	High-value customers (Top 10%)
Acquisition	New customers, Customer referral sources
Retention	At-risk customers
Geographic	International customers
Device/Time	Mobile shoppers, Weekend shoppers
Product Preference	Premium product buyers, Multi-category shoppers
📱 API Endpoints
Customer CRUD Operations
GET /api/customers/ - List customers with pagination and filtering

GET /api/customers/{customer_id} - Get specific customer

POST /api/customers/ - Create new customer

PUT /api/customers/{customer_id} - Update customer

DELETE /api/customers/{customer_id} - Delete customer

Bulk Customer Operations
POST /api/customers/bulk - Create multiple customers

POST /api/customers/bulk-upload - Upload customers via CSV

Customer Segments
GET /api/customers/segments/ - List segments with filtering

GET /api/customers/segments/{segment_id} - Get specific segment

POST /api/customers/segments/ - Create new segment

PUT /api/customers/segments/{segment_id} - Update segment

DELETE /api/customers/segments/{segment_id} - Delete segment

POST /api/customers/segments/{segment_id}/add-customers - Add customers to segment

Customer Requests
GET /api/customers/{customer_id}/requests - Get customer requests

POST /api/customers/{customer_id}/requests - Create customer request

🔄 Customer Management Flow
1. Customer Creation
python
POST /api/customers/
{
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "phone": "+1234567890",
    "customer_type": "regular",
    "status": "active"
}
2. Bulk Import via CSV
csv
first_name,last_name,email,phone,customer_type,status
John,Doe,john@example.com,+1234567890,regular,active
Jane,Smith,jane@example.com,+1987654320,vip,active
3. Segment Assignment
python
POST /api/customers/segments/{segment_id}/add-customers
{
    "memberships": [
        {"customer_id": "uuid1"},
        {"customer_id": "uuid2"}
    ]
}
4. Request Management
python
POST /api/customers/{customer_id}/requests
{
    "title": "Product Inquiry",
    "description": "Looking for product availability",
    "category": "product",
    "priority": "medium"
}
💡 Key Features
1. Smart Segmentation
Automatic Categorization: 24 pre-defined segments

Dynamic Updates: Segment counts update automatically

Flexible Criteria: Custom segments with configurable rules

Real-time Updates: Customer activity triggers segment updates

2. Comprehensive Customer Profiles
Complete Demographics: Personal and contact information

Address Management: Multiple address support

Activity History: Creation, updates, and last activity

Loyalty Tracking: Points system for rewards

3. Bulk Operations
CSV Import: Standardized customer import

Batch Processing: Efficient bulk creation

Error Handling: Detailed error reporting for failed imports

Validation: Comprehensive data validation

4. Request Tracking
Ticket System: Customer inquiry management

Priority Levels: High, medium, low prioritization

Status Tracking: Full lifecycle management

Customer Context: Requests linked to customer profiles

🔒 Security & Validation
Data Validation
python
# Email validation
email: EmailStr = Field(...)

# Phone validation (optional pattern)
phone: Optional[str] = Field(pattern=r'^\+?[1-9]\d{1,14}$')

# Required fields validation
first_name: str = Field(min_length=1, max_length=100)
last_name: str = Field(min_length=1, max_length=100)
Unique Constraints
Email: Unique across all customers

Segment Names: Unique segment identifiers

Customer ID: UUID primary keys

Access Control
API Authentication: Token-based authentication

Data Ownership: Customer data access controls

Audit Logging: Track all customer modifications

🗄️ Database Schema
Key Relationships
text
Customer 1───* CustomerRequest
   │
   └───* CustomerSegmentMembership *─── CustomerSegment
Indexes for Performance
customers(email) - Fast email lookups

customers(status, customer_type) - Filtering optimization

customer_segments(name, type) - Segment search

customer_requests(customer_id, status) - Request management

Data Types
UUID: All primary keys

String: Customer names, emails, addresses

Date/DateTime: Birthdays, timestamps

JSON/Text: Notes, criteria descriptions

Integer: Loyalty points, counts

🐛 Common Issues & Solutions
1. Customer Creation Issues
Duplicate Email: Check existing customers before creation

Invalid Data: Validate all input fields

Missing Required Fields: Ensure first_name, last_name, email are provided

Database Constraints: Check foreign key relationships

2. Bulk Import Issues
CSV Format: Ensure proper header row

Large Files: Implement pagination for large imports

Data Types: Validate date formats and phone numbers

Error Recovery: Continue processing after errors

3. Segment Management Issues
Empty Segments: Initialize with sample data on startup

Count Mismatches: Recalculate segment counts periodically

Criteria Updates: Handle segment criteria changes

Performance: Index segment membership tables

4. Debug Tools
python
# Check startup initialization
@customer_router.on_event("startup")
async def startup_event():
    # Initializes sample segments
    
# Verify segment creation
GET /api/customers/segments/

# Test customer creation
POST /api/customers/ with sample data
📈 Monitoring & Analytics
Key Metrics
Customer Growth: New customers per period

Segment Distribution: Customer distribution across segments

Request Volume: Support request trends

Activity Rates: Customer engagement metrics

Import Success: Bulk operation success rates

Logging Strategy
python
# Info: Customer lifecycle
logger.info(f"Created customer {customer_id}")

# Warning: Data issues
logger.warning(f"Duplicate email attempt: {email}")

# Error: System failures
logger.error(f"Bulk import failed: {error}")

# Debug: Detailed processing
logger.debug(f"Segment update for {customer_count} customers")
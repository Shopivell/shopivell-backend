Overview
This module provides seamless integration with Facebook Pages for social media management. It allows users to connect their Facebook Pages, schedule posts, and manage social content directly from the e-commerce platform.

🚀 Quick Start
Prerequisites
Python 3.9+

PostgreSQL database

Facebook Developer Account

Facebook App with Pages API permissions

User authentication system

Installation
Install dependencies:

bash
pip install fastapi sqlalchemy psycopg2-binary requests python-multipart
Configure Facebook App:

env
FACEBOOK_APP_ID=your_facebook_app_id
FACEBOOK_APP_SECRET=your_facebook_app_secret
FACEBOOK_REDIRECT_URI=http://localhost:8000/api/social/facebook/callback
FACEBOOK_API_VERSION=v24.0
📁 Project Structure
text
modules/social/
├── models.py           # Database models (FacebookPageConnection, SocialPost)
├── schemas.py          # Pydantic schemas
├── api.py              # FastAPI endpoints
└── README.md           # This documentation
🔧 Core Components
1. Database Models
FacebookPageConnection
Stores Facebook Page OAuth connections:

Facebook Page ID: Unique Facebook Page identifier

Page Token: Access token for Page API calls

User Mapping: Links Facebook user to Shopivell user

Permission Tracking: Granted permissions and token validity

SocialPost
Manages social media posts:

Content: Message, media, links

Scheduling: Post scheduling capabilities

Platform Support: Facebook (expandable to other platforms)

Post Tracking: Facebook post IDs and statuses

2. OAuth Flow Overview
Initiation: User clicks "Connect Facebook Page"

Facebook Login: Redirect to Facebook OAuth

Permission Grant: User grants page access permissions

Callback: Exchange code for access token

Page Listing: Fetch user's Facebook Pages

Connection Storage: Save page tokens to database

📱 API Endpoints
Facebook OAuth & Connection
GET /api/social/facebook/debug - Check Facebook configuration

GET /api/social/facebook/oauth-url - Generate OAuth URL

POST /api/social/facebook/callback - Handle OAuth callback

POST /api/social/facebook/connect-page - Store page connection

GET /api/social/facebook/connections - Get user's connections

DELETE /api/social/facebook/connections/{id} - Disconnect page

Social Post Management
POST /api/social/posts - Create new post

GET /api/social/posts - Get user's posts

POST /api/social/posts/{id}/publish - Publish post

DELETE /api/social/posts/{id} - Delete post

POST /api/social/posts/{id}/schedule - Schedule post

🔄 Facebook Integration Flow
1. App Configuration
Create Facebook App with these settings:

App Type: Business

Added Products: Facebook Login, Pages API

OAuth Settings:

Valid OAuth Redirect URIs: http://localhost:8000/api/social/facebook/callback

App Domains: localhost

2. Required Permissions
python
scopes = [
    "pages_show_list",        # See user's Pages
    "pages_manage_posts",     # Create and manage posts
    "public_profile",         # Basic profile info
    "business_management"     # Business features
]
3. Token Management
Short-lived Token: 1-2 hours (initial)

Long-lived Token: 60 days (after exchange)

Page Token: Permanent (until user revokes)

💡 Step-by-Step Integration
Step 1: Generate OAuth URL
python
GET /api/social/facebook/oauth-url?user_id=uuid
Returns redirect URL for Facebook OAuth.

Step 2: User Redirect & Login
Frontend redirects user to Facebook:

javascript
// Redirect user to Facebook
window.location.href = response.auth_url;
Step 3: Handle Callback
Facebook redirects back with code:

python
POST /api/social/facebook/callback
{
    "code": "AQB...",
    "state": "user_uuid"
}
Step 4: Fetch User's Pages
System exchanges code for token and fetches pages:

python
# Internal flow:
1. Exchange code → User access token
2. Get long-lived token (optional)
3. Fetch /me/accounts → List of Pages
4. Return pages to frontend
Step 5: Connect Specific Page
User selects which Page to connect:

python
POST /api/social/facebook/connect-page
{
    "shopivell_user_id": "uuid",
    "store_id": "uuid",
    "facebook_page_id": "123456789",
    "facebook_page_name": "My Business",
    "facebook_page_token": "EAAG...",
    "facebook_user_id": "987654321",
    "granted_permissions": ["pages_show_list", "pages_manage_posts"]
}
📤 Posting to Facebook
1. Create Post
python
POST /api/social/posts
{
    "message": "Check out our new product!",
    "media_url": "https://example.com/image.jpg",
    "media_type": "image",
    "link": "https://myshop.com/product",
    "page_connection_id": "uuid",
    "scheduled_for": "2024-01-25T14:30:00Z"
}
2. Publish Immediately
python
POST /api/social/posts/{post_id}/publish
3. Schedule for Later
python
POST /api/social/posts/{post_id}/schedule
{
    "scheduled_for": "2024-01-25T14:30:00Z"
}
🔒 Security & Permissions
Token Security
Never log tokens in production

Store encrypted in database

Validate token expiry before use

Handle token refresh automatically

Permission Management
Least privilege: Request only needed permissions

User consent: Clear explanation of permissions

Revocation handling: Detect and handle revoked permissions

Re-authentication: Guide users through reconnection

Data Privacy
User data: Store only necessary identifiers

Post content: Encrypt sensitive content

Access control: Users can only access their own data

Audit logs: Track all API calls and changes

🗄️ Database Schema
Key Relationships
text
User 1───* FacebookPageConnection
   │           │
   │           └───* SocialPost
   │
   └───* SocialPost (direct)
Indexes for Performance
facebook_page_connections(shopivell_user_id, status) - User connections

facebook_page_connections(facebook_page_id) - Page lookups

social_posts(page_connection_id, status) - Post management

social_posts(scheduled_for, status) - Scheduling queries

🐛 Common Issues & Solutions
1. OAuth Errors
Invalid redirect URI: Verify exact match in Facebook App settings

Missing permissions: Check requested scopes in OAuth URL

App not approved: Submit for review in Facebook Developer Portal

User declined: Handle gracefully with retry option

2. Token Issues
Expired token: Implement token refresh flow

Invalid token: Check token format and permissions

Page token missing: Ensure proper token exchange flow

Permission revoked: Detect and prompt for reconnection

3. API Errors
Rate limiting: Implement exponential backoff

Invalid parameters: Validate before API call

Network errors: Implement retry logic

Facebook downtime: Monitor Facebook API status

4. Debug Tools
Use the debug endpoint:

python
GET /api/social/facebook/debug
Returns configuration status for troubleshooting.

📈 Monitoring & Analytics
Key Metrics
Connection success rate

Post publication success rate

Average post engagement

Token refresh success rate

API error rates by endpoint

Logging Strategy
python
# Info: Business flows
logger.info(f"User {user_id} connected Facebook page {page_id}")

# Warning: Non-critical issues
logger.warning(f"Token near expiry for page {page_id}")

# Error: Critical failures
logger.error(f"Failed to publish post {post_id}: {error}")

# Debug: Detailed tracing (development only)
logger.debug(f"OAuth params: {params}")
Health Checks
Token validity: Check stored tokens are still valid

API connectivity: Test Facebook API connection

Scheduled posts: Verify scheduled posts will execute

Database integrity: Validate data consistency

🚀 Production Checklist
Facebook App in Live mode

Business Verification completed

Privacy Policy URL configured

App Review completed for permissions

SSL certificates configured

Token encryption implemented

Rate limiting configured

Error monitoring set up

Backup strategy for scheduled posts

User documentation created

📚 Integration Examples
Frontend Integration
javascript
// 1. Initiate Facebook connection
const connectFacebook = async (userId) => {
    const response = await fetch(`/api/social/facebook/oauth-url?user_id=${userId}`);
    const data = await response.json();
    
    // Redirect to Facebook
    window.location.href = data.auth_url;
};

// 2. Handle callback (in callback page)
const handleCallback = async () => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    
    const response = await fetch('/api/social/facebook/callback', {
        method: 'POST',
        body: JSON.stringify({ code })
    });
    
    const pages = await response.json();
    // Show pages to user for selection
    return pages;
};

// 3. Connect selected page
const connectPage = async (pageData) => {
    const response = await fetch('/api/social/facebook/connect-page', {
        method: 'POST',
        body: JSON.stringify(pageData)
    });
    return await response.json();
};
Scheduled Posts
python
# Background task for scheduled posts
async def process_scheduled_posts():
    posts = db.query(SocialPost).filter(
        SocialPost.status == "scheduled",
        SocialPost.scheduled_for <= datetime.utcnow()
    ).all()
    
    for post in posts:
        try:
            # Get page token
            connection = post.page_connection
            page_token = connection.facebook_page_token
            
            # Post to Facebook
            result = post_to_facebook(
                page_id=connection.facebook_page_id,
                token=page_token,
                message=post.message,
                media_url=post.media_url
            )
            
            # Update post status
            post.status = "published"
            post.facebook_post_id = result["id"]
            post.posted_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to publish post {post.id}: {str(e)}")
            post.status = "failed"
            db.commit()
🔄 Workflow Examples
New Page Connection
User clicks "Connect Facebook Page"

System generates OAuth URL with user ID

User logs into Facebook and grants permissions

System fetches user's Pages

User selects which Page to connect

System stores Page token and connection details

Page is now available for posting

Creating a Post
User creates post with content

Optionally schedules for future

System validates content and scheduling

For immediate posts: Publishes to Facebook

For scheduled posts: Stores for later processing

User can view post status and engagement

Token Refresh Flow
System detects token near expiry (45 days)

Notifies user to re-authenticate

User initiates reconnection flow

System obtains new long-lived token

Updates stored token and expiry

Continues normal operation

📄 Facebook Platform Policies
Compliance Requirements
Data Use: Only use data as permitted

User Consent: Clear permission requests

Privacy: Respect user privacy settings

Content: No spam or prohibited content

Best Practices
Clear labeling: Identify your app clearly

Error handling: Graceful degradation

User control: Easy disconnect option

Testing: Thorough testing before launch

Review Process
Business Verification: Required for Pages API

App Review: Submit for permission approval

Continued compliance: Regular policy adherence

🆘 Support & Troubleshooting
Common Error Messages
"Invalid OAuth redirect URI": Check exact match in Facebook settings

"Missing permissions": Verify scopes in OAuth URL

"Token expired": Implement refresh flow

"Page not found": Verify page ID and user permissions
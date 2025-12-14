# Facebook Business Integration Module – Developer Documentation

## Overview

The **Facebook Business Integration Module** provides a comprehensive system for connecting, managing, and interacting with **Facebook Business Accounts** and **Facebook Pages**. It handles OAuth authentication, page management, content posting, and analytics retrieval using the **Facebook Graph API**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│          Facebook Business Integration Module                │
├──────────────┬────────────────┬─────────────────┬───────────┤
│   OAuth      │   Business     │     Page        │  Graph    │
│   Flow       │   Accounts     │   Management    │   API     │
├──────────────┴────────────────┴─────────────────┴───────────┤
│                  Facebook Graph API                          │
│                   (v18.0 – v19.0+)                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Models

### 1. FacebookBusinessAccount

Stores Facebook Business Account connections.

**Fields:**

* `id` – UUID primary key
* `business_account_id` – Facebook Business Account ID (unique)
* `business_name` – Display name
* `access_token` – Long-lived access token (≈60 days)
* `user_id` – Facebook user ID
* `expires_at` – Token expiration timestamp
* `is_connected` / `is_active` – Status flags
* `created_at` / `updated_at` – Timestamps

**Relationships:**

* `pages` – One-to-many with `FacebookPage`
* `whatsapp_accounts` – One-to-many with WhatsApp accounts

---

### 2. FacebookPage

Stores connected Facebook Pages.

**Fields:**

* `id` – UUID primary key
* `business_account_id` – Foreign key to `FacebookBusinessAccount`
* `page_id` – Facebook Page ID
* `page_name` – Page display name
* `page_access_token` – Page-specific token
* `category` / `category_list` – Page categorization
* `about` – Page description
* `cover_photo_url` / `profile_picture_url` – Media URLs
* `website`, `phone`, `email`, `location` – Contact info
* `tasks` – Granted permissions
* `is_connected` / `is_active` – Status flags
* `last_synced_at` – Last sync timestamp
* `created_at` / `updated_at` – Timestamps

---

## API Endpoints

**Base URL:** `/api/business`

---

## OAuth Authentication Flow

### 1. POST `/facebook/oauth-url`

Generate OAuth URL for Facebook Business connection.

**Request Body – FacebookOAuthUrlRequest**

```json
{
  "redirect_uri": "https://yourapp.com/callback"
}
```

**Response**

```json
{
  "auth_url": "https://www.facebook.com/v18.0/dialog/oauth?client_id=...",
  "state": "unique-state-value"
}
```

**Frontend Flow:**

1. Request OAuth URL
2. Redirect user to Facebook
3. User authenticates
4. Facebook redirects with `code`
5. Exchange `code` via callback endpoint

---

### 2. POST `/facebook/callback`

OAuth callback endpoint to exchange authorization code.

**Request Body – FacebookCallbackRequest**

```json
{
  "code": "AQB...",
  "state": "unique-state-value",
  "redirect_uri": "https://yourapp.com/callback"
}
```

**Response – FacebookOAuthResponse**

```json
{
  "success": true,
  "message": "Successfully connected 3 Facebook pages",
  "business_account_id": "uuid-here",
  "pages": []
}
```

---

### 3. POST `/connect`

Directly connect using an existing access token.

**Request Body – FacebookOAuthRequest**

```json
{
  "access_token": "user-access-token-here"
}
```

---

## Business Account Management

### GET `/accounts`

List all connected business accounts.

**Query Parameters:**

* `skip` – Offset (default: 0)
* `limit` – Max records (default: 100, max: 1000)

---

### GET `/accounts/{account_id}`

Retrieve a specific business account.

---

### DELETE `/accounts/{account_id}`

Disconnect a business account and its pages.

---

## Page Management

### GET `/pages`

List connected Facebook pages.

**Query Parameters:**

* `skip`
* `limit`
* `business_account_id`

---

### GET `/pages/{page_id}`

Retrieve page details.

---

### DELETE `/pages/{page_id}`

Disconnect a single page.

---

### POST `/pages/{page_id}/sync`

Sync page data from Facebook Graph API.

---

## Content Management

### POST `/pages/{page_id}/post`

Publish or schedule content to a Facebook page.

**Request Body – FacebookPostCreate**

```json
{
  "message": "Hello Facebook!",
  "link": "https://example.com",
  "published": true,
  "scheduled_publish_time": "2024-12-25T10:00:00Z"
}
```

**Response – FacebookPostResponse**

```json
{
  "success": true,
  "message": "Content posted to Facebook page successfully",
  "post_id": "123456789012345",
  "post_url": "https://facebook.com/123456789012345"
}
```

---

## Analytics & Insights

### GET `/pages/{page_id}/posts`

Retrieve recent page posts.

**Query Parameters:**

* `limit` – Default: 25 (max: 100)

---

### GET `/posts/{post_id}/analytics`

Retrieve analytics for a specific post.

**Query Parameters:**

* `page_id` – Page UUID

---

### GET `/pages/{page_id}/analytics`

Retrieve overall page analytics.

**Query Parameters:**

* `since` – Start date (YYYY-MM-DD)
* `until` – End date (YYYY-MM-DD)

---

## Pydantic Schemas

### Core Models

**FacebookBusinessAccountBase**

```python
business_account_id: str
business_name: str
user_id: str
is_connected: bool = True
is_active: bool = True
```

**FacebookPageBase**

```python
page_id: str
page_name: str
category: Optional[str]
is_connected: bool = True
is_active: bool = True
```

---

### OAuth Schemas

```python
class FacebookOAuthUrlRequest(BaseModel):
    redirect_uri: Optional[str]

class FacebookCallbackRequest(BaseModel):
    code: str
    state: Optional[str]
    redirect_uri: Optional[str]
```

---

### Content & Analytics Schemas

```python
class FacebookPostCreate(BaseModel):
    message: str
    link: Optional[str]
    published: bool = True
    scheduled_publish_time: Optional[datetime]
```

---

## Helper Functions

### Token Management

* `exchange_short_lived_token_for_long_lived(token)`
* `get_facebook_user_info(access_token)`

### API Interactions

* `get_facebook_business_accounts(access_token)`
* `get_facebook_pages(access_token, business_account_id)`
* `post_to_facebook_page(page_id, token, post_data)`
* `get_facebook_page_posts(page_id, token, limit)`
* `get_facebook_post_insights(post_id, token)`

---

## Configuration

### Environment Variables

```bash
FACEBOOK_APP_ID=your_app_id
FACEBOOK_APP_SECRET=your_app_secret
FACEBOOK_BUSINESS_REDIRECT_URI=http://localhost:8000/api/business/facebook/callback
FB_GRAPH_API_BASE=https://graph.facebook.com/v18.0
```

---

## OAuth Scopes

The module requests the following permissions:

* `public_profile`
* `pages_show_list`
* `pages_read_engagement`
* `pages_manage_posts`
* `business_management`
* `ads_management` / `ads_read` (optional)
* `whatsapp_business_*`

---

## Security Considerations

* Secure storage of access tokens
* Encrypt tokens at rest
* Regular token rotation
* Least-privilege OAuth scopes
* Audit logging for API access

---

## Extensibility

### Adding New Facebook Features

* Extend Graph API handlers
* Add new analytics endpoints
* Support additional permissions

### WhatsApp Integration

* Link WhatsApp Business accounts
* Enable message sending via Graph API
* Reuse token lifecycle management

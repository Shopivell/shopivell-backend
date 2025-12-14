# Automation Module – Developer Documentation

## Overview

The **Automation Module** provides a comprehensive system for managing social media automation, workflow orchestration, error logging, and message sending. It integrates with external automation tools (such as **n8n**) and exposes a robust API for managing automated workflows across multiple social media and messaging platforms.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Automation Module                         │
├──────────────┬────────────────┬─────────────────┬───────────┤
│ Social Media │    Workflow    │      Error      │  Message  │
│ Automation   │    Logging     │    Tracking     │  Sending  │
├──────────────┴────────────────┴─────────────────┴───────────┤
│                      Database Layer                          │
│                (PostgreSQL + SQLAlchemy)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Models

### 1. SocialMediaConfig

Stores configuration for different social media platforms.

**Fields:**

* `id` – Integer primary key
* `business_id` – Foreign key to businesses
* `platform` – Platform name (`facebook`, `instagram`, `twitter`)
* `enabled` – Whether platform is active
* `page_id` / `account_id` – Platform-specific identifiers
* `access_token` – OAuth access token
* `api_key` / `api_secret` – API credentials
* `auto_post` – Enable automatic posting
* `posting_schedule` – JSON schedule configuration
* `created_at` / `updated_at` – Timestamps

---

### 2. SocialPost

Manages social media posts across platforms.

**Fields:**

* `id` – Integer primary key
* `business_id` – Foreign key to businesses
* `caption` – Post caption or text
* `hashtags` – JSON array of hashtags
* `cta` – Call-to-action text
* `image_url` – Media/image URL
* `platforms` – JSON results from posting to platforms
* `status` – `draft`, `approved`, `published`, `rejected`
* `approved_at` / `published_at` – Status timestamps
* `created_at` – Creation timestamp

---

### 3. WorkflowLog

Logs workflow execution details.

**Fields:**

* `id` – Integer primary key
* `business_id` – Foreign key to businesses
* `workflow_id` – Unique workflow identifier
* `execution_id` – Unique execution identifier
* `status` – `success`, `failed`, `rejected`
* `success_count` / `failure_count` – Result counts
* `message` – Execution message
* `started_at` / `completed_at` – Execution timestamps

---

### 4. ErrorLog

Tracks errors from workflow execution.

**Fields:**

* `id` – Integer primary key
* `business_id` – Foreign key to businesses
* `workflow_id` / `execution_id` – Workflow references
* `error_type` – Error category
* `error_message` – Error description
* `stack_trace` – Detailed error trace
* `request_data` – JSON context data
* `created_at` – Error timestamp

---

## API Endpoints

**Base URL:** `/api/automation`

---

## Core Business Operations

### POST `/business/send-message`

Send messages through external platforms.

**Status Code:** `202 Accepted`

**Request Body – MessageSend**

```json
{
  "message_body": "Hello, this is an automated message!",
  "recipient": "+1234567890",
  "platform": "whatsapp"
}
```

**Response – MessageSendResponse**

```json
{
  "success": true,
  "message": "Message successfully scheduled for whatsapp."
}
```

---

## Webhook Integration

### POST `/webhook/social-automation`

Trigger social media automation workflows.

**Request Body – WebhookResponse**

```json
{
  "businessId": 123,
  "trigger": "social_automation"
}
```

**Response**

```json
{
  "success": true,
  "message": "Social automation triggered successfully",
  "business_id": 123,
  "workflow_log_id": 456
}
```

---

## Business Logic Functions

### Database Operations

* `get_business(db, business_id)` – Retrieve a business by ID
* `get_business_social_config(db, business_id)` – Retrieve full social config

```python
{
  "business": BusinessObject,
  "social_media": {
    "facebook": SocialMediaConfigObject,
    "instagram": SocialMediaConfigObject
  }
}
```

* `create_social_post(db, post_data)` – Save social post
* `get_social_posts(db, business_id, skip, limit)` – Paginated posts
* `create_workflow_log(db, log_data)` – Log workflow start
* `update_workflow_log_completion(db, log_id, status, message)` – Log completion
* `create_error_log(db, error_data)` – Log errors

---

## External Integration

### send_message_externally

```python
{
  "success": true,
  "message": "Status message",
  "task_id": "external_service_id"
}
```

**Parameters:**

* `recipient`
* `message_body`
* `platform` (`whatsapp`, `sms`, `email`, etc.)

---

## Pydantic Schemas

### Social Media Schemas

**SocialPostBase**

```python
caption: str
hashtags: List[str]
cta: str
image_url: str
platforms: List[PlatformResult]
```

**SocialPostCreate**

```python
business_id: int
```

**SocialPost**

```python
id: int
status: str
created_at: datetime
approved_at: Optional[datetime]
published_at: Optional[datetime]
```

**PlatformResult**

```python
platform: str
success: bool
post_id: Optional[str]
error: Optional[str]
```

---

### Workflow Schemas

```python
workflow_id: str
execution_id: str
status: str
success_count: int
failure_count: int
message: Optional[str]
```

---

### Error Schemas

```python
error_type: str
error_message: str
stack_trace: Optional[str]
request_data: Optional[Dict[str, Any]]
```

---


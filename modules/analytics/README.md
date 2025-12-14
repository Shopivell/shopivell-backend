# Analytics Module – Developer Documentation

## Overview

The **Analytics Module** is a comprehensive system for managing, ingesting, and analyzing data from various analytics platforms. It provides a unified interface for handling:

* Web analytics
* Social media data
* Advertising metrics
* E-commerce analytics

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Analytics Module                          │
├──────────────┬────────────────┬─────────────────┬───────────┤
│  Platforms   │     Data       │    Reports      │   Views   │
│  Management  │   Ingestion    │    System       │  Tracking │
├──────────────┴────────────────┴─────────────────┴───────────┤
│                      Database Layer                          │
│                (PostgreSQL + SQLAlchemy)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Models

### 1. AnalyticsPlatform

Stores configuration for different analytics platforms.

**Fields:**

* `id` – UUID primary key
* `name` – Platform name (Google Analytics, Facebook, etc.)
* `platform_type` – `web_analytics`, `social_media`, `advertising`, `ecommerce`
* `api_config` – JSON configuration for API connections
* `is_active` – Whether platform is active
* `last_sync` – Last successful data sync timestamp
* `sync_status` – Current sync status
* `created_at` / `updated_at` – Timestamps

---

### 2. PlatformData

Stores actual metrics and dimensions from platforms.

**Fields:**

* `id` – UUID primary key
* `platform_id` – Foreign key to `AnalyticsPlatform`
* `data_type` – Type of data (sessions, conversions, etc.)
* `date` – Date of the data
* `metrics` – JSON object containing metric values
* `dimensions` – JSON object containing dimension values

---

### 3. AnalyticsReport

Manages analytical reports and explorations.

**Fields:**

* `id` – UUID primary key
* `name` – Report name
* `category` – Report category (Acquisition, Behavior, etc.)
* `report_type` – `standard`, `custom`, or `exploration`
* `data_source` – Source of data
* `configuration` – JSON configuration for report filters
* `has_info` – Whether report has additional info
* `is_active` / `is_favorite` – Status flags

---

### 4. ReportView

Tracks report views for usage analytics.

**Fields:**

* `id` – UUID primary key
* `report_id` – Foreign key to `AnalyticsReport`
* `viewed_at` – View timestamp
* `viewed_by` – User who viewed the report

---

### 5. DataSyncLog

Logs data synchronization activities.

**Fields:**

* `id` – UUID primary key
* `platform_id` – Foreign key to `AnalyticsPlatform`
* `sync_type` – `full`, `incremental`, `realtime`
* `status` – Success / failed
* `records_processed` – Number of records synced
* `error_message` – Error details if sync failed

---

## API Endpoints

**Base URL:** `/api/analytics`

---

## Platform Management

### 1. GET `/platforms`

Retrieve all analytics platforms with pagination.

**Query Parameters:**

* `skip` – Number of records to skip (default: `0`)
* `limit` – Maximum records to return (default: `20`, max: `100`)
* `is_active` – Filter by active status

**Response:** `PlatformListResponse`

---

### 2. POST `/platforms`

Create a new analytics platform.

**Request Body:** `PlatformCreate`

```json
{
  "name": "Google Analytics",
  "platform_type": "web_analytics",
  "api_config": {
    "api_key": "your-api-key",
    "property_id": "UA-XXXXXX"
  }
}
```

---

### 3. PATCH `/platforms/{platform_id}/activate`

Activate a platform for data ingestion.

---

## Data Ingestion

### 1. POST `/data/ingest`

Ingest data from external platforms.

**Headers:**

* `Authorization` – API key for authentication

**Request Body:** `DataIngestionRequest`

```json
{
  "platform": "google_analytics",
  "data_type": "sessions",
  "date": "2024-01-15",
  "metrics": {
    "sessions": 1500,
    "users": 1200,
    "pageviews": 4500
  },
  "dimensions": {
    "device_category": "mobile",
    "country": "US"
  }
}
```

---

### 2. POST `/data/ingest/bulk`

Bulk ingest multiple data points.

**Request Body:** `BulkDataIngestionRequest`

```json
{
  "platform": "facebook",
  "data": [
    {
      "data_type": "impressions",
      "date": "2024-01-15",
      "metrics": {"impressions": 10000},
      "dimensions": {"campaign": "winter_sale"}
    }
  ]
}
```

---

## Report Management

### 1. GET `/reports`

Retrieve all reports with advanced filtering.

**Query Parameters:**

* `search` – Search by report name
* `category` – Filter by category
* `created_by` – Filter by creator
* `data_source` – Filter by data source
* `is_favorite` – Filter favorite reports
* `is_active` – Filter active reports
* `skip` / `limit` – Pagination

---

### 2. GET `/reports/{report_id}`

Retrieve a specific report by ID.

---

### 3. POST `/reports`

Create a new report.

**Request Body:** `ReportCreate`

```json
{
  "name": "Monthly Traffic Report",
  "category": "Acquisition",
  "description": "Monthly overview of website traffic",
  "configuration": {
    "date_range": "last_30_days",
    "metrics": ["sessions", "users"],
    "dimensions": ["source", "medium"]
  }
}
```

---

### 4. PUT `/reports/{report_id}`

Update an existing report.

**Request Body:** `ReportUpdate` (partial update supported)

---

### 5. DELETE `/reports/{report_id}`

Soft delete a report (sets `is_active` to `false`).

---

### 6. PATCH `/reports/{report_id}/favorite`

Toggle favorite status.

---

### 7. POST `/reports/{report_id}/view`

Record a report view for analytics.

---

## Explorations

### POST `/explorations`

Create an ad-hoc exploration report.

**Request Body:** `ExplorationCreate`

```json
{
  "name": "User Behavior Analysis",
  "description": "Exploring user session patterns",
  "category": "Behavior",
  "metrics": ["session_duration", "pages_per_session"],
  "dimensions": ["device_type", "user_type"],
  "visualization_type": "bar",
  "date_range": {
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
  }
}
```

---

## Data Query

### GET `/data/platform/{platform_id}`

Retrieve data for a specific platform.

**Query Parameters:**

* `start_date` / `end_date` – Date range filter
* `data_type` – Filter by data type
* `skip` / `limit` – Pagination

---

## Sync Logs

### GET `/sync-logs`

Retrieve data synchronization logs.

**Query Parameters:**

* `platform_id` – Filter by platform
* `status` – Filter by sync status
* `skip` / `limit` – Pagination

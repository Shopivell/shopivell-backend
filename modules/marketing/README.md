# Meta Marketing API Module – Developer Documentation

## Overview

The **Meta Marketing API Module** provides comprehensive integration with Facebook/Meta's Advertising Platform (formerly Facebook Ads API). It enables creation, management, monitoring, and optimization of Meta ad campaigns, ad sets, ads, and creatives through a unified RESTful interface.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                   Meta Marketing API Module                  │
├──────────────┬────────────────┬─────────────────┬───────────┤
│  Campaign    │    Ad Sets     │      Ads        │ Creatives │
│  Management  │   Management   │   Management    │  Builder  │
├──────────────┴────────────────┴─────────────────┴───────────┤
│                    Insights & Analytics                      │
├─────────────────────────────────────────────────────────────┤
│                    Meta Graph API (v24.0)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Models

### 1. MetaAdAccount

Represents a Meta Ad Account connection.

**Fields**

* `id` (UUID, PK)
* `ad_account_id` (Meta ID, unique)
* `account_name`
* `account_status` (1=ACTIVE, 2=DISABLED)
* `currency`
* `timezone_name`
* `business_id`, `business_name`
* `access_token`
* `user_id`
* `expires_at`
* `business_account_id` (FK)
* `is_connected`, `is_active`
* `last_synced_at`

**Relationships**

* campaigns
* ad_sets
* ads
* ad_creatives
* automated_rules
* experiments

---

### 2. MetaCampaign

Represents an ad campaign.

**Fields**

* `id` (UUID, PK)
* `campaign_id` (Meta ID, unique)
* `ad_account_id` (FK)
* `name`
* `objective`
* `status`
* `special_ad_categories`
* `buying_type`
* `daily_budget`, `lifetime_budget`
* `start_time`, `stop_time`
* `bid_strategy`
* `created_time`, `updated_time`
* `effective_status`
* `is_active`

---

### 3. MetaAdSet

Represents an ad set (ad group).

**Fields**

* `id` (UUID, PK)
* `adset_id` (Meta ID, unique)
* `ad_account_id` (FK)
* `campaign_id` (FK)
* `name`
* `status`
* `targeting` (JSON)
* `optimization_goal`
* `billing_event`
* `daily_budget`, `lifetime_budget`
* `bid_amount`
* `bid_strategy`
* `start_time`, `end_time`
* `placement`, `publisher_platforms`

---

### 4. MetaAd

Represents an individual ad.

**Fields**

* `id` (UUID, PK)
* `ad_id` (Meta ID, unique)
* `ad_account_id` (FK)
* `campaign_id` (FK)
* `adset_id` (FK)
* `creative_id` (FK)
* `name`
* `status`
* `ad_format`
* `tracking_specs`

**Draft Support**

* `is_draft`
* `notes`
* `draft_data`
* `published_at`

---

### 5. MetaAdCreative

Represents ad creative assets.

**Fields**

* `id` (UUID, PK)
* `creative_id` (Meta ID, unique)
* `ad_account_id` (FK)
* `creative_type`
* `object_story_spec`
* `object_type`
* `link_data`, `image_data`, `video_data`
* `title`, `body`
* `call_to_action_type`
* `image_url`, `image_hash`
* `video_url`, `video_id`
* `url`

---

### 6. MetaExperiment

Represents A/B testing experiments.

**Fields**

* `id` (UUID, PK)
* `experiment_id` (Meta ID, unique)
* `ad_account_id` (FK)
* `name`
* `type`
* `status`
* `control_id`, `treatment_id`
* `confidence_level`, `confidence`
* `sample_size`
* `duration_days`
* `winner`
* `metric_results`
* `start_time`, `end_time`

---

### 7. MetaAutomatedRule

Represents automated optimization rules.

**Fields**

* `id` (UUID, PK)
* `rule_id` (Meta ID, unique)
* `ad_account_id` (FK)
* `name`
* `entity_type`
* `status`
* `conditions`
* `action`
* `schedule_type`
* `schedule_spec`
* `execution_count`
* `last_execution_time`
* `last_execution_result`

---

### 8. MetaAdInsight

Stores ad performance metrics.

**Fields**

* `id` (UUID, PK)
* `ad_id` (FK)
* `date`
* `impressions`, `clicks`
* `spend`
* `cpm`, `cpc`, `ctr`
* `frequency`, `reach`
* `conversions`
* `cost_per_conversion`, `conversion_rate`
* `likes`, `comments`, `shares`
* `raw_data`

---

## API Endpoints

### Base URL

```
/api/marketing
```

---

## Ad Account Management

### POST /business/{business_account_id}/sync-ad-accounts

Sync Meta ad accounts from a connected business account.

**Response**: `SuccessMessage`

---

### GET /ad-accounts

Retrieve all connected Meta ad accounts.

**Query Parameters**

* `skip` (default: 0)
* `limit` (default: 100, max: 1000)
* `business_account_id`

---

### GET /ad-accounts/{account_id}

Retrieve a specific ad account with statistics.

---

## Campaign Management

### POST /ad-accounts/{account_id}/campaigns

Create a new campaign.

```json
{
  "name": "Summer Sale Campaign",
  "objective": "OUTCOME_SALES",
  "status": "ACTIVE",
  "daily_budget": 5000,
  "lifetime_budget": 50000,
  "start_time": "2024-06-01T00:00:00Z",
  "special_ad_categories": ["NONE"]
}
```

---

### GET /campaigns

Retrieve campaigns with filters and statistics.

---

### PUT /campaigns/{campaign_id}

Update campaign details.

---

### POST /campaigns/{campaign_id}/sync

Sync campaign data from Meta.

---

## Ad Set Management

### POST /campaigns/{campaign_id}/adsets

Create a new ad set.

```json
{
  "name": "Age 25–34 Targeting",
  "status": "ACTIVE",
  "optimization_goal": "LINK_CLICKS",
  "billing_event": "IMPRESSIONS",
  "daily_budget": 1000,
  "bid_amount": 200,
  "targeting": {
    "age_min": 25,
    "age_max": 34,
    "locations": [{"country": "US"}]
  }
}
```

---

## Ad Creative Management

### POST /ad-accounts/{account_id}/creatives

Create a new ad creative.

**Features**

* Automatic image upload
* Multiple creative types
* CTA configuration

---

## Ad Management

### POST /adsets/{adset_id}/ads

Create an ad.

**Draft Support**

* Failed Meta API calls are saved as drafts
* Drafts can be published later

---

### POST /ads/{ad_id}/publish-draft

Publish a saved draft ad.

---

## Insights & Analytics

### POST /insights/sync

Sync insights for active ads.

---

### GET /ads/{ad_id}/insights

Retrieve insights for a specific ad.

---

### GET /campaigns/{campaign_id}/insights/summary

Retrieve campaign insights summary.

---

## Performance Dashboard

### GET /dashboard/performance

Retrieve performance dashboard data.

Includes:

* Summary metrics
* Daily trends
* Top campaigns

---

## Health Check

### GET /health

```json
{"status": "healthy", "service": "meta-marketing-api"}
```

---

## Configuration

### Environment Variables

```bash
FB_GRAPH_API_BASE=https://graph.facebook.com/v24.0
FACEBOOK_APP_ID=your_app_id
FACEBOOK_APP_SECRET=your_app_secret
DATABASE_URL=postgresql://user:password@localhost/marketing_db
```

---

## Security Considerations

* Secure OAuth token storage
* Token expiration monitoring
* Input validation via Pydantic
* Rate limiting and exponential backoff
* Encrypted sensitive data

---

## Performance Optimization

* Indexed database queries
* Cached campaign and insight data
* Background task processing
* Connection pooling

---

## Testing Strategy

* Unit tests with mocked Meta API
* Integration tests for full campaign flows
* Mocked Ads Library responses

---

## Deployment Considerations

* Horizontal scaling
* Redis caching
* Background job queues
* Monitoring & alerting

---

## Best Practices

* Start with small budgets
* Use A/B testing
* Monitor performance daily
* Follow Meta ad policies

---

## Support & Resources

* Meta Marketing API Documentation
* API changelog and error references
* Community support channels
* Regular module maintenance

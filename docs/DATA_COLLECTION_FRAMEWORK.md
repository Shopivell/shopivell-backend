# Data Collection Framework

> **Note (September 2026)**: The ad system has migrated to OpenClaw + Zernio.
> This data framework remains relevant - data is now collected via:
> - **Zernio API** for Meta Ads performance data
> - **OpenClaw optimizer plugin** for lead scoring and optimization signals
> - **Offline Conversions API** via `zernio-ads.send_offline_conversion()`

A comprehensive data collection framework covering what to collect, where to get it, and how to structure it for future modeling.

---

## Three Layers of Data

| Layer | Source | Purpose |
|-------|--------|---------|
| **Creative Metadata** | Internal (at creation time) | Know *what* was shown |
| **Ad Performance** | Meta Ads API | Know *how it performed* |
| **Business Outcome** | Store / CRM | Know *what it actually drove* |

---

## Layer 1: Creative Metadata (Collected at Ad Creation)

Data captured internally when each ad variation is generated and published.

### 1.1 Ad Identity

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `ad_id` | string | Internal unique ID | `uuid` |
| `meta_ad_id` | string | Meta platform ad ID | `23851234567890` |
| `meta_adset_id` | string | Meta ad set ID | `23851234567891` |
| `meta_campaign_id` | string | Meta campaign ID | `23851234567892` |
| `strategy_id` | string | FK to MicroStrategy | `uuid` |
| `phase_id` | string | FK to MicroStrategyPhase | `uuid` |
| `variation_index` | int | Variation number (1-5) | `3` |
| `naming_convention` | string | Structured name | `AV001_HEADLINE_V3_FOMO` |
| `store_id` | string | FK to store | `uuid` |
| `created_at` | datetime | When ad was created | `2026-03-01T12:00:00Z` |

### 1.2 Creative Content

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `headline` | string | Primary headline text | `"Transform Your Morning Routine"` |
| `body_text` | string | Ad body / primary text | `"Discover our premium..."` |
| `cta_type` | enum | Call-to-action button | `LEARN_MORE`, `SHOP_NOW`, `SIGN_UP` |
| `image_url` | string | Creative image URL | `https://...` |
| `video_url` | string | Creative video URL (if any) | `https://...` |
| `destination_url` | string | Landing page URL | `https://store.com/offer` |
| `display_link` | string | Visible URL text | `store.com` |

### 1.3 Creative Attributes (Tags)

These structured tags enable future pattern analysis and ML modeling.

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `emotion_tag` | string | Primary emotional appeal | `fomo`, `trust`, `curiosity`, `urgency`, `aspiration`, `relief` |
| `hook_type` | string | Opening hook category | `question`, `statistic`, `story`, `bold_claim`, `how_to`, `pain_point` |
| `visual_style` | string | Image/video style | `lifestyle`, `product_hero`, `testimonial`, `infographic`, `before_after`, `ugc`, `flat_lay` |
| `color_dominant` | string | Primary color in creative | `blue`, `red`, `green`, `warm`, `cool`, `neutral` |
| `has_face` | boolean | Contains human face | `true` / `false` |
| `has_text_overlay` | boolean | Text overlaid on image | `true` / `false` |
| `text_density` | enum | Amount of text on image | `none`, `low`, `medium`, `high` |
| `offer_type` | string | Type of offer/incentive | `percentage_off`, `free_trial`, `bundle`, `urgency`, `bonus`, `none` |
| `offer_value` | string | Specific offer value | `20%`, `7 days`, `Buy 2 Get 1` |
| `content_angle` | string | Messaging angle | `social_proof`, `scarcity`, `authority`, `benefit_focused`, `problem_solution` |
| `tone` | string | Writing tone | `professional`, `casual`, `playful`, `urgent`, `empathetic` |

### 1.4 Audience Targeting

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `audience_name` | string | Descriptive name | `"Young Parents 25-34"` |
| `audience_type` | enum | Targeting method | `interest`, `lookalike`, `custom`, `broad`, `retargeting` |
| `age_min` | int | Minimum age | `25` |
| `age_max` | int | Maximum age | `44` |
| `gender` | enum | Gender targeting | `all`, `male`, `female` |
| `geo_locations` | json | Countries/regions/cities | `{"countries": ["US"], "cities": [...]}` |
| `interests` | json | Interest targeting IDs + names | `[{"id": "123", "name": "Fitness"}]` |
| `behaviors` | json | Behavioral targeting | `[{"id": "456", "name": "Online shoppers"}]` |
| `custom_audience_id` | string | Custom audience reference | `23851234567893` |
| `lookalike_spec` | json | Lookalike config | `{"source_id": "...", "ratio": 0.02}` |
| `excluded_audiences` | json | Excluded custom audiences | `[{"id": "...", "name": "Existing customers"}]` |

### 1.5 Campaign Configuration

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `objective` | enum | Campaign objective | `OUTCOME_TRAFFIC`, `OUTCOME_LEADS`, `OUTCOME_SALES` |
| `optimization_goal` | string | What Meta optimizes for | `LINK_CLICKS`, `LEAD_GENERATION`, `OFFSITE_CONVERSIONS` |
| `bid_strategy` | enum | Bidding approach | `LOWEST_COST`, `COST_CAP`, `BID_CAP` |
| `daily_budget_cents` | int | Daily budget in cents | `200` ($2.00) |
| `lifetime_budget_cents` | int | Lifetime budget (if set) | `5000` ($50.00) |
| `placement` | json | Where ads show | `{"facebook_feed": true, "instagram_feed": true, "stories": true}` |
| `schedule_start` | datetime | When ad set starts | `2026-03-01T00:00:00Z` |
| `schedule_end` | datetime | When ad set ends (if set) | `2026-03-08T00:00:00Z` |

---

## Layer 2: Ad Performance (From Meta Ads API)

Data synced from Meta Ads Insights API on a regular interval (every 15 minutes for active campaigns, daily for completed).

### 2.1 Core Delivery Metrics

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `impressions` | int | `insights.impressions` | Total times ad was shown |
| `reach` | int | `insights.reach` | Unique people who saw the ad |
| `frequency` | float | `insights.frequency` | Average times each person saw ad |
| `spend` | float | `insights.spend` | Total amount spent (dollars) |
| `date_start` | date | `insights.date_start` | Reporting period start |
| `date_stop` | date | `insights.date_stop` | Reporting period end |

### 2.2 Engagement Metrics

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `clicks` | int | `insights.clicks` | All clicks (link + other) |
| `link_clicks` | int | `insights.actions[action_type=link_click]` | Clicks to destination |
| `ctr` | float | `insights.ctr` | Click-through rate (%) |
| `cpc` | float | `insights.cpc` | Cost per click |
| `unique_clicks` | int | `insights.unique_clicks` | Unique people who clicked |
| `unique_ctr` | float | `insights.unique_ctr` | Unique click-through rate |
| `post_engagement` | int | `insights.actions[action_type=post_engagement]` | Total post engagements |
| `post_reactions` | int | `insights.actions[action_type=post_reaction]` | Reactions (like, love, etc.) |
| `post_comments` | int | `insights.actions[action_type=comment]` | Comments on ad |
| `post_shares` | int | `insights.actions[action_type=post]` | Shares of ad |
| `video_views_3s` | int | `insights.actions[action_type=video_view]` | 3-second video views |
| `video_views_thruplay` | int | `insights.video_thruplay_actions` | Completed/15s+ video views |

### 2.3 Conversion Metrics

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `leads` | int | `insights.actions[action_type=lead]` | Lead form submissions |
| `purchases` | int | `insights.actions[action_type=purchase]` | Purchase conversions |
| `add_to_cart` | int | `insights.actions[action_type=omni_add_to_cart]` | Add-to-cart events |
| `initiate_checkout` | int | `insights.actions[action_type=omni_initiated_checkout]` | Checkout initiations |
| `view_content` | int | `insights.actions[action_type=omni_view_content]` | Content view events |
| `complete_registration` | int | `insights.actions[action_type=omni_complete_registration]` | Registration completions |
| `cost_per_lead` | float | `insights.cost_per_action_type[lead]` | Cost per lead |
| `cost_per_purchase` | float | `insights.cost_per_action_type[purchase]` | Cost per purchase |
| `purchase_value` | float | `insights.action_values[action_type=purchase]` | Total purchase revenue |
| `roas` | float | `insights.purchase_roas` | Return on ad spend |

### 2.4 Quality & Relevance Indicators

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `quality_ranking` | enum | `insights.quality_ranking` | `ABOVE_AVERAGE`, `AVERAGE`, `BELOW_AVERAGE_10`, etc. |
| `engagement_rate_ranking` | enum | `insights.engagement_rate_ranking` | Relative engagement quality |
| `conversion_rate_ranking` | enum | `insights.conversion_rate_ranking` | Relative conversion quality |
| `ad_delivery_status` | string | Ad object `effective_status` | `ACTIVE`, `PAUSED`, `ADSET_PAUSED`, etc. |
| `learning_phase_status` | string | Ad set `learning_phase_info` | `LEARNING`, `SUCCESS`, `LEARNING_LIMITED` |

### 2.5 Breakdown Dimensions (Optional, for deeper analysis)

Request these via `breakdowns` parameter on Insights API:

| Breakdown | Description | Use Case |
|-----------|-------------|----------|
| `age` | Age buckets | Which ages respond best |
| `gender` | Male/Female/Unknown | Gender performance split |
| `country` | Country code | Geographic performance |
| `region` | State/region | Regional patterns |
| `publisher_platform` | Facebook/Instagram/Audience Network | Platform comparison |
| `platform_position` | Feed/Stories/Reels/Right Column | Placement performance |
| `device_platform` | Mobile/Desktop | Device preference |
| `impression_device` | iPhone/Android/Desktop | Granular device data |
| `hourly_stats_aggregated_by_advertiser_time_zone` | Hour of day | Time-of-day patterns |

---

## Layer 3: Business Outcome (From Store / CRM)

Data collected from the store's own systems, linked back to ads via UTM parameters, pixel events, or lead IDs.

### 3.1 Lead Quality Data

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `lead_id` | string | CRM / Lead form | Unique lead identifier |
| `ad_id` | string | UTM / Meta lead data | Which ad generated the lead |
| `adset_id` | string | UTM / Meta lead data | Which ad set |
| `campaign_id` | string | UTM / Meta lead data | Which campaign |
| `lead_source` | string | UTM `utm_source` | Traffic source |
| `lead_medium` | string | UTM `utm_medium` | Traffic medium |
| `lead_campaign` | string | UTM `utm_campaign` | Campaign name |
| `submitted_at` | datetime | Form submission time | When lead was captured |
| `lead_status` | enum | CRM | `new`, `contacted`, `qualified`, `converted`, `disqualified`, `lost` |
| `lead_score` | float | CRM / ML model | Quality score (0-100) |
| `disqualification_reason` | string | CRM | Why lead was disqualified |
| `time_to_contact` | int | CRM | Minutes from submission to first contact |
| `time_to_qualify` | int | CRM | Minutes from submission to qualification |
| `time_to_convert` | int | CRM | Minutes from submission to conversion |

### 3.2 Revenue & Conversion Data

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `order_id` | string | Store | Purchase order ID |
| `order_value` | float | Store | Order total (dollars) |
| `order_items` | int | Store | Number of items |
| `product_categories` | json | Store | Categories purchased |
| `is_first_purchase` | boolean | Store | New vs returning customer |
| `customer_id` | string | Store | Customer identifier |
| `ltv_30d` | float | Store | 30-day lifetime value |
| `ltv_90d` | float | Store | 90-day lifetime value |
| `repeat_purchase_count` | int | Store | Repeat purchases in 90 days |
| `average_order_value` | float | Store | Customer AOV |
| `refund_amount` | float | Store | Refunds issued |
| `net_revenue` | float | Computed | Order value - refunds |

### 3.3 Customer Journey Events

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `event_type` | enum | Pixel / Store | `page_view`, `view_content`, `add_to_cart`, `initiate_checkout`, `purchase`, `lead` |
| `event_timestamp` | datetime | Pixel / Store | When event occurred |
| `event_value` | float | Pixel / Store | Monetary value (if any) |
| `page_url` | string | Pixel | Page where event fired |
| `referrer_url` | string | Pixel | Previous page |
| `session_id` | string | Pixel / Analytics | Session identifier |
| `device_type` | string | Pixel | `mobile`, `desktop`, `tablet` |
| `browser` | string | Pixel | Browser name |
| `country` | string | Pixel / IP | Visitor country |
| `city` | string | Pixel / IP | Visitor city |

### 3.4 Attribution Mapping

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `attribution_window` | enum | Config | `1d_click`, `7d_click`, `1d_view`, `7d_click_1d_view` |
| `first_touch_ad_id` | string | Analytics | First ad the user interacted with |
| `last_touch_ad_id` | string | Analytics | Last ad before conversion |
| `touch_count` | int | Analytics | Total ad interactions before conversion |
| `days_to_convert` | int | Computed | Days from first touch to conversion |
| `conversion_path` | json | Analytics | Ordered list of touchpoints |

---

## Data Structure for Future Modeling

### Unified Record Schema

Each record joins all three layers for a single ad variation:

```
unified_ad_record = {
    # Identity
    ad_id, strategy_id, phase_id, variation_index, store_id,

    # Creative (Layer 1)
    headline, body_text, image_url, cta_type,
    emotion_tag, hook_type, visual_style, offer_type, tone,

    # Audience (Layer 1)
    audience_name, audience_type, age_min, age_max, interests,

    # Config (Layer 1)
    objective, daily_budget_cents, placement,

    # Performance (Layer 2)
    impressions, reach, clicks, ctr, cpc, spend,
    leads, purchases, purchase_value, roas,
    quality_ranking, engagement_rate_ranking,

    # Outcome (Layer 3)
    qualified_leads, disqualified_leads, lead_quality_score_avg,
    total_revenue, net_revenue, customer_ltv_90d_avg,
    conversion_rate, cost_per_qualified_lead,
}
```

### Key Computed Metrics

| Metric | Formula | Purpose |
|--------|---------|---------|
| `cost_per_qualified_lead` | `spend / qualified_leads` | True lead acquisition cost |
| `lead_to_customer_rate` | `purchases / leads` | Lead quality indicator |
| `true_roas` | `net_revenue / spend` | Actual return (post-refunds) |
| `creative_score` | Weighted(ctr, cpa, quality_ranking) | Composite creative quality |
| `audience_efficiency` | `qualified_leads / impressions * 1000` | Audience targeting quality |
| `time_value_score` | `ltv_90d / cost_per_qualified_lead` | Long-term value efficiency |

### Recommended Sync Schedule

| Data Layer | Frequency | Method |
|------------|-----------|--------|
| Creative Metadata | At creation | Stored internally on publish |
| Ad Performance (active) | Every 15 minutes | Meta Insights API via scheduler |
| Ad Performance (completed) | Daily | Meta Insights API batch |
| Lead Quality | Real-time (webhook) + hourly batch | CRM webhooks + API polling |
| Revenue / Orders | Real-time (webhook) + daily reconciliation | Store webhooks + API |
| Pixel Events | Real-time (pixel fires) | Meta Pixel / Conversions API |

### Storage Recommendations

| Store | Technology | Data |
|-------|-----------|------|
| **Primary DB** | PostgreSQL | Creative metadata, strategy/phase/variation records, lead records |
| **Time-series** | PostgreSQL (partitioned) or TimescaleDB | Hourly/daily performance snapshots for trend analysis |
| **Analytics** | Materialized views / dbt | Pre-aggregated metrics for dashboards |
| **ML Feature Store** | Parquet files / Feature table | Flattened records for model training |

### Indexing Strategy

```sql
-- Primary lookups
CREATE INDEX idx_variations_strategy ON phase_variations(strategy_id);
CREATE INDEX idx_variations_phase ON phase_variations(phase_id);
CREATE INDEX idx_variations_meta_ad ON phase_variations(meta_ad_id);

-- Performance queries
CREATE INDEX idx_variations_winner ON phase_variations(is_winner) WHERE is_winner = true;
CREATE INDEX idx_performance_date ON ad_performance_snapshots(date_start, ad_id);

-- Attribution joins
CREATE INDEX idx_leads_ad ON leads(ad_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);

-- Analytics queries
CREATE INDEX idx_variations_emotion ON phase_variations USING gin(emotion_tag);
CREATE INDEX idx_variations_store_created ON phase_variations(store_id, created_at);
```

---

## Future ML Use Cases

This framework enables:

1. **Creative Performance Prediction** - Predict CTR/CPA before launch based on creative attributes (emotion, hook type, visual style)
2. **Audience-Creative Matching** - Which creative attributes work best for which audience segments
3. **Budget Optimization** - Predict optimal budget allocation across variations
4. **Winner Prediction** - Early winner detection before statistical significance (reducing test duration)
5. **Cross-Store Learnings** - Pattern recognition across all stores (e.g., "lifestyle images outperform product shots for fashion stores")
6. **Automated Creative Generation** - Feed winning patterns back to AI agents for better initial generation
7. **Lead Quality Prediction** - Score leads at capture time based on ad + audience + behavior signals
8. **LTV Prediction** - Predict customer lifetime value based on acquisition channel and creative exposure

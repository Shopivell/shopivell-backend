# Shopivell AI Ad Engine - System Architecture

> **DEPRECATED (September 2026)**: This document describes the legacy Python agents system.
> The system has been replaced by **OpenClaw + Zernio**.
> See: `modules/openclaw/` for the new implementation.

---

## New Architecture (OpenClaw + Zernio)

```
┌─────────────────────────────────────────────────────────┐
│                    Shopivell Frontend                    │
│                  (openclawService.ts)                    │
└─────────────────────┬───────────────────────────────────┘
                      │ /api/openclaw/*
┌─────────────────────▼───────────────────────────────────┐
│                 Shopivell Backend                        │
│              (modules/openclaw/router.py)                │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                     OpenClaw                             │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Skills                                           │    │
│  │  • ad-creator    → AI campaign generation        │    │
│  │  • zernio-ads    → Meta Ads via Zernio API       │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Plugins                                          │    │
│  │  • optimizer     → 24/7 autonomous monitoring    │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                   Zernio API                             │
│         (Meta Marketing Partner - No App Review)         │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                   Meta Ads API                           │
└─────────────────────────────────────────────────────────┘
```

**Why the change:**
1. Meta App Review rejected `ads_management` permission
2. Zernio provides Meta API access without App Review
3. OpenClaw unifies fragmented Python agents into one platform

**New API Endpoints:**
- `POST /api/openclaw/stores/{id}/generate-campaign`
- `POST /api/openclaw/stores/{id}/launch-campaign`
- `GET /api/openclaw/stores/{id}/optimizer/status`

---

## Legacy Documentation (Archived)

## Overview

Shopivell's AI Ad Engine is a fully autonomous advertising system. Given a website URL, it scrapes the site, understands the business, generates ad creatives with brand-matched visuals, publishes to Meta Ads, and optimizes 24/7 with automated rules, creative refresh, lead scoring, and audience refinement.

---

## End-to-End Pipeline

```
URL Input
    |
    v
[1. Scrape & Analyze]
    Website scraping (Tavily) -> Brand DNA extraction -> Vision AI analysis
    Extracts: logo, colors, uniforms, vehicles, products, visual style
    |
    v
[2. Market Research]
    MarketResearchAgent conducts research + Ad Library competitor analysis
    Outputs: industry analysis, competitor insights, target audience data
    |
    v
[3. Audience Generation]
    CreativeStrategistAgent generates Meta audience targeting via LLM
    -> Interest tags validated against Meta Interest Search API
    -> If <30% valid, auto-retries with broader terms (up to 2 retries)
    -> Reach estimation via Meta Reach Estimate API
    |
    v
[4. Ad Content Generation]
    Ad copy (AdCopyAgent) + Image prompts + Media generation (Gemini/FLUX)
    Brand-aware images using store assets (logo, colors, product photos)
    |
    v
[5. Publish to Meta Ads]
    Campaign -> Ad Sets -> Ads created via Meta Marketing API
    Lifetime budget with dayparting (industry-optimized ad schedule)
    Top-performing Facebook Page auto-selected from historical data
    |
    v
[6. 24/7 Optimization]
    Automated Rules Scheduler runs tiered cycles:
    - Every 15 min: Rules engine (scale/kill/pause based on performance)
    - Every 6 hr:  Sync insights from Meta API
    - Every 24 hr: Daily performance summary + lead quality check + notifications
    - Every 7 days: Audience refinement + weekly report + creative fatigue check
```

---

## Core Components

### Quick Launch (`POST /api/url-campaigns/quick-launch`)

Single endpoint that executes the entire pipeline:

1. Scrapes URL and creates campaign with brand analysis
2. Generates ad content (headlines, descriptions, buyer personas, images)
3. Publishes to Meta Ads Manager (campaign + ad sets + ads)
4. Registers with the 24/7 optimizer scheduler

**Budget Handling:**
- Default: `lifetime` budget with automatic dayparting
- Converts daily budget to lifetime: `daily x duration_days x 100` (cents)
- Ad schedule auto-determined from business industry

**Page Selection:**
- Queries historical MetaAdInsight data across all connected Facebook Pages
- Scores pages by weighted performance: 60% CTR + 40% conversion rate
- Falls back to business_id or first connected page if no history

---

### Dayparting Service (`modules/marketing/dayparting_service.py`)

Automatically schedules ad delivery based on business type:

| Industry Profile | Schedule | Rationale |
|-----------------|----------|-----------|
| B2B Default | Mon-Fri 8AM-6PM | Business hours |
| B2B Tech/SaaS | Mon-Fri 7AM-9PM, Sat 9AM-2PM | Decision makers browse evenings |
| E-commerce | Mon-Fri 9AM-10PM, Weekends 10AM-9PM | Peak shopping windows |
| Food/Restaurant | Lunch 10AM-2PM, Dinner 4PM-9PM, Weekends all day | Meal decision times |
| Local Services | Mon-Fri 7AM-7PM, Sat 8AM-4PM, Sun 9AM-2PM | When customers call |
| Real Estate | Mon-Fri 12PM-9PM, Weekends 9AM-8PM | When people browse listings |
| Fashion | Lunch + evenings + weekends | Browsing patterns |
| Health/Fitness | Early morning + evenings | Gym-goer schedules |
| Entertainment | Evenings + weekends | Leisure time |

79 industry keywords map to 11 schedule profiles. Optional AI-powered schedule generation via LLM with rule-based fallback.

---

### Audience Generation & Validation

**CreativeStrategistAgent** generates Meta audience targeting:

1. LLM generates 25-40 interest tags across categories (core, tech, business, consumer, behavioral, complementary)
2. Each tag validated against Meta's Interest Search API (`GET /search?type=adinterest`)
3. **Retry loop**: If <30% of interests validate, regenerates with feedback about which tags failed, requesting broader terms. Up to 2 retries.
4. Validated interests used to build targeting spec
5. Reach estimated via Meta Reach Estimate API

**Performance Feedback Loop** (runs weekly):
- Fetches demographic breakdown from Meta API (`breakdowns=age,gender`)
- LLM refines targeting based on which demographics convert best
- Updates audience recommendations (age narrowing, gender focus, new interests)

---

### Automated Rules Engine (`modules/agents/monitor_optimizer_agent.py`)

24/7 optimization via configurable rules:

| Rule Template | Trigger Condition | Action |
|--------------|-------------------|--------|
| `scale_winning_ads` | ROAS >= target x 1.25 for 3 days | Increase budget +20% |
| `kill_underperformers` | CPA > 2x target AND 0 purchases after 2000+ impressions | Cut budget 50% |
| `creative_fatigue` | Frequency > 3 AND CTR decline > 30% for 3 days | Pause ad |
| `creative_fatigue_refresh` | Same as fatigue | Auto-refresh: new copy + new image + new ad |
| `scale_high_lead_quality` | Lead quality score > 70 AND hot leads > 5 | Increase budget +15% |

**Computed Metrics:**
- `ctr_decline_pct`: Compares last 3 days CTR vs previous 3 days
- `lead_quality_score`: Weighted average from WhatsApp lead scores

---

### Creative Refresh (`_refresh_creative`)

When creative fatigue is detected:

1. **Pause** the fatigued ad
2. **Generate new copy** via AdCopyAgent (new headline, primary text, description)
3. **Generate new image** via MediaGeneratorAgent (brand-aware with store assets)
4. **Create new Meta ad** in the same ad set with fresh creative + image
5. New ad set to ACTIVE, old ad stays PAUSED

---

### Lead Scoring Integration

**WhatsApp Lead Scoring** (`GET /api/whatsapp/leads/analytics`):
- Queries WhatsAppLead model for 7-day window
- Categorizes: HOT (70+), WARM (40-69), COOL (20-39), COLD (<20)
- Returns: total leads, category counts, average score, conversion rate

**Scheduler Integration:**
- Every 24 hours: `get_lead_quality_signal()` computes average scores
- High lead quality signal triggers `scale_high_lead_quality` rule
- Daily notification includes lead quality metrics

---

### Tiered Scheduler (`modules/agents/scheduler.py`)

Background scheduler using `_run_count` modular arithmetic:

| Cycle | Frequency | What Runs |
|-------|-----------|-----------|
| Every cycle | 15 min | `run_all_rules()` for all ad accounts + micro-strategy checks |
| Every 24th | ~6 hr | `sync_insights_for_all_accounts(days=3)` |
| Every 96th | ~24 hr | Performance summary + lead quality check + daily notification |
| Every 672nd | ~7 days | `refine_audience_from_performance()` + `generate_weekly_report()` + weekly notification |

Auto-starts on app boot via `@app.on_event("startup")`. Registers all connected ad accounts.

---

### Weekly Report Generator (`modules/agents/report_generator.py`)

Aggregates 7 days of MetaAdInsight data:
- Total spend, impressions, clicks, CTR, CPC, conversions, ROAS
- Top 5 and worst 5 performing ads
- Daily breakdown with trend analysis
- Week-over-week comparison
- LLM-generated narrative summary with recommendations
- Creates system notification with key metrics

---

### Interest Validation & Reach Estimation (`modules/marketing/meta_targeting_service.py`)

- `validate_interests()`: Searches Meta's ad interest taxonomy for each tag
- `get_reach_estimate()`: Sizes audience with targeting spec
- `build_targeting_spec()`: Constructs Meta-compatible targeting JSON
- `create_custom_audience()`: SHA256 hashes phone numbers, uploads to Meta
- `create_lookalike_audience()`: Creates lookalike from source audience (configurable ratio 1%-20%)

---

### Keyword Intelligence (`modules/agents/keyword_intelligence_agent.py`)

- Primary: DataForSEO API for search volume, CPC, competition data
- Fallback: Google Autocomplete suggestions
- LLM clusters keywords by intent: informational, commercial, transactional, navigational
- Endpoint: `POST /api/agents/keyword-research`

---

### Brand Asset Awareness (`modules/agents/media_generator_agent.py`)

When `store_id` is provided:
1. Queries Asset model for logos, brand photos, product images
2. Gets store brand colors and description
3. Builds brand context prompt (colors, asset descriptions, style guidance)
4. Prepends to image generation prompt for brand-consistent output

---

### Ad Library Integration (`modules/agents/market_research_agent.py`)

During `conduct_research()`:
1. Extracts search keywords from products/services
2. Calls `fetch_ads_library()` with keywords + country
3. Injects competitor ad data into LLM research prompt
4. Research output includes competitor creative analysis

---

### Insights Sync Service (`modules/marketing/insights_service.py`)

Extracted from marketing router for reuse:
- `sync_ad_insights()`: Fetches insights for a single ad from Meta API
- `sync_insights_background()`: Background task for bulk sync
- `sync_insights_for_all_accounts()`: Iterates all connected accounts
- `get_demographic_breakdown()`: Age/gender performance breakdown for audience refinement

---

## API Endpoints

### Campaign Pipeline
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/url-campaigns/quick-launch` | Full end-to-end pipeline |
| POST | `/api/agents/campaigns/{id}/run-pipeline` | Run pipeline for existing campaign |

### Audience & Targeting
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/agents/validate-interests` | Validate interest tags against Meta |
| POST | `/api/agents/audience-from-url-validated` | Generate + validate audience from URL |
| POST | `/api/agents/dayparting/recommend` | Get optimal ad schedule for industry |

### Audiences
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/marketing/custom-audiences/upload` | Upload phone list as custom audience |
| POST | `/api/marketing/lookalike-audiences/create` | Create lookalike from source |

### Intelligence
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/agents/keyword-research` | Keyword research with clustering |
| POST | `/api/agents/weekly-report/{account_id}` | Generate weekly performance report |

### Scheduler
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/agents/scheduler/start` | Start optimization scheduler |
| POST | `/api/agents/scheduler/stop` | Stop scheduler |
| POST | `/api/agents/scheduler/add-account` | Register ad account |
| POST | `/api/agents/scheduler/run-now` | Trigger immediate cycle |
| GET | `/api/agents/scheduler/status` | Get scheduler status |

### Lead Scoring
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/whatsapp/leads/analytics` | Lead scoring analytics dashboard |

---

## Frontend Pages

| Page | Route | Purpose |
|------|-------|---------|
| Quick Launch | `/:userId/marketing/quick-launch` | URL-to-campaign form with progress indicators |
| Lead Scoring | `/:userId/marketing/lead-scoring` | Lead funnel visualization + scores table |
| Insights | `/:userId/marketing/insights` | Ad performance insights dashboard |
| Micro-Strategy | `/:userId/marketing/micro-strategy` | Micro-strategy management |
| Pixel Tracker | `/:userId/marketing/pixel-tracker` | Conversion tracking pixels |

---

## Data Flow Diagram

```
                    +------------------+
                    |   Quick Launch   |
                    |   (URL + Config) |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Website Scraper  |
                    |  + Brand DNA      |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
    +---------v----------+     +-----------v-----------+
    | Market Research     |     | Ad Content Generator  |
    | + Ad Library        |     | (Copy + Images)       |
    +-----+---------+----+     +----------+------------+
          |         |                     |
          |    +----v-----+               |
          |    | Audience  |               |
          |    | Generator |               |
          |    | + Validate|               |
          |    | + Retry   |               |
          |    +----+------+               |
          |         |                      |
          +---------+----------+-----------+
                               |
                    +----------v-----------+
                    |  Meta Ads Publisher   |
                    |  + Dayparting         |
                    |  + Top Page Selection |
                    +----------+-----------+
                               |
                    +----------v-----------+
                    |  24/7 Scheduler       |
                    |  Tiered Optimization  |
                    +----------+-----------+
                               |
              +----------------+----------------+
              |                |                |
    +---------v------+  +-----v------+  +------v--------+
    | Rules Engine   |  | Insights   |  | Weekly Report |
    | Scale/Kill/    |  | Sync       |  | + Audience    |
    | Refresh        |  | Lead Score |  | Refinement    |
    +----------------+  +------------+  +---------------+
```

---

## Environment Requirements

| Requirement | Purpose | Fallback |
|-------------|---------|----------|
| Meta Access Token | Publishing ads, insights sync | Simulated mode |
| OpenRouter API Key | LLM for all agents | OpenAI fallback |
| Google Gemini API Key | Image generation | FLUX fallback |
| Cloudinary | Image hosting | Local storage |
| DataForSEO Login/Password | Keyword research | Google Autocomplete |
| Redis | Response caching | Disabled (non-blocking) |

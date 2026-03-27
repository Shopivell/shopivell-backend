# Shopivell AI Ad Engine - Component Reference

**Last Updated:** March 2026

---

## System Components

### 1. Website Scraping & Brand Analysis

**How it works:**
The system scrapes any website URL using Tavily, then analyzes all extracted images with Vision AI (GPT-4o-mini) to build a complete brand profile.

| Component | File | What It Does |
|-----------|------|-------------|
| Website Scraper | `modules/stores/scraping_service.py` | Scrapes text + images from multiple pages |
| Brand DNA Extractor | `modules/brand_intelligence/brand_dna_extractor.py` | Orchestrates complete brand analysis |
| Asset Categorizer | `modules/brand_intelligence/asset_categorizer.py` | Categorizes images (team, vehicle, product, logo, hero) |
| Visual Style Analyzer | `modules/brand_intelligence/visual_style_analyzer.py` | Extracts photography style, color treatment, composition |

**Extraction capabilities:**
- Logo (WordPress selectors, OG image, favicon fallback)
- Brand colors (from logo via Vision AI, WordPress preset filtering)
- Uniforms (image URLs + text description of colors/style/badges)
- Vehicles (image URLs + branding details)
- Equipment (image URLs)
- Visual style DNA (photography style, color treatment, composition, typography)

**Tracking pixel filter:** Blocks Facebook pixels, Google Analytics, tracking beacons, 1x1 GIFs, spacers.

---

### 2. Market Research Agent

**File:** `modules/agents/market_research_agent.py`

**How it works:**
1. Takes scraped website data as input
2. Fetches competitor ads from Meta Ad Library using business keywords
3. Sends combined data (website + competitor ads) to LLM
4. Returns: industry analysis, competitor positioning, target audience insights, messaging opportunities

---

### 3. Creative Strategist Agent

**File:** `modules/agents/creative_strategist_agent.py`

**How it works:**

**Audience Generation (`generate_meta_audience_validated`):**
1. LLM generates 25-40 interest tags across 6 categories
2. Each tag validated against Meta Interest Search API
3. If <30% validate, auto-retries with broader terms (injects failed tags as context)
4. Up to 2 retries before returning best available result
5. Reach estimated via Meta Reach Estimate API

**Audience Refinement (`refine_audience_from_performance`):**
1. Fetches demographic breakdown from Meta API (age x gender)
2. LLM analyzes which demographics convert best
3. Outputs refined targeting: narrowed age ranges, gender focus, new interests

---

### 4. Ad Copy Agent

**File:** `modules/agents/ad_copy_agent.py`

**How it works:**
- Generates B2B and B2C ad copy variants
- Outputs: headline, primary text, description, CTA
- Supports platform-specific copy (Facebook, Instagram)
- Uses research data + audience info for contextual messaging

---

### 5. Media Generator Agent

**File:** `modules/agents/media_generator_agent.py`

**How it works:**
- Primary: Gemini image generation with reference images
- Fallback: FLUX via Replicate
- Brand-aware: queries store assets (logos, photos) when `store_id` provided
- Builds brand context prompt from colors, asset descriptions, visual style
- Supports image and video generation

**Gemini Image Generator** (`modules/agents/gemini_image_generator.py`):
- Model: `gemini-2.5-flash-image`
- Accepts logo + uniform + vehicle images as references
- Prompt includes brand DNA style instructions

**Ad Image Composer** (`modules/agents/ad_image_composer.py`):
- PIL-based post-processing
- Gradient overlay, word-wrapped headline, bullet points, rounded CTA button
- Logo overlay at proportional size (~8% height, ~20% width)

---

### 6. Campaign Service

**File:** `modules/campaigns/service.py`

**`_generate_ad_content()`:** LLM generates from scraped content:
- Business name, type, key metrics (extracted from website)
- 1 buyer persona ad set with: audience tags, primary text, headline, features, visual direction
- Campaign data is isolated — AI derives everything from URL, not store data

**`_create_ad_sets()`:** Creates ad set records:
- Maps business type to industry template
- Generates AI images via Gemini with brand references (uniforms, vehicles, logo)
- Uploads to Cloudinary
- Falls back to MediaGenerator if Gemini fails

---

### 7. Quick Launch Pipeline

**File:** `modules/campaigns/router.py` — `POST /api/url-campaigns/quick-launch`

**Flow:**
1. Scrape URL -> create campaign with brand analysis
2. Generate ad content (copy + images for buyer persona)
3. Select Facebook Page (top performer by CTR/conversion or fallback)
4. Create Meta Campaign (lifetime budget with dayparting or daily budget)
5. For each ad set: build targeting spec -> create Meta ad set (with schedule if lifetime) -> create Meta ads
6. Register with scheduler for 24/7 optimization
7. Create notification

**Budget modes:**
- `lifetime` (default): Converts daily to lifetime, applies industry dayparting schedule
- `daily`: Standard daily budget, no scheduling

---

### 8. Dayparting Service

**File:** `modules/marketing/dayparting_service.py`

**How it works:**
- 79 industry keywords mapped to 11 schedule profiles
- `get_schedule_for_industry(industry, business_type)` returns optimal time blocks
- `build_adset_schedule_params()` creates Meta API params: `lifetime_budget`, `end_time`, `pacing_type`, `adset_schedule`
- Optional: `generate_schedule_with_ai()` uses LLM for custom schedules

---

### 9. Monitor Optimizer Agent (Rules Engine)

**File:** `modules/agents/monitor_optimizer_agent.py`

**Rule templates:**
| Template | Condition | Action |
|----------|-----------|--------|
| `scale_winning_ads` | ROAS >= target x 1.25 for 3 days | +20% budget |
| `kill_underperformers` | CPA > 2x target, 0 purchases after 2000 impressions | -50% budget |
| `creative_fatigue` | Frequency > 3, CTR decline > 30% over 3 days | Pause |
| `creative_fatigue_refresh` | Same as fatigue | Full creative refresh |
| `scale_high_lead_quality` | Lead score > 70, 5+ hot leads | +15% budget |

**Computed metrics:**
- `ctr_decline_pct`: Last 3 days CTR vs previous 3 days
- `lead_quality_score`: Weighted average from WhatsApp lead data

**Creative refresh process:**
1. Pause fatigued ad
2. AdCopyAgent generates new headline, primary text, description
3. MediaGeneratorAgent generates new brand-aware image
4. Create new Meta ad in same ad set (ACTIVE)
5. Old ad stays PAUSED

**Lead quality signal:**
- Queries WhatsAppLead model for 7-day window
- Categories: HOT (70+), WARM (40-69), COOL (20-39), COLD (<20)
- Returns average score, category counts, total leads

---

### 10. Tiered Scheduler

**File:** `modules/agents/scheduler.py`

**How it works:**
- Background thread with configurable interval (default: 15 min)
- Uses `_run_count` modular arithmetic for tiered execution
- Auto-starts on app boot, registers all connected ad accounts
- Graceful shutdown on app stop

| Tier | Frequency | Tasks |
|------|-----------|-------|
| 1 | Every 15 min | Rules engine for all accounts + micro-strategy cycle |
| 2 | Every 6 hr | Sync insights from Meta API (3-day window) |
| 3 | Every 24 hr | Performance summary + lead quality check + daily notification |
| 4 | Every 7 days | Audience refinement + weekly report + weekly notification |

---

### 11. Insights Service

**File:** `modules/marketing/insights_service.py`

| Function | Purpose |
|----------|---------|
| `sync_ad_insights()` | Fetch insights for single ad from Meta API |
| `sync_insights_background()` | Background task for bulk sync |
| `sync_insights_for_all_accounts()` | Iterate all connected accounts, sync all ads |
| `get_demographic_breakdown()` | Age x gender breakdown for audience refinement |

---

### 12. Meta Targeting Service

**File:** `modules/marketing/meta_targeting_service.py`

| Function | Purpose |
|----------|---------|
| `validate_interests()` | Search Meta Interest taxonomy for each tag |
| `get_reach_estimate()` | Size audience with targeting spec |
| `build_targeting_spec()` | Construct Meta-compatible targeting JSON |
| `create_custom_audience()` | SHA256 hash phone numbers, batch upload to Meta |
| `create_lookalike_audience()` | Create lookalike from source (1%-20% ratio) |

---

### 13. Weekly Report Generator

**File:** `modules/agents/report_generator.py`

**How it works:**
1. Aggregates 7 days of MetaAdInsight data per ad account
2. Calculates: total spend, impressions, clicks, CTR, CPC, conversions, ROAS
3. Identifies top 5 and worst 5 ads by CTR
4. Builds daily breakdown with spend/click trends
5. Computes week-over-week changes
6. LLM generates narrative summary with actionable recommendations

---

### 14. Keyword Intelligence Agent

**File:** `modules/agents/keyword_intelligence_agent.py`

**How it works:**
1. Primary: DataForSEO API (search volume, CPC, competition, trends)
2. Fallback: Google Autocomplete suggestions
3. LLM clusters keywords by intent: informational, commercial, transactional, navigational
4. Returns keyword groups with metrics for ad targeting

---

### 15. Notification System Integration

The scheduler creates notifications at key moments:
- **Daily (Tier 3):** Performance summary with lead quality metrics
- **Weekly (Tier 4):** Full report with spend, clicks, conversions, CTR
- **Quick Launch:** Campaign published notification with ad set/ads counts
- **Creative Refresh:** When fatigue detected and new creative created

---

## Frontend Pages

| Page | File | Route |
|------|------|-------|
| Quick Launch | `pages/marketing/QuickLaunch.tsx` | `/:userId/marketing/quick-launch` |
| Lead Scoring | `pages/marketing/LeadScoring.tsx` | `/:userId/marketing/lead-scoring` |

**Quick Launch UI:** URL input, store/account IDs, budget, goal selector, country picker, demographics, auto-optimizer toggle. Shows 4-stage progress animation during launch. Result view with ad sets/ads counts and Meta campaign ID.

**Lead Scoring UI:** Summary cards (total, hot, warm, cool, cold + avg score). Funnel visualization with proportional bars. Filterable table with score bars, status badges, interests tags.

---

## File Reference

### Core Pipeline
| File | Purpose |
|------|---------|
| `modules/campaigns/router.py` | Quick Launch endpoint, campaign publishing |
| `modules/campaigns/service.py` | Content generation, ad set creation |
| `modules/campaigns/schemas.py` | QuickLaunchRequest/Response schemas |

### AI Agents
| File | Purpose |
|------|---------|
| `modules/agents/market_research_agent.py` | Market research + Ad Library |
| `modules/agents/creative_strategist_agent.py` | Audience generation + validation + refinement |
| `modules/agents/ad_copy_agent.py` | Ad copy generation |
| `modules/agents/media_generator_agent.py` | Image/video generation with brand awareness |
| `modules/agents/monitor_optimizer_agent.py` | Rules engine + creative refresh + lead scoring |
| `modules/agents/keyword_intelligence_agent.py` | Keyword research |
| `modules/agents/report_generator.py` | Weekly performance reports |
| `modules/agents/scheduler.py` | Tiered background scheduler |
| `modules/agents/router.py` | All agent API endpoints |

### Marketing Services
| File | Purpose |
|------|---------|
| `modules/marketing/insights_service.py` | Meta insights sync |
| `modules/marketing/meta_targeting_service.py` | Interest validation, audiences |
| `modules/marketing/dayparting_service.py` | Ad scheduling by industry |
| `modules/marketing/router.py` | Marketing API endpoints |

### Brand Intelligence
| File | Purpose |
|------|---------|
| `modules/brand_intelligence/brand_dna_extractor.py` | Complete brand identity extraction |
| `modules/brand_intelligence/asset_categorizer.py` | Image categorization |
| `modules/brand_intelligence/visual_style_analyzer.py` | Photography/design style analysis |

### WhatsApp
| File | Purpose |
|------|---------|
| `modules/whatsapp/router.py` | Lead analytics endpoint |

### App
| File | Purpose |
|------|---------|
| `main.py` | Scheduler auto-start/stop on app lifecycle |

# Ad Creative System - Technical Reference

> **DEPRECATED (September 2026)**: This document describes the legacy Python agents system.
> The ad creative system has been replaced by **OpenClaw + Zernio**.
> See: `modules/openclaw/skills/ad-creator/SKILL.md` for the new implementation.

---

## New Architecture (OpenClaw)

```
OpenClaw (AI Agent Platform)
├── skills/
│   ├── ad-creator/     → AI ad generation (GPT-Image-2.5)
│   │   ├── research_market()
│   │   ├── generate_angles()
│   │   ├── generate_ad_copy()
│   │   ├── generate_image()
│   │   └── generate_full_campaign()
│   └── zernio-ads/     → Meta Ads via Zernio API (no App Review needed)
└── plugins/
    └── optimizer/      → 24/7 autonomous monitoring
```

**Key Changes:**
- Image generation: Gemini → **OpenAI GPT-Image-2.5**
- Meta API access: Direct → **Zernio** (Meta Marketing Partner)
- Agent platform: Python agents → **OpenClaw** (TypeScript)
- API endpoints: `/api/agents/*` → `/api/openclaw/*`

---

## Legacy Documentation (Archived)

## Overview

The ad creative system generates brand-matched ad images autonomously from a website URL. It scrapes the website, extracts visual branding (logo, colors, uniforms, vehicles, products), generates ad copy and image prompts, and produces actual images using Gemini AI with reference images from the website.

---

## System Flow

```
1. Scrape Website (Tavily)
       |
2. Extract Images (BeautifulSoup)
   - Logo: WordPress selectors, OG image, favicon fallback
   - Lazy-loading: prefers data-src/data-lazy-src
   - Filters: tracking pixels, loaders, placeholders
       |
3. Analyze Images with Vision AI (GPT-4o-mini)
   - Brand colors from logo
   - Uniform images + descriptions
   - Vehicle images + descriptions
   - Equipment images
       |
4. Brand DNA Analysis (BrandDNAExtractor)
   - Visual style (photography, color treatment, composition)
   - Asset categorization (team, product, hero, vehicle)
   - Style-matched prompt generation
       |
5. Generate Ad Copy (AdCopyAgent via OpenRouter)
   - Headlines, primary text, descriptions
   - B2B and B2C variants
   - Platform-specific formatting
       |
6. Generate Ad Image (Gemini)
   - Logo + uniform + vehicle images as references
   - Brand DNA style instructions in prompt
   - PIL logo overlay at proportional size
   - Upload to Cloudinary
       |
7. If creative fatigue detected later:
   - AdCopyAgent generates new copy
   - MediaGeneratorAgent generates new image (brand-aware)
   - New Meta ad created, old one paused
```

---

## Components

### Website Scraping (`modules/stores/scraping_service.py`)

| Function | Purpose |
|----------|---------|
| `extract_store_info_from_website(url)` | Main entry point for scraping |
| `_extract_images_from_website(url)` | Extract logo, OG image, all images |
| `_analyze_images_with_vision(images, domain)` | Vision AI analysis for brand elements |
| `_extract_brand_colors_from_css(url)` | CSS color extraction (fallback) |

**Logo extraction priority:**
1. Header/nav elements with "logo" class/alt
2. Links with "logo" class
3. Images with "logo" class
4. First image in header
5. Favicon fallback

**Tracking pixel filter blocks:** `facebook.com/tr`, `google-analytics.com`, `doubleclick.net`, `pixel`, `tracking`, `beacon`, `1x1`, `spacer`, `.gif`, `analytics`, `stat`, `counter`, `noscript`

**WordPress preset filter:** Skips `#ABB8C3`, `pale-pink`, `luminous-vivid-orange`, and other WP default colors.

---

### Brand DNA Extraction (`modules/brand_intelligence/`)

| Component | File | Purpose |
|-----------|------|---------|
| BrandDNAExtractor | `brand_dna_extractor.py` | Orchestrates complete brand analysis |
| AssetCategorizer | `asset_categorizer.py` | Categorizes images by type (team, vehicle, product, logo, hero, office) |
| VisualStyleAnalyzer | `visual_style_analyzer.py` | Extracts photography style, color treatment, composition, lighting |

**Output structure:**
```python
{
    "business_identity": {"company_name", "industry", "business_type", "visual_requirements"},
    "visual_style": {"photography_style", "color_treatment", "uniform_details", "vehicle_details"},
    "brand_colors": ["#005B5C", "#FFFFFF"],
    "categorized_images": {"team": [...], "vehicle": [...], "product": [...]},
    "style_prompt": "PHOTOGRAPHY STYLE: Professional studio photography..."
}
```

---

### Ad Creative Agent (`modules/agents/ad_creative_agent.py`)

Generates ad creative content via OpenRouter (Claude/GPT-4o).

**Input:** product name, description, target audience, benefits, logo URL, brand color, visual profile

**Output:**
```python
{
    "headline": "Professional Protection Around The Clock",
    "ad_angle": "24/7 security coverage for commercial properties",
    "image_prompt": "Professional advertisement image for..."
}
```

---

### Gemini Image Generator (`modules/agents/gemini_image_generator.py`)

Generates images using `gemini-2.5-flash-image` with reference images.

**Reference image strategy:**
- Logo: exact placement reference
- Up to 2 uniform images: staff appearance matching
- Up to 1 vehicle image: fleet branding matching

**Prompt includes:**
- Brand color palette
- Visual style instructions from Brand DNA
- Explicit instructions: "use uniforms EXACTLY as shown in reference"
- No emoji, no cartoon, professional studio quality

---

### Ad Image Composer (`modules/agents/ad_image_composer.py`)

PIL-based post-processing:
- Gradient overlay for text readability
- Word-wrapped headline text
- Bullet points for features
- Rounded CTA button
- Logo overlay at ~8% height, ~20% width

---

### Media Generator Agent (`modules/agents/media_generator_agent.py`)

Full media generation pipeline with brand awareness:

1. If `store_id` provided: queries Asset model for logos, brand photos, product images
2. Builds brand context prompt from store colors and asset descriptions
3. Primary: Gemini generation with references
4. Fallback: FLUX via Replicate
5. Uploads to Cloudinary

---

### Campaign Service Integration (`modules/campaigns/service.py`)

**`_create_ad_sets()`** uses Gemini as primary generator:
1. Builds reference images list from scraped uniform/vehicle/logo images
2. Includes Brand DNA style prompt in generation request
3. Generates image via Gemini with references
4. Falls back to MediaGenerator if Gemini fails
5. Uploads to Cloudinary

**Data isolation:** AI derives everything from scraped content only. No store database data is passed to prevent cross-contamination between campaigns.

---

### Creative Refresh (Fatigue Loop)

When the rules engine detects creative fatigue (frequency > 3, CTR decline > 30%):

1. **Pause** the fatigued ad
2. **AdCopyAgent** generates new headline, primary text, description
3. **MediaGeneratorAgent** generates new brand-aware image (with store_id for brand context)
4. **New Meta ad** created in same ad set with `picture` field set to new image URL
5. Old ad stays PAUSED, new ad set to ACTIVE

---

## Campaign Data Isolation

Each URL scrape is fully isolated from store data:

- `_generate_ad_content()`: `store_info_section = ""` — AI determines business name from scraped content
- `_create_ad_sets()`: `store_name = business_name` — uses AI-determined name from scraped URL
- Regeneration: `store_context = None` — same isolation

This prevents stale store data from leaking into campaigns for different businesses.

---

## Configuration

### Required Environment Variables
```bash
OPENAI_API_KEY=...          # Vision AI analysis (GPT-4o-mini)
OPENROUTER_API_KEY=...      # LLM for ad copy (Claude, GPT-4o)
GOOGLE_API_KEY=...          # Gemini image generation
TAVILY_API_KEY=...          # Website scraping
CLOUDINARY_URL=...          # Image hosting
```

### Gemini Models
| Model | Use Case |
|-------|----------|
| `gemini-2.5-flash-image` | Fast generation (current default) |
| `gemini-3-pro-image-preview` | High quality, supports 14 reference images |

---

## Usage

### Quick Launch (Full Pipeline)
```bash
POST /api/url-campaigns/quick-launch
{
    "url": "https://example.com",
    "store_id": "uuid",
    "ad_account_id": "uuid",
    "daily_budget": 10.0,
    "budget_type": "lifetime",
    "campaign_duration_days": 30,
    "countries": ["ZW"],
    "goal": "traffic"
}
```

### Standalone Image Generation
```bash
POST /api/agents/generate-image
{
    "prompt": "Professional security guard at office entrance",
    "style": "photorealistic",
    "aspect_ratio": "1:1",
    "store_id": "uuid"  // optional, for brand awareness
}
```

---

## Test Scripts

| Script | Purpose |
|--------|---------|
| `test_gemini_image_gen.py` | E2E test with Gemini image generation |
| `test_real_e2e_flow.py` | E2E test for ad set generation |
| `test_2adsets_securesights.py` | Full pipeline test (any website URL) |

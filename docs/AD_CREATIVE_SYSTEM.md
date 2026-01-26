# Ad Creative System Documentation

## Overview

This system generates ad creatives autonomously from a website URL. It scrapes the website, extracts visual branding (logo, uniforms, vehicles), generates ad copy and image prompts, and generates actual images using Gemini AI with reference images.

---

## Status Summary

### COVERED (Completed)

| Feature | Status | File(s) |
|---------|--------|---------|
| Website scraping with Tavily | DONE | `modules/stores/scraping_service.py` |
| Logo extraction (WordPress, OG image) | DONE | `modules/stores/scraping_service.py` |
| Vision AI image analysis (uniforms, vehicles, equipment) | DONE | `modules/stores/scraping_service.py` |
| Brand color extraction from logo | DONE | `modules/stores/scraping_service.py` |
| Tracking pixel filtering | DONE | `modules/stores/scraping_service.py` |
| WordPress preset color filtering | DONE | `modules/stores/scraping_service.py` |
| Ad Creative Agent (headlines, image prompts) | DONE | `modules/agents/ad_creative_agent.py` |
| Gemini image generation with reference images | DONE | `modules/agents/gemini_image_generator.py` |
| Campaign data isolation (no store data leakage) | DONE | `modules/campaigns/service.py`, `router.py` |
| E2E test script | DONE | `test_gemini_image_gen.py` |

### NOT COVERED (Pending)

| Feature | Priority | Notes |
|---------|----------|-------|
| Integration with campaign service | HIGH | Connect Gemini generator to `_create_ad_sets()` |
| Cloud storage for generated images | HIGH | Upload to Cloudinary instead of local files |
| Batch generation for all 5 ad sets | MEDIUM | Currently generates 1 image at a time |
| Retry logic for transient failures | MEDIUM | Handle API rate limits, timeouts |
| Image aspect ratio variations | LOW | 1:1, 16:9, 9:16 for different placements |
| A/B testing image variants | LOW | Generate multiple images per ad set |

---

## System Flow

```
1. Scrape Website (Tavily)
       ↓
2. Extract Images (BeautifulSoup)
       ↓
3. Analyze Images with Vision AI (OpenAI GPT-4o-mini)
   - Extract brand colors from logo
   - Identify uniform images
   - Identify vehicle images
   - Identify equipment images
       ↓
4. Generate Ad Copy & Image Prompt (Claude/Anthropic)
   - Uses visual profile (uniforms, vehicles) in prompts
   - Incorporates brand color
       ↓
5. Generate Actual Image (Gemini)
   - Passes logo as reference image
   - Passes uniform/vehicle images as references
   - Outputs PNG image
```

---

## What We've Built

### 1. Website Scraping (`modules/stores/scraping_service.py`)

**Functions:**
- `extract_store_info_from_website(url)` - Main entry point
- `_extract_images_from_website(url)` - Extracts logo, OG image, and other images
- `_analyze_images_with_vision(images_data, domain)` - Analyzes images with OpenAI Vision
- `_extract_brand_colors_from_css(url)` - Extracts colors from CSS (fallback)

**What Works:**
- Logo extraction from WordPress sites
- OG image extraction
- Image collection (up to 20 images)
- Tracking pixel filtering (Facebook, Google Analytics, etc.)
- Vision-based analysis to identify:
  - Brand colors from logo
  - Uniform descriptions (color, style, badges)
  - Vehicle descriptions (type, color, branding)
  - Equipment descriptions
  - Which specific images contain uniforms/vehicles/equipment

---

### 2. Ad Creative Agent (`modules/agents/ad_creative_agent.py`)

**Function:**
- `generate_ad_creative(...)` - Generates headline, ad angle, and image prompt

**Parameters:**
- `product_name` - Business name
- `product_description` - What the business does
- `target_audience` - Who the ad targets
- `key_benefits` - List of benefits
- `logo_url` - Company logo URL
- `brand_color` - Hex color from logo
- `visual_profile` - Dict with uniform/vehicle/equipment descriptions

**What Works:**
- Generates compelling headlines
- Creates detailed image prompts
- Incorporates brand color in prompts
- Incorporates visual profile (uniforms, vehicles) in prompts

**Output Format:**
```python
{
    "headline": "Professional Protection Around The Clock",
    "ad_angle": "Description of the ad angle...",
    "image_prompt": "Professional advertisement image for..."
}
```

---

### 3. Gemini Image Generator (`modules/agents/gemini_image_generator.py`)

**Function:**
- `generate_ad_image(prompt, logo_url, reference_images, output_path)`

**Parameters:**
- `prompt` - Image generation prompt
- `logo_url` - Logo to include as reference
- `reference_images` - List of dicts with `url` and `type` (uniform, vehicle, equipment)
- `output_path` - Where to save generated image
- `model` - Default: `gemini-2.5-flash-image`

**What Works:**
- Fetches images from URLs
- Builds enhanced prompts with reference image instructions
- Passes multiple reference images to Gemini
- Generates and saves PNG images

---

## Successful Test Results

### Test 1: Securico (https://securico.co.zw)

**Vision Analysis Results:**
| Item | Extracted Value |
|------|-----------------|
| Brand Colors | `#005B5C`, `#FFFFFF`, `#4B7F99` |
| Logo | Shield with globe, crossed batons, "SECURICO SECURITY SERVICES" |
| Vehicles | White trucks/vans with green branding |
| Uniform Image | Found 1 image showing staff |
| Vehicle Images | Found 2 images showing fleet |

**Reference Images Passed to Gemini:**
- Logo: `https://securico.co.zw/wp-content/uploads/2024/10/logo.png`
- Uniform: `https://securico.co.zw/wp-content/uploads/2024/07/how-we-make_-1024x682.jpg`
- Vehicle: `https://securico.co.zw/wp-content/uploads/2024/07/cars-e1694096854202-1536x563-1.jpg`

**Status:** SUCCESS - Image generated at `generated_images/securico_co_zw_ad.png`

### Test 2: Safeguard (https://safeguard.co.zw)

**Vision Analysis Results:**
| Item | Extracted Value |
|------|-----------------|
| Brand Colors | `#FFFF00`, `#000000` |
| Logo | Bold "SAFeguard" text in yellow/black triangular design |
| Uniforms | Not detected (no uniform images on website) |
| Vehicles | Not detected (no vehicle images on website) |

**Reference Images Passed to Gemini:**
- Logo: `https://www.safeguard.co.zw/wp-content/uploads/2025/04/SAFEGUARD-LOGO-1-1-1.png`

**Status:** SUCCESS - Image generated at `generated_images/safeguard_co_zw_ad.png`

---

## Issues Fixed

### Issue 1: Gemini Model Name (FIXED)
- **Error:** `models/gemini-2.5-flash-preview-05-20 is not found`
- **Fix:** Changed model to `gemini-2.5-flash-image`

### Issue 2: Facebook Tracking Pixels (FIXED)
- **Error:** `Failed to download image from https://www.facebook.com/tr?...`
- **Fix:** Added filter to skip tracking pixels before analysis
- **Filtered patterns:** `facebook.com/tr`, `google-analytics`, `doubleclick`, `pixel`, `tracking`, `beacon`, `1x1`, `spacer`, `.gif`, `analytics`, `stat`, `counter`, `noscript`

### Issue 3: WordPress Default Colors (FIXED)
- **Problem:** Extracting WordPress preset colors like `#ABB8C3` instead of brand colors
- **Fix:** Added WordPress preset filter + prioritize Vision-extracted colors from logo

---

## Configuration

### Required Environment Variables
```bash
OPENAI_API_KEY=your_openai_key          # For Vision analysis
ANTHROPIC_API_KEY=your_anthropic_key    # For Claude (AdCreativeAgent)
GOOGLE_API_KEY=your_google_key          # For Gemini image generation
TAVILY_API_KEY=your_tavily_key          # For web scraping
```

### Gemini Models for Image Generation
| Model | Use Case |
|-------|----------|
| `gemini-2.5-flash-image` | Fast image generation (recommended, current) |
| `gemini-3-pro-image-preview` | High quality, supports 14 reference images |

---

## Usage Example

```python
from modules.stores.scraping_service import _extract_images_from_website, _analyze_images_with_vision
from modules.agents.ad_creative_agent import AdCreativeAgent
from modules.agents.gemini_image_generator import GeminiImageGenerator

# 1. Extract images from website
images = _extract_images_from_website("https://example.com")
logo_url = images.get("logo_url")

# 2. Analyze images with Vision AI
vision_analysis = _analyze_images_with_vision(images, "example.com")

# 3. Build visual profile
visual_profile = {
    "uniform_description": vision_analysis.get("uniform_description"),
    "vehicle_description": vision_analysis.get("vehicle_description"),
    "equipment_description": vision_analysis.get("equipment_description"),
    "reference_images": vision_analysis.get("reference_images", []),
    "uniform_images": vision_analysis.get("uniform_images", []),
    "vehicle_images": vision_analysis.get("vehicle_images", [])
}

# 4. Generate ad creative (headline, angle, prompt)
agent = AdCreativeAgent()
result = await agent.generate_ad_creative(
    product_name="Example Company",
    product_description="Security services",
    target_audience="Business Owners",
    logo_url=logo_url,
    brand_color=vision_analysis.get("brand_colors", ["#000000"])[0],
    visual_profile=visual_profile
)

print(f"Headline: {result['headline']}")
print(f"Image Prompt: {result['image_prompt']}")

# 5. Generate actual image with Gemini (with reference images)
generator = GeminiImageGenerator()

# Prepare reference images
reference_images = []
for url in visual_profile.get("uniform_images", [])[:2]:
    reference_images.append({"url": url, "type": "uniform"})
for url in visual_profile.get("vehicle_images", [])[:1]:
    reference_images.append({"url": url, "type": "vehicle"})

gen_result = await generator.generate_ad_image(
    prompt=result["image_prompt"],
    logo_url=logo_url,
    reference_images=reference_images,
    output_path="output/ad_image.png"
)

if gen_result["success"]:
    print(f"Image saved to: {gen_result['image_path']}")
```

---

## Test Scripts

- `test_gemini_image_gen.py` - Full E2E test with Gemini image generation
- `test_real_e2e_flow.py` - E2E test for ad set generation (without image generation)

---

## Campaign Data Isolation (FIXED)

### Problem
When scraping a URL (e.g., `edgarsstores.co.zw` for clothing), the generated campaign contained "SecureSights" (a different security company) content because store data was being passed to the AI.

### Root Cause
The `store.store_name` from the database was being passed to AI prompts, causing data leakage when the store was previously used for a different business.

### Solution Implemented

**File: `modules/campaigns/service.py`**

1. **Line 130** - `scrape_url_for_campaign()`:
```python
# IMPORTANT: When scraping a NEW URL, use ONLY the scraped data
# DO NOT use ANY store data (store_name, business_type, etc.)
store_context = None  # Pass nothing - AI will derive everything from scraped content
```

2. **Lines 279-283** - `_generate_ad_content()`:
```python
# NOTE: We intentionally do NOT pass any store context to the AI
# The AI should determine business name, type, and everything else from SCRAPED CONTENT ONLY
store_info_section = ""  # Empty - AI derives everything from scraped content
```

3. **Lines 488-491** - `_create_ad_sets()`:
```python
# IMPORTANT: Use SCRAPED data from the current URL, NOT store data
# Always use business_name from AI-generated content (derived from scraped URL)
store_name = business_name  # From ad_content - determined by AI from scraped content
```

**File: `modules/campaigns/router.py`**

4. **Lines 763-767** - Regenerate endpoint:
```python
# IMPORTANT: Do NOT pass any store context for regeneration
# The AI should determine business name, type, and everything else from SCRAPED CONTENT ONLY
store_context = None  # AI derives everything from scraped content
```

### Result
- Scraping `edgarsstores.co.zw` now produces "Edgars" campaigns with clothing content
- No references to "SecureSights" or security services
- Each URL scrape is fully isolated from store database records

---

## Next Steps (Priority Order)

### HIGH Priority
1. **Integrate Gemini with campaign service** - Connect `GeminiImageGenerator` to `_create_ad_sets()` in `modules/campaigns/service.py`
2. **Cloud storage for images** - Upload generated images to Cloudinary instead of saving locally

### MEDIUM Priority
3. **Batch generation** - Generate images for all 5 ad sets in parallel
4. **Retry logic** - Handle API rate limits, network timeouts, and transient failures

### LOW Priority
5. **Aspect ratio variations** - Generate 1:1, 16:9, 9:16 for different ad placements
6. **A/B testing variants** - Generate multiple image options per ad set

# Fully Autonomous Ad Creative System - Implementation Plan

## Vision

Given **only a website URL**, the system should:
1. **Fully understand** the company (brand, products, services, visual identity)
2. **Extract everything** (logos, colors, uniforms, vehicles, products, style)
3. **Create ad images** that look like they belong to the website - as if made by the same designer
4. **Zero hardcoding** - works for any business type automatically

---

## Current State vs Target State

### What We Have Now

| Component | Status | Limitation |
|-----------|--------|------------|
| Website scraping | WORKING | Text content only, limited image extraction |
| Logo extraction | WORKING | Basic - may miss logos on some sites |
| Brand color extraction | WORKING | From logo only, misses full color palette |
| Uniform detection | PARTIAL | Identifies uniforms but doesn't capture style details |
| Vehicle detection | PARTIAL | Identifies vehicles but doesn't capture branding details |
| Product extraction | NOT DONE | No product catalog extraction |
| Visual style understanding | NOT DONE | Doesn't understand design style, typography, tone |
| Image generation | WORKING | Generic - doesn't match website's visual style |

### What We Need (Target State)

| Component | Target |
|-----------|--------|
| Deep brand analysis | Extract complete brand identity (colors, fonts, tone, style) |
| Visual asset extraction | All images categorized (team, products, vehicles, office, etc.) |
| Product catalog | Extract all products/services with images and descriptions |
| Style DNA | Understand the visual style (modern, traditional, luxury, etc.) |
| Reference image selection | Intelligently select best reference images for each ad |
| Style-matched generation | Generate images that match website's exact visual style |

---

## The Problem

**Current:** We pass reference images to Gemini, but:
- Gemini creates **new** images inspired by references
- Generated images look **AI-generated**, not like the website
- No understanding of the **brand's visual DNA**

**Target:** Generated images should:
- Look like they were **taken from the website** or made by the **same designer**
- Match the exact **style, colors, quality, and feel**
- Be indistinguishable from the company's actual marketing materials

---

## Implementation Plan

### Phase 1: Deep Brand Analysis (Foundation)

**Goal:** Extract complete brand identity from website

#### 1.1 Enhanced Image Extraction
```
Current: Extract ~20 images, basic categorization
Target:  Extract ALL images, smart categorization
```

**Implementation:**
- Crawl multiple pages (home, about, services, gallery, team)
- Extract all images above 200x200px
- Categorize using Vision AI:
  - `hero_images` - Main banner/hero images
  - `team_images` - Staff photos, group shots
  - `product_images` - Products/services
  - `vehicle_images` - Company vehicles/fleet
  - `office_images` - Office/facility photos
  - `logo_variations` - All logo versions (color, white, icon)
  - `lifestyle_images` - Lifestyle/context images
  - `icon_graphics` - Icons, graphics, illustrations

#### 1.2 Brand DNA Extraction
```
New component: BrandDNAExtractor
```

**Extract:**
```python
{
    "brand_identity": {
        "primary_colors": ["#005B5C", "#FFFFFF"],
        "secondary_colors": ["#4B7F99", "#F5F5F5"],
        "accent_colors": ["#FF6B00"],
        "color_usage": "Primary green for headers, white backgrounds, orange CTAs"
    },
    "visual_style": {
        "style_category": "professional_corporate",  # or: modern_minimal, luxury_elegant, friendly_casual, bold_vibrant
        "photography_style": "professional_studio",  # or: lifestyle_candid, product_focused, documentary
        "image_treatment": "high_contrast_saturated",  # or: soft_muted, black_white, warm_tones
        "composition": "centered_subjects",  # or: rule_of_thirds, asymmetric, full_bleed
    },
    "typography_style": {
        "heading_style": "bold_sans_serif",
        "body_style": "clean_readable",
        "tone": "professional_authoritative"  # or: friendly_casual, luxury_refined, technical_precise
    },
    "brand_elements": {
        "logo_placement": "top_left",
        "badge_style": "shield_emblem",
        "graphic_elements": ["diagonal_lines", "shield_shapes"]
    }
}
```

#### 1.3 Product/Service Extraction
```
New component: ProductExtractor
```

**Extract:**
```python
{
    "products": [
        {
            "name": "Armed Response",
            "description": "24/7 armed security response service",
            "image_urls": ["url1", "url2"],
            "category": "security_services",
            "key_features": ["24/7 availability", "Armed personnel", "Rapid response"]
        },
        ...
    ],
    "service_categories": ["guarding", "armed_response", "monitoring", "investigations"]
}
```

---

### Phase 2: Visual Asset Intelligence

**Goal:** Intelligently select and use reference images

#### 2.1 Reference Image Scoring
```
New component: ReferenceImageScorer
```

**Score images on:**
- **Quality** (resolution, clarity, professional look)
- **Relevance** (matches ad set topic)
- **Brand representation** (shows uniforms, vehicles, branding)
- **Composition** (usable as reference for ad creation)

**Output:** Ranked list of best reference images per ad set

#### 2.2 Asset-to-AdSet Matching
```
For each ad set, select most relevant references:

Ad Set: "Security Guards for Retail"
→ Select: team photos showing guards in retail environment
→ Select: uniform close-ups showing badges/branding
→ Select: any retail-related images

Ad Set: "Vehicle Patrol Services"
→ Select: vehicle images showing branded cars/trucks
→ Select: patrol/mobile response images
→ Select: action shots of vehicles
```

---

### Phase 3: Style-Matched Image Generation

**Goal:** Generate images that match the website's exact style

#### 3.1 Style Transfer Prompt Engineering
```
Current prompt: "Create an ad for security company with green uniforms"
Target prompt:  "Create an image matching THIS EXACT STYLE..."
```

**Enhanced prompt structure:**
```
VISUAL STYLE REQUIREMENTS:
- Match the professional corporate photography style seen in the reference images
- Use the exact color palette: primary #005B5C, accents white and orange
- Photography should be high-contrast, saturated, professional studio quality
- Subjects should be centered with clean backgrounds
- Lighting: Professional studio lighting with soft shadows

BRAND ELEMENTS TO INCLUDE:
- Staff wearing EXACT uniforms from reference (dark green tactical, company badges)
- If vehicles shown, match EXACT branding (white base, green logo placement)
- Logo placement: bottom-right corner, use provided logo exactly

COMPOSITION:
- 1:1 square format for social media
- Subject fills 60-70% of frame
- Clean, uncluttered background matching brand colors
- Professional, trustworthy feel

DO NOT:
- Create cartoon or illustrated styles
- Use generic stock photo aesthetics
- Modify the uniform colors or vehicle branding
- Add elements not seen in the reference images
```

#### 3.2 Multi-Reference Image Strategy
```
Pass to Gemini:
1. Logo (exact, for placement)
2. Best uniform image (for staff appearance)
3. Best vehicle image (if relevant to ad)
4. Hero/style image (for overall visual style)
5. Product image (if relevant to ad)
```

#### 3.3 Style Consistency Verification
```
New component: StyleConsistencyChecker
```

After generation, verify:
- Color palette matches (within tolerance)
- Style category matches (professional, casual, etc.)
- Brand elements present (logo, colors)
- Quality meets standards

If verification fails → regenerate with adjusted prompt

---

### Phase 4: Autonomous Decision Making

**Goal:** System makes all decisions without hardcoding

#### 4.1 Business Type Auto-Detection
```
Current: Hardcoded industry mapping
Target:  AI-determined business classification
```

**Use LLM to determine:**
```python
{
    "business_type": "security_services",
    "business_model": "B2B",
    "target_market": "commercial_properties",
    "service_delivery": "on_site_personnel",
    "visual_requirements": {
        "must_show": ["uniformed_staff", "professional_equipment"],
        "should_show": ["branded_vehicles", "monitoring_technology"],
        "avoid": ["weapons_focus", "aggressive_imagery"]
    }
}
```

#### 4.2 Ad Strategy Auto-Generation
```
Based on business analysis, automatically determine:
- Best ad angles (what to highlight)
- Target audiences (who to reach)
- Visual approaches (what to show)
- Messaging tone (how to communicate)
```

#### 4.3 Self-Improving Feedback Loop
```
Future: Track ad performance → adjust generation strategy
```

---

## Technical Architecture

### New Components to Build

```
modules/
├── brand_intelligence/
│   ├── brand_dna_extractor.py      # Extract complete brand identity
│   ├── visual_style_analyzer.py    # Analyze visual style (photography, colors, composition)
│   ├── product_extractor.py        # Extract products/services catalog
│   └── asset_categorizer.py        # Categorize all extracted images
│
├── reference_intelligence/
│   ├── reference_scorer.py         # Score and rank reference images
│   ├── asset_matcher.py            # Match assets to ad sets
│   └── style_consistency.py        # Verify generated images match style
│
├── autonomous_generation/
│   ├── style_prompt_builder.py     # Build style-matched prompts
│   ├── multi_reference_generator.py # Generate with multiple references
│   └── quality_verifier.py         # Verify output quality
```

### Enhanced Data Flow

```
URL Input
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  PHASE 1: Deep Brand Analysis                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ Image       │  │ Brand DNA   │  │ Product     │      │
│  │ Extraction  │→ │ Extractor   │→ │ Extractor   │      │
│  │ (All pages) │  │ (Style,     │  │ (Catalog)   │      │
│  └─────────────┘  │ colors,tone)│  └─────────────┘      │
│                   └─────────────┘                        │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  PHASE 2: Visual Asset Intelligence                      │
│  ┌─────────────┐  ┌─────────────┐                       │
│  │ Asset       │  │ Reference   │                       │
│  │ Categorizer │→ │ Scorer      │                       │
│  │ (team,      │  │ (quality,   │                       │
│  │ products,   │  │ relevance)  │                       │
│  │ vehicles)   │  └─────────────┘                       │
│  └─────────────┘                                         │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  PHASE 3: Style-Matched Generation                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ Style       │  │ Multi-Ref   │  │ Quality     │      │
│  │ Prompt      │→ │ Generator   │→ │ Verifier    │      │
│  │ Builder     │  │ (Gemini)    │  │ (Style      │      │
│  └─────────────┘  └─────────────┘  │ match check)│      │
│                                     └─────────────┘      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
Final Ad Images (Style-matched, brand-consistent)
```

---

## Implementation Priority

### Sprint 1: Foundation (Brand DNA) - COMPLETED

1. [x] Build `BrandDNAExtractor` - extract complete brand identity
2. [x] Enhance image extraction - crawl all pages, extract all images
3. [x] Build `AssetCategorizer` - categorize images by type
4. [x] Build `VisualStyleAnalyzer` - analyze photography/design style
5. [x] Integrate with campaign service

**Files Created:**
- `modules/brand_intelligence/__init__.py`
- `modules/brand_intelligence/brand_dna_extractor.py`
- `modules/brand_intelligence/asset_categorizer.py`
- `modules/brand_intelligence/visual_style_analyzer.py`
- `test_brand_dna.py`

**Integration:**
- Updated `modules/campaigns/service.py` to use `BrandDNAExtractor`
- Style prompt now included in Gemini image generation

### Sprint 2: Intelligence (Reference Selection) - PENDING
1. [ ] Build `ReferenceScorer` - score images on quality/relevance
2. [ ] Build `AssetMatcher` - match best assets to each ad set
3. [ ] Improve Vision AI prompts for better analysis

### Sprint 3: Generation (Style Matching) - PENDING
1. [ ] Build `StylePromptBuilder` - create detailed style-matched prompts
2. [ ] Implement multi-reference strategy (5+ images per generation)
3. [ ] Build `QualityVerifier` - verify style consistency

### Sprint 4: Autonomy (Self-Deciding) - PENDING
1. [ ] Remove all hardcoded industry mappings
2. [ ] LLM-based business type detection
3. [ ] Auto-generate ad strategies based on analysis

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Brand color accuracy | ~70% | 95%+ |
| Uniform accuracy | ~50% | 90%+ |
| Style consistency | Low | High (human-indistinguishable) |
| Manual intervention needed | Often | Never |
| Works for any business | No (security-focused) | Yes (fully autonomous) |

---

## Example: Fully Autonomous Flow

**Input:** `https://securico.co.zw`

**Step 1: Brand DNA Extraction**
```json
{
  "company_name": "Securico Security Services",
  "industry": "security_services",
  "brand_colors": {
    "primary": "#005B5C",
    "secondary": "#FFFFFF",
    "accent": "#4B7F99"
  },
  "visual_style": "professional_corporate",
  "photography_style": "professional_studio",
  "brand_elements": {
    "logo_type": "shield_emblem",
    "uniform_style": "tactical_green_with_badges",
    "vehicle_branding": "white_base_green_logo"
  }
}
```

**Step 2: Asset Extraction & Categorization**
```json
{
  "team_images": [
    {"url": "...", "quality_score": 0.9, "shows": ["uniformed_staff", "professional_pose"]},
    {"url": "...", "quality_score": 0.7, "shows": ["group_photo", "office_setting"]}
  ],
  "vehicle_images": [
    {"url": "...", "quality_score": 0.85, "shows": ["branded_truck", "fleet_view"]}
  ],
  "service_images": [
    {"url": "...", "quality_score": 0.8, "shows": ["guard_at_gate", "access_control"]}
  ]
}
```

**Step 3: Ad Set Generation (Autonomous)**
```
Ad Set 1: "Property Management Security"
- Selected references: team_image[0], vehicle_image[0], logo
- Generated image: Guard in exact Securico uniform at property entrance
- Style: Matches website's professional photography style

Ad Set 2: "24/7 Armed Response"
- Selected references: vehicle_image[0], team_image[1], logo
- Generated image: Securico vehicle responding, exact branding
- Style: Action shot matching website's dynamic imagery
```

**Output:** 5 ad images that look like they came from Securico's own marketing team

---

## Files to Create

| File | Purpose |
|------|---------|
| `modules/brand_intelligence/brand_dna_extractor.py` | Extract complete brand identity |
| `modules/brand_intelligence/visual_style_analyzer.py` | Analyze photography and design style |
| `modules/brand_intelligence/product_extractor.py` | Extract product/service catalog |
| `modules/brand_intelligence/asset_categorizer.py` | Categorize all images |
| `modules/reference_intelligence/reference_scorer.py` | Score reference image quality |
| `modules/reference_intelligence/asset_matcher.py` | Match assets to ad sets |
| `modules/autonomous_generation/style_prompt_builder.py` | Build style-matched prompts |
| `modules/autonomous_generation/quality_verifier.py` | Verify output quality |

---

## Conclusion

The key to fully autonomous, style-matched ad generation is:

1. **Deep Understanding** - Extract complete brand DNA, not just colors
2. **Smart Selection** - Choose the best reference images for each ad
3. **Style Matching** - Generate images that match the exact visual style
4. **Zero Hardcoding** - Let AI make all decisions based on analysis

This transforms the system from "AI that generates ads" to "AI that extends the brand's visual identity."

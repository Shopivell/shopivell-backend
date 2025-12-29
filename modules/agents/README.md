# AI Agents Module - Shopivell Ad Generation System

## System Architecture

```
                              USER INPUT (Campaign Brief)
                                        |
                                        v
                    +------------------------------------------+
                    |      CREATIVE STRATEGIST AGENT          |
                    |         (GPT-4o via OpenRouter)          |
                    |  - Analyzes audience & objectives        |
                    |  - Generates 3-5 creative angles         |
                    |  - Selects emotional hooks               |
                    +------------------------------------------+
                                        |
                                        v
              +-------------------------+-------------------------+
              |                         |                         |
              v                         v                         v
+---------------------------+  +---------------------------+  +---------------------------+
|   COPYWRITER AGENT        |  |  AD COPY AGENT            |  |  VISUAL DIRECTOR AGENT    |
|   (Claude Sonnet)         |  |  (Claude Sonnet)          |  |  (Claude Sonnet)          |
| - Meta ad copy            |  | - Headlines & CTAs        |  | - Image prompts           |
| - Primary text            |  | - Variations              |  | - Video concepts          |
| - Hashtags                |  | - A/B test versions       |  | - Shot breakdowns         |
+---------------------------+  +---------------------------+  +---------------------------+
              |                         |                         |
              +-------------------------+-------------------------+
                                        |
                                        v
                    +------------------------------------------+
                    |        COMPLIANCE AGENT                  |
                    |         (Claude Haiku)                   |
                    |  - Meta policy checking                  |
                    |  - Content safety validation             |
                    |  - Prompt sanitization                   |
                    +------------------------------------------+
                                        |
                         +--------------+--------------+
                         |                             |
                    COMPLIANT?                    NOT COMPLIANT
                         |                             |
                         v                             v
                    PROCEED               FEEDBACK LOOP #1
                         |              (Regenerate with suggestions)
                         |                             |
                         +<----------------------------+
                         |
                         v
                    +------------------------------------------+
                    |       MEDIA GENERATOR AGENT              |
                    |  Images: Nano Banana Pro (Gemini 3)      |
                    |  Videos: Veo 3.1 Fast                    |
                    +------------------------------------------+
                                        |
                                        v
                    +------------------------------------------+
                    |       AD CREATIVE AGENT                  |
                    |         (Claude Sonnet)                  |
                    |  - Final creative assembly               |
                    |  - Image + Copy combination              |
                    +------------------------------------------+
                                        |
                                        v
                    +------------------------------------------+
                    |         META ADS API                     |
                    |  - Campaign creation                     |
                    |  - Ad set configuration                  |
                    |  - Creative upload                       |
                    +------------------------------------------+
                                        |
                                        v
                    +------------------------------------------+
                    |       PERFORMANCE OPTIMIZER AGENT        |
                    |         (GPT-4o)                         |
                    |  - A/B test analysis                     |
                    |  - Performance metrics                   |
                    |  - Budget recommendations                |
                    +------------------------------------------+
                                        |
                                        v
                         FEEDBACK LOOP #2
                    (If underperforming, trigger new creative)
                                        |
                         +<-------------+
                         |
                    Back to Creative Strategist
```

## Model Assignments

| Task Type | Model | Reasoning |
|-----------|-------|-----------|
| Strategy/Research | GPT-4o | Best for complex analysis |
| Creative Writing | Claude Sonnet | Superior nuanced copy |
| Policy Checking | Claude Haiku | Fast, cheap, context-aware |
| Image Generation | Nano Banana Pro | Best quality, native text, $0.04/image |
| Video Generation | Veo 3.1 Fast | Best quality, native audio, $0.15/sec |

## Agents (10 Total)

| # | Agent | Model | Purpose | Cost Est. |
|---|-------|-------|---------|-----------|
| 1 | Creative Strategist | GPT-4o | Strategy & hooks generation | ~$0.01/campaign |
| 2 | Copywriter | Claude Sonnet | Meta ad copy writing | ~$0.005/variation |
| 3 | Ad Copy | Claude Sonnet | Headlines & CTAs | ~$0.003/ad |
| 4 | Visual Director | Claude Sonnet | Image/video prompts | ~$0.005/prompt |
| 5 | Ad Creative | Claude Sonnet | Final creative assembly | ~$0.003/creative |
| 6 | Compliance | Claude Haiku | Policy checking | ~$0.0003/check |
| 7 | Media Generator | Nano Banana Pro / Veo 3 | Image & video generation | ~$0.04/img, $0.15/sec |
| 8 | Performance Optimizer | GPT-4o | Performance analysis | ~$0.01/analysis |

**Estimated Total Cost per Ad Creative: ~$0.10 - $1.50** (depending on video inclusion)

## Industry Templates (10 Industries)

Meta-safe templates with specific backgrounds, subjects, props, and avoidance rules:

| Industry | Key Features |
|----------|-------------|
| `security` | No weapons, focus on technology and monitoring |
| `food_restaurant` | Appetizing imagery, no health claims |
| `retail_ecommerce` | Product focus, clean composition |
| `tech_saas` | Modern interfaces, no fake data |
| `beauty_cosmetics` | Product shots, no before/after |
| `health_fitness` | Equipment focus, no body transformation |
| `real_estate` | Property features, no discriminatory content |
| `professional_services` | Trust signals, no guaranteed results |
| `education` | Learning materials, no job guarantees |
| `automotive` | Vehicle details, no dangerous driving |

## Feedback Loops

### Loop #1: Compliance Feedback
When content violates Meta policy, the Compliance Agent provides suggestions and triggers regeneration through the Visual Director.

### Loop #2: Optimizer Feedback
When ads underperform (low CTR, high CPA, low ROAS), the Performance Optimizer triggers new creative generation through the Creative Strategist.

## File Structure

```
modules/agents/
├── README.md                      # This file
├── __init__.py                    # Agent exports
├── models.py                      # Database models
├── creative_strategist_agent.py   # Strategy & hooks (GPT-4o)
├── copywriter_agent.py            # Ad copy writing (Claude Sonnet)
├── ad_copy_agent.py               # Headlines & CTAs (Claude Sonnet)
├── visual_director_agent.py       # Visual prompts (Claude Sonnet)
├── ad_creative_agent.py           # Creative assembly (Claude Sonnet)
├── compliance_agent.py            # Policy checking (Claude Haiku)
├── media_generator_agent.py       # Image/Video gen (Nano Banana/Veo 3)
└── performance_optimizer_agent.py # Performance (GPT-4o)
```

## Environment Variables

```env
# Required
OPENROUTER_API_KEY=your_openrouter_key
GEMINI_API_KEY=your_gemini_key

# Optional fallbacks
OPENAI_API_KEY=your_openai_key
STABILITY_API_KEY=your_stability_key
REPLICATE_API_TOKEN=your_replicate_key
RUNWAY_API_KEY=your_runway_key
LUMA_API_KEY=your_luma_key
```

## Usage Example

```python
from modules.agents import (
    CreativeStrategistAgent,
    CopywriterAgent,
    VisualDirectorAgent,
    ComplianceAgent,
    MediaGeneratorAgent
)

# 1. Generate creative strategy
strategist = CreativeStrategistAgent()
angles = await strategist.generate_angles(campaign)

# 2. Generate copy for each angle
copywriter = CopywriterAgent()
copies = await copywriter.generate_all_copy(campaign)

# 3. Generate visual prompts
visual_director = VisualDirectorAgent()
visuals = await visual_director.generate_full_visual_package(campaign, angle)

# 4. Check compliance
compliance = ComplianceAgent()
check = await compliance.check_compliance(
    visuals["image_prompt"],
    {"industry": "security"}
)

# 5. Generate final media (with industry template)
if check["is_compliant"]:
    generator = MediaGeneratorAgent()
    image = await generator.generate_industry_ad_image(
        industry="security",
        product_name=campaign.product_name,
        product_description=campaign.product_description,
        headline_text=copies[0]["headline"]
    )
```

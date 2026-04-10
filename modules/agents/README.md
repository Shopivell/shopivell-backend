# AI Agents Module - Shopivell Ad Generation System

## Agent Responsibilities

| Agent | Single Job |
|-------|-----------|
| **Market Research Agent** | "WHAT exists" — scrapes websites, finds competitors, trends, keywords |
| **Creative Strategist** | "WHO to target" — generates audiences, Meta interest targeting, hooks |
| **Creative Angles** | "WHAT angle to take" — generates positioning per audience |
| **Ad Copy Agent** | "WHAT to say" — writes copy for a given audience + angle |
| **Ad Creative Agent** | "WHAT to show" — generates image prompts for a given angle |

## Pipeline Architecture

```
                         Website URL / Campaign Brief
                                    |
                                    v
                 +--------------------------------------+
                 |       MARKET RESEARCH AGENT          |
                 |         (Claude Sonnet 4)            |
                 |                                      |
                 |  - Scrapes website (Tavily/BS4/PW)   |
                 |  - Finds competitors (Serper+Tavily) |
                 |  - Industry trends (Tavily+Serper)   |
                 |  - Keyword discovery (Autocomplete)  |
                 |  - Structured data extraction (AI)   |
                 +--------------------------------------+
                                    |
                    Research data flows into all agents
                                    |
         +-------------+------------+------------+-------------+
         |             |            |            |             |
         v             v            v            v             v
   +-----------+ +-----------+ +---------+ +-----------+ +---------+
   |   SWOT    | | Creative  | | Ad Copy | |Ad Creative| |Screenshot|
   | Analysis  | | Strategist| |  Agent  | |   Agent   | | Capture |
   |   (AI)    | | (audiences| | (copy)  | | (images)  | |(Playwright)
   +-----------+ +-----------+ +---------+ +-----------+ +---------+
                       |              |
                       |    Audiences flow into Ad Copy
                       +-------->-----+
```

## How They Connect

### Standalone Research (POST /api/agents/research/website)

All run in parallel after data collection:
1. **SWOT** — AI analyzes strengths/weaknesses/opportunities/threats
2. **Creative Strategist** — generates 4-5 targetable audiences
3. **Ad Copy Agent** — receives audiences from Strategist, generates copy per audience x platform
4. **Ad Creative Agent** — generates 2 image prompts (Trust + Problem/Solution angles)
5. **Screenshot** — captures homepage via Playwright

### Campaign Pipeline (POST /api/agents/campaigns/{id}/pipeline)

Sequential steps:
1. **Market Research Agent** — full research on campaign URL
2. **Creative Angles Agent** — generates 3-10 positioning angles
3. **Ad Copy Agent** — generates copy for each angle
4. **Visual Director Agent** — generates image/video prompts per angle

## Agent Details

### Market Research Agent (`market_research_agent.py`)

**Input:** Website URL
**Output:** Company info, services, competitors, trends, audience insights, keywords, SWOT, ad copy, creatives, screenshot

Data sources:
- Tavily (website scraping + search)
- Serper (Google SERP + Maps + related searches)
- DataForSEO (competitor keyword overlap)
- Google Autocomplete (keyword suggestions)
- Playwright (JS-rendered pages)
- BeautifulSoup (HTML fallback)

### Creative Strategist (`creative_strategist_agent.py`)

**Input:** Research data (services, value props, location, website audiences)
**Output:** Targetable audience segments with demographics, pain points, urgency, platform, CTA

Also provides:
- Meta interest targeting tags (25-40 tags across 6 categories)
- Audience demographics (age, gender, location, languages)
- Job titles and industries to target
- Custom audience suggestions (lookalikes, website visitors)
- Ad set recommendations

### Creative Angles Agent (`creative_angles_agent.py`)

**Input:** Campaign brief + market research
**Output per angle:**
- `angle_name` — e.g. "Trust Builder", "Fear of Missing Out"
- `value_proposition` — unique value this angle presents
- `emotion_target` — emotion to evoke (relief, excitement, fear)
- `visual_direction` — what the image should look like
- `reasoning` — why this angle fits the research

### Ad Copy Agent (`ad_copy_agent.py`)

**Input:** Research data + audiences (from Creative Strategist)
**Output per audience x platform:**
- Hooks (3 types: pattern interrupt, question, social proof)
- Headlines (3 variations, max 40 chars)
- Primary Text (short/medium/long or story/benefits/urgency)
- Descriptions (2 variations, max 30 words)
- Call to Action (from Meta's available CTAs)

Supports B2B (LinkedIn-style) and B2C (consumer-style) copy.

### Ad Creative Agent (`ad_creative_agent.py`)

**Input:** Product info + creative angle
**Output:**
- `image_prompt` — detailed 10-element prompt for AI image generation
- `ad_angle` — 1-2 sentence creative direction
- `headline` — short headline for text overlay
- `bullet_points` — 3 key benefits
- `cta_text` — button text

Image prompts follow a strict format: art style, scene setup, subject, action, scenario, lighting, lens/camera, color theme, mood, technical specs. Generates CLEAN base images with no text — leaves space for programmatic text overlay.

## Model Assignments

| Agent | Model | Via |
|-------|-------|-----|
| Market Research (extraction) | Claude Sonnet 4 | OpenRouter / Anthropic direct |
| Creative Strategist | Claude Sonnet 4 | OpenRouter / Anthropic direct |
| Creative Angles | Claude Sonnet 4 | OpenRouter / Anthropic direct |
| Ad Copy Agent | Claude Sonnet 4 | OpenRouter / Anthropic direct |
| Ad Creative Agent | Claude Sonnet 4 (primary), GPT-4o (fallback) | OpenRouter |
| Copywriter Agent | Claude Sonnet 4 | OpenRouter / Anthropic direct |

All agents use OpenRouter as primary with Anthropic SDK as fallback.

## API Endpoints

### Research
| Method | Endpoint | Agent |
|--------|----------|-------|
| POST | `/api/agents/research/website?url=...` | Market Research + all agents |
| POST | `/api/agents/campaigns/{id}/research` | Market Research (campaign) |

### Audiences & Strategy
| Method | Endpoint | Agent |
|--------|----------|-------|
| POST | `/api/agents/audience/generate?url=...` | Creative Strategist |
| POST | `/api/agents/audience/compare` | Creative Strategist |

### Creative Angles
| Method | Endpoint | Agent |
|--------|----------|-------|
| POST | `/api/agents/campaigns/{id}/angles` | Creative Angles |
| GET | `/api/agents/campaigns/{id}/angles` | (DB lookup) |

### Ad Copy
| Method | Endpoint | Agent |
|--------|----------|-------|
| POST | `/api/agents/campaigns/{id}/copy` | Ad Copy Agent |
| POST | `/api/agents/ad-copy/from-research` | Ad Copy Agent |

### Full Pipeline
| Method | Endpoint | Agents |
|--------|----------|--------|
| POST | `/api/agents/campaigns/{id}/pipeline` | All (sequential) |

## Environment Variables

```env
# Required
OPENROUTER_API_KEY=your_openrouter_key    # Routes to Claude/GPT-4o
TAVILY_API_KEY=your_tavily_key            # Website scraping + search
SERPER_API_KEY=your_serper_key            # Google SERP + Maps

# Optional
ANTHROPIC_API_KEY=your_anthropic_key      # Direct fallback
OPENAI_API_KEY=your_openai_key            # GPT-4o fallback
DATAFORSEO_LOGIN=your_login               # Competitor keyword data
DATAFORSEO_PASSWORD=your_password
META_ACCESS_TOKEN=your_meta_token         # Ad Library access
SCREENSHOTONE_ACCESS_KEY=your_key         # Screenshot fallback
```

## File Structure

```
modules/agents/
├── README.md                         # This file
├── __init__.py                       # Agent exports
├── models.py                         # Database models (Campaign, MarketResearch, CreativeAngle, AdCopy)
├── router.py                         # API endpoints
├── schemas.py                        # Request/response schemas
│
├── market_research_agent.py          # Research orchestrator
├── creative_strategist_agent.py      # Audience + targeting generation
├── creative_angles_agent.py          # Creative angle positioning
├── ad_copy_agent.py                  # Ad copy generation (B2B + B2C)
├── ad_creative_agent.py              # Image prompt generation
│
├── copywriter_agent.py               # Meta copy (used in campaign service)
├── visual_director_agent.py          # Visual direction (used in pipeline)
├── compliance_agent.py               # Meta policy checking
├── media_generator_agent.py          # Image/video generation (Gemini/Veo)
├── monitor_optimizer_agent.py        # Performance optimization
└── competitive_intelligence_agent.py # DataForSEO competitor analysis
```

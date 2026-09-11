# market-research

OpenClaw skill — the **agentic/reasoning layer** for market research. Deterministic
data gathering (scraping, competitors, keyword demand, trends) lives in the
Shopivell backend and is exposed at `/v1/api/research/*`; this skill calls those
APIs and reasons over the results with the model.

## Architecture
```
market-research skill  ──calls──►  {SHOPIVELL_API_URL}/api/research/*  (X-Research-Token)
     │                                   ├─ /competitors  (Serper: organic + Maps)
     │                                   ├─ /keywords     (autocomplete + Serper + Keywords Everywhere volume)
     │                                   ├─ /trends       (Tavily + Serper)
     │                                   └─ /extract      (LLM structured business profile)
     └── model reasoning: SWOT, audience insights, creative angles
```

## Environment
- `SHOPIVELL_API_URL` — e.g. `https://api.shopivell.com/v1`
- `RESEARCH_SERVICE_TOKEN` — shared secret; sent as `X-Research-Token` (must match the backend)

## Actions

### analyze
Full market analysis for a business/website.

**Parameters**
- `url` (string) — the business website
- `content` (string, optional) — scraped page text, for structured extraction
- `business_type` (string, optional) — used if extraction is unavailable
- `location` (string, optional)
- `country_code` (string, default `US`)
- `company_name` (string, optional)
- `products` (string[], optional)

**Returns**
`business_type, company_name, products, geographic_coverage, competitors[],
keywords[] (with volume when Keywords Everywhere is funded), trends[],
swot{strengths,weaknesses,opportunities,threats},
audience_insights{demographics,psychographics,pain_points,buying_triggers},
angles[{angle_name,value_proposition,emotion_target,visual_direction}]`

## Notes
- Data sources' keys live on the backend (Serper, Tavily, Keywords Everywhere).
- The reasoning uses OpenClaw's configured model (Claude).
- Every backend call degrades gracefully — partial data still returns.

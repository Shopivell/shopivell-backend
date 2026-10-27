---
name: market-research
description: "Market research for a business or website: real competitors, keyword demand and industry trends from the Shopivell backend, reasoned into SWOT, audience insights and ad angles."
metadata:
  {
    "openclaw":
      {
        "emoji": "🔎",
        "requires": { "bins": ["curl"] },
      },
  }
---

# market-research

The reasoning layer for market research. Deterministic data gathering (competitor
discovery, keyword demand, trends, website extraction) lives in the Shopivell
backend at `/v1/api/research/*`; this skill calls those endpoints and reasons over
the results.

## Setup

Both come from the environment (already set in `/opt/openclaw/.env`):

- `SHOPIVELL_API_URL` — e.g. `https://api.shopivell.com/v1`
- `RESEARCH_SERVICE_TOKEN` — sent as the `X-Research-Token` header

Every call is `POST`, JSON in, JSON out:

```bash
curl -s -X POST "$SHOPIVELL_API_URL/api/research/<endpoint>" \
  -H "X-Research-Token: $RESEARCH_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

Check the backend is reachable first: `GET $SHOPIVELL_API_URL/api/research/health`
returns `{"ok":true,"sources":{...}}` and needs no token.

## Endpoints

| Endpoint | Body | Returns |
|---|---|---|
| `/extract` | `content` (scraped page text), `url` | Business profile: `company_name`, `industry`, `services_products`, `value_propositions`, `target_audiences`, `geographic_coverage`, `keyword_seeds` |
| `/competitors` | `business_type`, `location`, `products[]`, `domain`, `country_code`, `company_name` | `competitors[]` with `name`, `url`, `description`, `rating`, `reviews`, `source` |
| `/keywords` | `seeds[]`, `country_code`, `expand_alphabet`, and `business_type`/`location` (used as the seed when `seeds` is empty) | `keywords[]` with `keyword`, `source`, and `volume`/`cpc`/`competition` when Keywords Everywhere has credits |
| `/trends` | `industry`, `year`, `location`, `country_code` (localises the search and drops other-country reports) | `trends[]` with `title`, `source`, `insight` |

## How to run an analysis

1. **Understand the business.** Fetch the site's text (`curl -s <url>`, strip tags) and
   POST it to `/extract`. Use `business_type` (specific, e.g. "computer and IT
   equipment retailer") as the business type — not `industry`, which is a broad sector
   that sends competitor search to consultancies and listicles. Use
   `services_products` as the products, `keyword_seeds` as the keyword seeds, and
   `geographic_coverage` as the location. If extraction returns nothing, fall back to
   what the user told you.
2. **Gather data.** Call `/competitors`, `/keywords` and `/trends` with those values.
   Set `country_code` from the domain's TLD where it's a country (`.co.zw` → `ZW`),
   else the user's market.
3. **Reason over it** and return JSON:

```json
{
  "business_type": "", "company_name": "", "products": [], "geographic_coverage": "",
  "competitors": [], "keywords": [], "trends": [],
  "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
  "audience_insights": {"demographics": "", "psychographics": "", "pain_points": [], "buying_triggers": []},
  "angles": [{"angle_name": "", "value_proposition": "", "emotion_target": "", "visual_direction": ""}]
}
```

Use only the data the endpoints returned — never invent competitors, volumes or
statistics. Say so plainly when a section is thin.

## Notes

- Competitor results can include directory and listicle pages (zimbabweyp,
  "Top 10 ..." articles); prefer entries that are actual businesses, and treat
  Google Maps entries (`source: serper_maps`, with `rating`/`reviews`) as the
  strongest local signal.
- `volume` is absent when Keywords Everywhere is out of credits — rank on relevance
  then, and don't present missing volume as zero demand.
- Each endpoint degrades gracefully: a failure returns an empty list rather than an
  error, so partial data is normal.

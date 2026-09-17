"""
Market Research REST API — the backend tools the OpenClaw market-research skill
calls (OpenClaw does the agentic reasoning; this returns deterministic data).

Mounted at /v1/api/research. Protected by a shared token: set
RESEARCH_SERVICE_TOKEN on the backend and send it from OpenClaw as
`X-Research-Token` (or `Authorization: Bearer <token>`). If the env var is
unset, the endpoints are open (dev only) and a warning is logged.
"""

import os
import logging
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from modules.market_research.service import MarketResearchService

logger = logging.getLogger(__name__)
research_router = APIRouter(prefix="/api/research", tags=["market-research"])

RESEARCH_SERVICE_TOKEN = os.getenv("RESEARCH_SERVICE_TOKEN", "")


def _check_auth(x_research_token: Optional[str], authorization: Optional[str]):
    if not RESEARCH_SERVICE_TOKEN:
        logger.warning("[MarketResearch] RESEARCH_SERVICE_TOKEN not set — /api/research is open")
        return
    supplied = x_research_token or ""
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if supplied != RESEARCH_SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid research service token")


class CompetitorsRequest(BaseModel):
    business_type: str = ""
    location: str = ""
    products: List[str] = []
    domain: Optional[str] = None
    country_code: str = "US"
    company_name: Optional[str] = None


class KeywordsRequest(BaseModel):
    seeds: List[str] = []
    country_code: str = "US"
    expand_alphabet: bool = True
    # Used as the seed when `seeds` is empty (extraction found no products).
    business_type: str = ""
    location: str = ""


class TrendsRequest(BaseModel):
    industry: str
    year: str = "2026"
    # Localise the search and drop reports about other countries.
    location: str = ""
    country_code: str = ""


class ExtractRequest(BaseModel):
    content: str
    url: str = ""


@research_router.get("/health")
def research_health():
    svc = MarketResearchService()
    return {"ok": True, "sources": {
        "serper": svc.serper_available, "tavily": svc.tavily_available,
        "keywords_everywhere": svc.ke_available, "llm": svc._llm_ready(),
    }}


@research_router.post("/competitors")
def competitors(req: CompetitorsRequest,
                x_research_token: Optional[str] = Header(None),
                authorization: Optional[str] = Header(None)):
    _check_auth(x_research_token, authorization)
    svc = MarketResearchService()
    items = [c for c in svc.find_competitors(
        business_type=req.business_type, location=req.location, products=req.products,
        domain=req.domain, country_code=req.country_code, company_name=req.company_name)
        if not c.get("name", "").startswith("__")]
    return {"competitors": items, "count": len(items)}


@research_router.post("/keywords")
def keywords(req: KeywordsRequest,
             x_research_token: Optional[str] = Header(None),
             authorization: Optional[str] = Header(None)):
    _check_auth(x_research_token, authorization)
    svc = MarketResearchService()
    items = svc.find_keywords(req.seeds, req.country_code, req.expand_alphabet,
                              req.business_type, req.location)
    return {"keywords": items, "count": len(items)}


@research_router.post("/trends")
def trends(req: TrendsRequest,
           x_research_token: Optional[str] = Header(None),
           authorization: Optional[str] = Header(None)):
    _check_auth(x_research_token, authorization)
    svc = MarketResearchService()
    items = svc.find_trends(req.industry, req.year, req.location, req.country_code)
    return {"trends": items, "count": len(items)}


@research_router.post("/extract")
async def extract(req: ExtractRequest,
                  x_research_token: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None)):
    _check_auth(x_research_token, authorization)
    svc = MarketResearchService()
    data = await svc._extract_structured_website_data(req.content, req.url)
    return {"data": data}

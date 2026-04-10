# competitive_intelligence_agent.py - AI Agent for Competitive Intelligence
"""
Competitive Intelligence Agent that combines DataForSEO Labs API with Tavily web enrichment.

4-step pipeline:
1. Understand the user's business categories (DataForSEO domain_metrics_by_categories)
2. Discover top competitors (DataForSEO competitors_domain)
3. Analyze competitor keyword strategies (DataForSEO keywords_for_site)
4. Expand top opportunity keywords (reuses KeywordIntelligenceAgent)

Each step is enriched with Tavily web scraping for qualitative context.

Usage:
    agent = CompetitiveIntelligenceAgent()
    result = await agent.run_pipeline(request)
"""

import os
import json
import logging
import asyncio
import base64
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# DataForSEO credentials
DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")
DATAFORSEO_AVAILABLE = bool(DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD)

# Tavily
try:
    from tavily import TavilyClient
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    TAVILY_AVAILABLE = bool(tavily_api_key)
except ImportError:
    TAVILY_AVAILABLE = False
    tavily_api_key = None
    TavilyClient = None

# Redis cache
from utils.cache import RedisCache, CacheConfig

# OpenRouter LLM
_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
if _OPENROUTER_KEY:
    try:
        from modules.openrouter.langchain_adapter import ChatOpenRouter
        OPENROUTER_AVAILABLE = True
    except ImportError:
        from langchain_openai import ChatOpenAI as ChatOpenRouter
        OPENROUTER_AVAILABLE = False
else:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

import requests
from urllib.parse import urlparse

# Serper.dev API for Google SERP results
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_AVAILABLE = bool(SERPER_API_KEY)


class CompetitiveIntelligenceAgent:
    """
    AI Agent for competitive intelligence combining Serper.dev, DataForSEO Labs API,
    Tavily, and Google Autocomplete.

    Given a domain, discovers business categories, competitors, their keyword
    strategies, and expansion opportunities.
    """

    def __init__(self):
        self.dataforseo_available = DATAFORSEO_AVAILABLE
        if self.dataforseo_available:
            creds = f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}"
            self.dataforseo_auth = base64.b64encode(creds.encode()).decode()
        else:
            self.dataforseo_auth = None

        self.tavily = TavilyClient(api_key=tavily_api_key) if TAVILY_AVAILABLE else None
        self.serper_available = SERPER_AVAILABLE
        self.cache = RedisCache()

        logger.info(
            f"[CompetitiveIntelligenceAgent] Initialized - "
            f"DataForSEO: {self.dataforseo_available}, "
            f"Tavily: {TAVILY_AVAILABLE}, Serper: {SERPER_AVAILABLE}"
        )

    # ============ Helpers ============

    def _dataforseo_request(self, endpoint: str, payload: List[Dict]) -> Dict:
        """Make a request to DataForSEO API."""
        try:
            response = requests.post(
                f"https://api.dataforseo.com/v3/{endpoint}",
                headers={
                    "Authorization": f"Basic {self.dataforseo_auth}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[CompetitiveIntelligenceAgent] DataForSEO error on {endpoint}: {e}")
            return {"status_code": 500, "error": str(e)}

    def _get_location_code(self, country_code: str) -> int:
        """Map ISO country code to DataForSEO location code."""
        location_map = {
            "ZW": 2716, "ZA": 2710, "US": 2840, "GB": 2826,
            "CA": 2124, "AU": 2036, "DE": 2276, "FR": 2250,
            "IN": 2356, "NG": 2566, "KE": 2404, "GH": 2288,
            "BW": 2072, "ZM": 2894, "MZ": 2508, "NA": 2516,
            "TZ": 2834, "UG": 2800, "MW": 2454, "ET": 2231
        }
        return location_map.get(country_code.upper(), 2840)

    # ============ Step 1: Domain Categories ============

    def get_domain_categories(
        self,
        domain: str,
        country_code: str = "US",
        language_code: str = "en"
    ) -> List[Dict[str, Any]]:
        """
        Step 1: Understand the user's business by getting domain categories.

        Uses: dataforseo_labs/google/domain_metrics_by_categories/live
        Returns categories like "Security Cameras", "Home Automation" with traffic data.
        """
        if not self.dataforseo_available:
            return []

        # Check cache
        cache_key = f"ci:categories:{domain}:{country_code}"
        cached = self.cache.get(cache_key) if self.cache.is_connected else None
        if cached:
            logger.info(f"[CompetitiveIntelligenceAgent] Cache hit: {cache_key}")
            return cached

        payload = [{
            "target": domain,
            "location_code": self._get_location_code(country_code),
            "language_code": language_code
        }]

        result = self._dataforseo_request(
            "dataforseo_labs/google/domain_metrics_by_categories/live",
            payload
        )

        categories = []
        if result.get("status_code") == 20000:
            tasks = result.get("tasks", [])
            for task in tasks:
                if task.get("status_code") != 20000:
                    logger.warning(f"[CompetitiveIntelligenceAgent] Categories task error: {task.get('status_message')}")
                    continue
                items = task.get("result", [{}])
                for res in items:
                    if not res:
                        continue
                    for item in res.get("items", []):
                        categories.append({
                            "category": item.get("category", ""),
                            "organic_traffic": item.get("metrics", {}).get("organic", {}).get("etv"),
                            "organic_count": item.get("metrics", {}).get("organic", {}).get("count"),
                            "paid_traffic": item.get("metrics", {}).get("paid", {}).get("etv"),
                            "paid_count": item.get("metrics", {}).get("paid", {}).get("count"),
                        })

        # Sort by organic traffic descending
        categories.sort(key=lambda x: x.get("organic_traffic") or 0, reverse=True)

        # Cache results
        if categories and self.cache.is_connected:
            self.cache.set(cache_key, categories, ttl=CacheConfig.TTL_DAY)

        logger.info(f"[CompetitiveIntelligenceAgent] Found {len(categories)} categories for {domain}")
        return categories

    # ============ Serper.dev Helpers ============

    def _serper_search(self, query: str, country: str = "zw", num: int = 10, search_type: str = "search") -> Dict:
        """Search Google via Serper.dev API."""
        if not self.serper_available:
            return {}
        try:
            response = requests.post(
                f"https://google.serper.dev/{search_type}",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "gl": country.lower(), "hl": "en", "num": num},
                timeout=15
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[CompetitiveIntelligenceAgent] Serper error: {e}")
            return {}

    def _discover_competitors_serper(
        self,
        domain: str,
        business_type: str = "",
        location: str = "",
        country_code: str = "zw"
    ) -> List[Dict[str, Any]]:
        """Discover competitors using Serper.dev Google SERP + Maps results."""
        skip_domains = {
            "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
            "youtube.com", "reddit.com", "wikipedia.org", "tiktok.com", "pinterest.com",
            "lusha.com", "zoominfo.com", "crunchbase.com", "glassdoor.com",
            "ensun.io", "techbehemoths.com", "goodfirms.co", "clutch.co",
            "refrens.com", "arounddeal.com", "trustpilot.com", "yelp.com",
            "amazon.com", "ebay.com", "alibaba.com", "classifieds.co.zw",
        }

        own_domain = domain.replace("www.", "").lower()
        seen = set()
        competitors = []

        queries = []
        if business_type and location:
            queries.append(f"top {business_type} companies in {location}")
            queries.append(f"{business_type} {location}")
        queries.append(f"site:{'.'.join(domain.split('.')[-2:])} {business_type}" if business_type else f"companies like {domain}")

        for query in queries[:3]:
            result = self._serper_search(query, country=country_code)
            for item in result.get("organic", []):
                url = item.get("link", "")
                item_domain = urlparse(url).netloc.lower().replace("www.", "")
                if any(s in item_domain for s in skip_domains):
                    continue
                if own_domain in item_domain or item_domain in seen:
                    continue
                seen.add(item_domain)
                competitors.append({
                    "domain": item_domain,
                    "tavily_summary": item.get("snippet", "")[:500],
                    "intersections": None,
                    "organic_keywords": None,
                    "organic_traffic": None,
                    "competition_score": None,
                    "source": "serper"
                })

        # Maps
        if business_type and location:
            maps = self._serper_search(f"{business_type} {location}", country=country_code, search_type="places")
            for place in maps.get("places", []):
                competitors.append({
                    "domain": place.get("title", ""),
                    "tavily_summary": place.get("address", ""),
                    "rating": place.get("rating"),
                    "reviews": place.get("reviews", 0),
                    "source": "serper_maps"
                })

        logger.info(f"[CompetitiveIntelligenceAgent] Serper found {len(competitors)} competitors for {domain}")
        return competitors

    def _search_keywords_autocomplete(
        self,
        seed_keywords: List[str],
        country_code: str = "zw",
        expand_alphabet: bool = True
    ) -> List[Dict[str, Any]]:
        """Get keyword suggestions using Google Autocomplete (free)."""
        all_keywords = set()

        for seed in seed_keywords[:10]:
            try:
                response = requests.get(
                    "https://suggestqueries.google.com/complete/search",
                    params={"client": "firefox", "q": seed, "gl": country_code.lower()},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5
                )
                if response.status_code == 200:
                    for s in response.json()[1]:
                        all_keywords.add(s)
            except Exception:
                continue

        if expand_alphabet:
            for seed in seed_keywords[:3]:
                for letter in "abcdefghijklmnopqrstuvwxyz":
                    try:
                        response = requests.get(
                            "https://suggestqueries.google.com/complete/search",
                            params={"client": "firefox", "q": f"{seed} {letter}", "gl": country_code.lower()},
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=5
                        )
                        if response.status_code == 200:
                            for s in response.json()[1]:
                                all_keywords.add(s)
                    except Exception:
                        continue

        return [{"keyword": kw, "search_volume": None, "cpc": None, "source": "google_autocomplete"} for kw in sorted(all_keywords)]

    # ============ Step 2: Discover Competitors ============

    def discover_competitors(
        self,
        domain: str,
        country_code: str = "US",
        language_code: str = "en",
        limit: int = 10,
        business_type: str = "",
        location: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Step 2: Discover top competitors for the domain.

        Pipeline: DataForSEO (keyword overlap data) → Serper (Google SERP) → empty.
        """
        cache_key = f"ci:competitors:{domain}:{country_code}"
        cached = self.cache.get(cache_key) if self.cache.is_connected else None
        if cached:
            logger.info(f"[CompetitiveIntelligenceAgent] Cache hit: {cache_key}")
            return cached

        competitors = []

        # Try DataForSEO first
        if self.dataforseo_available:
            payload = [{
                "target": domain,
                "location_code": self._get_location_code(country_code),
                "language_code": language_code,
                "limit": limit,
                "exclude_top_domains": True
            }]

            result = self._dataforseo_request(
                "dataforseo_labs/google/competitors_domain/live",
                payload
            )

            if result.get("status_code") == 20000:
                tasks = result.get("tasks", [])
                for task in tasks:
                    if task.get("status_code") != 20000:
                        continue
                    items = task.get("result", [{}])
                    for res in items:
                        if not res:
                            continue
                        for item in res.get("items", []):
                            comp_domain = item.get("domain", "")
                            if comp_domain == domain:
                                continue
                            # Filter generic mega-domains
                            generic = {"youtube.com", "reddit.com", "facebook.com", "instagram.com",
                                       "linkedin.com", "twitter.com", "wikipedia.org", "amazon.com",
                                       "ebay.com", "walmart.com", "pinterest.com", "tiktok.com"}
                            if comp_domain in generic:
                                continue
                            metrics = item.get("full_domain_metrics", {}).get("organic", {})
                            competitors.append({
                                "domain": comp_domain,
                                "competition_score": item.get("avg_position"),
                                "intersections": item.get("intersections"),
                                "organic_keywords": metrics.get("count"),
                                "organic_traffic": metrics.get("etv"),
                                "paid_keywords": item.get("full_domain_metrics", {}).get("paid", {}).get("count"),
                                "tavily_summary": None,
                                "source": "dataforseo"
                            })

            competitors.sort(key=lambda x: x.get("intersections") or 0, reverse=True)

        # Fall back to Serper if DataForSEO returned nothing useful
        if not competitors and self.serper_available:
            logger.info(f"[CompetitiveIntelligenceAgent] DataForSEO empty, falling back to Serper for {domain}")
            competitors = self._discover_competitors_serper(domain, business_type, location, country_code)

        if competitors and self.cache.is_connected:
            self.cache.set(cache_key, competitors, ttl=CacheConfig.TTL_DAY)

        logger.info(f"[CompetitiveIntelligenceAgent] Found {len(competitors)} competitors for {domain}")
        return competitors

    # ============ Step 2.5: Tavily Enrichment ============

    def _enrich_single_competitor(self, competitor: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich a single competitor with Tavily web data."""
        comp_domain = competitor["domain"]
        try:
            summary_parts = []

            # Extract homepage content
            try:
                extract_result = self.tavily.extract(urls=[f"https://{comp_domain}"])
                if extract_result and extract_result.get("results"):
                    content = extract_result["results"][0].get("raw_content", "")
                    if content:
                        # Take first 1000 chars for summary
                        summary_parts.append(f"Website content: {content[:1000]}")
            except Exception as e:
                logger.warning(f"[CompetitiveIntelligenceAgent] Tavily extract failed for {comp_domain}: {e}")

            # Search for company overview
            try:
                search_result = self.tavily.search(
                    query=f"{comp_domain} company overview products services",
                    search_depth="basic",
                    max_results=3
                )
                if search_result and search_result.get("results"):
                    for sr in search_result["results"]:
                        snippet = sr.get("content", "")
                        if snippet:
                            summary_parts.append(snippet[:300])
            except Exception as e:
                logger.warning(f"[CompetitiveIntelligenceAgent] Tavily search failed for {comp_domain}: {e}")

            if summary_parts:
                competitor["tavily_summary"] = " | ".join(summary_parts)[:2000]

        except Exception as e:
            logger.warning(f"[CompetitiveIntelligenceAgent] Tavily enrichment failed for {comp_domain}: {e}")

        return competitor

    async def enrich_competitors_with_tavily(
        self,
        competitors: List[Dict[str, Any]],
        max_enrich: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Step 2.5: Enrich top competitors with Tavily web scraping.

        Scrapes competitor homepages and searches for company overviews
        to add qualitative context (offerings, positioning, pricing signals).
        """
        if not self.tavily:
            logger.info("[CompetitiveIntelligenceAgent] Tavily not available, skipping enrichment")
            return competitors

        to_enrich = competitors[:max_enrich]
        remaining = competitors[max_enrich:]

        # Run enrichment in parallel using asyncio.to_thread
        tasks = [
            asyncio.to_thread(self._enrich_single_competitor, comp)
            for comp in to_enrich
        ]
        enriched = await asyncio.gather(*tasks, return_exceptions=True)

        result = []
        for i, item in enumerate(enriched):
            if isinstance(item, Exception):
                logger.warning(f"[CompetitiveIntelligenceAgent] Enrichment exception: {item}")
                result.append(to_enrich[i])
            else:
                result.append(item)

        result.extend(remaining)
        logger.info(f"[CompetitiveIntelligenceAgent] Enriched {len(to_enrich)} competitors with Tavily")
        return result

    # ============ Step 3: Competitor Keyword Analysis ============

    def analyze_competitor_keywords(
        self,
        competitor_domains: List[str],
        country_code: str = "US",
        language_code: str = "en",
        min_cpc: float = 0.5,
        limit_per_competitor: int = 100
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Step 3: Analyze keyword strategies of top competitors.

        Uses: dataforseo_labs/google/keywords_for_site/live
        For each competitor, gets keywords they rank for, filtered by commercial value.

        Returns:
            (all_keywords, top_opportunity_keywords)
        """
        if not self.dataforseo_available:
            return [], []

        all_keywords = {}  # keyed by keyword for dedup

        for comp_domain in competitor_domains:
            cache_key = f"ci:keywords:{comp_domain}:{country_code}"
            cached = self.cache.get(cache_key) if self.cache.is_connected else None

            if cached:
                for kw in cached:
                    kw_text = kw["keyword"]
                    if kw_text not in all_keywords:
                        all_keywords[kw_text] = kw
                continue

            payload = [{
                "target": comp_domain,
                "location_code": self._get_location_code(country_code),
                "language_code": language_code,
                "limit": limit_per_competitor,
                "order_by": ["keyword_data.keyword_info.cpc,desc"],
                "filters": [
                    ["keyword_data.keyword_info.cpc", ">", min_cpc]
                ]
            }]

            result = self._dataforseo_request(
                "dataforseo_labs/google/keywords_for_site/live",
                payload
            )

            comp_keywords = []
            if result.get("status_code") == 20000:
                tasks = result.get("tasks", [])
                for task in tasks:
                    if task.get("status_code") != 20000:
                        logger.warning(
                            f"[CompetitiveIntelligenceAgent] Keywords task error for {comp_domain}: "
                            f"{task.get('status_message')}"
                        )
                        continue
                    items = task.get("result", [{}])
                    for res in items:
                        if not res:
                            continue
                        for item in res.get("items", []):
                            kw_data = item.get("keyword_data", {})
                            kw_info = kw_data.get("keyword_info", {})
                            kw_text = kw_data.get("keyword", "")
                            if not kw_text:
                                continue

                            entry = {
                                "keyword": kw_text,
                                "search_volume": kw_info.get("search_volume"),
                                "cpc": kw_info.get("cpc"),
                                "competition": kw_info.get("competition"),
                                "position": item.get("ranked_serp_element", {}).get("serp_item", {}).get("rank_absolute"),
                                "source_domain": comp_domain
                            }
                            comp_keywords.append(entry)

                            if kw_text not in all_keywords:
                                all_keywords[kw_text] = entry

            # Cache per competitor
            if comp_keywords and self.cache.is_connected:
                self.cache.set(cache_key, comp_keywords, ttl=CacheConfig.TTL_DAY)

            logger.info(f"[CompetitiveIntelligenceAgent] Found {len(comp_keywords)} keywords for {comp_domain}")

        # Convert to list and sort
        keyword_list = list(all_keywords.values())
        keyword_list.sort(key=lambda x: (x.get("cpc") or 0), reverse=True)

        # Top opportunities: highest composite score (volume * cpc)
        for kw in keyword_list:
            vol = kw.get("search_volume") or 0
            cpc = kw.get("cpc") or 0
            kw["opportunity_score"] = vol * cpc

        top_opportunities = sorted(
            keyword_list,
            key=lambda x: x.get("opportunity_score", 0),
            reverse=True
        )[:20]

        logger.info(
            f"[CompetitiveIntelligenceAgent] Total unique keywords: {len(keyword_list)}, "
            f"top opportunities: {len(top_opportunities)}"
        )
        return keyword_list, top_opportunities

    # ============ Step 4: Keyword Expansion ============

    def expand_keywords(
        self,
        seed_keywords: List[str],
        country_code: str = "US",
        language_code: str = "en",
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Step 4: Expand top opportunity keywords.

        Pipeline: DataForSEO (search volume data) → Google Autocomplete (free).
        """
        # Try DataForSEO first
        if self.dataforseo_available:
            try:
                from .keyword_intelligence_agent import KeywordIntelligenceAgent
                kw_agent = KeywordIntelligenceAgent()
                result = kw_agent.research_keywords_dataforseo(
                    seed_keywords=seed_keywords[:10],
                    country_code=country_code,
                    language_code=language_code,
                    limit=limit
                )
                if result.get("success") and result.get("keywords"):
                    return result
            except Exception as e:
                logger.warning(f"[CompetitiveIntelligenceAgent] DataForSEO keyword expansion failed: {e}")

        # Fallback to Google Autocomplete
        logger.info(f"[CompetitiveIntelligenceAgent] Using Google Autocomplete for keyword expansion")
        autocomplete_kws = self._search_keywords_autocomplete(seed_keywords, country_code)
        return {
            "success": True,
            "keywords": autocomplete_kws,
            "total_found": len(autocomplete_kws),
            "source": "google_autocomplete"
        }

    # ============ LLM Strategic Summary ============

    async def generate_strategic_summary(
        self,
        domain: str,
        categories: List[Dict],
        competitors: List[Dict],
        top_keywords: List[Dict]
    ) -> Optional[str]:
        """Generate an LLM-powered strategic summary of the competitive landscape."""
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser

            llm = ChatOpenRouter(
                model="openai/gpt-4o-mini" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
                temperature=0.3
            )

            # Format data for the prompt
            cat_text = "\n".join([
                f"- {c.get('category', 'N/A')} (organic traffic: {c.get('organic_traffic', 'N/A')})"
                for c in categories[:10]
            ]) or "No category data available"

            comp_text = "\n".join([
                f"- {c.get('domain', 'N/A')} (keyword overlap: {c.get('intersections', 'N/A')}, "
                f"organic traffic: {c.get('organic_traffic', 'N/A')})"
                + (f"\n  Context: {c.get('tavily_summary', '')[:200]}" if c.get('tavily_summary') else "")
                for c in competitors[:8]
            ]) or "No competitor data available"

            kw_text = "\n".join([
                f"- \"{kw.get('keyword', '')}\" (vol: {kw.get('search_volume', 'N/A')}, "
                f"CPC: ${kw.get('cpc', 'N/A')}, from: {kw.get('source_domain', 'N/A')})"
                for kw in top_keywords[:15]
            ]) or "No keyword data available"

            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a competitive intelligence strategist. Analyze the data and provide a concise strategic summary.

Return a markdown-formatted analysis with these sections:
## Business Overview
Brief summary of the domain's market position based on categories.

## Competitive Landscape
Key competitors, their strengths, and threat level.

## Keyword Opportunities
Top keyword gaps and opportunities for ad campaigns.

## Strategic Recommendations
3-5 actionable recommendations for the business owner.

Be specific and data-driven. Reference actual numbers and domains."""),
                ("human", """Analyze the competitive landscape for: {domain}

**Business Categories:**
{categories}

**Top Competitors:**
{competitors}

**High-Value Keyword Opportunities:**
{keywords}""")
            ])

            from modules.openrouter.context import set_ai_context
            chain = prompt | llm | StrOutputParser()
            with set_ai_context(agent_name="competitive_intelligence"):
                summary = await chain.ainvoke({
                    "domain": domain,
                    "categories": cat_text,
                    "competitors": comp_text,
                    "keywords": kw_text
                })

            return summary

        except Exception as e:
            logger.error(f"[CompetitiveIntelligenceAgent] Strategic summary failed: {e}")
            return None

    # ============ Pipeline Orchestrator ============

    async def run_pipeline(
        self,
        domain: str,
        country_code: str = "US",
        language_code: str = "en",
        top_competitors: int = 5,
        enrich_with_tavily: bool = True,
        expand_keywords: bool = True
    ) -> Dict[str, Any]:
        """
        Run the full 4-step competitive intelligence pipeline.

        Args:
            domain: Target domain (e.g., "example.com")
            country_code: ISO country code
            language_code: Language code
            top_competitors: Number of competitors to analyze
            enrich_with_tavily: Whether to scrape competitor sites
            expand_keywords: Whether to run keyword expansion (Step 4)

        Returns:
            Complete competitive intelligence report
        """
        errors = []

        if not self.dataforseo_available and not self.serper_available:
            return {
                "success": False,
                "domain": domain,
                "errors": ["No search API configured. Set SERPER_API_KEY or DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD."],
                "categories": [],
                "competitors": [],
                "competitor_keywords": [],
                "top_opportunity_keywords": [],
                "expanded_keywords": None,
                "strategic_summary": None
            }

        # Step 1: Understand business categories
        logger.info(f"[CompetitiveIntelligenceAgent] Step 1: Getting domain categories for {domain}")
        try:
            categories = self.get_domain_categories(domain, country_code, language_code)
        except Exception as e:
            logger.error(f"[CompetitiveIntelligenceAgent] Step 1 failed: {e}")
            categories = []
            errors.append(f"Step 1 (categories) failed: {str(e)}")

        # Step 2: Discover competitors
        logger.info(f"[CompetitiveIntelligenceAgent] Step 2: Discovering competitors for {domain}")
        try:
            competitors = self.discover_competitors(domain, country_code, language_code, top_competitors * 2)
        except Exception as e:
            logger.error(f"[CompetitiveIntelligenceAgent] Step 2 failed: {e}")
            competitors = []
            errors.append(f"Step 2 (competitors) failed: {str(e)}")

        # Step 2.5: Tavily enrichment
        if enrich_with_tavily and competitors:
            logger.info(f"[CompetitiveIntelligenceAgent] Step 2.5: Enriching competitors with Tavily")
            try:
                competitors = await self.enrich_competitors_with_tavily(competitors, max_enrich=top_competitors)
            except Exception as e:
                logger.error(f"[CompetitiveIntelligenceAgent] Step 2.5 failed: {e}")
                errors.append(f"Step 2.5 (Tavily enrichment) failed: {str(e)}")

        # Step 3: Analyze competitor keywords
        all_keywords = []
        top_opportunity_keywords = []
        if competitors:
            comp_domains = [c["domain"] for c in competitors[:top_competitors]]
            logger.info(f"[CompetitiveIntelligenceAgent] Step 3: Analyzing keywords for {len(comp_domains)} competitors")
            try:
                all_keywords, top_opportunity_keywords = self.analyze_competitor_keywords(
                    comp_domains, country_code, language_code
                )
            except Exception as e:
                logger.error(f"[CompetitiveIntelligenceAgent] Step 3 failed: {e}")
                errors.append(f"Step 3 (competitor keywords) failed: {str(e)}")

        # Step 4: Expand keywords
        expanded_keywords = None
        if expand_keywords and top_opportunity_keywords:
            seed_list = [kw["keyword"] for kw in top_opportunity_keywords[:10]]
            logger.info(f"[CompetitiveIntelligenceAgent] Step 4: Expanding {len(seed_list)} seed keywords")
            try:
                expanded_keywords = self.expand_keywords(seed_list, country_code, language_code)
            except Exception as e:
                logger.error(f"[CompetitiveIntelligenceAgent] Step 4 failed: {e}")
                errors.append(f"Step 4 (keyword expansion) failed: {str(e)}")

        # LLM Strategic Summary
        strategic_summary = None
        logger.info(f"[CompetitiveIntelligenceAgent] Generating strategic summary")
        try:
            strategic_summary = await self.generate_strategic_summary(
                domain, categories, competitors, top_opportunity_keywords
            )
        except Exception as e:
            logger.error(f"[CompetitiveIntelligenceAgent] Strategic summary failed: {e}")
            errors.append(f"Strategic summary failed: {str(e)}")

        success = bool(categories or competitors)

        return {
            "success": success,
            "domain": domain,
            "categories": categories,
            "competitors": competitors,
            "competitor_keywords": all_keywords[:200],  # Cap to avoid huge response
            "top_opportunity_keywords": top_opportunity_keywords,
            "expanded_keywords": expanded_keywords,
            "strategic_summary": strategic_summary,
            "errors": errors,
            "meta": {
                "total_categories": len(categories),
                "total_competitors": len(competitors),
                "total_keywords": len(all_keywords),
                "top_opportunities": len(top_opportunity_keywords),
                "tavily_enriched": enrich_with_tavily and TAVILY_AVAILABLE,
                "keywords_expanded": expand_keywords and expanded_keywords is not None
            }
        }

# keyword_intelligence_agent.py - AI Agent for Keyword Intelligence
"""
Keyword Intelligence Agent for SEO/SEM keyword research.

Features:
1. DataForSEO API integration for search volume, CPC, competition data
2. Google autocomplete suggestions as fallback
3. LLM-powered keyword clustering by search intent
4. Competitor keyword gap analysis

Usage:
    agent = KeywordIntelligenceAgent()
    result = await agent.research_keywords("appliance repair", country="ZW")
"""

import os
import json
import logging
import requests
import base64
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# DataForSEO credentials
DATAFORSEO_LOGIN = os.getenv("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.getenv("DATAFORSEO_PASSWORD")
DATAFORSEO_AVAILABLE = bool(DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD)


class KeywordIntelligenceAgent:
    """
    AI Agent for keyword research and competitive intelligence.

    Uses DataForSEO API (primary) with Google autocomplete as fallback.
    """

    def __init__(self):
        self.dataforseo_available = DATAFORSEO_AVAILABLE
        if self.dataforseo_available:
            creds = f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}"
            self.dataforseo_auth = base64.b64encode(creds.encode()).decode()
            logger.info("[KeywordIntelligenceAgent] Initialized with DataForSEO")
        else:
            self.dataforseo_auth = None
            logger.info("[KeywordIntelligenceAgent] Initialized (DataForSEO not configured, using fallback)")

    def _dataforseo_request(self, endpoint: str, payload: List[Dict]) -> Dict:
        """Make a request to DataForSEO API."""
        try:
            response = requests.post(
                f"https://api.dataforseo.com/v3/{endpoint}",
                headers={
                    "Authorization": f"Basic {self.dataforseo_auth}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"[KeywordIntelligenceAgent] DataForSEO error: {e}")
            return {"status_code": 500, "error": str(e)}

    def research_keywords_dataforseo(
        self,
        seed_keywords: List[str],
        country_code: str = "ZW",
        language_code: str = "en",
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Research keywords using DataForSEO Search Volume API.

        Uses the search_volume endpoint which works for smaller markets like Zimbabwe.
        Sends all keywords in a single request to minimize cost.

        Args:
            seed_keywords: List of seed keywords to research
            country_code: ISO country code (e.g., "ZW", "ZA", "US")
            language_code: Language code (default "en")
            limit: Max keywords to return per seed

        Returns:
            Dict with keyword data including volume, CPC, competition
        """
        if not self.dataforseo_available:
            return {"success": False, "error": "DataForSEO not configured"}

        all_keywords = []

        # Step 1: Get search volume for all seed keywords in one batch request
        payload = [{
            "keywords": seed_keywords,
            "location_code": self._get_location_code(country_code),
            "language_code": language_code,
            "sort_by": "relevance",
            "include_adult_keywords": False
        }]

        result = self._dataforseo_request(
            "keywords_data/google_ads/search_volume/live",
            payload
        )

        if result.get("status_code") == 20000:
            tasks = result.get("tasks", [])
            for task in tasks:
                if task.get("status_code") != 20000:
                    logger.warning(f"[KeywordIntelligenceAgent] Task error: {task.get('status_message')}")
                    continue
                results = task.get("result", [])
                for res in results:
                    if not res:
                        continue
                    # search_volume endpoint returns each keyword as a separate result item
                    keyword = res.get("keyword", "")
                    vol = res.get("search_volume")
                    if keyword:
                        all_keywords.append({
                            "keyword": keyword,
                            "search_volume": vol,
                            "cpc": res.get("cpc"),
                            "competition": res.get("competition"),
                            "competition_level": res.get("competition"),  # "LOW", "MEDIUM", "HIGH"
                            "competition_index": res.get("competition_index"),
                            "monthly_searches": res.get("monthly_searches", []),
                            "seed_keyword": keyword
                        })

        # Step 2: Also get keyword suggestions using keywords_for_keywords
        # (may return 0 for small markets but worth trying)
        try:
            for seed in seed_keywords[:3]:  # limit to 3 seeds to save cost
                payload2 = [{
                    "keywords": [seed],
                    "location_code": self._get_location_code(country_code),
                    "language_code": language_code,
                    "limit": limit,
                    "sort_by": "relevance",
                    "include_adult_keywords": False
                }]

                result2 = self._dataforseo_request(
                    "keywords_data/google_ads/keywords_for_keywords/live",
                    payload2
                )

                if result2.get("status_code") == 20000:
                    tasks2 = result2.get("tasks", [])
                    for task in tasks2:
                        if task.get("status_code") != 20000:
                            continue
                        items = task.get("result", [{}])[0].get("items", []) if task.get("result") else []
                        existing_kws = {kw["keyword"] for kw in all_keywords}
                        for item in items:
                            kw = item.get("keyword", "")
                            if kw and kw not in existing_kws:
                                all_keywords.append({
                                    "keyword": kw,
                                    "search_volume": item.get("search_volume"),
                                    "cpc": item.get("cpc"),
                                    "competition": item.get("competition"),
                                    "competition_level": item.get("competition_level", ""),
                                    "competition_index": item.get("competition_index"),
                                    "monthly_searches": item.get("monthly_searches", []),
                                    "seed_keyword": seed
                                })
        except Exception as e:
            logger.warning(f"[KeywordIntelligenceAgent] keywords_for_keywords failed: {e}")

        # Sort by search volume (nulls last)
        all_keywords.sort(key=lambda x: x.get("search_volume") or 0, reverse=True)

        return {
            "success": True,
            "keywords": all_keywords[:limit * len(seed_keywords)],
            "total_found": len(all_keywords),
            "source": "dataforseo"
        }

    def research_keywords_autocomplete(
        self,
        seed_keywords: List[str],
        country_code: str = "ZW"
    ) -> Dict[str, Any]:
        """
        Fallback: Get keyword suggestions from Google Autocomplete.

        Free alternative when DataForSEO is not available.
        """
        all_suggestions = []

        for seed in seed_keywords:
            try:
                response = requests.get(
                    "https://suggestqueries.google.com/complete/search",
                    params={
                        "client": "firefox",
                        "q": seed,
                        "gl": country_code.lower()
                    },
                    headers={"User-Agent": "Mozilla/5.0"}
                )

                if response.status_code == 200:
                    data = response.json()
                    suggestions = data[1] if len(data) > 1 else []
                    for suggestion in suggestions:
                        all_suggestions.append({
                            "keyword": suggestion,
                            "search_volume": None,  # Not available from autocomplete
                            "cpc": None,
                            "competition": None,
                            "seed_keyword": seed,
                            "source": "google_autocomplete"
                        })
            except Exception as e:
                logger.warning(f"[KeywordIntelligenceAgent] Autocomplete failed for '{seed}': {e}")

        return {
            "success": True,
            "keywords": all_suggestions,
            "total_found": len(all_suggestions),
            "source": "google_autocomplete",
            "note": "Search volume/CPC data requires DataForSEO API key"
        }

    async def research_keywords(
        self,
        seed_keyword: str,
        country_code: str = "ZW",
        additional_seeds: List[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Research keywords with automatic provider selection.

        Uses DataForSEO if available, falls back to Google Autocomplete.

        Args:
            seed_keyword: Primary keyword to research
            country_code: Target country code
            additional_seeds: Additional seed keywords
            limit: Max results

        Returns:
            Dict with keyword data and clusters
        """
        seeds = [seed_keyword]
        if additional_seeds:
            seeds.extend(additional_seeds)

        # Get raw keyword data
        if self.dataforseo_available:
            keyword_data = self.research_keywords_dataforseo(seeds, country_code, limit=limit)
        else:
            keyword_data = self.research_keywords_autocomplete(seeds, country_code)

        if not keyword_data.get("success"):
            return keyword_data

        # Cluster keywords by intent using LLM
        keywords = keyword_data.get("keywords", [])
        if keywords:
            clusters = await self.get_keyword_clusters(keywords)
            keyword_data["clusters"] = clusters

        return keyword_data

    async def get_keyword_clusters(
        self,
        keywords: List[Dict[str, Any]],
        max_keywords: int = 50
    ) -> Dict[str, Any]:
        """
        Cluster keywords by search intent using LLM.

        Groups keywords into:
        - Informational (how to, what is, guide)
        - Commercial (best, top, review, compare)
        - Transactional (buy, hire, near me, price)
        - Navigational (brand-specific searches)

        Args:
            keywords: List of keyword dicts
            max_keywords: Max keywords to cluster

        Returns:
            Dict with clustered keywords
        """
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser

            # Import OpenRouter LLM
            try:
                from modules.openrouter import ChatOpenRouter
                llm = ChatOpenRouter(model="gpt-4o-mini", temperature=0.3)
            except ImportError:
                logger.warning("[KeywordIntelligenceAgent] OpenRouter not available for clustering")
                return self._simple_cluster(keywords[:max_keywords])

            keyword_list = "\n".join([
                f"- {kw.get('keyword', '')} (vol: {kw.get('search_volume', 'N/A')}, cpc: ${kw.get('cpc', 'N/A')})"
                for kw in keywords[:max_keywords]
            ])

            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a keyword clustering expert. Group the given keywords by search intent.

Return JSON:
{{
    "informational": [{{"keyword": "...", "volume": 0, "intent_signal": "how to/guide/what is"}}],
    "commercial": [{{"keyword": "...", "volume": 0, "intent_signal": "best/review/compare"}}],
    "transactional": [{{"keyword": "...", "volume": 0, "intent_signal": "buy/hire/near me/price"}}],
    "navigational": [{{"keyword": "...", "volume": 0, "intent_signal": "brand name"}}],
    "ad_recommendations": [
        "Use transactional keywords for conversion campaigns",
        "Use commercial keywords for consideration campaigns",
        "..."
    ]
}}

Return ONLY valid JSON."""),
                ("human", "Keywords to cluster:\n{keywords}")
            ])

            from modules.openrouter.context import set_ai_context
            chain = prompt | llm | StrOutputParser()
            with set_ai_context(agent_name="keyword_intelligence"):
                response = await chain.ainvoke({"keywords": keyword_list})

            # Parse response
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]

            clusters = json.loads(cleaned.strip())
            return clusters

        except Exception as e:
            logger.error(f"[KeywordIntelligenceAgent] Clustering failed: {e}")
            return self._simple_cluster(keywords[:max_keywords])

    def _simple_cluster(self, keywords: List[Dict]) -> Dict[str, Any]:
        """Simple rule-based clustering as fallback."""
        clusters = {
            "informational": [],
            "commercial": [],
            "transactional": [],
            "navigational": [],
            "ad_recommendations": []
        }

        informational_signals = ["how", "what", "why", "guide", "tutorial", "tips", "learn"]
        commercial_signals = ["best", "top", "review", "compare", "vs", "alternative"]
        transactional_signals = ["buy", "hire", "price", "cost", "near me", "service", "repair", "fix"]

        for kw in keywords:
            keyword = kw.get("keyword", "").lower()
            entry = {"keyword": kw.get("keyword"), "volume": kw.get("search_volume")}

            if any(s in keyword for s in transactional_signals):
                entry["intent_signal"] = "transactional"
                clusters["transactional"].append(entry)
            elif any(s in keyword for s in commercial_signals):
                entry["intent_signal"] = "commercial"
                clusters["commercial"].append(entry)
            elif any(s in keyword for s in informational_signals):
                entry["intent_signal"] = "informational"
                clusters["informational"].append(entry)
            else:
                clusters["navigational"].append(entry)

        clusters["ad_recommendations"] = [
            f"Found {len(clusters['transactional'])} transactional keywords — use for conversion campaigns",
            f"Found {len(clusters['commercial'])} commercial keywords — use for consideration campaigns",
            f"Found {len(clusters['informational'])} informational keywords — use for awareness/content"
        ]

        return clusters

    def _get_location_code(self, country_code: str) -> int:
        """Map ISO country code to DataForSEO location code."""
        location_map = {
            "ZW": 2716, "ZA": 2710, "US": 2840, "GB": 2826,
            "CA": 2124, "AU": 2036, "DE": 2276, "FR": 2250,
            "IN": 2356, "NG": 2566, "KE": 2404, "GH": 2288,
            "BW": 2072, "ZM": 2894, "MZ": 2508, "NA": 2516,
            "TZ": 2834, "UG": 2800, "MW": 2454, "ET": 2231
        }
        return location_map.get(country_code.upper(), 2840)  # Default to US

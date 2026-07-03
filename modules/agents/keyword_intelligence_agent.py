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


SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_AVAILABLE = bool(SERPER_API_KEY)


# Single-word city names that are also common English words. Matching these as
# a place on their own causes false "foreign" flags (e.g. "mobile" in "mobile app",
# "reading" in "reading the manual"). They are ignored as one-word matches but
# still count inside an unambiguous multi-word name (e.g. "new york", "reading uk").
_AMBIGUOUS_PLACE_WORDS = {
    "mobile", "reading", "nice", "split", "bath", "same", "hull", "york",
    "deal", "worth", "bury", "march", "wells", "sale", "well", "most",
    "of", "as", "may", "are", "is", "the", "best", "home", "general",
}

# Informal country abbreviations that geonamescache doesn't store as place names.
# Mapped to the canonical country name so "...uk" / "...usa" are treated like the
# full name (local when it's the target, foreign otherwise). Kept conservative:
# only whole-token abbreviations unlikely to appear as ordinary English words
# (deliberately excludes "us", which collides with "call us", "about us").
_COUNTRY_ALIASES = {
    "uk": "united kingdom",
    "usa": "united states",
    "uae": "united arab emirates",
    "nz": "new zealand",
    "sa": "south africa",
}


class _Gazetteer:
    """
    World place lookup backed by geonamescache. Knows every country and every
    city above a population threshold, so foreign-market detection works without
    a hand-maintained list. Built once and reused (module-level singleton).
    """

    def __init__(self, min_city_pop: int = 100000):
        import geonamescache
        gc = geonamescache.GeonamesCache()

        countries = gc.get_countries()  # code -> {"name": ...}
        self.code_to_name = {
            code: (c.get("name") or "").lower()
            for code, c in countries.items() if c.get("name")
        }

        self.code_to_cities = {}
        self.all_city_tokens = set()
        for c in gc.get_cities().values():
            if (c.get("population") or 0) >= min_city_pop and c.get("name"):
                name = c["name"].lower()
                cc = c.get("countrycode", "")
                self.code_to_cities.setdefault(cc, set()).add(name)
                self.all_city_tokens.add(name)

        self.all_country_tokens = set(self.code_to_name.values())
        self.all_place_tokens = self.all_country_tokens | self.all_city_tokens
        # Longest place name in words, so n-gram scanning covers "cape town",
        # "united states", etc. Capped at 4 to bound work per keyword.
        self.max_ngram = min(
            max((len(t.split()) for t in self.all_place_tokens), default=1), 4
        )

    def country_name(self, code: str):
        return self.code_to_name.get((code or "").upper())

    def cities_for(self, code: str):
        return self.code_to_cities.get((code or "").upper(), set())

    def find_places(self, text: str) -> set:
        """Return the set of place tokens (country/city names) mentioned in text."""
        words = (text or "").lower().split()
        found = set()
        n = len(words)
        for size in range(1, self.max_ngram + 1):
            for i in range(n - size + 1):
                gram = " ".join(words[i:i + size])
                if size == 1:
                    # Skip one-word names that are also common English words; they
                    # only count as places inside a longer, unambiguous name.
                    if gram in _AMBIGUOUS_PLACE_WORDS:
                        continue
                    # Resolve informal country abbreviations (uk, usa, ...).
                    alias = _COUNTRY_ALIASES.get(gram)
                    if alias:
                        found.add(alias)
                        continue
                if gram in self.all_place_tokens:
                    found.add(gram)
        return found


_GAZETTEER = None
_GAZETTEER_TRIED = False


def _get_gazetteer():
    """Lazily build the gazetteer singleton. Returns None if geonamescache is
    unavailable, so callers fall back to the inline reference map."""
    global _GAZETTEER, _GAZETTEER_TRIED
    if _GAZETTEER_TRIED:
        return _GAZETTEER
    _GAZETTEER_TRIED = True
    try:
        _GAZETTEER = _Gazetteer()
        logger.info("[KeywordIntelligenceAgent] Gazetteer loaded (geonamescache)")
    except Exception as e:
        logger.warning(
            f"[KeywordIntelligenceAgent] geonamescache unavailable, using inline geo map: {e}"
        )
        _GAZETTEER = None
    return _GAZETTEER


class KeywordIntelligenceAgent:
    """
    AI Agent for keyword research and competitive intelligence.

    Pipeline: DataForSEO (search volume data) → Serper (related searches) → Google Autocomplete (free).
    """

    # Markets where Google Keyword Planner (DataForSEO's source) has no usable
    # search-volume/CPC data, so a paid DataForSEO call returns mostly nulls.
    # For these we skip DataForSEO entirely and go straight to the free
    # Serper + autocomplete question/idea path. Extend as needed.
    DATAFORSEO_LOW_DATA_MARKETS = {"ZW"}

    # Buyer-intent terms and score weights (higher = closer to a purchase).
    # Used to rank keywords when volume data is null (e.g. Zimbabwe).
    INTENT_TERMS = {
        "for sale": 6, "buy": 6, "near me": 6, "price": 5, "prices": 5,
        "cost": 5, "quote": 5, "hire": 5, "supplier": 5, "suppliers": 5,
        "installer": 5, "installation": 5, "install": 4, "rent": 4,
        "company": 4, "companies": 4, "repair": 4, "repairs": 4,
        "service": 3, "services": 3, "maintenance": 3, "motor": 3,
        "spare": 3, "parts": 3, "automation": 2, "automated": 2,
    }

    # Neutral geographic reference (NOT a target list). Maps country code -> its
    # own name + major cities. The *target* market is chosen per-request from
    # campaign data, then "local" = the target's tokens and "foreign" = every
    # other place in this reference. Nothing here is hardcoded to one customer's
    # country; add a row when you start selling into a new market.
    COUNTRY_CODE_TO_NAME = {
        "ZW": "zimbabwe", "ZA": "south africa", "ZM": "zambia", "BW": "botswana",
        "NA": "namibia", "MZ": "mozambique", "MW": "malawi", "TZ": "tanzania",
        "UG": "uganda", "KE": "kenya", "NG": "nigeria", "GH": "ghana",
        "US": "united states", "GB": "united kingdom", "CA": "canada",
        "AU": "australia", "IN": "india", "MY": "malaysia", "PH": "philippines",
        "SG": "singapore", "AE": "united arab emirates", "DE": "germany", "FR": "france",
    }

    COUNTRY_CITIES = {
        "ZW": {"harare", "bulawayo", "mutare", "gweru", "kwekwe", "chitungwiza", "victoria falls", "zim"},
        "ZA": {"johannesburg", "joburg", "cape town", "durban", "pretoria", "sandton", "port elizabeth"},
        "ZM": {"lusaka", "ndola", "kitwe"},
        "BW": {"gaborone", "francistown"},
        "NA": {"windhoek"},
        "KE": {"nairobi", "mombasa"},
        "NG": {"lagos", "abuja", "kano"},
        "GH": {"accra", "kumasi"},
        "AU": {"melbourne", "brisbane", "perth", "sydney", "adelaide"},
        "IN": {"chennai", "mumbai", "delhi", "bangalore", "bengaluru"},
        "GB": {"london", "manchester", "birmingham"},
        "US": {"new york", "los angeles", "chicago"},
        "MY": {"kuala lumpur"},
        "PH": {"manila"},
        "AE": {"dubai", "abu dhabi"},
    }

    def __init__(self):
        self.dataforseo_available = DATAFORSEO_AVAILABLE
        if self.dataforseo_available:
            creds = f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}"
            self.dataforseo_auth = base64.b64encode(creds.encode()).decode()
        else:
            self.dataforseo_auth = None

        self.serper_available = SERPER_AVAILABLE
        logger.info(
            f"[KeywordIntelligenceAgent] Initialized - "
            f"DataForSEO: {self.dataforseo_available}, Serper: {SERPER_AVAILABLE}"
        )

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

    def research_keywords_serper(
        self,
        seed_keywords: List[str],
        country_code: str = "ZW"
    ) -> Dict[str, Any]:
        """
        Get keyword ideas from Serper.dev Google SERP related searches + People Also Ask.
        """
        if not self.serper_available:
            return {"success": False, "error": "Serper not configured", "keywords": []}

        all_keywords = set()
        try:
            for seed in seed_keywords[:5]:
                response = requests.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                    json={"q": seed, "gl": country_code.lower(), "hl": "en", "num": 10},
                    timeout=15
                )
                if response.status_code == 200:
                    data = response.json()
                    for rs in data.get("relatedSearches", []):
                        q = rs.get("query", "")
                        if q:
                            all_keywords.add(q)
                    for paa in data.get("peopleAlsoAsk", []):
                        q = paa.get("question", "")
                        if q:
                            all_keywords.add(q)
        except Exception as e:
            logger.warning(f"[KeywordIntelligenceAgent] Serper keyword search failed: {e}")

        keywords = [
            {"keyword": kw, "search_volume": None, "cpc": None, "competition": None, "source": "serper_related"}
            for kw in sorted(all_keywords)
        ]

        return {
            "success": True,
            "keywords": keywords,
            "total_found": len(keywords),
            "source": "serper"
        }

    def research_keywords_autocomplete(
        self,
        seed_keywords: List[str],
        country_code: str = "ZW",
        expand_alphabet: bool = True
    ) -> Dict[str, Any]:
        """
        Get keyword suggestions from Google Autocomplete with alphabet expansion.
        Free, no API key needed, works for any local market.
        """
        all_keywords = set()

        # Direct autocomplete for each seed
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

        # Alphabet expansion on top 3 seeds
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

        keywords = [
            {"keyword": kw, "search_volume": None, "cpc": None, "competition": None,
             "seed_keyword": "", "source": "google_autocomplete"}
            for kw in sorted(all_keywords)
        ]

        return {
            "success": True,
            "keywords": keywords,
            "total_found": len(keywords),
            "source": "google_autocomplete"
        }

    async def research_keywords(
        self,
        seed_keyword: str,
        country_code: str = "ZW",
        additional_seeds: List[str] = None,
        limit: int = 50,
        target_cities: List[str] = None
    ) -> Dict[str, Any]:
        """
        Research keywords with automatic provider selection.

        Pipeline: DataForSEO (search volume) → Serper (related searches) + Autocomplete (free).
        """
        seeds = [seed_keyword]
        if additional_seeds:
            seeds.extend(additional_seeds)

        # Skip DataForSEO for markets Google has no volume data for (e.g. ZW):
        # the call costs a credit but returns mostly nulls. Fall through to the
        # free Serper + autocomplete path instead.
        skip_dataforseo = (country_code or "").upper() in self.DATAFORSEO_LOW_DATA_MARKETS
        if skip_dataforseo:
            logger.info(
                f"[KeywordIntelligenceAgent] Skipping DataForSEO for low-data market "
                f"'{country_code}'; using Serper + autocomplete."
            )

        # Try DataForSEO first (has search volume data)
        if self.dataforseo_available and not skip_dataforseo:
            keyword_data = self.research_keywords_dataforseo(seeds, country_code, limit=limit)
            if keyword_data.get("success") and keyword_data.get("keywords"):
                # Enrich with autocomplete keywords not in DataForSEO
                autocomplete = self.research_keywords_autocomplete(seeds, country_code, expand_alphabet=False)
                existing = {kw["keyword"].lower() for kw in keyword_data["keywords"]}
                for kw in autocomplete.get("keywords", []):
                    if kw["keyword"].lower() not in existing:
                        keyword_data["keywords"].append(kw)
                keyword_data["total_found"] = len(keyword_data["keywords"])
                # Continue to clustering below
                keyword_data_result = keyword_data
            else:
                keyword_data_result = None
        else:
            keyword_data_result = None

        # Fallback: combine Serper + Autocomplete
        if not keyword_data_result:
            all_keywords = {}

            # Serper related searches
            if self.serper_available:
                serper_data = self.research_keywords_serper(seeds, country_code)
                for kw in serper_data.get("keywords", []):
                    all_keywords[kw["keyword"].lower()] = kw

            # Google Autocomplete with alphabet expansion
            autocomplete_data = self.research_keywords_autocomplete(seeds, country_code)
            for kw in autocomplete_data.get("keywords", []):
                if kw["keyword"].lower() not in all_keywords:
                    all_keywords[kw["keyword"].lower()] = kw

            combined = list(all_keywords.values())
            keyword_data_result = {
                "success": True,
                "keywords": combined,
                "total_found": len(combined),
                "source": "serper+autocomplete" if self.serper_available else "google_autocomplete"
            }

        if not keyword_data_result.get("success"):
            return keyword_data_result

        # Score + rank by buyer intent and local relevance. Essential when volume
        # is null (e.g. ZW): it orders results by intent and pushes foreign-market
        # noise ("...melbourne", "...malaysia") to the bottom.
        keywords = keyword_data_result.get("keywords", [])
        if keywords:
            keywords = self._score_and_rank_keywords(keywords, country_code, target_cities)
            keyword_data_result["keywords"] = keywords
            keyword_data_result["top_local"] = [
                k for k in keywords if k.get("is_local") and not k.get("is_foreign")
            ][:20]

            clusters = await self.get_keyword_clusters(keywords)
            keyword_data_result["clusters"] = clusters

        return keyword_data_result

    def _build_geo_context(self, country_code: str, target_cities: List[str] = None):
        """
        Derive geo context for the target market at request time.

        Returns (local_tokens, foreign_tokens, gaz):
          - local_tokens: target country name + code + its cities + campaign cities
          - foreign_tokens: only used in inline-fallback mode (gaz is None)
          - gaz: the gazetteer when available (foreign detected per-keyword instead)

        With the gazetteer, "foreign" = any world place named in a keyword that is
        not one of the target's local tokens. Without it, we fall back to the inline
        reference map. Either way nothing is hardcoded to a specific country.
        """
        cc = (country_code or "").upper()

        local_tokens = set()
        if cc:
            local_tokens.add(cc.lower())
        for city in (target_cities or []):
            if city:
                local_tokens.add(str(city).lower().strip())

        gaz = _get_gazetteer()
        if gaz is not None:
            name = gaz.country_name(cc)
            if name:
                local_tokens.add(name)
            local_tokens |= gaz.cities_for(cc)
            return local_tokens, None, gaz

        # Inline fallback (geonamescache not installed)
        name = self.COUNTRY_CODE_TO_NAME.get(cc)
        if name:
            local_tokens.add(name)
        local_tokens |= self.COUNTRY_CITIES.get(cc, set())
        all_places = set(self.COUNTRY_CODE_TO_NAME.values())
        for cities in self.COUNTRY_CITIES.values():
            all_places |= cities
        foreign_tokens = all_places - local_tokens
        return local_tokens, foreign_tokens, None

    def _geo_flags(self, term, local_tokens, foreign_tokens, gaz):
        """Return (is_local, is_foreign) for a keyword string.

        Local-target-wins: if the keyword names the target market (its country or
        a target city), it's an in-market search and the foreign penalty is
        suppressed. This rescues local commercial searches where another place
        token is really a brand/model that shares a city name, e.g. "Centurion"
        gate motors ("centurion gate motor harare" is a Harare buyer, not a
        South-Africa search).
        """
        is_local = any(g in term for g in local_tokens)
        if gaz is not None:
            places = gaz.find_places(term)
            if places & local_tokens:
                is_local = True
            is_foreign = bool(places - local_tokens)
        else:
            is_foreign = any(g in term for g in (foreign_tokens or set()))

        if is_local:
            is_foreign = False
        return is_local, is_foreign

    def _score_and_rank_keywords(
        self,
        keywords: List[Dict[str, Any]],
        country_code: str = "ZW",
        target_cities: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Attach an intent_score to each keyword and sort best-first.

        Score = buyer-intent terms (price/near me/installation...) + local geo
        boost (target country + its cities) - foreign geo penalty (any other
        market) + a capped bonus for real search volume when present. Each keyword
        also gets is_local / is_foreign flags so callers can filter.

        Geo sets are derived from the target market at call time (see
        _build_geo_context), so nothing is hardcoded to a specific country.
        """
        local_tokens, foreign_tokens, gaz = self._build_geo_context(country_code, target_cities)

        scored = []
        for kw in keywords:
            term = (kw.get("keyword") or "").lower().strip()
            if not term:
                continue

            score = 0.0
            for phrase, weight in self.INTENT_TERMS.items():
                if phrase in term:
                    score += weight

            is_local, is_foreign = self._geo_flags(term, local_tokens, foreign_tokens, gaz)
            if is_local:
                score += 8
            if is_foreign:
                score -= 10

            vol = kw.get("search_volume")
            if isinstance(vol, (int, float)) and vol > 0:
                score += min(vol / 1000.0, 10)  # capped so volume never dominates

            kw["intent_score"] = round(score, 1)
            kw["is_local"] = is_local
            kw["is_foreign"] = is_foreign
            scored.append(kw)

        scored.sort(key=lambda k: -k["intent_score"])
        return scored

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

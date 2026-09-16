"""
MarketResearchService — deterministic market-research data gathering.

The "smart" reasoning (SWOT, angles, ad copy) lives in the OpenClaw skill, which
calls this service's REST API (see router.py). This service is the reliable,
deterministic half: scraping, competitor discovery, keyword demand, and trends,
using data sources whose keys are already configured on the backend.

Data sources:
  * Serper.dev  (SERPER_API_KEY)          — Google organic + Maps competitors, trends
  * Google autocomplete (no key)          — keyword suggestions (+ a-z expansion)
  * Keywords Everywhere (KEYWORDS_EVERYWHERE_API_KEY) — real search VOLUME/CPC by country
  * Tavily      (TAVILY_API_KEY)          — deep trend/content extraction
  * Anthropic/OpenAI (optional)           — structured website extraction

Every method is defensive: on error it returns an empty result so callers can
degrade gracefully. Method names mirror the historical agent so existing callers
(the campaign scrape-stream) work unchanged; clean public aliases are also given.
"""

import os
import re
import json
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
KEYWORDS_EVERYWHERE_API_KEY = os.getenv("KEYWORDS_EVERYWHERE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_SKIP_DOMAINS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "reddit.com", "wikipedia.org", "tiktok.com", "pinterest.com",
    "lusha.com", "zoominfo.com", "crunchbase.com", "glassdoor.com", "ensun.io",
    "techbehemoths.com", "goodfirms.co", "clutch.co", "refrens.com", "arounddeal.com",
    "trustpilot.com", "yelp.com", "amazon.com", "ebay.com", "alibaba.com", "scribd.com",
}


class MarketResearchService:
    def __init__(self):
        self.serper_available = bool(SERPER_API_KEY)
        self.tavily_available = bool(TAVILY_API_KEY)
        self.ke_available = bool(KEYWORDS_EVERYWHERE_API_KEY)
        logger.info("[MarketResearch] serper=%s tavily=%s keywords_everywhere=%s llm=%s",
                    self.serper_available, self.tavily_available, self.ke_available, self._llm_ready())

    # ---------------- low-level search helpers ----------------

    def _serper_search(self, query: str, country: str = "us", num: int = 10,
                       search_type: str = "search") -> Dict[str, Any]:
        if not self.serper_available:
            return {"organic": []}
        try:
            r = requests.post(
                f"https://google.serper.dev/{search_type}",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "gl": (country or "us").lower(), "hl": "en", "num": num},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("[MarketResearch] Serper error: %s", e)
            return {"organic": []}

    def _tavily_search(self, query: str, depth: str = "basic", max_results: int = 5) -> Dict[str, Any]:
        if not self.tavily_available:
            return {"results": []}
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": query,
                      "search_depth": depth, "max_results": max_results},
                timeout=20,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("[MarketResearch] Tavily error: %s", e)
            return {"results": []}

    def _keyword_volume(self, keywords: List[str], country: str = "us") -> Dict[str, Dict[str, Any]]:
        """Keywords Everywhere: real search volume/CPC/competition by country.
        Returns {keyword_lower: {vol, cpc, competition}}; empty if no key/credits."""
        if not self.ke_available or not keywords:
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        try:
            # KE accepts up to 100 kw per call; batch to be safe.
            for i in range(0, min(len(keywords), 200), 100):
                batch = keywords[i:i + 100]
                r = requests.post(
                    "https://api.keywordseverywhere.com/v1/get_keyword_data",
                    headers={"Authorization": f"Bearer {KEYWORDS_EVERYWHERE_API_KEY}",
                             "Accept": "application/json"},
                    data={"country": (country or "us").upper(), "currency": "usd",
                          "dataSource": "gkp", "kw[]": batch},
                    timeout=25,
                )
                if r.status_code == 402:
                    logger.warning("[MarketResearch] Keywords Everywhere: insufficient credits")
                    break
                if r.status_code >= 400:
                    logger.warning("[MarketResearch] KE error %s: %s", r.status_code, r.text[:150])
                    break
                for k in r.json().get("data", []):
                    out[str(k.get("keyword", "")).lower()] = {
                        "vol": k.get("vol"),
                        "cpc": (k.get("cpc") or {}).get("value"),
                        "competition": k.get("competition"),
                    }
        except Exception as e:
            logger.warning("[MarketResearch] KE call failed: %s", e)
        return out

    # ---------------- competitors ----------------

    @staticmethod
    def _name_key(text: str) -> str:
        """Compact brand key for de-duplication, e.g. 'Elite Dreams Global — Bringing
        Technology…' and 'Elite Dreams Global (Pvt) Ltd' both -> 'elitedreamsglobal'."""
        name = re.split(r"\s[-|—–:]\s|\s\|", (text or "").lower())[0]
        name = re.sub(r"\((pvt|private)\)|\b(pvt|ltd|limited|inc|llc)\b\.?", " ", name)
        return re.sub(r"[^a-z0-9]", "", name)

    @classmethod
    def _same_business(cls, place_key: str, comp: Dict[str, Any]) -> bool:
        """True if a Maps place (by name key) is a competitor we already have, matched
        on its name or, for organic results, its domain (fusertech.co.zw ~ 'Fuser Technologies')."""
        if len(place_key) < 6:
            return False
        keys = [cls._name_key(comp.get("name", ""))]
        if comp.get("source") == "serper":
            host = urlparse(comp.get("url", "")).netloc.lower().replace("www.", "")
            keys.append(re.sub(r"[^a-z0-9]", "", host.split(".")[0]))
        return any(len(k) >= 6 and (k.startswith(place_key) or place_key.startswith(k)) for k in keys)

    def _search_competitors_enhanced(self, business_type: str, location: str,
                                     products: List[str], domain: str = None,
                                     country_code: str = "US", company_name: str = None) -> List[Dict[str, Any]]:
        country = (country_code or "us").lower()
        own_domain = (domain or "").replace("www.", "").lower()
        seen, competitors = set(), []

        queries = [f"top {business_type} companies in {location}".strip()]
        if products:
            queries.append(f"{', '.join([p for p in products if p][:3])} {location}".strip())
        if company_name:
            queries.append(f"{company_name} competitors alternatives {location}".strip())

        for query in queries[:3]:
            result = self._serper_search(query, country=country)
            for item in result.get("organic", []):
                url = item.get("link", "")
                d = urlparse(url).netloc.lower().replace("www.", "")
                if not d or any(s in d for s in _SKIP_DOMAINS):
                    continue
                if own_domain and own_domain in d:
                    continue
                if d in seen:
                    continue
                seen.add(d)
                competitors.append({"name": item.get("title", ""), "url": url,
                                    "description": (item.get("snippet", "") or "")[:500],
                                    "rating": None, "reviews": None, "source": "serper"})

        maps = self._serper_search(f"{business_type} {location}".strip(),
                                   country=country, search_type="places")
        for place in maps.get("places", []):
            title = place.get("title", "")
            if not title or (company_name and company_name.lower() in title.lower()):
                continue
            # Serper places use `ratingCount` (not `reviews`) and carry no website.
            rating, reviews = place.get("rating"), place.get("ratingCount")
            key = self._name_key(title)
            match = next((c for c in competitors if self._same_business(key, c)), None)
            if match:
                # Already found (organic or another branch): keep one entry, add Maps stats.
                match["rating"] = match.get("rating") or rating
                match["reviews"] = match.get("reviews") or reviews
                continue
            cid = place.get("cid")
            competitors.append({"name": title,
                                "url": place.get("website") or (f"https://www.google.com/maps?cid={cid}" if cid else ""),
                                "description": place.get("address", ""),
                                "rating": rating, "reviews": reviews, "source": "serper_maps"})
        logger.info("[MarketResearch] competitors: %d", len(competitors))
        return competitors

    # ---------------- keywords (+ real volume) ----------------

    def _search_keywords_autocomplete(self, seed_keywords: List[str],
                                      country_code: str = "us",
                                      expand_alphabet: bool = True) -> List[Dict[str, Any]]:
        country = (country_code or "us").lower()
        found: Dict[str, str] = {}

        def _ac(q):
            try:
                r = requests.get(
                    "https://suggestqueries.google.com/complete/search",
                    params={"client": "firefox", "q": q, "gl": country},
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=6,
                )
                if r.status_code == 200:
                    data = r.json()
                    return data[1] if isinstance(data, list) and len(data) > 1 else []
            except Exception:
                pass
            return []

        seeds = [s for s in (seed_keywords or []) if s]
        for seed in seeds[:10]:
            for s in _ac(seed):
                found.setdefault(str(s).lower(), "google_autocomplete")
        if expand_alphabet:
            for seed in seeds[:3]:
                for letter in "abcdefghijklmnopqrstuvwxyz":
                    for s in _ac(f"{seed} {letter}"):
                        found.setdefault(str(s).lower(), "google_autocomplete")
        if self.serper_available:
            for seed in seeds[:3]:
                res = self._serper_search(seed, country=country, num=5)
                for rel in res.get("relatedSearches", []):
                    if rel.get("query"):
                        found.setdefault(rel["query"].lower(), "serper_related")
                for paa in res.get("peopleAlsoAsk", []):
                    if paa.get("question"):
                        found.setdefault(paa["question"].lower(), "serper_paa")
        if self.tavily_available and seeds:
            res = self._tavily_search(f"{seeds[0]} popular searches related keywords", "basic", 3)
            for r in res.get("results", []):
                for phrase in re.findall(r'"([^"]{3,40})"', r.get("content", "") or ""):
                    if len(phrase.split()) <= 5:
                        found.setdefault(phrase.lower(), "tavily")
        for seed in seeds:
            found.setdefault(seed.lower(), "seed")

        keywords = [{"keyword": kw, "source": src} for kw, src in sorted(found.items())]

        # Enrich with real search volume (Keywords Everywhere), when funded.
        volumes = self._keyword_volume([k["keyword"] for k in keywords], country)
        if volumes:
            for k in keywords:
                v = volumes.get(k["keyword"].lower())
                if v:
                    k.update({"volume": v.get("vol"), "cpc": v.get("cpc"),
                              "competition": v.get("competition")})
            # Sort by volume desc when we have it.
            keywords.sort(key=lambda k: (k.get("volume") or 0), reverse=True)
        return keywords

    # ---------------- trends ----------------

    def _search_industry_trends(self, industry: str, year: str = "2024") -> List[Dict[str, Any]]:
        trends, seen = [], set()
        if self.tavily_available:
            res = self._tavily_search(
                f"{industry} industry trends {year} market growth statistics", "advanced", 6)
            for r in res.get("results", []):
                url = r.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    trends.append({"title": r.get("title", ""), "source": url,
                                   "insight": (r.get("content", "") or "")[:400]})
        if self.serper_available:
            res = self._serper_search(f"{industry} trends {year} forecast outlook", num=6)
            for r in res.get("organic", []):
                url = r.get("link", "")
                if url and url not in seen:
                    seen.add(url)
                    trends.append({"title": r.get("title", ""), "source": url,
                                   "insight": (r.get("snippet", "") or "")[:400]})
        return trends

    # ---------------- structured website extraction (LLM) --------------

    def _llm_ready(self) -> bool:
        return bool(OPENROUTER_API_KEY) or ANTHROPIC_API_KEY.startswith("sk-ant") or OPENAI_API_KEY.startswith("sk-")

    def _llm_json(self, prompt: str) -> Dict[str, Any]:
        content = ""
        try:
            if OPENROUTER_API_KEY:
                # OpenRouter first: one key for every model (see modules/openrouter).
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                             "HTTP-Referer": "https://shopivell.com",
                             "X-Title": "Shopivell Market Research",
                             "Content-Type": "application/json"},
                    json={"model": os.getenv("RESEARCH_LLM_MODEL", "openai/gpt-4o-mini"),
                          "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]},
                    timeout=60,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
            elif ANTHROPIC_API_KEY.startswith("sk-ant"):
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": os.getenv("RESEARCH_LLM_MODEL_ANTHROPIC", "claude-sonnet-4-5"),
                          "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]},
                    timeout=40,
                )
                r.raise_for_status()
                content = "".join(b.get("text", "") for b in r.json().get("content", []))
            elif OPENAI_API_KEY.startswith("sk-"):
                r = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]},
                    timeout=40,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
            else:
                return {}
            content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
            try:
                return json.loads(content)
            except Exception:
                m = re.search(r"\{.*\}", content, re.S)
                return json.loads(m.group(0)) if m else {}
        except Exception as e:
            logger.warning("[MarketResearch] LLM extraction failed: %s", e)
            return {}

    async def _extract_structured_website_data(self, content: str, url: str) -> Dict[str, Any]:
        if not content or not self._llm_ready():
            return {}
        prompt = (
            "Analyze the following website content and return ONLY a JSON object.\n\n"
            f"Website URL: {url}\nWebsite Content:\n{content[:8000]}\n\n"
            "JSON fields: company_name, tagline, industry, "
            '"services_products" (array of {name, description, category}), '
            "value_propositions (array), target_audiences (array), "
            "geographic_coverage (countries/regions served), "
            '"keyword_seeds" (5-10 short 2-4 word buyer search queries incl. city/country, '
            "generic categories not model names). Only include fields you find. Return ONLY JSON."
        )
        data = self._llm_json(prompt)
        if isinstance(data, dict):
            sp = data.get("services_products") or []
            norm = []
            for item in sp if isinstance(sp, list) else []:
                if isinstance(item, dict) and item.get("name"):
                    norm.append({"name": str(item["name"])})
                elif isinstance(item, str) and item.strip():
                    norm.append({"name": item.strip()})
            data["services_products"] = norm
            return data
        return {}

    # ---------------- clean public aliases (for the REST API) ----------

    def find_competitors(self, **kw) -> List[Dict[str, Any]]:
        return self._search_competitors_enhanced(**kw)

    def find_keywords(self, seeds: List[str], country_code: str = "us",
                      expand_alphabet: bool = True) -> List[Dict[str, Any]]:
        return self._search_keywords_autocomplete(seeds, country_code, expand_alphabet)

    def find_trends(self, industry: str, year: str = "2024") -> List[Dict[str, Any]]:
        return self._search_industry_trends(industry, year)

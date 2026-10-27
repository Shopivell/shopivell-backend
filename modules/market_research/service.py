"""
MarketResearchService — market-research data gathering + OpenClaw judgement.

The division of labour: this module owns the deterministic half (scraping,
competitor discovery, keyword demand, trends), because those are tool calls to
real data sources, not judgement. Every place that needs to *decide* something
about that data - is this company really a competitor, which keywords would a
customer of THIS business in THIS market type, which reports are actually about
this industry, what does this website sell - is one turn of the ads-research
OpenClaw agent on the gateway (see modules/openclaw/gateway.py).

Data sources:
  * Serper.dev  (SERPER_API_KEY)          — Google organic + Maps competitors, trends
  * Google autocomplete (no key)          — keyword suggestions (+ a-z expansion)
  * Keywords Everywhere (KEYWORDS_EVERYWHERE_API_KEY) — real search VOLUME/CPC by country
  * Tavily      (TAVILY_API_KEY)          — deep trend/content extraction
  * OpenClaw gateway (ads-research agent) — all filtering, naming and extraction judgement

Data-source methods stay defensive: a dead source returns an empty list so one
provider outage cannot fail an entire report. The agent calls are not: if the
gateway is unconfigured or unreachable the caller gets 503 rather than an
unfiltered, unjudged answer passed off as researched data. Method names mirror
the historical agent so existing callers (the campaign scrape-stream) work
unchanged; clean public aliases are also given.
"""

import hashlib
import os
import re
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from modules.openclaw import gateway

logger = logging.getLogger(__name__)

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
KEYWORDS_EVERYWHERE_API_KEY = os.getenv("KEYWORDS_EVERYWHERE_API_KEY", "")

# The agent's standing role. The per-call user turn carries the task and the
# candidate rows; the judgement is the model's, never a rule in this file.
_RESEARCH_AGENT_SYSTEM = """You are a market-research analyst for a small-business advertising system.
You are given one task and its raw data as a JSON-ish listing, gathered from real
search sources. You decide what that data means for THIS business in THIS market.

Answer with JSON only - no prose, no code fence, exactly the schema the task asks
for. Judge by what the data actually shows: never invent a competitor, a keyword,
a trend or a product that is not in the rows you were given, and never "complete"
a short list to look thorough. An empty keep list is a valid answer when nothing
in the rows fits. Ignore anything about a different industry, country or market
unless the task explicitly asks for a global view."""

# Place names and country-only retailers that tie a keyword or report to one market.
_COUNTRY_MARKERS = {
    "zw": ["zimbabwe", "harare", "bulawayo"],
    "za": ["south africa", "johannesburg", "cape town", "durban", "pretoria"],
    "ke": ["kenya", "nairobi", "mombasa"],
    "ng": ["nigeria", "lagos", "abuja"],
    "gh": ["ghana", "accra"],
    "zm": ["zambia", "lusaka"],
    "bw": ["botswana", "gaborone"],
    "us": ["usa", "united states", "america", "walmart"],
    "gb": ["united kingdom", "uk", "england", "london", "asda", "tesco", "sainsbury"],
    "in": ["india", "delhi", "mumbai", "bangalore", "bengaluru", "chennai", "flipkart"],
    "pk": ["pakistan", "karachi", "lahore"],
    "ph": ["philippines", "manila"],
    "au": ["australia", "sydney", "melbourne"],
    "ca": ["canada", "toronto", "vancouver", "edmonton", "calgary", "montreal"],
    "ae": ["dubai", "uae"],
    "de": ["germany", "berlin", "munich"],
    "ie": ["ireland", "dublin"],
}


def _about_other_country(text: str, country: str) -> bool:
    """True when text is about a market other than `country` — e.g. "building
    materials online app india" or a "U.S. Online Grocery Market" report for a
    Kenyan grocer. Unknown target countries are never filtered."""
    country = "gb" if (country or "").lower() == "uk" else (country or "").lower()
    if country not in _COUNTRY_MARKERS:
        return False
    low = (text or "").lower()
    for code, terms in _COUNTRY_MARKERS.items():
        if code != country and any(re.search(rf"\b{re.escape(t)}\b", low) for t in terms):
            return True
    return country != "us" and bool(re.search(r"\bU\.S\.|\bUS\b", text or ""))


_SKIP_DOMAINS = {
    "researchgate.net", "medpages.info", "thedirectory.co.zw", "tripadvisor.com", "edurank.org",
    # Booking / travel aggregators list hotels; they aren't a hotel's competitor.
    "expedia.com", "booking.com", "hotels.com", "agoda.com", "trivago.com", "kayak.com",
    "airbnb.com", "fivestaralliance.com", "lonelyplanet.com", "tripadvisor.co.za",
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
        logger.info("[MarketResearch] serper=%s tavily=%s keywords_everywhere=%s gateway=%s",
                    self.serper_available, self.tavily_available, self.ke_available,
                    bool(os.getenv("OPENCLAW_GATEWAY_URL")))

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

    # Model numbers / specs / sales phrasing mark a product-listing title, not a business.
    _PRODUCT_TITLE = re.compile(r"\b[a-z]*\d{2,}[a-z]*\b|\b(gb|tb|ghz|ssd)\b|"
                                r"\bfor sale\b|\bprice(s)?\b|\bbuy\b", re.I)
    # Trailing segments that are navigation/CTA text, not the site's name.
    _JUNK_TAIL = re.compile(r"^(page\s*\d*(\s*of\s*\d+)?|call us.*|home|shop( now)?|store|"
                            r"contact( us)?|archives?|about( us)?|products?|blog|news|"
                            r"online (shop|store)|zimbabwe|harare)$", re.I)

    @staticmethod
    def _own_keys(company_name: str) -> List[str]:
        """Tokens identifying the business itself, so its own pages and sibling brands
        ("Bulawayo Carousel - Edgars Stores Ltd") aren't returned as competitors."""
        name = (company_name or "").lower()
        keys = {re.sub(r"[^a-z0-9]", "", name)}
        if name.split():
            keys.add(re.sub(r"[^a-z0-9]", "", name.split()[0]))
        return [k for k in keys if len(k) >= 5]

    @staticmethod
    def _is_own_business(title: str, domain: str, own_keys: List[str]) -> bool:
        hay = re.sub(r"[^a-z0-9]", "", f"{title} {domain}".lower())
        return any(k in hay for k in own_keys)

    @staticmethod
    def _brand_from_domain(domain: str) -> str:
        return (domain or "").split(".")[0].replace("-", " ").strip().title()

    # Commerce filler that says what a page sells, not who sells it.
    _GENERIC_WORDS = {"shop", "shops", "store", "stores", "online", "buy", "best", "top", "product",
                      "products", "directory", "list", "category", "categories", "sale", "deals",
                      "price", "prices", "near", "official", "website", "over", "counter", "range",
                      "collection", "page", "home", "new", "and", "the", "for", "with"}
    # Directory / listicle results are never a competitor themselves.
    # ...nor are regulators, professional bodies or journals.
    _LISTING_TITLE = re.compile(r"\bdirector(y|ies)\b|^(top|best)\s+\d+|\blist of\b|"
                                r"\b(council|society|association|journal|medical aid)\b", re.I)

    @classmethod
    def _looks_generic(cls, title: str, vocab: List[str]) -> bool:
        """A title made of category words ("OTC Medication", "Shop Pharmacy Products")
        describes stock, not a business — matched loosely on 5-char stems."""
        first = re.split(r"\s[-|–—:]\s", title or "")[0]
        words = [w for w in re.findall(r"[a-z]+", first.lower()) if len(w) > 2]
        if not words:
            return True

        def generic(w):
            return w in cls._GENERIC_WORDS or any(w[:5] == v[:5] for v in vocab if len(v) >= 3)
        return sum(generic(w) for w in words) / len(words) >= 0.7

    @classmethod
    def _display_name(cls, title: str, domain: str, vocab: Optional[List[str]] = None) -> str:
        """The business behind a result. Product pages ("HP ProBook 450 G10 8GB/512GB")
        name a product, not a competitor, so use the trailing site name when the title
        carries one ("hp probook 450 g10 - Laptop World") else the domain's brand."""
        t = (title or "").strip()
        if not t or (vocab and cls._looks_generic(t, vocab)):
            return cls._brand_from_domain(domain)
        if len(t) > 45 or cls._PRODUCT_TITLE.search(t):
            tail = re.split(r"\s[-|–—]\s", t)[-1].strip()
            if (2 < len(tail) <= 30 and not cls._PRODUCT_TITLE.search(tail)
                    and not cls._JUNK_TAIL.match(tail)):
                return tail
            return cls._brand_from_domain(domain)
        return t

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
        own_keys = self._own_keys(company_name)
        seen, competitors = set(), []

        # Buyer-intent queries first: "top <x> companies in <y>" pulls directory pages,
        # listicles and agencies rather than the businesses a shop competes with.
        top_products = [p for p in (products or []) if p][:3]
        vocab = re.findall(r"[a-z]+", f"{business_type} {' '.join(top_products)} {location}".lower())
        queries = []
        if top_products:
            # "shop"/"store" keeps Google on businesses; "buy <product>" or a bare
            # product name returns individual product listing pages instead.
            queries.append(f"{top_products[0]} shop {location}".strip())
        queries.append(f"best {business_type} in {location}".strip())
        # Chains and groups (hotel groups, supermarket chains) compete with peers of
        # their size, which "best <x>" and Maps bury under small independents.
        queries.append(f"largest {business_type} companies in {location}".strip())
        if company_name:
            queries.append(f"{company_name} competitors alternatives {location}".strip())
        # National chains (Clicks, Edgars) compete with other chains, which product
        # queries miss — they return category pages instead.
        queries.append(f"{business_type} chains {location}".strip())
        if top_products:
            queries.append(f"{', '.join(top_products)} store {location}".strip())

        for query in queries[:6]:
            result = self._serper_search(query, country=country)
            for item in result.get("organic", []):
                url = item.get("link", "")
                d = urlparse(url).netloc.lower().replace("www.", "")
                if not d or any(s in d for s in _SKIP_DOMAINS):
                    continue
                if own_domain and own_domain in d:
                    continue
                if self._is_own_business(item.get("title", ""), d, own_keys):
                    continue
                if ".gov" in d or self._LISTING_TITLE.search(item.get("title", "")):
                    continue
                if d in seen:
                    continue
                seen.add(d)
                competitors.append({"name": self._display_name(item.get("title", ""), d, vocab), "url": url,
                                    "description": (item.get("snippet", "") or "")[:500],
                                    "rating": None, "reviews": None, "source": "serper"})

        # Maps: a product term ("laptops Harare") finds shops; a sector term
        # ("Information Technology Harare") finds consultancies.
        maps = self._serper_search(f"{top_products[0] if top_products else business_type} {location}".strip(),
                                   country=country, search_type="places")
        for place in maps.get("places", []):
            title = place.get("title", "")
            if not title or self._is_own_business(title, "", own_keys):
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
        competitors = self._refine_competitors(competitors, business_type, location, company_name, top_products)
        logger.info("[MarketResearch] competitors: %d", len(competitors))
        return competitors

    def _refine_competitors(self, competitors: List[Dict[str, Any]], business_type: str,
                            location: str, company_name: Optional[str],
                            products: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Final LLM pass: keep only businesses that actually compete, name them by brand,
        and merge branches of one chain. The regex filters above cheaply remove obvious
        noise, but can't tell a craft shop from a hardware store or an app listing from a
        grocer — each new domain found another case, so judgement lives here."""
        if len(competitors) < 3 or not business_type:
            return competitors
        rows = []
        for i, c in enumerate(competitors[:60]):
            where = ("Google Maps listing" if c.get("source") == "serper_maps"
                     else urlparse(c.get("url") or "").netloc)
            stars = f"{c['rating']}★ ({c.get('reviews') or 0} reviews) | " if c.get("rating") else ""
            rows.append(f"{i}. {c['name'][:60]} | {where} | {stars}{(c.get('description') or '')[:100]}")
        data = self._agent_json(
            "competitors",
            f"Business: {company_name or 'unknown'}, a {business_type} in {location or 'its market'}"
            f"{' that offers: ' + ', '.join(products) if products else ''}.\n"
            "Below are web and Google Maps search results. Return ONLY JSON: "
            '{"keep": [{"i": <index>, "name": "<competitor brand name only>"}]}\n'
            "Keep a result only if it is a business selling to the same customers in the same market. "
            "Google Maps listings are real local businesses — keep them whenever they are the right kind of "
            "business. A company in a DIFFERENT industry that uses a similar service name is NOT a competitor "
            "(a bank, insurer or mobile-money app offering 'cash management' or 'risk management' does not "
            "compete with a security company's cash-in-transit or guarding). Drop articles, lists and "
            "directories, booking and travel aggregators (Expedia, "
            "Booking.com), review and listing sites, tourist attractions and landmarks, app stores, software, "
            "regulators and associations, news, manufacturers or wholesalers that don't sell to these "
            "customers, businesses in a different industry, and the business itself. Order the list most "
            "direct competitor first: businesses of similar type and scale (for a chain or group, other "
            "chains and groups) before small independents. Use the brand name (from the title or domain), "
            "not the page title. Branches of one chain get exactly the same brand name "
            '(e.g. "DIY Depot" for "DIY Depot Savoy").\n\n' + "\n".join(rows),
            scope=f"{business_type}|{location}")
        keep = data.get("keep") if isinstance(data, dict) else None
        if not isinstance(keep, list) or not keep:
            return competitors
        merged: Dict[str, Dict[str, Any]] = {}
        for k in keep:
            try:
                c = competitors[int(k.get("i"))]
            except (AttributeError, TypeError, ValueError, IndexError):
                continue
            name = str(k.get("name") or c["name"]).strip()
            # Merge on the brand name itself, never on a model-chosen "group": given one,
            # gpt-4o-mini grouped eight different banks together for fbc.co.zw.
            group = re.sub(r"[^a-z0-9]", "", name.lower()) or str(len(merged))
            if group in merged:
                m = merged[group]
                m["branches"] = m.get("branches", 1) + 1
                if (c.get("reviews") or 0) > (m.get("reviews") or 0):
                    m["rating"], m["reviews"] = c.get("rating"), c.get("reviews")
                if not m.get("url") and c.get("url"):
                    m["url"] = c["url"]
            else:
                merged[group] = {**c, "name": name}
        return list(merged.values()) or competitors

    def _refine_keywords(self, keywords: List[Dict[str, Any]], business_type: str,
                         location: str) -> List[Dict[str, Any]]:
        """LLM pass over autocomplete output: keep what this business's customers in this
        market would search (drops other countries, unrelated products, jobs/news)."""
        if len(keywords) < 5 or not business_type:
            return keywords
        lines = "\n".join(f"{i}. {k['keyword']}" for i, k in enumerate(keywords[:120]))
        data = self._agent_json(
            "keywords",
            f"A {business_type} in {location or 'its market'} wants the search keywords its customers use. "
            'Return ONLY JSON {"keep": [<indices>]} for keywords a customer of THIS business in THIS '
            "market would search when looking to buy what it sells. Drop other countries or cities, "
            "different meanings of a word (e.g. printing services or book printers for a shop selling "
            "printers), unrelated products, and job, news or how-to queries.\n\n" + lines,
            scope=f"{business_type}|{location}")
        idx = data.get("keep") if isinstance(data, dict) else None
        if not isinstance(idx, list) or not idx:
            return keywords
        return [keywords[i] for i in idx if isinstance(i, int) and 0 <= i < len(keywords)] or keywords

    # ---------------- keywords (+ real volume) ----------------

    def _search_keywords_autocomplete(self, seed_keywords: List[str],
                                      country_code: str = "us",
                                      expand_alphabet: bool = True,
                                      business_type: str = "",
                                      location: str = "") -> List[Dict[str, Any]]:
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
        if not seeds and business_type:
            # Extraction found no products/seeds: search the business type itself so the
            # caller still gets demand signal instead of an empty list.
            seeds = [business_type] + ([f"{business_type} {location}".strip()] if location else [])
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

        # Autocomplete is global: drop suggestions aimed at another market.
        keywords = [{"keyword": kw, "source": src} for kw, src in sorted(found.items())
                    if not _about_other_country(kw, country)]

        keywords = self._refine_keywords(keywords, business_type, location)

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

    def _search_industry_trends(self, industry: str, year: str = "2024", location: str = "",
                                country_code: str = "") -> List[Dict[str, Any]]:
        trends, seen = [], set()
        where = f" {location}" if location else ""
        if self.tavily_available:
            res = self._tavily_search(
                f"{industry} industry trends{where} {year} market growth statistics", "advanced", 6)
            for r in res.get("results", []):
                url = r.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    trends.append({"title": r.get("title", ""), "source": url,
                                   "insight": (r.get("content", "") or "")[:400]})
        if self.serper_available:
            res = self._serper_search(f"{industry} trends{where} {year} forecast outlook",
                                      country=country_code or "us", num=6)
            for r in res.get("organic", []):
                url = r.get("link", "")
                if url and url not in seen:
                    seen.add(url)
                    trends.append({"title": r.get("title", ""), "source": url,
                                   "insight": (r.get("snippet", "") or "")[:400]})
        # Global reports are fine; reports about a different country are not.
        trends = [t for t in trends if not _about_other_country(t["title"], country_code)]
        return self._refine_trends(trends, industry, location)

    def _refine_trends(self, trends: List[Dict[str, Any]], business_type: str,
                       location: str) -> List[Dict[str, Any]]:
        """LLM pass: keep market reports, statistics and trend articles about this kind of
        business (in its country, or global industry-wide) — not company websites,
        "Related Companies" pages, directories or unrelated sectors."""
        if len(trends) < 3 or not business_type:
            return trends
        rows = "\n".join(f"{i}. {t['title'][:90]} | {urlparse(t.get('source') or '').netloc} | "
                         f"{(t.get('insight') or '')[:120]}" for i, t in enumerate(trends[:30]))
        data = self._agent_json(
            "trends",
            f"A {business_type} in {location or 'its market'} wants market trends and statistics for its "
            'industry. Return ONLY JSON {"keep": [<indices>]} for results that are market reports, '
            "statistics, forecasts or trend articles about this industry in this country, or global reports "
            "for this industry. Drop company or restaurant websites, 'related companies' and directory pages, "
            "job posts, and anything about a different industry or country.\n\n" + rows,
            scope=f"{business_type}|{location}")
        idx = data.get("keep") if isinstance(data, dict) else None
        if not isinstance(idx, list):
            return trends
        kept, titles = [], set()
        for i in idx:
            if isinstance(i, int) and 0 <= i < len(trends) and trends[i]["title"] not in titles:
                titles.add(trends[i]["title"])
                kept.append(trends[i])
        # An over-strict pass must not wipe the section: fall back to the unrefined list.
        return kept or trends

    # ---------------- the ads-research agent (all judgement lives there) -----

    def _agent_json(self, task: str, prompt: str, scope: str = "",
                    images: Optional[List[str]] = None) -> Dict[str, Any]:
        """One turn of the ads-research agent on the OpenClaw gateway.

        `task` names the judgement (competitors/keywords/trends/website) and only
        keys the session; `scope` (the business+market) keeps one store's history
        out of another's. The answer must be a JSON object - an empty completion,
        a non-JSON reply or a dead gateway raises 502/503 instead of quietly
        falling back to an unfiltered list, because an unfiltered list is exactly
        the hardcoded guess this agent replaced.
        """
        digest = hashlib.sha1((scope or "market").lower().encode("utf-8")).hexdigest()[:10]
        data = gateway.ask_json_sync(
            "research",
            f"{gateway.agent_id('research')}:{task}:{digest}",
            _RESEARCH_AGENT_SYSTEM,
            prompt,
            images=images,
        )
        if not isinstance(data, dict):
            raise gateway.output_error("research", f"expected a JSON object for {task}")
        return data

    # ---------------- structured website extraction (ads-research) -------

    _BLOCK_MARKERS = ("attention required", "just a moment", "checking your browser",
                      "enable javascript and cookies", "cf-browser-verification",
                      "verify you are human", "access denied")

    def _is_blocked_page(self, content: str) -> bool:
        """A bot-check / challenge page (Cloudflare etc.) or nearly empty text."""
        low = (content or "")[:3000].lower()
        return len(low.strip()) < 200 or any(m in low for m in self._BLOCK_MARKERS)

    def _fetch_text_fallback(self, url: str) -> str:
        """Page text when our own fetch hits a bot check: Tavily extract (its fetcher
        usually passes), else Google snippets for the site. Empty if both fail."""
        if self.tavily_available:
            try:
                r = requests.post("https://api.tavily.com/extract",
                                  json={"api_key": TAVILY_API_KEY, "urls": [url]}, timeout=30)
                r.raise_for_status()
                text = ((r.json().get("results") or [{}])[0].get("raw_content") or "")
                if not self._is_blocked_page(text):
                    return text
            except Exception as e:
                logger.warning("[MarketResearch] Tavily extract failed: %s", e)
        domain = urlparse(url).netloc.replace("www.", "")
        if domain and self.serper_available:
            res = self._serper_search(f"site:{domain}", num=10)
            text = " ".join(f"{o.get('title', '')}. {o.get('snippet', '')}" for o in res.get("organic", []))
            if len(text) > 200:
                return text
        return ""

    async def _extract_structured_website_data(self, content: str, url: str) -> Dict[str, Any]:
        if self._is_blocked_page(content):
            # Never profile a challenge page — that's how naivas.online became an
            # "online retail store" selling electronics.
            logger.info("[MarketResearch] %s returned a bot-check page; using fallback text", url)
            content = self._fetch_text_fallback(url) if url else ""
        if not content:
            return {}
        prompt = (
            "Analyze the following website content and return ONLY a JSON object.\n\n"
            f"Website URL: {url}\nWebsite Content:\n{content[:8000]}\n\n"
            "JSON fields: company_name, tagline, industry, "
            '"business_type" (the kind of company a customer would call it — its industry category, '
            'specific and buyer-facing — e.g. "computer and IT equipment retailer", "private security '
            'company", "wedding photographer", "pharmacy"; NOT a broad sector like "Information '
            'Technology" and NOT just its service labels like "cash and risk management services"), '
            '"services_products" (array of {name, description, category}; each name must be '
            'a generic product/service CATEGORY a buyer would search for — "cookware", '
            '"laptops", "school uniforms" — and NEVER the company\'s own brand, sub-brand, '
            "store or loyalty-programme names), "
            "value_propositions (array), target_audiences (array), "
            "geographic_coverage (countries/regions served), "
            '"keyword_seeds" (ALWAYS return 5-10 short 2-4 word buyer search queries incl. '
            "city/country, generic categories, never model or own-brand names). "
            "Return ONLY JSON."
        )
        data = self._agent_json("website", prompt, scope=urlparse(url).netloc or url)
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
                      expand_alphabet: bool = True, business_type: str = "",
                      location: str = "") -> List[Dict[str, Any]]:
        return self._search_keywords_autocomplete(seeds, country_code, expand_alphabet,
                                                  business_type, location)

    def find_trends(self, industry: str, year: str = "2024", location: str = "",
                    country_code: str = "") -> List[Dict[str, Any]]:
        return self._search_industry_trends(industry, year, location, country_code)

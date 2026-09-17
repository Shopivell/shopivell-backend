"""
Ad angles — the bridge between market research and ad creation.

Turns a business profile plus its market research (competitors, keywords, trends)
into a few distinct advertising angles. Each angle starts from a real situation a
customer faces — their pain, the outcome they want, and the proof from the website
that this business resolves it — rather than restating a website feature. The
campaign builder generates one ad set per angle.
"""

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ANGLE_FIELDS = ("angle_name", "customer_pain", "desired_outcome", "hook", "value_proposition", "proof",
                "website_basis", "competitor_gap", "target_audience", "emotion", "keywords", "visual_direction")

# Promises a model reaches for that a business may not be able to back up.
_UNSUPPORTED_CLAIMS = ("guarantee", "best", "#1", "number one", "cheapest", "fastest", "lowest price")

_SCHEMA = {"angles": [{
    "angle_name": "short name for the customer situation",
    "customer_pain": "the situation or worry, in the customer's own words",
    "desired_outcome": "what they want to feel or achieve",
    "hook": "<=40 char headline speaking to the pain or outcome, never a feature name",
    "value_proposition": "how this business resolves it",
    "proof": "a concrete fact from the website excerpt that makes it believable",
    "website_basis": "the website value proposition or product this rests on",
    "competitor_gap": "names competitors from the list and the evidence, e.g. X is rated 3.9 stars",
    "target_audience": "specific persona in a situation, e.g. students buying a first laptop",
    "emotion": "the feeling the buyer wants: relief, confidence, pride, peace of mind",
    "keywords": ["3-6 of the customer searches above"],
    "visual_direction": "a real moment from the customer's situation for the ad image",
}]}


def generate_ad_angles(profile: Dict[str, Any], competitors: List[Dict[str, Any]],
                       keywords: List[Dict[str, Any]], trends: List[Dict[str, Any]],
                       count: int = 3, website_excerpt: str = "") -> List[Dict[str, Any]]:
    """Distinct customer-first ad angles grounded in the research and website. Returns []
    when there is no LLM or no usable profile, so callers fall back to one ad set."""
    from modules.market_research.service import MarketResearchService

    svc = MarketResearchService()
    if not svc._llm_ready() or not (profile.get("business_type") or profile.get("company_name")):
        return []

    def as_list(value):
        return ", ".join(str(v.get("name") if isinstance(v, dict) else v) for v in (value or []) if v)

    location = profile.get("location") or profile.get("geographic_coverage") or ""
    excerpt = (website_excerpt or "")[:3500]
    comp_lines = "\n".join(
        f"- {c.get('name', '')}"
        + (f" ({c['rating']}★, {c.get('reviews') or 0} reviews)" if c.get("rating") else "")
        + (f": {(c.get('description') or '')[:100]}" if c.get("description") else "")
        for c in competitors[:12]) or "- none found"
    trend_lines = "\n".join(f"- {t.get('title', '')}" for t in trends[:6]) or "- none found"

    data = svc._llm_json(
        f"You are a direct-response copywriter who deeply understands customers in {location or 'this market'}. "
        "Plan Facebook/Instagram ad angles.\n\n"
        f"BUSINESS: {profile.get('company_name') or 'unknown'} — {profile.get('business_type') or ''}\n"
        f"Location: {location}\n"
        f"Products/services: {as_list(profile.get('products') or profile.get('services_products'))}\n"
        f"Value propositions: {as_list(profile.get('value_propositions'))}\n"
        f"Audiences: {as_list(profile.get('target_audiences'))}\n\n"
        f"WEBSITE EXCERPT (the only source of facts and proof):\n{excerpt or 'not available'}\n\n"
        f"COMPETITORS:\n{comp_lines}\n\n"
        f"CUSTOMER SEARCHES: {', '.join(k.get('keyword', '') for k in keywords[:25]) or 'none found'}\n\n"
        f"MARKET TRENDS:\n{trend_lines}\n\n"
        f"Create exactly {count} DISTINCT angles, each built on a DIFFERENT real situation a customer of this "
        "business faces. Think about their day: what goes wrong, what they worry about, what they want to feel. "
        f"Return ONLY JSON shaped like:\n{json.dumps(_SCHEMA)}\n\n"
        "Rules: every fact, number and promise must come from the website excerpt or the profile above — never "
        "invent prices, discounts, delivery times, warranties, awards or statistics, and do not use 'guarantee', "
        "'best', '#1', 'cheapest' or 'fastest' unless the website says so. Hooks speak to the customer's pain or "
        "desired outcome and never just name a feature ('Genuine Products Here!', 'Secure Payments'). No clichés "
        "('you deserve the best', 'say goodbye to', 'experience the difference', 'look no further'). "
        "competitor_gap must name competitors from the list with the evidence, or be an empty string. "
        "Pick keywords only from the searches listed.",
        # Angles are customer-facing strategy, generated once per campaign: worth the
        # stronger writer (Claude clearly beat gpt-4o-mini on reliabletech.co.zw).
        model=os.getenv("AD_ANGLES_MODEL", "anthropic/claude-sonnet-4.6"))

    angles = data.get("angles") if isinstance(data, dict) else None
    if not isinstance(angles, list):
        logger.warning("[AdAngles] no angles returned")
        return []
    names = [str(c.get("name") or "").lower() for c in competitors if c.get("name")]
    site_text = (f"{as_list(profile.get('value_propositions'))} {as_list(profile.get('products'))} "
                 f"{excerpt}").lower()
    clean = []
    for a in angles[:count]:
        if not (isinstance(a, dict) and a.get("angle_name") and a.get("value_proposition")):
            continue
        angle = {k: a.get(k) for k in ANGLE_FIELDS}
        # A gap naming no researched competitor is filler ("many competitors don't ...").
        gap = str(angle.get("competitor_gap") or "").lower()
        if not any(n.split()[0] in gap for n in names if n.split()):
            angle["competitor_gap"] = ""
        # Replace promises the website itself doesn't make with what it does say.
        for field in ("hook", "value_proposition"):
            text = str(angle.get(field) or "")
            if any(w in text.lower() and w not in site_text for w in _UNSUPPORTED_CLAIMS):
                angle[field] = str(angle.get("website_basis") or text)
        clean.append(angle)
    logger.info("[AdAngles] generated %d angles for %s", len(clean), profile.get("company_name"))
    return clean

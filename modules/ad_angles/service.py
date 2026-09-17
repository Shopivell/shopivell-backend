"""
Ad angles — the bridge between market research and ad creation.

Turns a business profile plus its market research (competitors, keywords, trends)
into a few distinct advertising angles, each built on a gap the competition leaves
open. The campaign builder generates one ad set per angle, so research shapes the
ads instead of only being displayed.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ANGLE_FIELDS = ("angle_name", "hook", "value_proposition", "competitor_gap",
                "target_audience", "emotion", "keywords", "visual_direction")


def generate_ad_angles(profile: Dict[str, Any], competitors: List[Dict[str, Any]],
                       keywords: List[Dict[str, Any]], trends: List[Dict[str, Any]],
                       count: int = 3) -> List[Dict[str, Any]]:
    """Distinct ad angles grounded in the research. Returns [] when there is no LLM
    or no usable profile, so callers fall back to their single generic ad set."""
    from modules.market_research.service import MarketResearchService

    svc = MarketResearchService()
    if not svc._llm_ready() or not (profile.get("business_type") or profile.get("company_name")):
        return []

    def as_list(value):
        return ", ".join(str(v.get("name") if isinstance(v, dict) else v) for v in (value or []) if v)

    comp_lines = "\n".join(
        f"- {c.get('name', '')}"
        + (f" ({c['rating']}★, {c.get('reviews') or 0} reviews)" if c.get("rating") else "")
        + (f": {(c.get('description') or '')[:100]}" if c.get("description") else "")
        for c in competitors[:12]) or "- none found"
    trend_lines = "\n".join(f"- {t.get('title', '')}" for t in trends[:6]) or "- none found"

    data = svc._llm_json(
        "You are a senior performance marketer planning Facebook/Instagram ads.\n\n"
        f"BUSINESS: {profile.get('company_name') or 'unknown'} — {profile.get('business_type') or ''}\n"
        f"Location: {profile.get('location') or profile.get('geographic_coverage') or ''}\n"
        f"Products/services: {as_list(profile.get('products') or profile.get('services_products'))}\n"
        f"Value propositions (from its website): {as_list(profile.get('value_propositions'))}\n"
        f"Target audiences (from its website): {as_list(profile.get('target_audiences'))}\n\n"
        f"COMPETITORS:\n{comp_lines}\n\n"
        f"CUSTOMER SEARCHES: {', '.join(k.get('keyword', '') for k in keywords[:25]) or 'none found'}\n\n"
        f"MARKET TRENDS:\n{trend_lines}\n\n"
        f"Create exactly {count} DISTINCT ad angles — each a different reason to choose this business "
        "(e.g. value, trust/expertise, convenience, range, local presence). Return ONLY JSON:\n"
        '{"angles": [{"angle_name": "", "hook": "<=40 char headline", "value_proposition": "", '
        '"competitor_gap": "what competitors leave open that this angle exploits", '
        '"target_audience": "specific buyer persona", "emotion": "", '
        '"keywords": ["3-6 of the customer searches above"], "visual_direction": "scene for the ad image"}]}\n\n'
        "Rules: base every claim ONLY on the business's own products, value propositions and audiences "
        "above — never invent prices, discounts, delivery times, awards or statistics. Name competitors in "
        "competitor_gap only where the research supports it. Pick keywords only from the searches listed.")

    angles = data.get("angles") if isinstance(data, dict) else None
    if not isinstance(angles, list):
        logger.warning("[AdAngles] no angles returned")
        return []
    clean = [{k: a.get(k) for k in ANGLE_FIELDS}
             for a in angles[:count]
             if isinstance(a, dict) and a.get("angle_name") and a.get("value_proposition")]
    logger.info("[AdAngles] generated %d angles for %s", len(clean), profile.get("company_name"))
    return clean

"""
The fact bank: the real, checkable facts a business's website states about itself.

Prices and price points, sub-brands and product lines, programs and payment terms, where it operates, scale,
credentials, and how it makes or delivers what it sells. Each fact carries a short verbatim quote, and a fact is
kept only if that quote really appears in the site text, so the bank can never hold something the site does not
say. Angles and ads draw their claims about the business from here; the buyer's own life (names, situations,
deadlines) comes from the buyer profiles.

Nothing here names a brand or an industry.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FACT_KINDS = ("price", "program", "brand", "process", "credential", "scale", "location", "other")

_SCHEMA = {"facts": [{
    "fact": "one plain sentence stating the fact exactly as the website states it",
    "kind": "one of: " + ", ".join(FACT_KINDS),
    "offering": "which product, service or brand the fact belongs to",
    "quote": "a SHORT VERBATIM quote (under 160 characters) copied from the website text that states the fact",
    "ad_worthy": "true if a customer would find this attractive or reassuring in an ad (a benefit, a price, an offer, "
                 "a strength); false for contact details, addresses, fees, restrictions, terms and conditions",
}]}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def build_fact_bank(svc, business: str, website_text: str, model: Optional[str] = None,
                    max_facts: int = 30) -> List[Dict[str, Any]]:
    """Verified facts from the site text, each with an id (F1, F2...). Never raises; returns [] on any failure."""
    if not (website_text or "").strip():
        return []
    prompt = (
        "Extract the concrete, checkable facts this business's website states about itself.\n\n"
        f"BUSINESS: {business}\n\nWEBSITE TEXT:\n{website_text[:12000]}\n\n"
        "Include, where the text states them: prices and price points; sub-brands and product lines; programs and "
        "payment terms (credit, instalments, warranties, guarantees, free offers); where it operates or delivers; "
        "scale (years in business, branches, clients, products, projects); certifications, awards and credentials; "
        "and how it makes, sources or delivers what it sells (for example local production).\n"
        "Rules: state only what the text says, do not infer and do not add anything. Every fact needs a SHORT "
        "VERBATIM quote copied from the text. Prefer facts that a customer would care about. "
        f"Return at most {max_facts} facts.\n\nReturn ONLY JSON shaped like:\n{json.dumps(_SCHEMA)}")
    try:
        data = svc._llm_json(prompt, model=model)
    except Exception as e:
        logger.info("[FactBank] extraction failed: %s", e)
        return []
    site = _norm(website_text)
    facts: List[Dict[str, Any]] = []
    seen = set()
    for f in (data.get("facts") if isinstance(data, dict) else None) or []:
        if not isinstance(f, dict):
            continue
        quote, text = str(f.get("quote") or "").strip(), str(f.get("fact") or "").strip()
        nq = _norm(quote)
        if not text or len(nq) < 12 or nq not in site or text.lower() in seen:
            continue   # the quote must really be in the site text
        seen.add(text.lower())
        kind = str(f.get("kind") or "other").strip().lower()
        facts.append({"id": f"F{len(facts) + 1}", "fact": text[:300], "kind": kind if kind in FACT_KINDS else "other",
                      "offering": str(f.get("offering") or "")[:80], "quote": quote[:200],
                      "ad_worthy": str(f.get("ad_worthy", True)).strip().lower() in ("true", "yes", "1")})
    logger.info("[FactBank] %d verified facts for %s", len(facts), business)
    return facts


def facts_block(facts: List[Dict[str, Any]]) -> str:
    """The fact bank as prompt text."""
    if not facts:
        return ""
    lines = "\n".join(f"{f['id']} [{f['kind']}] {f['fact']}" + (f" (offering: {f['offering']})" if f.get("offering") else "")
                      + ("" if f.get("ad_worthy", True) else " [do not lead an ad with this]") for f in facts)
    return ("\nFACT BANK (real facts the website states about the business; the only source for claims about the "
            "business):\n" + lines + "\n")


def pick_offering_facts(facts: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """Up to `n` facts to lead offering-led angles, as different from each other as possible: one per kind first
    (most distinctive kinds first), then different offerings, then the rest."""
    order = {k: i for i, k in enumerate(FACT_KINDS)}
    worthy = [f for f in facts if f.get("ad_worthy", True)]
    ranked = sorted(worthy if len(worthy) >= n else facts, key=lambda f: order.get(f["kind"], 99))
    chosen: List[Dict[str, Any]] = []
    kinds, offers = set(), set()
    for f in ranked:
        if len(chosen) >= n:
            break
        if f["kind"] not in kinds and f["offering"].lower() not in offers:
            chosen.append(f); kinds.add(f["kind"]); offers.add(f["offering"].lower())
    for f in ranked:
        if len(chosen) >= n:
            break
        if f not in chosen:
            chosen.append(f)
    return chosen

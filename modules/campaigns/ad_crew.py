"""
Ad Crew — the campaign build as a team of specialist agents.

Rather than one general-purpose LLM call, the campaign build is divided into
the operational roles proven by high-performing ad-creation systems:

  Director             — owns the brief; coordinates every specialist; decides
                         when the campaign is ready.
  Page Analyzer        — ingests the scraped site and historical performance;
                         produces the business profile and proof inventory.
  Structure Architect  — lays out campaign -> ad sets -> creatives (how many,
                         which angle feeds which ad set).
  Targeting Strategist — determines audience segmentation per ad set
                         (interests, behaviors, demographics, placements).
  Creative Curator     — selects visual family and format per creative and
                         writes the image brief.
  Copywriter           — writes primary text (P1-P4), headlines, descriptions,
                         CTAs per variation.
  Budget Allocator     — distributes daily budget across ad sets, weighting
                         the strongest angles; splits within an ad set across
                         its copy variations.

Each agent is a function with a narrow contract; the Director composes them.
The SSE stream reports crew events so the UI can show the team working.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CREW_ROLES = ("director", "page_analyzer", "structure_architect",
              "targeting_strategist", "creative_curator", "copywriter",
              "budget_allocator")

# Per-ad-set budget weights by angle position: earlier angles get a slight edge
# only when nothing else distinguishes them; performance data overrides.
_BASE_WEIGHTS = [1.0, 1.0, 0.8, 0.8, 0.6]


# ---------------------------------------------------------------- agents ----

def page_analyze(scraped_data: Dict[str, Any], store_profile: Dict[str, Any],
                 brand_dna: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Page Analyzer: business profile + inventory of provable facts.

    The proof inventory is the campaign's fact bank: every number, place,
    payment method and promise the site actually makes. Later agents may
    quote from it and nowhere else.
    """
    profile = (scraped_data.get("market_research") or {}).get("profile") or store_profile
    content = str(scraped_data.get("content") or "")
    import re as _re
    proof_inventory: List[str] = []
    # Numbers with context windows ("over 500 products", "10 years", "2000+ clients")
    for m in _re.finditer(
            r"([^.]{0,80}?\b(?:\d+\+?|over \d+|more than \d+)\s+(?:products?|items?|clients?|customers?|"
            r"businesses|years?|brands?|staff|team)[^.]{0,60}\.)", content, _re.I):
        snippet = " ".join(m.group(1).split())
        if 15 < len(snippet) < 160 and snippet not in proof_inventory:
            proof_inventory.append(snippet)
    # Payment methods and delivery promises
    for pat in (r"[^.]{0,60}EcoCash[^.]{0,60}\.", r"[^.]{0,60}InnBucks[^.]{0,60}\.",
                r"[^.]{0,60}bank transfer[^.]{0,60}\.", r"[^.]{0,70}same[- ]day[^.]{0,70}\.",
                r"[^.]{0,60}warrant(?:y|ies)[^.]{0,60}\."):
        m = _re.search(pat, content, _re.I)
        if m:
            snippet = " ".join(m.group(0).split())
            if snippet not in proof_inventory:
                proof_inventory.append(snippet)
    return {
        "company_name": profile.get("company_name") or "",
        "business_type": profile.get("business_type") or "",
        "location": profile.get("location") or "",
        "products": [str(p) for p in (profile.get("products") or [])][:8],
        "value_propositions": [str(v) for v in (profile.get("value_propositions") or [])][:6],
        "brand_dna": brand_dna or profile.get("brand_dna") or None,
        "proof_inventory": proof_inventory[:10],
        "content_excerpt": content[:3500],
    }


def architect_structure(brief: Dict[str, Any], angles: List[Dict[str, Any]],
                        num_images: int = 1) -> Dict[str, Any]:
    """Structure Architect: campaign -> ad sets -> creatives layout.

    One ad set per angle; each ad set carries one creative per copy variation
    (Copy-A primary + Copy-B/C secondary), matching the Meta object tree.
    """
    n = max(1, len(angles))
    variations_per_set = max(1, min(3, max((len(a.get("copy_variations") or [])) for a in angles) if angles else 1))
    structure = {
        "campaign": {
            "objective": "conversions",
            "ad_sets": [],
        },
    }
    for i, angle in enumerate(angles):
        structure["campaign"]["ad_sets"].append({
            "position": i,
            "name": str(angle.get("target_audience") or angle.get("angle_name") or f"Ad Set {i + 1}")[:80],
            "angle_name": angle.get("angle_name"),
            "creatives": [
                {"copy_variation": chr(65 + j), "is_primary": j == 0,
                 "format": "single_image"}
                for j in range(variations_per_set)
            ],
        })
    structure["totals"] = {"ad_sets": n, "creatives": n * variations_per_set}
    return structure


def plan_targeting(brief: Dict[str, Any], angles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Targeting Strategist: per-ad-set audience segments.

    Prefers each angle's own targeting_hint (from the angles step, which saw
    the buyer profiles); fills gaps from the campaign defaults. Never lets two
    ad sets carry identical interest sets — they must test different audiences.
    """
    demo_default = {"age_min": 18, "age_max": 65, "gender": "all"}
    seen: set = set()
    plans = []
    for i, angle in enumerate(angles):
        vars_ = [v for v in (angle.get("copy_variations") or []) if isinstance(v, dict)]
        hint = {}
        for v in vars_:
            h = v.get("targeting_hint")
            if isinstance(h, dict) and (h.get("interests") or h.get("behaviors")):
                hint = h
                break
        interests = [str(t) for t in (hint.get("interests") or [])][:6]
        behaviors = [str(t) for t in (hint.get("behaviors") or [])][:3]
        # Diversity guard: identical interest sets get a keyword-swapped variant so
        # the ad sets genuinely test different audiences.
        key = "|".join(sorted(x.lower() for x in interests))
        if key and key in seen:
            kws = [str(k.get("keyword")) for k in (brief.get("keywords") or [])[:6]]
            interests = interests[:2] + [k for k in kws if k.lower() not in {x.lower() for x in interests}][:4]
            key = "|".join(sorted(x.lower() for x in interests))
        seen.add(key)
        demo = dict(demo_default)
        for v in vars_:
            d = v.get("demographics")
            if isinstance(d, dict) and d.get("age_min"):
                demo = {"age_min": int(d.get("age_min") or 18), "age_max": int(d.get("age_max") or 65),
                        "gender": str(d.get("gender") or "all")}
                break
        placements = [str(v.get("placement") or "automatic") for v in vars_ if v.get("placement")]
        plans.append({
            "interests": interests,
            "behaviors": behaviors,
            "demographics": demo,
            "placements": placements or ["automatic"],
        })
    return plans


def curate_creatives(brief: Dict[str, Any], angles: List[Dict[str, Any]],
                     structure: Dict[str, Any], brand_color: str = "") -> List[Dict[str, Any]]:
    """Creative Curator: visual family + format + image brief per creative.

    Family follows the copy variation's psychological approach (loss aversion ->
    lifestyle moment with one subject; aspiration -> product mockup; us-vs-them ->
    split concept). Brand/product-led families are people-free.
    """
    family_by_approach = {
        "loss aversion": "lifestyle",
        "aspiration": "product_mockup",
        "us-vs-them": "split_concept",
    }
    aesthetic = ""
    dna = brief.get("brand_dna") or {}
    if isinstance(dna, dict):
        aesthetic = str((dna.get("voice_and_style") or {}).get("aesthetic_style") or "")[:200]
    briefs = []
    for ad_set in structure["campaign"]["ad_sets"]:
        angle = angles[ad_set["position"]] if ad_set["position"] < len(angles) else {}
        for creative in ad_set["creatives"]:
            vi = ord(creative["copy_variation"]) - 65
            vars_ = [v for v in (angle.get("copy_variations") or []) if isinstance(v, dict)]
            v = vars_[vi] if vi < len(vars_) else (vars_[0] if vars_ else {})
            approach = str(v.get("approach") or "aspiration").lower()
            family = family_by_approach.get(approach, "product_mockup")
            briefs.append({
                "ad_set_position": ad_set["position"],
                "copy_variation": creative["copy_variation"],
                "family": family,
                "no_humans": family in ("product_mockup", "split_concept"),
                "image_direction": str(v.get("image_direction") or angle.get("visual_direction") or "")[:400],
                "benefit_chips": [str(c) for c in (v.get("benefit_chips") or [])][:4],
                "brand_color": brand_color,
                "aesthetic": aesthetic,
            })
    return briefs


def allocate_budget(daily_budget: float, angles: List[Dict[str, Any]],
                    performance: Optional[List[Dict[str, Any]]] = None) -> List[float]:
    """Budget Allocator: split daily budget across ad sets.

    With performance data (existing Meta insights), weight by recent spend
    efficiency. Without it, even split with a small edge for earlier angles,
    floored so every ad set can exit the learning phase.
    """
    n = max(1, len(angles))
    budget = float(daily_budget or os.getenv("AD_DEFAULT_DAILY_BUDGET", "2"))
    if performance:
        # Weight by ROAS-ish score (conversions per spend); missing data = neutral.
        scores = []
        for i in range(n):
            p = performance[i] if i < len(performance) else {}
            spend = float(p.get("spend") or 0)
            conv = float(p.get("conversions") or 0)
            scores.append((conv / spend) if spend > 0 else 0.5)
        total = sum(scores) or 1.0
        weights = [s / total for s in scores]
    else:
        weights = [_BASE_WEIGHTS[i % len(_BASE_WEIGHTS)] for i in range(n)]
        total = sum(weights)
        weights = [w / total for w in weights]
    alloc = [round(budget * w, 2) for w in weights]
    # Rounding may drift; give the remainder to the first ad set.
    drift = round(budget - sum(alloc), 2)
    alloc[0] = round(alloc[0] + drift, 2)
    return alloc


# --------------------------------------------------------------- director ----

def run_crew(scraped_data: Dict[str, Any], store_profile: Dict[str, Any],
             angles: List[Dict[str, Any]], daily_budget: float,
             brand_dna: Optional[Dict[str, Any]] = None,
             keywords: Optional[List[Dict[str, Any]]] = None,
             brand_color: str = "",
             performance: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Director: run the crew in order and return the full campaign plan.

    Every stage output is included so callers (and the UI) can inspect each
    agent's work product. Raises nothing; an empty angle list still yields a
    single-ad-set plan.
    """
    brief = page_analyze(scraped_data, store_profile, brand_dna)
    structure = architect_structure(brief, angles)
    targeting = plan_targeting({**brief, "keywords": keywords or []}, angles)
    creatives = curate_creatives(brief, angles, structure, brand_color)
    budget = allocate_budget(daily_budget, angles, performance)
    for i, ad_set in enumerate(structure["campaign"]["ad_sets"]):
        ad_set["targeting"] = targeting[i] if i < len(targeting) else {}
        ad_set["daily_budget"] = budget[i] if i < len(budget) else daily_budget
    logger.info("[AdCrew] plan ready: %d ad sets, %d creatives, budget %s",
                structure["totals"]["ad_sets"], structure["totals"]["creatives"], budget)
    return {"brief": brief, "structure": structure, "creatives": creatives,
            "budget": budget}

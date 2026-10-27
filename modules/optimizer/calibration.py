"""
Model-driven calibration for the ad optimizer: both the targets (target_roas/
target_cpa) AND the rule thresholds (roas_threshold, cooldowns, budget steps, etc.)
are proposed by a model here - but the 15-minute execution loop in service.py stays
completely untouched and deterministic. This module only runs infrequently (opt-in,
on demand or on a ~weekly cooldown), and every numeric value it returns is hard-
clamped in code before it's ever saved, regardless of what the model proposed -
this still tunes real ad spend, so the bounds are not optional.

Runs as the dedicated OpenClaw calibrator agent (same gateway as the goal, planner
and evaluator agents), so its numbers come from a real agent turn grounded in the
store's niche and market rather than from a local heuristic.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from modules.openclaw import gateway
from modules.optimizer.rules import DEFAULT_RULES

logger = logging.getLogger(__name__)

# (min, max, type) per rule field. The model's proposal is clamped into this range no
# matter what it returns - these bounds are the actual safety mechanism, not the prompt.
RULE_BOUNDS: Dict[str, Dict[str, tuple]] = {
    "scale_winner": {
        "roas_threshold": (1.05, 3.0, float), "consecutive_days": (1, 14, int),
        "min_conversions": (1, 50, int), "budget_increase": (5, 100, float),
        "max_budget": (10, 1_000_000, float), "cooldown_hours": (1, 168, float),
    },
    "kill_loser": {
        "cpa_threshold": (1.0, 5.0, float), "min_impressions": (100, 50_000, int),
        "budget_decrease": (10, 90, float), "min_budget": (1, 10_000, float),
        "cooldown_hours": (1, 168, float),
    },
    "pause_no_spend": {
        "min_age_hours": (6, 336, float), "cooldown_hours": (1, 168, float),
    },
    "creative_fatigue": {
        "frequency_threshold": (1.5, 10.0, float), "ctr_decline_percent": (10, 80, float),
        "days": (1, 14, int), "cooldown_hours": (1, 168, float),
    },
    "low_message_conversion": {
        "min_clicks": (10, 500, int), "min_conversion_rate": (2, 50, float),
        "budget_decrease": (10, 90, float), "min_budget": (1, 10_000, float),
        "cooldown_hours": (1, 168, float),
    },
}

CALIBRATION_PROMPT = f"""You are tuning an ad optimizer for one specific business: both the
targets it measures against, and the rule thresholds that decide when it scales, cuts, or
pauses an ad set. This runs infrequently (roughly weekly) to set numbers a separate,
fixed 15-minute engine then executes deterministically - you are not making live decisions,
only choosing sensible numbers for that engine to use until you're asked again.

Use any research/search tools configured on you to ground every number in REAL current
benchmarks for this business's niche, country and spend level - do not invent generic
numbers. If the store has too
little of its own performance history to be meaningful, rely more heavily on researched
category benchmarks; if it has real history, weigh that too.

Rule mechanics you may tune (default shape and current values given below - change only
what you have an actual reason to change; leave a field out to keep its current value):
{DEFAULT_RULES}

Guidance on the mechanics:
- A high-velocity, low-margin, impulse-buy niche can usually tolerate a more aggressive
  kill_loser (lower min_impressions/cooldown) and faster scale_winner than a considered,
  long-sales-cycle B2B niche, which needs more data before acting.
- Every value you return will be hard-clamped to a safe range in code regardless of what
  you propose, so there is no need to be conservative purely out of caution - propose what
  you actually think is right for this business; the system enforces the floor/ceiling.

Rules:
1. target_roas / target_cpa: conservative, realistic, grounded - see above. Return null for
   either if you genuinely cannot find or estimate a defensible number; the optimizer simply
   won't run that rule until a real target is set.
2. "rules": only include a rule name / field if you have an actual reason to change it from
   its current value; omit anything you're not changing.
3. "reasoning" must name the actual benchmark/signal used for the targets AND explain any
   rule-mechanic changes in terms of this business's niche - never write a reasoning that
   isn't grounded in something you actually looked at or reasoned about.

Return ONLY JSON, no prose, no code fence:
{{"target_roas": 0 or null, "target_cpa": 0 or null,
"rules": {{"scale_winner": {{}}, "kill_loser": {{}}, "pause_no_spend": {{}}, "creative_fatigue": {{}}}},
"reasoning": "..."}}
"""


def _clamp_rule_overrides(proposed: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Keep only known rule/field names, and hard-clamp every value into RULE_BOUNDS -
    the model's own judgment is never trusted as the safety mechanism, this is."""
    out: Dict[str, Dict[str, Any]] = {}
    for rule_name, fields in (proposed or {}).items():
        if rule_name not in RULE_BOUNDS or not isinstance(fields, dict):
            continue
        clamped = {}
        for field, value in fields.items():
            bounds = RULE_BOUNDS[rule_name].get(field)
            if bounds is None or value is None:
                continue
            lo, hi, cast = bounds
            try:
                num = cast(value)
            except (TypeError, ValueError):
                continue
            clamped[field] = max(lo, min(hi, num))
        if clamped:
            out[rule_name] = clamped
    return out


def calibrate_targets(
    store_name: str,
    business_type: str,
    about: str,
    country: str,
    currency: str,
    performance: Dict[str, Any],
    current_targets: Dict[str, Optional[float]],
    current_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    store_id: str = "",
) -> Dict[str, Any]:
    """One grounded proposal for target_roas/target_cpa and (optionally) rule-mechanic
    overrides. Does not write anything - the caller decides whether/how to persist it.
    Rule overrides are already clamped to RULE_BOUNDS by the time this returns."""
    prompt = (
        f"Business: {store_name} ({business_type or 'unknown type'}), market: {country or 'unknown'}, "
        f"currency: {currency or 'USD'}.\n"
        f"About the business: {(about or 'no description available')[:500]}\n\n"
        f"Current targets (may be the generic unset default, not a real signal): "
        f"target_roas={current_targets.get('target_roas')}, target_cpa={current_targets.get('target_cpa')}\n"
        f"Current rule overrides already in effect (on top of the defaults shown in your "
        f"instructions): {current_rules or 'none - running on defaults'}\n\n"
        f"This store's own recent ad performance (last 7 days, may be thin/absent for a new store): "
        f"spend=${performance.get('total_spend', 0):.2f}, revenue=${performance.get('total_revenue', 0):.2f}, "
        f"conversions={performance.get('conversions', 0)}, active_ad_sets={performance.get('active_ad_sets', 0)}."
    )
    data = gateway.ask_json_sync(
        "calibrator",
        f"ads-calibrator:{store_id or store_name or 'unknown-store'}",
        CALIBRATION_PROMPT,
        prompt,
        expect="object",
        timeout=180.0,
    )
    if not isinstance(data, dict):
        raise gateway.output_error("calibrator", "expected a JSON object")
    return {
        "target_roas": data.get("target_roas"),
        "target_cpa": data.get("target_cpa"),
        "rules": _clamp_rule_overrides(data.get("rules")),
        "reasoning": data.get("reasoning") or "",
        "calibrated_at": datetime.utcnow().isoformat(),
    }

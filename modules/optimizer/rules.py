"""
Ad optimizer rules — pure functions over Zernio ad-set metrics.

Ported from modules/openclaw/plugins/optimizer/PLUGIN.md (that OpenClaw plugin
was never deployed). No I/O here, so the rules are testable offline; service.py
fetches the data, enforces dry-run, and applies results through Zernio.

Rules work at the ad-set level because Shopivell campaigns use ad-set budgets.
Rules that compare against a goal (scale_winner: ROAS, kill_loser: CPA) only run
once the store has set that target — we never act on a made-up goal.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DEFAULT_RULES: Dict[str, Dict[str, Any]] = {
    # ROAS >= target_roas * roas_threshold on each of the last N days -> +budget_increase%
    "scale_winner": {"enabled": True, "roas_threshold": 1.25, "consecutive_days": 3, "min_conversions": 3,
                     "budget_increase": 20, "max_budget": 10000, "cooldown_hours": 6},
    # 0 conversions after min_impressions and spend > target_cpa * cpa_threshold -> -budget_decrease%
    "kill_loser": {"enabled": True, "cpa_threshold": 2.0, "min_impressions": 2000,
                   "budget_decrease": 50, "min_budget": 1, "cooldown_hours": 12},
    # Active for min_age_hours but spent nothing yesterday -> pause
    "pause_no_spend": {"enabled": True, "min_age_hours": 48, "cooldown_hours": 24},
    # Frequency > threshold and CTR down ctr_decline_percent vs `days` ago -> pause for a creative refresh
    "creative_fatigue": {"enabled": True, "frequency_threshold": 3, "ctr_decline_percent": 30,
                         "days": 3, "cooldown_hours": 24},
}


def merged_rules(overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    """Defaults with a store's overrides applied (unknown rules/keys are ignored)."""
    rules = {name: dict(cfg) for name, cfg in DEFAULT_RULES.items()}
    for name, cfg in (overrides or {}).items():
        if name in rules and isinstance(cfg, dict):
            rules[name].update({k: v for k, v in cfg.items() if k in DEFAULT_RULES[name]})
    return rules


def ad_set_metrics(ad_set: Dict[str, Any]) -> Dict[str, Any]:
    m = ad_set.get("metrics") or {}

    def num(key):
        try:
            return float(m.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    spend, conversions, impressions, reach = num("spend"), num("conversions"), num("impressions"), num("reach")
    return {"spend": spend, "impressions": impressions, "reach": reach, "clicks": num("clicks"),
            "conversions": conversions, "roas": num("roas"), "ctr": num("ctr"),
            "cpa": round(spend / conversions, 2) if conversions else None,
            "frequency": round(impressions / reach, 2) if reach else 0.0}


def daily_budget(ad_set: Dict[str, Any]) -> Optional[float]:
    """The ad set's own daily budget, or None (lifetime or campaign-level budget)."""
    b = ad_set.get("adSetBudget") or {}
    if str(b.get("type", "")).lower() != "daily":
        return None
    try:
        return float(b.get("amount")) or None
    except (TypeError, ValueError):
        return None


def _created_at(ad_set: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ad_set.get("createdTime") or "").replace("Z", ""))
    except ValueError:
        return None


def evaluate(ad_set: Dict[str, Any], metrics: Dict[str, Any], *, rules: Dict[str, Dict[str, Any]],
             history: Dict[Any, Dict[str, Any]], yesterday_spend: Optional[float],
             last_fired: Dict[str, datetime], now: datetime,
             target_roas: Optional[float] = None, target_cpa: Optional[float] = None) -> List[Dict[str, Any]]:
    """Proposed actions for one ad set.

    history: {date: metrics} snapshots from previous days (today excluded).
    yesterday_spend: yesterday's spend, or None if unknown.
    last_fired: {rule: datetime} of the latest decision per rule, for cooldowns.
    Returns [{rule, action, reason, old_budget?, new_budget?}]; a pause wins over budget changes.
    """
    if str(ad_set.get("status", "")).lower() != "active":
        return []
    today = now.date()
    budget = daily_budget(ad_set)
    out: List[Dict[str, Any]] = []

    r = rules["scale_winner"]
    if r.get("enabled") and target_roas and budget:
        threshold = target_roas * r["roas_threshold"]
        prior = [history.get(today - timedelta(days=i)) for i in range(1, int(r["consecutive_days"]))]
        if (metrics["roas"] >= threshold and metrics["conversions"] >= r["min_conversions"]
                and all(p and (p.get("roas") or 0) >= threshold for p in prior)):
            new = min(round(budget * (1 + r["budget_increase"] / 100), 2), float(r["max_budget"]))
            if new > budget:
                out.append({"rule": "scale_winner", "action": "budget_increase", "old_budget": budget,
                            "new_budget": new,
                            "reason": f"ROAS {metrics['roas']:.2f} >= {threshold:.2f} for {r['consecutive_days']} days"})

    r = rules["kill_loser"]
    if (r.get("enabled") and target_cpa and budget and metrics["conversions"] == 0
            and metrics["impressions"] >= r["min_impressions"]
            and metrics["spend"] > target_cpa * r["cpa_threshold"]):
        new = max(round(budget * (1 - r["budget_decrease"] / 100), 2), float(r["min_budget"]))
        if new < budget:
            out.append({"rule": "kill_loser", "action": "budget_decrease", "old_budget": budget, "new_budget": new,
                        "reason": f"${metrics['spend']:.2f} spent over {int(metrics['impressions'])} impressions "
                                  f"with 0 conversions"})

    r = rules["pause_no_spend"]
    created = _created_at(ad_set)
    if (r.get("enabled") and yesterday_spend == 0 and created
            and now - created >= timedelta(hours=r["min_age_hours"])):
        out.append({"rule": "pause_no_spend", "action": "pause", "reason": "Active but spent nothing yesterday"})

    r = rules["creative_fatigue"]
    past = history.get(today - timedelta(days=int(r["days"])))
    if r.get("enabled") and metrics["frequency"] > r["frequency_threshold"] and past and past.get("ctr"):
        decline = (past["ctr"] - metrics["ctr"]) / past["ctr"] * 100
        if decline >= r["ctr_decline_percent"]:
            out.append({"rule": "creative_fatigue", "action": "pause",
                        "reason": f"Frequency {metrics['frequency']:.1f} and CTR down {decline:.0f}% "
                                  f"in {r['days']} days"})

    out = [p for p in out if not (p["rule"] in last_fired and
                                  now - last_fired[p["rule"]] < timedelta(hours=rules[p["rule"]]["cooldown_hours"]))]
    pauses = [p for p in out if p["action"] == "pause"]
    return pauses[:1] or out

"""
Element scoring: learn which parts of an ad work, from real results, and use that to make more of what wins.

Every ad is tagged with its elements (the lever it pulls, the craft move, the kind of hook and headline, the button
label, the closing action, the image style and so on). Results come from the platform per ad (impressions, clicks,
conversions, spend). This module scores every element VALUE across all the ads that used it, with statistics that
are honest about small data, then names the winners and turns them into weights for the next batch.

How it stays honest:
  * Rates are smoothed toward the overall average (a Beta prior), so a value seen in a few impressions cannot look
    like a star by luck.
  * Winners are chosen with a permutation test that corrects for comparing many values at once, so noise is not
    mistaken for a result, and the real ad-to-ad variation is respected.
  * A value needs several distinct ads and enough impressions before it can be called a winner.
  * Below a minimum amount of data the module says "not enough data" instead of picking a winner.
  * Generation keeps an exploration share, so new ideas are still tried.

Element scores are marginal (each value is averaged over the other elements it appeared with), which is the standard
creative-analytics approach and is a guide, not proof of cause. Nothing here names a brand or an industry.
"""

import math
import random
import re
from typing import Any, Dict, List, Optional, Tuple

# objective -> (successes field, trials field). Rates are per trial.
OBJECTIVE_METRIC = {
    "awareness": ("clicks", "impressions"),
    "traffic": ("clicks", "impressions"),
    "leads": ("conversions", "impressions"),
    "messages": ("conversions", "impressions"),
    "conversions": ("conversions", "impressions"),
    "sales": ("conversions", "impressions"),
}
MIN_ADS_PER_VALUE = 2          # distinct ads a value must appear in before it can be called a winner
MIN_TRIALS_PER_VALUE = 3000    # impressions a value must have gathered
MIN_TOTAL_IMPRESSIONS = 20000  # below this across all ads: not enough data to pick anything
SIGNIFICANCE = 0.10          # family-wise adjusted p-value a value needs before it is called a winner or a loser
MIN_LIFT = 0.10                # and a practical effect: at least 10% better (or worse) than the rest
EXPLORATION_SHARE = 0.20       # share of the next batch reserved for values that are not the current favourite


# ------------------------------------------------------------------------------------------------ tagging
_PRICE = re.compile(r"(?:US\$|\$)\s?\d")
_PROOF = re.compile(r"\b\d[\d,]*\+?\s*(?:years?|clients?|customers?|stores?|branches|projects?|products?|patients?|"
                    r"prescriptions?|families|homes|locations?)\b|\bsince\s+(?:19|20)\d\d\b", re.I)
_DEADLINE = re.compile(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december|"
                       r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|this week|"
                       r"next week|this month|\d{1,2}\s*(?:am|pm)|\d{1,2}:\d\d)\b", re.I)
_ACTIONS = ("visit", "call", "upload", "request", "book", "order", "send", "shop", "get", "message", "apply", "find")


def tag_image(image_direction: str) -> Dict[str, str]:
    """Image elements from the image brief (the text the image was generated from)."""
    t = (image_direction or "").lower()
    subject = ("person" if re.search(r"\b(person|people|family|woman|man|customer|team|staff|couple|child|owner)\b", t)
               else "place" if re.search(r"\b(store|shop|storefront|building|street|office|vehicle|site|branch)\b", t)
               else "product" if re.search(r"\b(product|garment|item|close-?up|polo|banner|sign|label|package|device)\b", t)
               else "other")
    style = ("before_after" if re.search(r"before|after|split", t) else "ugc" if re.search(r"ugc|phone|handheld|selfie", t)
             else "text_overlay" if re.search(r"text overlay|headline on|big text", t)
             else "studio" if re.search(r"studio|flat ?lay|plain background", t) else "photo")
    return {"image_subject": subject, "image_style": style}


def tag_ad(ad: Dict[str, Any], image_direction: str = "") -> Dict[str, str]:
    """The elements of one finished ad (as produced by ad_copy.write_ad), as short, comparable values."""
    text = str(ad.get("primary_text") or "")
    paras = [p for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    first = paras[0] if paras else ""
    last = paras[-1] if paras else ""
    head = str(ad.get("headline") or "")
    words = len(text.split())
    hook = ("question" if "?" in re.split(r"(?<=[.!?])\s", first)[0] else "number" if re.search(r"\d", first)
            else "you_direct" if re.match(r"\s*(you|your)\b", first, re.I)
            else "situation" if re.match(r"\s*(when|if|the week|before|after)\b", first, re.I) else "statement")
    headline_form = ("question" if head.strip().endswith("?") else "two_part" if len(re.findall(r"\.\s+\S", head)) >= 1
                     else "number" if re.search(r"\d", head) else "statement")
    closing = next((a for a in _ACTIONS if re.search(r"\b" + a, last, re.I)), "other")
    tags = {
        "lever": str(ad.get("lever") or ""), "slot": str(ad.get("slot") or ""), "situation": str(ad.get("situation") or ""),
        "craft_move": str(ad.get("craft_move") or "")[:40], "offering": str(ad.get("offering") or "").lower()[:40],
        "hook_type": hook, "headline_form": headline_form,
        "length": "short" if words < 120 else "medium" if words <= 150 else "long",
        "has_price": "yes" if _PRICE.search(text) else "no", "has_proof_figure": "yes" if _PROOF.search(text) else "no",
        "has_deadline": "yes" if _DEADLINE.search(" ".join(paras[:2])) else "no",
        "closing_action": closing, "button_label": str(ad.get("button_label") or "").lower()[:30],
        "meta_cta": str(ad.get("meta_cta") or ""),
    }
    tags.update(tag_image(image_direction))
    return {k: v for k, v in tags.items() if v}


# ------------------------------------------------------------------------------------------------ statistics
def _shrunk(successes: float, trials: float, p0: float, strength: float) -> float:
    """Rate smoothed toward the overall average: a value seen on few impressions stays near the average."""
    return (p0 * strength + successes) / (strength + trials)


def _perm_test(rows: List[Dict[str, Any]], succ_f: str, trial_f: str, keys_of, min_ads: int, rng: random.Random,
               perms: int = 300) -> Dict[Any, Dict[str, float]]:
    """Max-T permutation test. For every group (an element value, or a single ad) it measures how far the group's rate
    sits from the rest of the ads, then asks how often the BEST-looking group would look that good if results were
    random across ads. Shuffling the real ad results keeps the true ad-to-ad variation, and taking the maximum over all
    groups controls the chance of crowning a winner by luck across the whole family of comparisons."""
    s = [float(r.get(succ_f) or 0) for r in rows]
    t = [float(r.get(trial_f) or 0) for r in rows]
    members: Dict[Any, List[int]] = {}
    for i, r in enumerate(rows):
        for key in keys_of(r):
            members.setdefault(key, []).append(i)
    members = {k: v for k, v in members.items() if len(v) >= min_ads}
    if not members:
        return {}
    total_s, total_t = sum(s), sum(t)
    p = total_s / total_t

    def stat(ss, tt):
        out = {}
        for k, idx in members.items():
            sg, tg = sum(ss[i] for i in idx), sum(tt[i] for i in idx)
            sr, tr = total_s - sg, total_t - tg
            if tg <= 0 or tr <= 0:
                out[k] = 0.0
                continue
            se = math.sqrt(max(p * (1 - p), 1e-12) * (1 / tg + 1 / tr))
            out[k] = (sg / tg - sr / tr) / se
        return out

    obs = stat(s, t)
    pos_hits = {k: 0 for k in members}
    neg_hits = {k: 0 for k in members}
    order = list(range(len(rows)))
    for _ in range(perms):
        rng.shuffle(order)
        z = stat([s[i] for i in order], [t[i] for i in order])
        mx, mn = max(z.values()), min(z.values())
        for k, v in obs.items():
            if mx >= v:
                pos_hits[k] += 1
            if mn <= v:
                neg_hits[k] += 1
    return {k: {"z": obs[k], "p_better": (1 + pos_hits[k]) / (1 + perms), "p_worse": (1 + neg_hits[k]) / (1 + perms),
                "ads": len(members[k]), "trials": sum(t[i] for i in members[k]), "successes": sum(s[i] for i in members[k]),
                "spend": sum(float(rows[i].get("spend") or 0) for i in members[k])} for k in members}


def score_elements(rows: List[Dict[str, Any]], objective: str = "leads", seed: int = 7) -> Dict[str, Any]:
    """Score every element value across ads. `rows` are ads: {"id", "elements": {key: value}, "impressions", "clicks",
    "conversions", "spend"}. Each element value gets a (shrunk) rate, its lift over the average, and a family-wise
    adjusted p-value for being better (p_better) or worse (p_worse) than the rest. Small p is strong evidence."""
    succ_f, trial_f = OBJECTIVE_METRIC.get(objective, OBJECTIVE_METRIC["leads"])
    total_s = sum(float(r.get(succ_f) or 0) for r in rows)
    total_t = sum(float(r.get(trial_f) or 0) for r in rows)
    total_imp = sum(float(r.get("impressions") or 0) for r in rows)
    out: Dict[str, Any] = {"objective": objective, "metric": f"{succ_f} per {trial_f[:-1] if trial_f.endswith('s') else trial_f}",
                           "total_impressions": total_imp, "ads": len(rows), "enough_data": False, "elements": [], "ad_scores": []}
    if total_t <= 0 or total_s <= 0:
        return out
    p0 = total_s / total_t
    strength = max(2000.0, 0.02 * total_t)
    out["baseline_rate"] = p0
    out["enough_data"] = total_imp >= MIN_TOTAL_IMPRESSIONS and len(rows) >= 4
    rng = random.Random(seed)
    for (k, v), st in _perm_test(rows, succ_f, trial_f, lambda r: [(k, str(v)) for k, v in (r.get("elements") or {}).items()],
                                 MIN_ADS_PER_VALUE, rng).items():
        rate = _shrunk(st["successes"], st["trials"], p0, strength)
        out["elements"].append({"element": k, "value": v, "ads": st["ads"], "trials": st["trials"], "successes": st["successes"],
                                "rate": rate, "lift": rate / p0 - 1, "z": st["z"], "p_better": st["p_better"],
                                "p_worse": st["p_worse"], "spend": st["spend"], "reliable": st["trials"] >= MIN_TRIALS_PER_VALUE})
    out["elements"].sort(key=lambda e: (e["p_better"], -e["lift"]))
    for aid, st in _perm_test(rows, succ_f, trial_f, lambda r: [r.get("id")], 1, rng).items():
        rate = _shrunk(st["successes"], st["trials"], p0, strength)
        out["ad_scores"].append({"id": aid, "rate": rate, "lift": rate / p0 - 1, "z": st["z"], "p_better": st["p_better"],
                                 "p_worse": st["p_worse"], "trials": st["trials"], "spend": st["spend"]})
    out["ad_scores"].sort(key=lambda a: (a["p_better"], -a["lift"]))
    return out


# ------------------------------------------------------------------------------------------------ decisions
def winners(scores: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The best value per element, only where the evidence is strong: significant after correcting for how many values
    were compared, reliable, and a meaningful lift. Empty when there is not enough data."""
    if not scores.get("enough_data"):
        return {}
    best: Dict[str, Dict[str, Any]] = {}
    for e in scores["elements"]:
        if e["reliable"] and e["p_better"] <= SIGNIFICANCE and e["lift"] >= MIN_LIFT and e["element"] not in best:
            best[e["element"]] = e
    return best


def losers(scores: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not scores.get("enough_data"):
        return []
    return sorted((e for e in scores["elements"] if e["reliable"] and e["p_worse"] <= SIGNIFICANCE and e["lift"] <= -MIN_LIFT),
                  key=lambda e: e["p_worse"])


def recommend(scores: Dict[str, Any]) -> Dict[str, Any]:
    """What to do next, with the reason. Conservative by design: it recommends nothing until the data supports it."""
    if not scores.get("enough_data"):
        return {"status": "not_enough_data",
                "reason": f"{scores.get('total_impressions', 0):,.0f} impressions across {scores.get('ads', 0)} ads; need "
                          f"{MIN_TOTAL_IMPRESSIONS:,} across at least 4 ads. Keep running the variations.",
                "promote_ads": [], "pause_ads": [], "winning_elements": {}, "losing_elements": []}
    top = [a for a in scores["ad_scores"] if a["p_better"] <= SIGNIFICANCE and a["lift"] >= MIN_LIFT][:2]
    bad = [a for a in scores["ad_scores"] if a["p_worse"] <= SIGNIFICANCE and a["lift"] <= -MIN_LIFT]
    win = winners(scores)
    return {"status": "ok", "promote_ads": [a["id"] for a in top], "pause_ads": [a["id"] for a in bad],
            "winning_elements": {k: {"value": e["value"], "lift": round(e["lift"], 3), "p_adjusted": round(e["p_better"], 3),
                                     "ads": e["ads"]} for k, e in win.items()},
            "losing_elements": [{"element": e["element"], "value": e["value"], "lift": round(e["lift"], 3),
                                 "p_adjusted": round(e["p_worse"], 3)} for e in losers(scores)[:8]],
            "reason": "Promote the top ads with more budget and make the next batch from the winning elements, keeping an "
                      f"exploration share of {int(EXPLORATION_SHARE * 100)}%."}


def generation_weights(scores: Dict[str, Any], values_by_element: Dict[str, List[str]]) -> Dict[str, Dict[str, float]]:
    """Probability of choosing each value of each element in the next batch. A value's pull is its lift, scaled by how
    strong the evidence is; weak evidence barely moves it. Every value keeps an exploration share."""
    table = ({(e["element"], e["value"]): e for e in scores.get("elements", []) if e["reliable"]}
             if scores.get("enough_data") else {})
    out: Dict[str, Dict[str, float]] = {}
    for key, values in values_by_element.items():
        raw = {}
        for v in values:
            e = table.get((key, v))
            if not e:
                raw[v] = 1.0
                continue
            p = e["p_better"] if e["lift"] >= 0 else e["p_worse"]
            raw[v] = math.exp(2.0 * e["lift"] * max(0.0, 1.0 - p))
        total = sum(raw.values())
        out[key] = {v: (1 - EXPLORATION_SHARE) * raw[v] / total + EXPLORATION_SHARE / len(values) for v in values}
    return out


def choose(weights: Dict[str, float], rng: Optional[random.Random] = None) -> str:
    rng = rng or random.Random()
    r, acc = rng.random(), 0.0
    for v, w in weights.items():
        acc += w
        if r <= acc:
            return v
    return next(iter(weights))

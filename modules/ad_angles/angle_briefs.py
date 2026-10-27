"""
Stage 1 of ad creation: angle briefs only, no copy.

An angle is a deliberate combination of WHO is spoken to, the MOMENT that makes them act and
the LEVER the ad pulls. A good set is a portfolio: different people, moments and levers.

Models are poor at judging their own diversity, so this stage does not ask for it. It:
  1. has the model write one candidate per assigned lever slot (levers are assigned here, in code),
     each for a different kind of buyer, over-generating so there is something to choose from;
  2. selects the final set in code: farthest-point selection on how different the candidates are
     (embeddings), subject to coverage rules from angle_policy.py;
  3. checks the set against those rules and asks the model to replace only what fails.

Nothing here names a brand, an industry or an example person: offerings, buyer types and people
come from the business's own website and buyer profiles.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from modules.ad_angles import angle_policy as policy
from modules.ad_angles.fact_bank import build_fact_bank, facts_block, pick_offering_facts

logger = logging.getLogger(__name__)

LEVERS = policy.LEVERS
# a concrete figure: digits or a spelled-out number
_FIGURE = (r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
           r"hundred|thousand|dozen|half|double|triple)\b")
_BRIEF_FIELDS = ("angle_name", "name", "who", "who_is_on_site", "from_profile", "profile", "archetype", "life_stage",
                 "where_they_are", "buying_for", "offering", "offering_led", "fact_ids", "trigger_moment", "tension",
                 "lever", "insight", "proof", "specific", "objection", "hook_idea", "action")

_CANDIDATE_SCHEMA = {
    "angle_name": "3-6 words naming the situation, never a product name",
    "name": "the person's first name; different for every candidate and never one used in the buyer profiles",
    "who": "one specific person in one specific situation: role, circumstances and what they are trying to do",
    "who_is_on_site": "true ONLY if the website explicitly names this kind of person; false if you inferred them",
    "from_profile": "true only if this person wants the same thing as one of the known buyer profiles (the same "
                    "purchase goal and reason, with a NEW name and a new situation), false otherwise",
    "profile": "if from_profile is true, the exact title of the known buyer profile this person re-imagines; else empty",
    "archetype": "the kind of buyer this is, in 2-4 words, different for every candidate",
    "life_stage": "one of: " + ", ".join(policy.BUYER_DIMENSIONS["life_stage"]),
    "where_they_are": "one of: " + ", ".join(policy.BUYER_DIMENSIONS["where_they_are"]),
    "buying_for": "one of: " + ", ".join(policy.BUYER_DIMENSIONS["buying_for"]),
    "offering": "which core offering this person is buying, or 'other'",
    "trigger_moment": "the exact moment or event that makes them need this now",
    "tension": "what they feel and what it costs them to do nothing",
    "lever": "the lever assigned to this slot, exactly",
    "insight": "the non-obvious truth about this person that makes the ad feel written for them",
    "offering_led": "true if this angle leads with a real fact from the FACT BANK; false if it leads with a person's "
                    "situation",
    "fact_ids": ["ids of the fact-bank facts this angle relies on, such as F3; empty if none"],
    "proof": "the real fact (from the fact bank) or the detail from a buyer profile that the ad leans on, stated as it "
             "appears there",
    "specific": "one concrete figure, time, place or quantity taken from the fact bank or from the buyer profiles",
    "objection": "the doubt this person has that the ad must answer",
    "hook_idea": "the literal opening line the reader would see",
    "action": "what you want them to do (call, WhatsApp, visit, book, request a quote, order)",
}


# ---------------------------------------------------------------- slots and prompt
def _slots(n: int) -> List[str]:
    """One lever per candidate slot: every lever once, then extra slots drawn from the required groups
    so the selection step always has more than one option for the levers a set must contain."""
    slots = list(LEVERS)
    extras = [lv for group in policy.REQUIRED_LEVER_GROUPS for lv in group]
    i = 0
    while len(slots) < n and extras:
        slots.append(extras[i % len(extras)])
        i += 1
    return slots[:max(n, len(LEVERS))]


def _profile_titles(profile: Dict[str, Any]) -> List[str]:
    dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else {}
    return [str(p.get("name") or "") for p in (dna.get("buyer_profiles") or []) if isinstance(p, dict) and p.get("name")]


def _slot_lines(n: int, titles: List[str], lead_facts: Optional[List[Dict[str, Any]]] = None) -> str:
    """Numbered slot instructions. Each slot carries its assigned lever. Known buyer profiles and the facts that
    lead offering-led angles are assigned to slots here, in code, so they are guaranteed to be written, not merely
    requested. Every special slot takes a lever from a DIFFERENT required lever group in turn, so writing them also
    satisfies the coverage rules and leaves the remaining slots free."""
    levers = _slots(n)
    specials = [("profile", t) for t in titles[:policy.MAX_PROFILE_SEGMENTS]] + [("fact", f) for f in (lead_facts or [])]
    at, used = {}, set()
    for j, item in enumerate(specials):
        group = set(policy.REQUIRED_LEVER_GROUPS[j % len(policy.REQUIRED_LEVER_GROUPS)])
        idx = next((i for i, lv in enumerate(levers) if lv in group and i not in used), None)
        if idx is None:
            idx = next((i for i in range(len(levers)) if i not in used), None)
        if idx is None:
            break
        used.add(idx)
        at[idx] = item
    lines = []
    for i, lv in enumerate(levers):
        line = f"{i + 1}. lever = {lv}"
        kind, val = at.get(i, (None, None))
        if kind == "profile":
            line += (f"; re-imagine this known buyer profile as a NEW person who wants the same thing: '{val}' "
                     f"(from_profile true, profile = that exact title, offering_led false)")
        elif kind == "fact":
            line += (f"; OFFERING-LED: lead with this real fact and write the person it matters to: {val['id']} "
                     f"'{val['fact']}' (offering_led true, fact_ids [\"{val['id']}\"], from_profile false)")
        else:
            line += "; from_profile false, offering_led false"
        lines.append(line)
    return "\n".join(lines)


_PROFILE_SKIP = {"id", "name", "profile_name", "character_name", "created_at", "updated_at", "brand_kit_id",
                 "team_id", "workspace_id", "targeting_hint"}
_PROFILE_FIELD_CAP = 450      # characters kept per profile field
_PROFILE_CAP = 2600           # characters kept per profile


def _profile_text(p: Dict[str, Any]) -> str:
    """One buyer profile as prompt text, using EVERY field it has (situation, pain, daily reality, triggers, the
    customer's own words, objections, creative direction...), not a fixed few. A richer profile gives
    richer angles; the field names are shown to the model as labels, so no field list is hardcoded."""
    title = p.get("name") or p.get("profile_name") or "profile"
    parts = []
    for k, v in p.items():
        if k in _PROFILE_SKIP or v in (None, "", [], {}):
            continue
        value = " | ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)
        parts.append(f"  {k.replace('_', ' ')}: {value.strip()[:_PROFILE_FIELD_CAP]}")
    body = "\n".join(parts)[:_PROFILE_CAP]
    return f"- {title}\n{body}"


def _profiles_block(profile: Dict[str, Any]) -> Tuple[str, str]:
    dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else {}
    vs, about = dna.get("voice_and_style") or {}, dna.get("about") or {}
    profiles = [p for p in (dna.get("buyer_profiles") or []) if isinstance(p, dict)]
    block = ""
    if vs or about:
        block = (f"\nBRAND VOICE: {vs.get('tone_of_voice', '')}\n"
                 f"TARGET DEMOGRAPHIC: {vs.get('target_demographic', '')}\n"
                 f"PROBLEM THEY SOLVE: {about.get('problem_solved', '')}\n"
                 f"DIFFERENTIATOR: {about.get('differentiation', '')}\n"
                 + (f"POSITIONING: {about.get('positioning')}\n" if about.get("positioning") else ""))
    text = ""
    if profiles:
        text = "\n".join(_profile_text(p) for p in profiles)
        block += ("\nKNOWN BUYER PROFILES (segments that already buy. Never reuse a personal name that appears "
                  "here):\n" + text + "\n")
    return block, text


def _rules() -> str:
    return ("RULES\n"
            "- Ground every angle. The specifics (figures, prices, terms, places, times, deadlines, quantities) come "
            "only from the FACT BANK (real facts about the business) and from the KNOWN BUYER PROFILES (the situations, "
            "numbers, events and words of the people who buy). People beyond the profiles live in the same world as "
            "the profiles. Do not add prices, offers, awards, customer counts or other claims about the business "
            "that are not in the fact bank.\n"
            "- specific must contain a concrete figure, time, place or quantity from those sources. State proof and "
            "specific as they appear there.\n"
            "- hook_idea is the literal opening line, written out, not a description of a scene. Do not end more than "
            "a few hooks with a question mark.\n"
            "- Every person must be someone who could realistically buy what this business sells within weeks.\n"
            "- Tag every candidate on life_stage, where_they_are and buying_for using the listed values. Across the "
            "candidates, use every value that fits this business; do not make most of them the same kind of person.\n"
            "- No em dashes, no clichés, no emojis.\n")


def _build_prompt(profile: Dict[str, Any], website_text: str, count: int, n_candidates: int,
                  replace: Optional[List[Dict[str, str]]] = None, taken: Optional[List[str]] = None,
                  facts: Optional[List[Dict[str, Any]]] = None,
                  lead_facts: Optional[List[Dict[str, Any]]] = None) -> str:
    def as_list(value):
        return ", ".join(str(v.get("name") if isinstance(v, dict) else v) for v in (value or []) if v)

    brand_block, _ = _profiles_block(profile)
    lever_lines = "\n".join(f"- {k}: {v}" for k, v in LEVERS.items())
    head = (
        "You are a senior advertising strategist planning Facebook/Instagram ads. You write angle candidates "
        "only; another writer will write the copy.\n\n"
        f"BUSINESS: {profile.get('company_name') or 'unknown'}: {profile.get('business_type') or ''}\n"
        f"Location: {profile.get('location') or 'unknown'}\n"
        f"Products/services: {as_list(profile.get('products') or profile.get('services_products'))}\n"
        f"Value propositions: {as_list(profile.get('value_propositions'))}\n"
        f"Audiences: {as_list(profile.get('target_audiences'))}\n"
        + brand_block
        + facts_block(facts or [])
        + f"\nWEBSITE TEXT:\n{(website_text or 'not available')[:9000]}\n\n"
        "THE IDEA\n"
        "An angle is a deliberate combination of WHO is being spoken to, the MOMENT that makes them act, and the "
        "LEVER the ad pulls. A strong set is a portfolio of different people, moments and levers, so each ad would "
        "stop a different scroller.\n\nLEVERS\n" + lever_lines + "\n\n")

    if replace:
        slots = "\n".join(f"{i + 1}. {r['instruction']}" for i, r in enumerate(replace))
        return (head + "TASK\nWrite replacement candidates for a set that is missing something. Write exactly one "
                "candidate for each numbered instruction, in order. Each must be a different kind of buyer, with a "
                "first name not already taken"
                + (f" (taken: {', '.join(taken)})" if taken else "") + ".\n\nINSTRUCTIONS\n" + slots + "\n\n"
                + _rules() + "\nReturn ONLY JSON shaped like:\n"
                + json.dumps({"candidates": [_CANDIDATE_SCHEMA]}))

    slots = _slot_lines(n_candidates, _profile_titles(profile), lead_facts)
    return (head + "HOW TO THINK\n"
            "0. Name the 3 or 4 core offerings this business lives on (core_offerings), from the website.\n"
            "1. List 8 to 12 different kinds of buyer (candidate_people): role, situation, what each secretly fears "
            "or wants. The known buyer profiles are the brand owner's own statement of who they want to reach, "
            "so re-imagine 2 or 3 of them as different people with new names and situations, keeping exactly what "
            "each profile wants to buy and why (mark them from_profile true), then go well beyond them: people the site never mentions, people buying "
            "for someone else, newcomers, sceptics who were burned before, and people with a deadline.\n"
            "2. Write one candidate per slot below, in order. Slot k MUST use exactly the lever given, and where a "
            "slot names a known buyer profile you MUST write a new person who wants what that profile wants, and where "
            "a slot is OFFERING-LED the angle leads with that real fact (the hook states or builds on the fact) and "
            "the person is someone it matters to. Every candidate "
            "is a different person from a different kind of buyer, in a different situation, with a different first "
            "name that does not appear in the buyer profiles. Spread the candidates across the core offerings.\n\n"
            "SLOTS\n" + slots + "\n\n" + _rules()
            + f"\nWe will keep {count} of the {n_candidates} candidates, so make every one strong and distinct.\n"
            "Return ONLY JSON shaped like:\n"
            + json.dumps({"core_offerings": ["3-4 main products, services or customer groups from the website"],
                          "candidate_people": ["8-12 kinds of buyer"], "candidates": [_CANDIDATE_SCHEMA]}))


# ---------------------------------------------------------------- distance and selection
def _tokens(c: Dict[str, Any]) -> set:
    text = " ".join(str(c.get(k) or "") for k in ("who", "trigger_moment", "hook_idea", "archetype", "lever"))
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())}


def _vectors(cands: List[Dict[str, Any]]):
    """Embedding vectors for the candidates (self-hosted by default), or None if unavailable."""
    try:
        from utils.embeddings import embed_texts
        texts = [f"{c.get('who')}. {c.get('trigger_moment')}. {c.get('hook_idea')}. {c.get('lever')}" for c in cands]
        vecs = embed_texts(texts, agent_name="angle_selection")
        if len(vecs) == len(cands):
            return vecs
    except Exception as e:  # never let selection break on the embedding backend
        logger.info("[AngleBriefs] embeddings unavailable, using word overlap: %s", e)
    return None


def _distance_matrix(cands: List[Dict[str, Any]]) -> List[List[float]]:
    n = len(cands)
    vecs = _vectors(cands)
    d = [[0.0] * n for _ in range(n)]
    sets = [_tokens(c) for c in cands]
    for i in range(n):
        for j in range(i + 1, n):
            if vecs is not None:
                dot = sum(a * b for a, b in zip(vecs[i], vecs[j]))
                norm = (sum(a * a for a in vecs[i]) ** 0.5) * (sum(b * b for b in vecs[j]) ** 0.5) or 1.0
                dist = 1.0 - dot / norm
            else:
                union = sets[i] | sets[j]
                dist = 1.0 - (len(sets[i] & sets[j]) / len(union) if union else 0.0)
            d[i][j] = d[j][i] = dist
    return d


def select_diverse(cands: List[Dict[str, Any]], count: int, offerings: List[str],
                   n_profiles: int = 0, n_facts: int = 0) -> List[Dict[str, Any]]:
    """Pick `count` candidates that are most different from each other while meeting the coverage rules."""
    if len(cands) <= count:
        return list(cands)
    dist = _distance_matrix(cands)
    chosen: List[int] = []
    groups = [set(g) for g in policy.REQUIRED_LEVER_GROUPS]
    offs = [o.lower() for o in offerings][:policy.OFFERING_COVERAGE_SLOTS]
    unmet_groups = list(range(len(groups)))
    unmet_offs = list(range(len(offs)))
    off_site_needed = policy.MIN_OFF_SITE_PEOPLE
    profile_needed = min(policy.MIN_PROFILE_SEGMENTS, n_profiles)
    profile_used = 0
    used_titles = set()
    names, lever_count = set(), {}
    dim_count = {d: {} for d in policy.BUYER_DIMENSIONS}

    def dim_over(c):
        return any(dim_count[d].get(str(c.get(d) or ""), 0) >= policy.MAX_PER_DIMENSION_VALUE
                   for d in policy.BUYER_DIMENSIONS if c.get(d))

    def dim_new(c):
        return sum(1 for d in policy.BUYER_DIMENSIONS if c.get(d) and not dim_count[d].get(str(c.get(d)), 0))

    def buys(c, k):
        return bool(offs[k]) and offs[k][:14] in str(c.get("offering") or "").lower()

    def gain(i):
        c = cands[i]
        g = sum(1 for k in unmet_groups if c.get("lever") in groups[k])
        o = sum(1 for k in unmet_offs if buys(c, k))
        s = 1 if (not c.get("who_is_on_site") and off_site_needed > 0) else 0
        t = str(c.get("profile") or "").strip().lower()
        p = 1 if (c.get("from_profile") and profile_needed > 0 and t not in used_titles) else 0
        return g + o + s + p

    def take(i):
        nonlocal unmet_groups, unmet_offs, off_site_needed, profile_used, profile_needed
        c = cands[i]
        chosen.append(i)
        names.add(str(c.get("name") or "").strip().lower())
        lever_count[c.get("lever")] = lever_count.get(c.get("lever"), 0) + 1
        for d in policy.BUYER_DIMENSIONS:
            if c.get(d):
                dim_count[d][str(c.get(d))] = dim_count[d].get(str(c.get(d)), 0) + 1
        unmet_groups = [k for k in unmet_groups if c.get("lever") not in groups[k]]
        unmet_offs = [k for k in unmet_offs if not buys(c, k)]
        if not c.get("who_is_on_site") and off_site_needed > 0:
            off_site_needed -= 1
        if c.get("from_profile"):
            used_titles.add(str(c.get("profile") or "").strip().lower())
            profile_used += 1
            profile_needed = max(0, profile_needed - 1)

    # Known buyer profiles are the brand owner's explicit instruction, so reserve a slot for each required
    # profile first; the other rules then fill the remaining slots. (Otherwise they compete for the same few
    # slots and the profile requirement is the one that loses.)
    by_title: Dict[str, List[int]] = {}
    for i, c in enumerate(cands):
        t = str(c.get("profile") or "").strip().lower()
        if c.get("from_profile") and t:
            by_title.setdefault(t, []).append(i)
    for t, idxs in list(by_title.items())[:profile_needed]:
        if len(chosen) >= count:
            break
        pick = max(idxs, key=lambda i: (gain(i), sum(dist[i])))
        if str(cands[pick].get("name") or "").strip().lower() not in names:
            take(pick)

    # Offering-led angles (leading with a real fact) are reserved next, one per distinct fact.
    by_fact: Dict[str, List[int]] = {}
    for i, c in enumerate(cands):
        if c.get("offering_led") and c.get("fact_ids"):
            by_fact.setdefault(str(c["fact_ids"][0]), []).append(i)
    led_needed = min(policy.MIN_OFFERING_LED, n_facts)
    for _, idxs in list(by_fact.items()):
        if led_needed <= 0 or len(chosen) >= count:
            break
        pick = max((i for i in idxs if i not in chosen), key=lambda i: (gain(i), sum(dist[i])), default=None)
        if pick is not None and str(cands[pick].get("name") or "").strip().lower() not in names:
            take(pick)
            led_needed -= 1

    relaxed = False   # if the caps leave no candidate, drop the soft caps rather than return a short set
    while len(chosen) < count:
        best, best_key = None, None
        for i, c in enumerate(cands):
            if i in chosen:
                continue
            nm = str(c.get("name") or "").strip().lower()
            if nm and nm in names:
                continue
            if not relaxed:
                if lever_count.get(c.get("lever"), 0) >= policy.MAX_PER_LEVER:
                    continue
                if c.get("from_profile") and n_profiles and profile_used >= policy.MAX_PROFILE_SEGMENTS:
                    continue
                if dim_over(c):
                    continue
            spread = (min(dist[i][j] for j in chosen) if chosen
                      else sum(dist[i]) / max(1, len(cands) - 1))
            key = (gain(i), dim_new(c), 0 if lever_count.get(c.get("lever"), 0) else 1, spread)
            if best_key is None or key > best_key:
                best, best_key = i, key
        if best is None:
            if relaxed:
                break
            relaxed = True
            continue
        take(best)
    return [cands[i] for i in chosen]


# ---------------------------------------------------------------- checks
def check_set(briefs: List[Dict[str, Any]], offerings: List[str], profile_text: str,
              n_profiles: int = 0, profile_titles: Optional[List[str]] = None,
              facts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Rule violations in a final set, each with a plain-language instruction for a replacement."""
    problems = []
    levers = [b.get("lever") for b in briefs]
    for group in policy.REQUIRED_LEVER_GROUPS:
        if not any(lv in group for lv in levers):
            problems.append({"kind": "lever_group", "instruction": f"Use one of these levers: {', '.join(group)}."})
    for lv in set(levers):
        if levers.count(lv) > policy.MAX_PER_LEVER:
            problems.append({"kind": "lever_repeat", "instruction": f"Use a lever other than {lv}."})
    if len(set(levers)) < policy.MIN_DISTINCT_LEVERS:
        problems.append({"kind": "distinct_levers", "instruction": "Use a lever not yet used in this set."})
    for o in offerings[:policy.OFFERING_COVERAGE_SLOTS]:
        if not any(o.lower()[:14] in str(b.get("offering") or "").lower() for b in briefs):
            problems.append({"kind": "offering", "instruction": f"The person is buying this offering: {o}."})
    if sum(1 for b in briefs if not b.get("who_is_on_site")) < policy.MIN_OFF_SITE_PEOPLE:
        problems.append({"kind": "off_site", "instruction": "The person must be someone the website does not address."})
    if n_profiles:
        covered = {str(b.get("profile") or "").strip().lower() for b in briefs if b.get("from_profile")}
        missing = [t for t in (profile_titles or []) if t and t.strip().lower() not in covered]
        need = min(policy.MIN_PROFILE_SEGMENTS, n_profiles) - len(covered)
        for t in missing[:max(0, need)]:
            problems.append({"kind": "profile", "instruction":
                             f"Re-imagine this known buyer profile as a new person who wants the same thing: '{t}'. "
                             f"Set from_profile true and profile to that exact title."})
    if facts:
        led = [b for b in briefs if b.get("offering_led") and b.get("fact_ids")]
        used = {str(b["fact_ids"][0]) for b in led}
        spare = [f for f in pick_offering_facts(facts, policy.OFFERING_LED_CANDIDATES + len(used)) if f["id"] not in used]
        for f in spare[:max(0, min(policy.MIN_OFFERING_LED, len(facts)) - len(led))]:
            problems.append({"kind": "offering_led", "instruction":
                             f"OFFERING-LED: lead with this real fact and write the person it matters to: {f['id']} "
                             f"'{f['fact']}' (offering_led true, fact_ids [\"{f['id']}\"])."})
    for d in policy.BUYER_DIMENSIONS:
        vals = [str(b.get(d)) for b in briefs if b.get(d)]
        for v in set(vals):
            if vals.count(v) > policy.MAX_PER_DIMENSION_VALUE:
                problems.append({"kind": "dimension",
                                 "instruction": f"The person must not be '{v}' for {d}; choose a different {d}."})
                break
    if any(not re.search(_FIGURE, " ".join(str(b.get(k) or "") for k in ("specific", "proof", "hook_idea")), re.I)
           for b in briefs):
        problems.append({"kind": "specific",
                         "instruction": "The specific must contain a concrete figure, time or quantity."})
    banned = set(re.findall(r"\b[A-Z][a-z]{2,}\b", profile_text or ""))
    seen = set()
    for b in briefs:
        nm = str(b.get("name") or "").strip()
        if nm and (nm in banned or nm.lower() in seen):
            problems.append({"kind": "name", "instruction": "Give the person a new first name."})
        seen.add(nm.lower())
    return problems


# ---------------------------------------------------------------- orchestration
def _clean(a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not (isinstance(a, dict) and a.get("who") and a.get("lever")):
        return None
    b = {k: a.get(k) for k in _BRIEF_FIELDS}
    lever = str(b["lever"] or "").strip().lower().replace(" ", "_").replace("-", "_")
    b["lever"] = lever if lever in LEVERS else "aspiration_outcome"
    for d, allowed in policy.BUYER_DIMENSIONS.items():
        v = str(a.get(d) or "").strip().lower().replace(" ", "_").replace("-", "_")
        b[d] = v if v in allowed else None
    for flag in ("who_is_on_site", "from_profile", "offering_led"):
        b[flag] = str(a.get(flag)).strip().lower() in ("true", "yes", "1")
    ids = a.get("fact_ids") if isinstance(a.get("fact_ids"), list) else []
    b["fact_ids"] = [str(x).strip() for x in ids if re.fullmatch(r"F\d+", str(x).strip())]
    if not b["fact_ids"]:
        b["offering_led"] = False
    return b


def generate_angle_briefs_detailed(profile: Dict[str, Any], website_text: str, count: int = 5) -> Dict[str, Any]:
    """Full result: final briefs plus the candidate pool, problems found and repairs made (for evaluation)."""
    from modules.market_research.service import MarketResearchService

    svc = MarketResearchService()
    empty = {"briefs": [], "pool": [], "core_offerings": [], "problems": [], "repaired": 0}
    if not svc._llm_ready() or not (profile.get("business_type") or profile.get("company_name")):
        return empty
    model = os.getenv("AD_ANGLES_MODEL", "anthropic/claude-sonnet-4.6")
    n = max(policy.MIN_CANDIDATES, count * 2 + 2)
    _, profile_text = _profiles_block(profile)
    profile_titles = _profile_titles(profile)
    n_profiles = len(profile_titles)

    facts = build_fact_bank(svc, str(profile.get("company_name") or ""), website_text, model=model)
    lead_facts = pick_offering_facts(facts, policy.OFFERING_LED_CANDIDATES) if facts else []
    data = svc._llm_json(_build_prompt(profile, website_text, count, n, facts=facts, lead_facts=lead_facts),
                         model=model)
    raw = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        logger.warning("[AngleBriefs] no candidates returned")
        return empty
    offerings = [str(o) for o in (data.get("core_offerings") or []) if o]
    pool = [b for b in (_clean(a) for a in raw) if b]
    briefs = select_diverse(pool, count, offerings, n_profiles, len(facts))
    problems = check_set(briefs, offerings, profile_text, n_profiles, profile_titles, facts)
    repaired = 0
    for _ in range(policy.REPAIR_ROUNDS):
        if not problems:
            break
        taken = [str(b.get("name")) for b in pool if b.get("name")]
        fix = svc._llm_json(_build_prompt(profile, website_text, count, n, replace=problems[:4], taken=taken,
                                          facts=facts), model=model)
        extra = [b for b in (_clean(a) for a in ((fix or {}).get("candidates") or [])) if b]
        if not extra:
            break
        repaired += len(extra)
        pool += extra
        briefs = select_diverse(pool, count, offerings, n_profiles, len(facts))
        problems = check_set(briefs, offerings, profile_text, n_profiles, profile_titles, facts)
    logger.info("[AngleBriefs] %d briefs for %s (pool %d, repairs %d, problems left %d)",
                len(briefs), profile.get("company_name"), len(pool), repaired, len(problems))
    return {"briefs": briefs, "pool": pool, "core_offerings": offerings, "problems": problems, "repaired": repaired,
            "facts": facts}


def generate_angle_briefs(profile: Dict[str, Any], website_text: str, count: int = 5) -> List[Dict[str, Any]]:
    """`count` angle briefs for any business, or [] when no model or profile is available."""
    return generate_angle_briefs_detailed(profile, website_text, count)["briefs"]

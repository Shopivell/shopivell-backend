"""
Angle generation, plan then fill.

The earlier approach asked one model call for about a dozen candidates, then selected five in code and repaired
what was missing. Many rules competed for five slots, so something always lost. This module does it the other way
round:

  1. PLAN (code, deterministic): decide the composition of the set up front. Some slots are profile-led (a known
     buyer profile re-imagined as a new person), some are offering-led (they lead with a real fact from the fact
     bank), the rest are free. Every slot is assigned its lever, so the required lever groups are met by
     construction, plus hints for the kind of buyer so slots differ.
  2. FILL (model, one small focused call per slot, in parallel): write the angle for exactly that slot.
  3. VALIDATE (code, per slot): grounding, assigned lever, names, and a real specific in offering-led hooks.
     A slot that fails is rewritten once with the reason. The set is also checked for near-duplicates.

Nothing here names a brand, an industry or an example person. Claims about the business come from the fact bank;
the buyer's own situation, numbers and words come from the buyer profiles.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from modules.ad_angles import angle_policy as policy
from modules.ad_angles.angle_briefs import _profile_text
from modules.ad_angles.fact_bank import facts_block, pick_offering_facts

logger = logging.getLogger(__name__)

# Words that make a figure a CLAIM ABOUT THE BUSINESS or a count of people, which must come from the fact bank,
# the profiles or the site, never be made up.
_COUNT_UNITS = (r"(stores?|branches|branch|clients?|customers?|families|households|homes|years|products|projects|patients|"
                r"prescriptions|members|shoppers|people|businesses|organi[sz]ations|locations|offices|staff|"
                r"professionals|parents|owners|buyers|investors)")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "your", "you", "are", "its", "has", "have", "was", "all"}


# Letters a slot's first name must start with (different per slot, so names cannot collide).
_INITIALS = "AKMRTBCDGHJLNPSWY"


def _rotate(seq: list, k: int) -> list:
    if not seq:
        return seq
    k %= len(seq)
    return seq[k:] + seq[:k]


# ---------------------------------------------------------------- PLAN
def plan_set(count: int, profiles: List[Dict[str, Any]], facts: List[Dict[str, Any]], seed: int = 0) -> List[Dict[str, Any]]:
    """Deterministic composition of the set: which slots are profile-led, offering-led or free, each with its
    assigned lever (the three required lever groups are met by the first slots) and buyer-type hints."""
    n_prof = min(policy.MIN_PROFILE_SEGMENTS, len(profiles))
    slots: List[Dict[str, Any]] = [{"kind": "profile", "profile": p} for p in _rotate(profiles, seed)[:n_prof]]
    slots += [{"kind": "offering", "fact": f} for f in (pick_offering_facts(facts, policy.MIN_OFFERING_LED) if facts else [])]
    slots = slots[:count]
    while len(slots) < count:
        slots.append({"kind": "free"})
    groups = [list(g) for g in policy.REQUIRED_LEVER_GROUPS]
    others = _rotate([lv for lv in policy.LEVERS if not any(lv in g for g in groups)], seed)
    oi = 0
    for i, s in enumerate(slots):
        if i < len(groups):
            s["lever"] = _rotate(groups[i], seed)[0]
        else:
            s["lever"] = others[oi % len(others)]
            oi += 1
        s["situation"] = policy.SITUATION_TYPES[(i * 3 + seed) % len(policy.SITUATION_TYPES)]
        s["initial"] = _INITIALS[(i * 4 + seed) % len(_INITIALS)]
        if s["kind"] != "profile":
            s["hints"] = {d: vals[(i * (j + 2) + seed) % len(vals)]
                          for j, (d, vals) in enumerate(policy.BUYER_DIMENSIONS.items())}
    # Free slots are each pointed at a different offering from the fact bank than the offering-led slots use.
    used = {str(s["fact"].get("offering") or "").lower() for s in slots if s["kind"] == "offering"}
    spare = [o for o in dict.fromkeys(str(f.get("offering") or "") for f in facts) if o and o.lower() not in used]
    for k, s in enumerate(x for x in slots if x["kind"] == "free"):
        if spare:
            s["offering_focus"] = spare[(k + seed) % len(spare)]
    return slots


# ---------------------------------------------------------------- FILL
_SCHEMA = {
    "angle_name": "3-6 words naming the situation, never a product name",
    "name": "the person's first name",
    "who": "one specific person in one specific situation: role, circumstances and what they are trying to do",
    "archetype": "the kind of buyer, in 2-4 words",
    "life_stage": "one of: " + ", ".join(policy.BUYER_DIMENSIONS["life_stage"]),
    "where_they_are": "one of: " + ", ".join(policy.BUYER_DIMENSIONS["where_they_are"]),
    "buying_for": "one of: " + ", ".join(policy.BUYER_DIMENSIONS["buying_for"]),
    "offering": "which of the business's offerings this person is buying",
    "trigger_moment": "the exact moment or event that makes them need this now",
    "tension": "what they feel and what it costs them to do nothing",
    "insight": "the non-obvious truth about this person that makes the ad feel written for them",
    "proof": "the real fact (from the fact bank) or the detail from a buyer profile the ad leans on, as it appears there",
    "specific": "one concrete figure, time, place or quantity taken from the fact bank or from the buyer profiles",
    "objection": "the doubt this person has that the ad must answer",
    "hook_idea": "the literal opening line the reader would see",
    "action": "what you want them to do (call, WhatsApp, visit, book, request a quote, order)",
}

_RULES = (
    "RULES\n"
    "- Ground the angle. Claims about the business (prices, terms, places, scale, programs, how it makes or delivers "
    "things) come ONLY from the FACT BANK. The person's own situation, numbers, events, deadlines and words come from "
    "the BUYER PROFILES, so a person you write lives in the same world as the profiles. Never add prices, offers, "
    "awards or customer counts that are not in the fact bank.\n"
    "- hook_idea is the literal opening line, written out, not a description of a scene. It is concrete and specific.\n"
    "- specific must contain a concrete figure, time, place or quantity from those sources.\n"
    "- The person must be someone who could realistically buy what this business sells within weeks.\n"
    "- No em dashes, no clichés, no emojis.\n")


def _context(profile: Dict[str, Any], website_text: str, facts: List[Dict[str, Any]]) -> str:
    dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else {}
    vs, about = dna.get("voice_and_style") or {}, dna.get("about") or {}
    lines = [f"BUSINESS: {profile.get('company_name') or 'unknown'}: {profile.get('business_type') or ''}",
             f"Location: {profile.get('location') or 'unknown'}"]
    for label, val in (("BRAND VOICE", vs.get("tone_of_voice")), ("POSITIONING", about.get("positioning")),
                       ("PROBLEM THEY SOLVE", about.get("problem_solved")), ("DIFFERENTIATOR", about.get("differentiation"))):
        if val:
            lines.append(f"{label}: {val}")
    ctx = "\n".join(lines) + "\n" + facts_block(facts)
    if not facts:
        ctx += f"\nWEBSITE TEXT:\n{(website_text or '')[:6000]}\n"
    return ctx


def _describe(slot: Dict[str, Any]) -> str:
    what = (f"re-imagines profile '{slot['profile'].get('name')}'" if slot["kind"] == "profile"
            else f"leads with fact {slot['fact']['id']}" if slot["kind"] == "offering" else "a buyer nobody else covers")
    return f"{what}; lever {slot['lever']}; moment type: {slot['situation']}"


def _slot_prompt(slot: Dict[str, Any], ctx: str, profiles: List[Dict[str, Any]], taken_names: List[str],
                 avoid: Optional[str] = None, issues: Optional[List[str]] = None,
                 others: Optional[List[str]] = None) -> str:
    lever = slot["lever"]
    head = ("You are a senior advertising strategist. Write ONE angle for a Facebook/Instagram ad; another writer will "
            "write the copy.\n\n" + ctx + f"\nLEVER for this angle: {lever}: {policy.LEVERS[lever]}\n")
    if slot["kind"] == "profile":
        task = ("\nBUYER PROFILE (the brand owner's own picture of who buys):\n" + _profile_text(slot["profile"]) +
                "\n\nTASK: write a NEW person who wants what this profile wants, in a new situation. Keep what the profile "
                "buys and why. Reuse the profile's own world: its numbers, events, deadlines, fears and words. Give them a "
                "first name that is not the profile's character name.\n")
    elif slot["kind"] == "offering":
        f = slot["fact"]
        task = (f"\nLEAD FACT: {f['id']} \"{f['fact']}\"\n\nTASK: write an OFFERING-LED angle. The hook states or builds on "
                f"the specific in this fact (a price, a named program, a number, a place), not a vague paraphrase of the "
                f"brand. The person is someone it matters to; take their situation from the profiles' world.\n"
                "KNOWN BUYER PROFILES (for the world the person lives in):\n" +
                "\n".join(_profile_text(p) for p in profiles[:2]) + "\n")
    else:
        task = ("\nKNOWN BUYER PROFILES (for the world the person lives in):\n" +
                "\n".join(_profile_text(p) for p in profiles[:2]) +
                "\n\nTASK: write an angle for a buyer the website and the profiles do not already cover: for example "
                "someone buying for another person, a newcomer, a sceptic who was burned before, or someone with a "
                "deadline. Their life lives in the same world as the profiles.\n")
    task += (f"The moment that makes them act is of this type: {slot['situation']} (adapt it to the world of the profiles). "
             f"The person's first name starts with the letter {slot['initial']}.\n")
    if slot.get("offering_focus"):
        task += f"This person is buying: {slot['offering_focus']}.\n"
    if others:
        task += ("The rest of the set, so this angle stays clearly different from them:\n- " + "\n- ".join(others) + "\n")
    hints = slot.get("hints")
    if hints:
        task += ("Prefer this kind of buyer (change it only if unrealistic for this business): "
                 + ", ".join(f"{k} = {v}" for k, v in hints.items()) + ".\n")
    if taken_names:
        task += f"Do not use these first names: {', '.join(taken_names)}.\n"
    if avoid:
        task += f"The set already contains this hook; write something clearly different: \"{avoid}\"\n"
    if issues:
        task += "Your previous attempt was rejected because: " + "; ".join(issues) + ". Fix that.\n"
    return head + task + "\n" + _RULES + "\nReturn ONLY JSON shaped like:\n" + json.dumps(_SCHEMA)


# ---------------------------------------------------------------- VALIDATE
def _norm_num(s: str) -> str:
    return re.sub(r"[^\d.]", "", s).rstrip(".")


def _supported(text: str, *sources: str) -> bool:
    return any(text in re.sub(r"[,\s]", "", src) or text in src for src in sources)


def validate_brief(brief: Dict[str, Any], slot: Dict[str, Any], facts: List[Dict[str, Any]], profile_text: str,
                   site_text: str, banned_names: List[str]) -> List[str]:
    """Reasons this brief should be rewritten; empty when it is acceptable."""
    issues: List[str] = []
    text = " ".join(str(brief.get(k) or "") for k in ("hook_idea", "proof", "specific"))
    bank = " ".join(f["fact"] + " " + f["quote"] for f in facts)
    for m in re.finditer(r"\$?\d[\d,]*(?:\.\d+)?\+?\s*(?:%|" + _COUNT_UNITS + r")\b", text, re.I):
        num = _norm_num(re.match(r"\$?\d[\d,]*(?:\.\d+)?", m.group(0)).group(0))
        if num and not _supported(num, bank, profile_text, site_text):
            issues.append(f"'{m.group(0).strip()}' is a claim about the business or a count of people that is not in the "
                          f"fact bank or the profiles")
    if not str(brief.get("hook_idea") or "").strip():
        issues.append("no hook_idea")
    if re.search(r"[—–]", " ".join(str(v) for v in brief.values())):
        issues.append("contains an em or en dash")
    nm = str(brief.get("name") or "").strip()
    if not nm or nm.lower() in {n.lower() for n in banned_names}:
        issues.append("the first name is missing or already used")
    if slot["kind"] == "offering":
        fact_tokens = {t for t in re.findall(r"[A-Z][A-Za-z]{2,}|\d[\d,.]*", slot["fact"]["fact"])
                       if t.lower() not in _STOP}
        hook = " ".join(str(brief.get(k) or "") for k in ("hook_idea", "proof"))
        if fact_tokens and not any(t in hook for t in fact_tokens):
            issues.append("an offering-led hook must state or build on the specific in the lead fact")
    return issues


# ---------------------------------------------------------------- orchestration
def _similar(a: str, b: str) -> bool:
    ta, tb = set(re.findall(r"[a-z]{4,}", a.lower())), set(re.findall(r"[a-z]{4,}", b.lower()))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) > 0.5


def generate_angle_set(profile: Dict[str, Any], website_text: str, facts: List[Dict[str, Any]],
                       llm: Callable[[str], Dict[str, Any]], count: int = 5, seed: int = 0) -> Dict[str, Any]:
    """Plan the set, fill every slot with one focused call (in parallel), validate each, and return the briefs."""
    dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else {}
    profiles = [p for p in (dna.get("buyer_profiles") or []) if isinstance(p, dict)]
    profile_text = "\n".join(_profile_text(p) for p in profiles)
    banned = re.findall(r"\b[A-Z][a-z]{2,}\b", profile_text)
    ctx = _context(profile, website_text, facts)
    slots = plan_set(count, profiles, facts, seed)
    calls = {"n": 0}

    def fill(idx: int) -> Dict[str, Any]:
        slot, issues, brief = slots[idx], [], {}
        for attempt in range(2):
            calls["n"] += 1
            raw = llm(_slot_prompt(slot, ctx, profiles, banned, issues=issues or None,
                                   others=[_describe(o) for k, o in enumerate(slots) if k != idx]))
            brief = raw if isinstance(raw, dict) else {}
            issues = validate_brief(brief, slot, facts, profile_text, website_text, banned) if brief else ["empty reply"]
            if not issues:
                break
        brief = dict(brief)
        brief.update({"lever": slot["lever"], "slot": slot["kind"], "situation": slot.get("situation"),
                      "from_profile": slot["kind"] == "profile",
                      "profile": (slot.get("profile") or {}).get("name") if slot["kind"] == "profile" else None,
                      "offering_led": slot["kind"] == "offering",
                      "fact_ids": [slot["fact"]["id"]] if slot["kind"] == "offering" else [],
                      "who_is_on_site": slot["kind"] == "profile", "unresolved": issues})
        return brief

    with ThreadPoolExecutor(max_workers=min(5, len(slots))) as pool:
        briefs = list(pool.map(fill, range(len(slots))))

    # Set level: rewrite a slot whose hook is a near-duplicate of an earlier one, and de-duplicate first names.
    for i in range(1, len(briefs)):
        dup = next((briefs[j] for j in range(i) if _similar(str(briefs[i].get("hook_idea")) + " " + str(briefs[i].get("who")),
                                                          str(briefs[j].get("hook_idea")) + " " + str(briefs[j].get("who")))), None)
        if dup:
            names = banned + [str(b.get("name")) for b in briefs]
            calls["n"] += 1
            raw = llm(_slot_prompt(slots[i], ctx, profiles, names, avoid=str(dup.get("hook_idea")),
                                   others=[_describe(o) for k, o in enumerate(slots) if k != i]))
            if isinstance(raw, dict) and raw.get("hook_idea"):
                keep = {k: briefs[i][k] for k in ("lever", "slot", "from_profile", "profile", "offering_led", "fact_ids",
                                                  "who_is_on_site")}
                briefs[i] = {**raw, **keep, "unresolved": validate_brief(raw, slots[i], facts, profile_text, website_text, names)}
    problems = [{"kind": "slot", "slot": i, "issues": b.get("unresolved")} for i, b in enumerate(briefs) if b.get("unresolved")]
    return {"briefs": briefs, "plan": [{k: v for k, v in s.items() if k not in ("profile", "fact")} |
                                       ({"profile": s["profile"].get("name")} if s.get("profile") else {}) |
                                       ({"fact": s["fact"]["id"]} if s.get("fact") else {}) for s in slots],
            "facts": facts, "problems": problems, "calls": calls["n"]}

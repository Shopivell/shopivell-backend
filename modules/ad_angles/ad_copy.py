"""
Stage 2: turn an angle brief into a finished ad.

One focused call per angle, in parallel. The ad is built for how Meta ads are read: the first two lines carry the hook
on their own (only about 125 characters show before "See more"), one offering per ad, a confident voice, a closing
instruction that names a way to act, a two-part headline, a short description and a custom button label.

Two modes. An OFFER-LED angle opens with a confident statement about the benefit or problem the offer solves, aimed
at everyone who needs it, with no backstory. A SCENE angle (profile-led or free) opens on the moment from the angle,
described in general terms, never asserting facts about the reader's age, health, money, family or life events.

Claims about the business come only from the fact bank. The person's details come only from the angle brief and the
buyer profile. A validator checks grounding, length, structure, voice, invented people and Meta-sensitive wording; a
failed ad is rewritten once with the reasons, and anything still unresolved is returned flagged for human review.

Nothing here names a brand, an industry or an example.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from modules.ad_angles.angle_briefs import _profile_text
from modules.ad_angles.angle_plan import _COUNT_UNITS, _context

logger = logging.getLogger(__name__)

META_CTAS = ("Learn More", "Shop Now", "Get Quote", "Contact Us", "Book Now", "Sign Up", "Get Offer")
MIN_WORDS, MAX_WORDS = 110, 175
MIN_PARAGRAPHS = 5
HOOK_MAX_CHARS = 160
MIN_YOU_PER_100 = 3.5
HEADLINE_MAX, DESCRIPTION_MAX = 40, 30

_SCHEMA = {
    "primary_text": "the ad body: paragraphs separated by a blank line",
    "headline": f"at most {HEADLINE_MAX} characters",
    "description": f"at most {DESCRIPTION_MAX} characters",
    "button_label": "2-4 words saying what happens next",
    "meta_cta": "one of: " + ", ".join(META_CTAS),
    "facts_used": ["ids of the fact-bank facts the ad states, such as F3"],
}

_MODE_OFFER = (
    "MODE: OFFER-LED. Open with a confident statement about the benefit, or the problem, that this offer addresses, "
    "aimed at everyone who needs it and spoken to 'you'. No backstory, no named person, no invented scene. Build the "
    "whole ad on the lead fact and its one offering.\n")
_MODE_SCENE = (
    "MODE: SCENE. Open on the moment from the angle, described in general terms ('When...', 'If...', 'The week "
    "before...'). Do not assert facts about the reader's age, health, money, family, job or life events (never "
    "'you've retired', 'your prescription', 'you're in debt'); describe situations as situations. If the angle has a "
    "real deadline or event, that is the urgency.\n")

_STRUCTURE = (
    "STRUCTURE (follow it):\n"
    "1. Opening paragraph: one or two short lines, about 140 characters in total. It is the hook and must stand "
    "alone, because only the first lines show before 'See more'. Concrete and specific; do not open with a slogan.\n"
    "2. Two to four short paragraphs: the problem and what it costs to leave it, or what life looks like with the "
    "offer. Vivid and concrete, with no padding.\n"
    "3. The offer as the way out: the real fact or facts from the fact bank, stated confidently and exactly as they "
    "appear there. One offering only.\n"
    "4. One short line that removes the doubt by turning it into a reason to act.\n"
    "5. Closing: a short rhythmic line of three beats or fewer, then a direct instruction to act that names a way to "
    "act the business really offers. Use only contact details, addresses, channels or websites that appear in the fact "
    "bank (facts marked 'do not lead an ad with this' are fine here); never invent a link.\n"
    "LENGTH AND RHYTHM: 125 to 160 words in 6 to 9 short paragraphs, most of them one or two lines. Average sentence "
    "under 11 words, with a few very short ones. Plain spoken words.\n"
    "HEADLINE: at most 40 characters, in two short parts such as 'Part one. Part two.' or a direct benefit, about the "
    "reader or the offer.\n"
    "DESCRIPTION: at most 30 characters, adds a detail and does not repeat the headline.\n"
    "BUTTON: a short custom label of 2 to 4 words saying what happens next, and meta_cta one of the listed values.\n")

_CRAFT = (
    "CRAFT (how it should sound; it governs the wording):\n"
    "- Sound like a sharp, confident human copywriter, never like a report. Intelligent, warm, a little witty.\n"
    "- Speak straight to the reader: use 'you' and 'your' often, at least once in most sentences.\n"
    "- Sell the benefit and the payoff, not the process. Show life with the offer.\n"
    "- Build the ad around the SIGNATURE MOVE assigned below, and add one simple extra move. Do NOT use the reframe "
    "'This isn't X. It's Y.' unless it is your assigned move. A confident aside such as 'Yes, you read that right.' is "
    "allowed ONLY right after a genuinely surprising fact such as a low price or a big number.\n"
    "- Never write a line that says what the offer or the quote is not ('You're asking for a quote, not a promise').\n"
    "- Rhythm: mix punches of 2 to 6 words with one longer sentence. Vary how sentences begin.\n"
    "- NO FILLER: every sentence must add a fact, an image or a push. Never write a sentence that only restates the "
    "previous one or comments on it ('That gives you...', 'That keeps...', 'That's a lot of...').\n"
    "- NO CATALOG: never list what the business offers as 'We offer X. We offer Y. We offer Z.' Pick the one offering "
    "and sell it.\n"
    "- Never write: 'we know you', 'we understand', 'we invite you', 'guessing leaves you', 'waiting leaves you', "
    "'consider', 'explore'.\n")

_RULES = (
    "RULES\n"
    "- Claims about the business (prices, terms, places, scale, programs, how it makes or delivers things, contact "
    "details) come ONLY from the FACT BANK, stated as they appear. The person's numbers, events and words come ONLY "
    "from the angle and the profile.\n"
    "- Do not invent people, referrals, testimonials, customer stories, customer counts or claims about competitors. "
    "Name no person at all.\n"
    "- Urgency only if the angle gives a real deadline or the fact bank states a real time-limited offer. Otherwise "
    "no urgency and no scarcity.\n"
    "- Meta rules: no guarantees, absolutes ('always', 'never', 'best'), cures or risk-free claims unless the fact "
    "bank states them. Do not imply you know the reader's personal circumstances.\n"
    "- VOICE: after the opening, speak as the business ('we', 'our'). State facts as the business's own claims; never "
    "write 'the website says', '<the business> states that' or 'describes itself as'.\n"
    "- No em dashes, no emojis, no hashtags.\n")


def _prompt(brief: Dict[str, Any], ctx: str, profile_text: str, issues: Optional[List[str]] = None) -> str:
    angle = "\n".join(f"{k}: {brief.get(k)}" for k in
                      ("angle_name", "who", "trigger_moment", "tension", "insight", "lever", "hook_idea", "proof",
                       "specific", "objection", "action") if brief.get(k))
    mode = _MODE_OFFER if brief.get("slot") == "offering" else _MODE_SCENE
    if brief.get("craft_move"):
        mode += "SIGNATURE MOVE for this ad: " + brief["craft_move"] + "\n"
    head = ("You are a senior direct-response copywriter. Write ONE finished Facebook/Instagram ad.\n\n" + ctx +
            "\nTHE ANGLE:\n" + angle + "\n\nTHE PERSON'S WORLD (buyer profile, for the details of their situation):\n" +
            profile_text + "\n\n" + mode + "\n")
    if issues:
        head += "Your previous attempt was rejected because: " + "; ".join(issues) + ". Fix that.\n\n"
    return (head + _STRUCTURE + "\n" + _CRAFT + "\n" + _RULES + "\nReturn ONLY JSON shaped like:\n" + json.dumps(_SCHEMA))


def _clean_dashes(text: str) -> str:
    return re.sub(r"\s*[—–]\s*", ", ", text or "")


def _fit(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut.rsplit(" ", 1)[0] if " " in cut and text[limit] != " " else cut).rstrip(" ,;:-")


def _figures(text: str) -> List[str]:
    """Figures that need a source: money, 3+ digit numbers, and numbers attached to counts or percentages."""
    found = []
    for m in re.finditer(r"(?:US\$|\$)\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:%|" + _COUNT_UNITS + r"\b)|\b\d{3,}\b",
                         text, re.I):
        num = re.sub(r"[^\d.]", "", re.search(r"\d[\d,]*(?:\.\d+)?", m.group(0)).group(0)).rstrip(".")
        if num:
            found.append(num)
    return found


# ---- checks -------------------------------------------------------------------------------------------------
_FILLER = r"(?:^|(?<=[.!?]\s))(?:That|This) (?:gives|keeps|means|puts|lets|makes|is why|explains|shows|helps)\b"
_CATALOG = r"(?:^|(?<=[.!?]\s))We (?:offer|provide|sell|supply|stock)\b"
_BANNED = (r"we know you|we understand|we invite you|the website says|states that|describes itself|"
           r"guessing (leaves|can)|waiting (leaves|can)|\bconsider(ed)?\b|\bexplore\b|not whether you")
_DISCLAIMER = (r"(you['’]re asking for [^.]{0,40}, not|(this|it) isn['’]t (a |an )?(production|instant|promise|"
               r"guarantee|about knowing)|not an instant|not a promise)")
_REFRAME = r"(?:This|It) isn['’]t (?:just |only |about )?[^.]{0,60}\.\s+It['’]s"
CRAFT_MOVES = (
    "a reframe: 'This isn't X. It's Y.'",
    "a three-beat run: 'No more A. No more B. Just C.'",
    "a contrast: 'X shouldn't cost Y.' or 'Not X. Y.'",
    "a direct question the reader can only answer yes to, then the payoff",
    "a vivid before-and-after pair: one line of the problem, one line of life with the offer",
    "a bold claim in the opening, then the proof straight away",
)
_OVERCLAIM = r"\b(guarantee[sd]?|always|never|risk-free|100%|best in|number one|#1|cure[sd]?|miracle)\b"
_PERSONAL = (r"\b(you|your|you're|you've)\b[^.!?]{0,45}\b(retire\w*|pension\w*|elderly|diabet\w*|cancer|asthma|"
             r"blood pressure|medication|prescriptions?|in debt|debt|bankrupt\w*|divorc\w*|pregnan\w*|disabled|widow\w*|"
             r"single mother|unemployed|poor)\b")
_REGULATED = {"health": r"\b(prescription\w*|medicine\w*|medication|pharmacist|treatment|diagnos\w+)\b",
              "credit": r"\b(loans?|credit|instal?ments?|interest|financ\w+)\b",
              "housing": r"\b(mortgage|tenant|landlord|rent(al)?|apartments?|townhouses?|stands?|property)\b"}
_ALWAYS_OK = {"whatsapp", "sms", "facebook", "instagram", "email", "monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december", "zimbabwe", "zimbabwean"}


_NAME_LEAD = (r"(?:^|(?<=[.!?]\s))([A-Z][a-z]{2,})(?:,\s+(?:a|an|the)\b|\s+(?:says|said|has|had|was|told|asked|"
              r"recommended|referred|is)\b)")


def _invented_names(text: str, allowed: set) -> List[str]:
    out = [m.group(1) for m in re.finditer(_NAME_LEAD, text, re.M)
           if m.group(1).lower() not in allowed and m.group(1).lower() not in _ALWAYS_OK]
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for w in sentence.split()[1:]:
            t = re.sub(r"[^A-Za-z]", "", w)
            if len(t) >= 3 and t[0].isupper() and not t.isupper() and t.lower() not in allowed and t.lower() not in _ALWAYS_OK:
                out.append(t)
    return sorted(set(out))


def validate_ad(ad: Dict[str, Any], brief: Dict[str, Any], facts: List[Dict[str, Any]], profile_text: str,
                site_text: str) -> Tuple[List[str], List[str]]:
    """(issues that force a rewrite, flags for human review)."""
    issues: List[str] = []
    text = str(ad.get("primary_text") or "")
    words = len(text.split())
    paras = [p for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    if not MIN_WORDS <= words <= MAX_WORDS:
        issues.append(f"the primary text is {words} words; it must be {MIN_WORDS} to {MAX_WORDS}")
    if len(paras) < MIN_PARAGRAPHS:
        issues.append(f"only {len(paras)} paragraphs; use at least {MIN_PARAGRAPHS} short ones")
    if paras and len(paras[0]) > HOOK_MAX_CHARS:
        issues.append(f"the opening paragraph is {len(paras[0])} characters; keep it under {HOOK_MAX_CHARS} so the hook "
                      f"shows before 'See more'")
    if len(str(ad.get("headline") or "")) > HEADLINE_MAX or not ad.get("headline"):
        issues.append(f"the headline must be 1 to {HEADLINE_MAX} characters")
    if len(str(ad.get("description") or "")) > DESCRIPTION_MAX:
        issues.append(f"the description must be at most {DESCRIPTION_MAX} characters")
    source_text = " ".join([" ".join(f["fact"] + " " + f["quote"] for f in facts), profile_text, site_text,
                            " ".join(str(v) for v in brief.values() if isinstance(v, (str, int)))])
    flat = re.sub(r"[,\s]", "", source_text) + " " + source_text
    for num in dict.fromkeys(_figures(text + " " + str(ad.get("headline") or ""))):
        if num not in flat:
            issues.append(f"the figure {num} is not in the fact bank, the angle or the profile")
    last = paras[-1] if paras else ""
    if not re.search(r"\b(call|visit|upload|request|book|order|check|message|send|apply|find|shop|get|join|speak|read|"
                     r"browse|register|contact|start|ask|talk|learn|see|try|come|download|bring|take|compare|tell)\b",
                     last, re.I):
        issues.append("the closing paragraph must be a direct instruction to act")
    banned_hits = {m.group(0).lower() for m in re.finditer(_BANNED, text, re.I)}
    if banned_hits:
        issues.append("it uses banned phrasing: " + ", ".join(sorted(banned_hits)))
    if len(re.findall(_FILLER, text, re.M)) >= 1:
        issues.append("it has filler sentences that only comment on the previous line ('That gives you...'); every "
                      "sentence must add a fact, an image or a push")
    if len(re.findall(_CATALOG, text, re.M)) >= 2:
        issues.append("it lists offerings as 'We offer X. We offer Y.'; sell one offering instead")
    if re.search(_DISCLAIMER, text, re.I):
        issues.append("it has a line saying what the offer or quote is not; write confident lines about what it is")
    if re.search(_REFRAME, text) and "reframe" not in str(brief.get("craft_move") or ""):
        issues.append("it uses the 'This isn't X. It's Y.' reframe, which is reserved for another ad in the set")
    if re.search(r"yes, you read that right", text, re.I) and not re.search(r"US\$|\$\s?\d|\d{3,}", text):
        issues.append("'Yes, you read that right' must follow a surprising fact such as a low price or a big number")
    you = len(re.findall(r"\byou(?:r|'re|'ve|'ll)?\b", text, re.I)) / max(1, words) * 100
    if you < MIN_YOU_PER_100:
        issues.append(f"it does not speak to the reader enough ({you:.1f} 'you' per 100 words; use at least {MIN_YOU_PER_100})")
    allowed = set(re.findall(r"[A-Za-z]+", source_text.lower()))
    names = _invented_names(text, allowed)
    if names:
        issues.append("it names people or things that are not in the sources: " + ", ".join(names))
    if re.search(_OVERCLAIM, text, re.I):
        bank = " ".join(f["fact"] for f in facts).lower()
        bad = [m for m in re.findall(_OVERCLAIM, text, re.I) if m.lower() not in bank]
        if bad:
            issues.append("it makes an absolute or guarantee claim that is not in the fact bank: " + ", ".join(sorted(set(bad))))
    if re.search(_PERSONAL, text, re.I):
        issues.append("it asserts a personal circumstance about the reader (age, health, money or life event); describe "
                      "the situation in general terms instead")
    by_id = {f["id"]: f for f in facts}
    unknown = [str(x) for x in (ad.get("facts_used") or []) if str(x) not in by_id]
    if unknown:
        issues.append("facts_used lists facts that are not available to this ad: " + ", ".join(unknown))
    used = [by_id[i] for i in (str(x) for x in (ad.get("facts_used") or [])) if i in by_id]
    if not used:
        issues.append("facts_used must list the fact-bank ids the ad states")
    offerings = {f.get("offering", "").lower() for f in used if f.get("kind") not in ("location", "other") and f.get("offering")}
    limit = 1 if brief.get("slot") == "offering" else 3
    if len(offerings) > limit:
        issues.append("it spreads across several offerings; keep the ad on " + ("one offering" if limit == 1 else "at most three"))
    flags = [f"regulated category: {k}" for k, rx in _REGULATED.items() if re.search(rx, text, re.I)]
    return issues, flags


def write_ad(brief: Dict[str, Any], profile: Dict[str, Any], website_text: str, facts: List[Dict[str, Any]],
             llm: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else {}
    profiles = [p for p in (dna.get("buyer_profiles") or []) if isinstance(p, dict)]
    own = next((p for p in profiles if brief.get("profile") and p.get("name") == brief.get("profile")), None)
    profile_text = _profile_text(own) if own else "\n".join(_profile_text(p) for p in profiles[:2])
    ctx = _context(profile, website_text, facts)
    issues: List[str] = []
    flags: List[str] = []
    ad: Dict[str, Any] = {}
    for _ in range(2):
        raw = llm(_prompt(brief, ctx, profile_text, issues or None))
        ad = raw if isinstance(raw, dict) else {}
        ad["primary_text"] = _clean_dashes(str(ad.get("primary_text") or ""))
        for k in ("headline", "description", "button_label"):
            ad[k] = _clean_dashes(str(ad.get(k) or "")).strip()
        issues, flags = validate_ad(ad, brief, facts, profile_text, website_text) if ad.get("primary_text") else (["empty reply"], [])
        if not issues:
            break
    ad["description"] = _fit(ad.get("description", ""), DESCRIPTION_MAX)
    cta = str(ad.get("meta_cta") or "").strip()
    ad["meta_cta"] = next((c for c in META_CTAS if c.lower() == cta.lower()), "Learn More")
    ad.update({"lever": brief.get("lever"), "angle_name": brief.get("angle_name"), "slot": brief.get("slot"),
               "situation": brief.get("situation"), "craft_move": brief.get("craft_move"),
               "offering": brief.get("offering"),
               "words": len(ad["primary_text"].split()), "unresolved": issues, "review_flags": flags})
    return ad


def _tok(text: str) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def allocate_facts(briefs: List[Dict[str, Any]], facts: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Give every ad its own facts, in code, so proof never repeats across a set. Each ad gets its lead fact (offering-led)
    or the facts closest to its angle, plus the shared facts (contact details, locations, anything not meant to lead an
    ad), which any ad may use for its closing line."""
    by_id = {f["id"]: f for f in facts}
    shared = [f for f in facts if f.get("kind") in ("location", "other") or not f.get("ad_worthy", True)]
    pool = [f for f in facts if f not in shared]
    used: set = set()
    mine: List[List[Dict[str, Any]]] = [[] for _ in briefs]
    for i, b in enumerate(briefs):   # 1. reserve every lead fact first
        for fid in b.get("fact_ids") or []:
            f = by_id.get(fid)
            if f and f in pool and fid not in used:
                mine[i].append(f)
                used.add(fid)

    def closeness(f, b):
        anchor = " ".join(str(b.get(k) or "") for k in ("proof", "specific", "hook_idea"))
        return len(_tok(f["fact"]) & _tok(anchor))

    for target in (1, 2, 3):   # 2. everyone gets a first fact, then a second, then a third, best match first
        for i, b in enumerate(briefs):
            cands = [f for f in pool if f["id"] not in used]
            if len(mine[i]) < target and cands:
                best = max(cands, key=lambda f: closeness(f, b) + (3 if mine[i] and f.get("offering") == mine[i][0].get("offering") else 0))
                mine[i].append(best)
                used.add(best["id"])
    return [m + shared for m in mine]


def _sentences(text: str) -> set:
    return {s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", (text or "").replace("\n", " ")) if len(s.split()) >= 6}


def generate_ads(angle_set: Dict[str, Any], profile: Dict[str, Any], website_text: str,
                 llm: Callable[[str], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One finished ad per angle in the set, written in parallel, each from its own allocated facts, then a pass that
    rewrites an ad that repeats a sentence from an earlier one."""
    facts = angle_set.get("facts") or []
    briefs = angle_set.get("briefs") or []
    allocation = allocate_facts(briefs, facts)
    briefs = [dict(b, craft_move=CRAFT_MOVES[i % len(CRAFT_MOVES)]) for i, b in enumerate(briefs)]   # a different move per ad
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(briefs)))) as pool:
        ads = list(pool.map(lambda ib: write_ad(ib[1], profile, website_text, allocation[ib[0]], llm), enumerate(briefs)))
    seen: set = set()
    for i, ad in enumerate(ads):
        mine = _sentences(ad["primary_text"])
        dup = mine & seen
        if dup and i > 0:
            note = "\nDo not reuse any of these sentences from the other ads in the set: " + " | ".join(sorted(dup)[:4]) + "\n"
            redo = write_ad(briefs[i], profile, website_text, allocation[i], lambda p, n=note: llm(p + n))
            if len(_sentences(redo["primary_text"]) & seen) < len(dup):
                ads[i], mine = redo, _sentences(redo["primary_text"])
        seen |= mine
    return ads

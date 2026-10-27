"""
Brand Intelligence — BrandDNA: the store's marketing brain.

Every store gets a generated Voice & Style (aesthetic, tone of voice, target
demographic), an About summary (problem solved, differentiation, #1 outcome)
and three deep Buyer Profiles (who they are, daily reality, deep pain, buying
triggers, their language, objections, ad creative direction). Generated once
per store by an LLM from the store's own profile, persisted on the Store row,
and fed to every ad angle/copy/image step so campaigns speak in the buyer's
own words instead of generic marketing filler.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# The canonical shape of a store's Brand DNA. Buyer-profile fields mirror the
# proven persona format: narrative sections plus quotable language the copy
# prompts can lift verbatim.
VOICE_STYLE_FIELDS = ("aesthetic_style", "tone_of_voice", "target_demographic")
ABOUT_FIELDS = ("problem_solved", "differentiation", "number_one_outcome", "positioning")
# Kinds of audience a website can speak to. 'customer' is the ordinary buyer; the rest are other audiences.
AUDIENCE_TYPES = ("customer", "investor", "partner", "supplier", "employer", "institution", "other")
PROFILE_FIELDS = (
    "name", "character_name", "demographic_snapshot", "who_they_are", "daily_reality", "deep_pain",
    "buying_triggers", "their_language", "objections", "ad_creative_direction", "audience_type", "targeting_hint",
)

# The ten fields every buyer profile must carry (targeting_hint is an extra, used for ad targeting).
REQUIRED_PROFILE_FIELDS = (
    "name", "character_name", "demographic_snapshot", "who_they_are", "daily_reality", "deep_pain",
    "buying_triggers", "their_language", "objections", "ad_creative_direction",
)


def missing_profile_fields(p: Dict[str, Any]) -> List[str]:
    """Which of the ten required fields this profile lacks or leaves empty."""
    return [f for f in REQUIRED_PROFILE_FIELDS if p.get(f) in (None, "", [], {})]


_PROFILE_SCHEMA = {
    "name": "the kind of buyer, as an archetype title in the form 'The <qualifier> <buyer type>', 3-6 words, no personal name",
    "character_name": "the persona's first name",
    "demographic_snapshot": "one line: age, location, income or business size, household or team, the devices and "
                            "channels they use, with real figures",
    "who_they_are": "about 900-1100 characters (5-8 sentences): age, role, business, team size, history, tech comfort, "
                    "what they are trying to become, with a few concrete figures (years, budget, headcount)",
    "daily_reality": "about 1000-1300 characters (6-10 sentences) of their actual day: times, places, tools, "
                     "workarounds, what it costs them, and the moment this problem bites; mostly scene and routine, "
                     "with a few figures",
    "deep_pain": "about 1200-1500 characters (9-13 sentences) in flowing prose, the longest field: the fear behind the frustration, a specific past "
                 "incident that went wrong and what it cost them in money, standing and relationships, how it changed "
                 "how they decide now, what they are afraid of becoming, and what they lie awake about. Written as "
                 "feeling and consequence, with at most two figures",
    "buying_triggers": ["4-6 concrete events that make them buy NOW, each with a specific detail (a date, an amount, "
                        "a person, a deadline)"],
    "their_language": ["6-8 first-person quotes of 1-2 sentences in their exact words, including their slang and "
                       "grammar and at least one concrete figure or named thing in most of them"],
    "objections": ["4-6 honest, specific objections, in their words"],
    "ad_creative_direction": "5-8 sentences: visual style, format, before/after or UGC direction, 3 ready hook lines "
                             "in the buyer's voice, and the emotional arc",
    "audience_type": "one of: " + ", ".join(AUDIENCE_TYPES),
    "targeting_hint": {"interests": ["3-6 Facebook interest targets"], "behaviors": ["0-3 behavior targets"]},
}

_DNA_SCHEMA = {
    "voice_and_style": {
        "aesthetic_style": "the brand's visual aesthetic in 2-3 sentences: palette mood, imagery style, what it must never look like",
        "tone_of_voice": "3-4 sentences: how the brand speaks, jargon rules, who it talks to",
        "target_demographic": "2-3 sentences: who buys, where, age band, situation",
    },
    "about": {
        "problem_solved": "2-4 sentences: the concrete problem, grounded in the store's own description",
        "differentiation": "2-4 sentences: what makes this business different, from its own value propositions",
        "number_one_outcome": "1-2 sentences: the #1 result customers get, concrete and observable",
        "positioning": "2 sentences, decided FIRST from the text: the price level (premium, mid-market or budget), "
                       "whether it sells to consumers, businesses or both, how far its reach goes, and what it wants "
                       "to be known for",
    },
    "audiences_addressed": [{
        "audience": "a distinct group of people the website text speaks to",
        "type": "one of: " + ", ".join(AUDIENCE_TYPES),
        "evidence": "a SHORT VERBATIM quote (under 160 characters) copied from the website text that shows it speaks "
                    "to this audience",
    }],
    "focus_audience": {
        "audience": "the single most valuable audience for this brand's positioning, chosen from audiences_addressed",
        "type": "one of: " + ", ".join(AUDIENCE_TYPES),
        "why": "one sentence: why this audience is the most valuable one for this brand",
    },
    "buyer_profiles": [_PROFILE_SCHEMA] * 3,
}


def _llm_json(prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Shared LLM JSON helper: OpenRouter for vendor-prefixed models, OpenAI direct
    otherwise, with an OpenAI-direct retry when OpenRouter is out of credits (402)."""
    import re as _re
    import requests
    openai_key = os.getenv("OPENAI_API_KEY", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = bool(model and "/" in model and openrouter_key)

    def attempt(use_router: bool) -> Optional[str]:
        try:
            if openai_key.startswith("sk-") and not use_router:
                # A vendor-prefixed model name ("anthropic/...") 400s on OpenAI direct:
                # translate to the equivalent OpenAI model for the retry.
                direct_model = (model or "gpt-4o-mini").split("/")[-1]
                if direct_model.startswith("claude"):
                    direct_model = "gpt-4o-mini"
                r = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={"model": os.getenv("BRAND_DNA_FALLBACK_MODEL", direct_model),
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=120)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            elif openrouter_key:
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openrouter_key}",
                             "HTTP-Referer": "https://shopivell.com",
                             "X-Title": "Shopivell Brand DNA",
                             "Content-Type": "application/json"},
                    json={"model": model or os.getenv("OPENROUTER_BRAND_DNA_MODEL", "openai/gpt-4o-mini"),
                          "max_tokens": 6000, "messages": [{"role": "user", "content": prompt}]},
                    timeout=180)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            return None
        except Exception as e:
            logger.warning("[BrandDNA] LLM attempt (router=%s) failed: %s", use_router, e)
            return None

    content = attempt(openrouter_model)
    if content is None and openrouter_model and openai_key.startswith("sk-"):
        logger.warning("[BrandDNA] OpenRouter rejected the call (credits?); retrying via OpenAI direct")
        content = attempt(False)
    if not content:
        return {}
    content = _re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=_re.MULTILINE).strip()
    try:
        return json.loads(content)
    except Exception:
        m = _re.search(r"\{.*\}", content, _re.S)
        return json.loads(m.group(0)) if m else {}


def _llm_ready() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY")) or os.getenv("OPENAI_API_KEY", "").startswith("sk-")


def _profile_hint(profile: Dict[str, Any]) -> Dict[str, Any]:
    hint = profile.get("targeting_hint") if isinstance(profile.get("targeting_hint"), dict) else {}
    return {
        "interests": [str(i).strip()[:60] for i in (hint.get("interests") or []) if str(i).strip()][:6],
        "behaviors": [str(b).strip()[:60] for b in (hint.get("behaviors") or []) if str(b).strip()][:3],
    }


def _clean_profile(p: Any) -> Optional[Dict[str, Any]]:
    """Validate/normalize one buyer profile; keep only well-formed entries."""
    if not isinstance(p, dict) or not (p.get("who_they_are") or p.get("name")):
        return None
    clean = {k: p.get(k) for k in PROFILE_FIELDS}
    clean["name"] = str(p.get("name") or "Primary buyer")[:120]
    for f in ("who_they_are", "daily_reality", "deep_pain", "ad_creative_direction"):
        clean[f] = str(p.get(f) or "").strip()
    clean["character_name"] = str(p.get("character_name") or "").strip()[:60]
    atype = str(p.get("audience_type") or "customer").strip().lower()
    clean["audience_type"] = atype if atype in AUDIENCE_TYPES else "customer"
    clean["demographic_snapshot"] = str(p.get("demographic_snapshot") or "").strip()[:300]
    clean["buying_triggers"] = [str(t).strip()[:200] for t in (p.get("buying_triggers") or []) if str(t).strip()][:5]
    clean["their_language"] = [str(t).strip()[:200] for t in (p.get("their_language") or []) if str(t).strip()][:7]
    clean["objections"] = [str(t).strip()[:200] for t in (p.get("objections") or []) if str(t).strip()][:5]
    clean["targeting_hint"] = _profile_hint(clean)
    # A profile needs a story and a voice to be usable downstream.
    if not (clean["who_they_are"] and clean["their_language"]):
        return None
    return clean


def _fallback_dna(store) -> Dict[str, Any]:
    """Minimal Brand DNA from whatever the store already has, so downstream steps
    always have a voice and at least one profile even without an LLM."""
    name = getattr(store, "store_name", None) or "This business"
    kind = getattr(store, "business_type", None) or "business"
    desc = getattr(store, "store_description", None) or ""
    country = getattr(store, "store_country", None) or ""
    products = [str(p) for p in (getattr(store, "products_or_services", None) or [])][:6]
    voice = getattr(store, "store_voice", None) or f"Clear, friendly and honest. {name} speaks to {kind} customers in {country or 'its market'} in plain language."
    return {
        "voice_and_style": {
            "aesthetic_style": "Clean and modern: real product photography, natural light, the brand's own colours on props and backgrounds. Never cluttered, never stock-photo staged.",
            "tone_of_voice": voice[:600],
            "target_demographic": f"{kind} customers{' in ' + country if country else ''} who want a reliable, professional result without fuss.",
        },
        "about": {
            "problem_solved": desc[:600] or f"{name} solves the everyday problems {kind} customers face with {', '.join(products) or 'its products'}.",
            "differentiation": f"{name} delivers a dependable, professional result with local knowledge of {country or 'its market'}.",
            "number_one_outcome": f"Customers get a {kind} result they can rely on, without the usual runaround.",
        },
        "buyer_profiles": [{
            "name": f"{kind.title()} customer",
            "character_name": "Customer",
            "demographic_snapshot": f"Adults{' in ' + country if country else ''} who buy {kind} products or services.",
            "who_they_are": f"A {kind} customer{' in ' + country if country else ''} who values quality and reliability.",
            "daily_reality": f"They juggle a busy schedule and need {', '.join(products[:3]) or 'a trusted provider'} without drama.",
            "deep_pain": f"Burned before by poor service or products that didn't last, they don't want to waste money again.",
            "buying_triggers": ["A bad experience with a previous provider", "An upcoming event or deadline", "A recommendation from someone they trust"],
            "their_language": ["I just want it done properly", "I don't have time for back-and-forth", "Is this the real thing?"],
            "objections": ["Price concerns", "Not sure it will work for my situation", "Worried about follow-up support"],
            "ad_creative_direction": f"Real, relatable people from {country or 'the local market'}; before/after or moment-of-relief scenes; clean modern layout",
            "targeting_hint": {"interests": products[:3] or [kind], "behaviors": []},
        }],
    }


def _site_text_for(store) -> str:
    """Clean text of the store's own website (homepage plus its best pages), or '' when there is no site or it
    cannot be read. Never raises."""
    domain = str(getattr(store, "domain", "") or "").strip()
    if not domain:
        return ""
    try:
        import requests
        from modules.ad_angles.service import gather_site_text
        url = domain if domain.startswith("http") else f"https://{domain}"
        html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}).text
        return gather_site_text(html, url)
    except Exception as e:
        logger.info("[BrandDNA] website text unavailable for %s: %s", domain, e)
        return ""


def generate_brand_dna(store, website_text: str = "") -> Dict[str, Any]:
    """Generate the full Brand DNA for a store. `store` is a Store model instance.
    `website_text` is the cleaned text of the store's site; when empty it is fetched from the store's domain.
    Returns the DNA dict; on any failure returns a minimal fallback built from
    the store's own fields (never raises).

    Metering happens at the API layer (stores router), which owns the DB session."""
    try:
        name = store.store_name
        kind = store.business_type or ""
        desc = store.store_description or ""
        voice = store.store_voice or ""
        country = store.store_country or ""
        city = store.store_city or ""
        products = [str(p) for p in (store.products_or_services or [])][:10]
        goals = [str(g) for g in (store.business_goals or [])][:5]
        payments = store.payment_methods if isinstance(store.payment_methods, dict) else {}
        pay_names = [str(k) for k in payments.keys()][:6] if payments else []
        if not _llm_ready():
            return _fallback_dna(store)

        location = ", ".join(x for x in (city, country) if x)
        site = (website_text or "").strip() or _site_text_for(store)
        prompt = (
            "You are a senior brand strategist and direct-response creative director. "
            "Build this business's marketing brain: its Voice & Style, a crisp About "
            "summary, and THREE deep buyer profiles.\n\n"
            f"BUSINESS: {name} — {kind or 'type unknown'}\n"
            f"Location: {location or 'not specified'}\n"
            f"What the owner says it does: {desc[:1200] or 'not provided'}\n"
            f"Brand voice so far: {voice[:400] or 'not provided'}\n"
            f"Products/services: {', '.join(products) or 'not listed'}\n"
            f"Business goals: {', '.join(goals) or 'not stated'}\n"
            f"Payment methods offered: {', '.join(pay_names) or 'unknown'}\n\n"
            + (f"WEBSITE TEXT (the business's own words and facts; ground the profiles in it):\n{site[:9000]}\n\n"
               if site else "")
            + f"Return ONLY JSON shaped like:\n{json.dumps(_DNA_SCHEMA)}\n\n"
            "Rules:\n"
            "- The three buyer profiles must be genuinely DIFFERENT people (different "
            "situations, team sizes, ambitions, budgets) who all buy from this business "
            "for different reasons. Give each a first name.\n"
            "- Make each profile specific to THIS business's actual products: reference the "
            "real product categories, real locations, real terms and real constraints that appear in the "
            "information above, and the concrete situations in which someone needs exactly this. A generic "
            "'small business owner' or 'busy parent' profile is a failure.\n"
            "- their_language: write 5-7 quotes the way THIS buyer actually talks — their "
            "slang, their grammar, their complaints, including concrete details (product "
            "models, budgets, deadlines, payment terms). These lines will be lifted verbatim "
            "into ad copy, so they must sound spoken, never written.\n"
            "- deep_pain: 4-8 sentences; go past the surface frustration to the fear and "
            "identity stuff (imposter syndrome, reputation, scale anxiety, audit fear). This "
            "is where the ad angles come from.\n"
            "- buying_triggers and objections: concrete events and honest, specific worries "
            "(cash flow, warranty honouring, documentation), not generic hesitations.\n"
            "- ad_creative_direction per profile: visual style, format (UGC/mockup/split "
            "screen), 2-3 ready hook lines written in the buyer's voice, and the emotional "
            "arc. Grounded in what this business actually sells and where it operates.\n"
            "- Facts about the BUSINESS (prices, guarantees, offers, locations, years, scale) must come only from "
            "the information above. The buyer's own life is invented to feel real: names, budgets, events, "
            "deadlines, quotes and numbers from their world. If payment methods suggest a market, factor that "
            "into the demographic.\n"
            "- Put concrete figures in demographic_snapshot, buying_triggers and their_language (ages, budgets, "
            "headcounts, years, amounts, dates, quantities). who_they_are and daily_reality carry a few; deep_pain "
            "stays narrative, with at most two figures.\n"
            "- Work in this order. (1) Decide the brand's positioning (about.positioning) from its prices, tone, "
            "products and who the text speaks to. (2) Fill audiences_addressed: every distinct audience the website "
            "text speaks to, each with its type and a SHORT VERBATIM quote copied from the website text as evidence; "
            "only list an audience if you can quote the text that addresses it. (3) Choose the ONE focus_audience "
            "from that list that is most valuable for this positioning: the people with both the need and the means, "
            "who would buy the most, the most often, or at the highest value (a premium brand calls for a premium "
            "audience, a budget brand for a price-conscious one, a business-to-business brand for the decision "
            "makers). (4) Write the three buyer profiles as three SHARP SUB-TYPES OF THAT ONE FOCUS AUDIENCE, "
            "distinguished by life situation, motivation, urgency and what each fears or wants most. They are three "
            "genuinely different people inside the same audience, not three versions of one person and not three "
            "unrelated audiences. Each profile title must name its sub-type, and every profile's audience_type is "
            "the focus audience's type. Say in who_they_are why this person cares about this business.\n"
            "- demographic_snapshot is one concrete line (age band, location, income or business size, household "
            "or team, devices and channels). character_name is the persona's first name.\n"
            "- tone_of_voice: 3-4 sentences that a copywriter could follow as a style rule.\n"
            "- target_demographic: include the market (country/city if known), an age band, "
            "and the kinds of businesses/people who buy.\n"
        )
        model = os.getenv("BRAND_DNA_MODEL", "anthropic/claude-sonnet-4.6")
        data: Dict[str, Any] = {}
        for _attempt in range(3):   # an empty or malformed reply is usually transient; retry before falling back
            data = _llm_json(prompt, model=model)
            usable = [_clean_profile(p) for p in ((data or {}).get("buyer_profiles") or [])] if isinstance(data, dict) else []
            if any(usable):
                break

        vs =data.get("voice_and_style") if isinstance(data.get("voice_and_style"), dict) else {}
        about = data.get("about") if isinstance(data.get("about"), dict) else {}
        profiles = [_clean_profile(p) for p in (data.get("buyer_profiles") or [])]
        profiles = [p for p in profiles if p][:3]

        # Enforce completeness: ask the model to fill in only the fields a profile is missing.
        for p in profiles:
            gaps = missing_profile_fields(p)
            if not gaps:
                continue
            fix = _llm_json(
                "Complete this buyer profile for the business below. Return ONLY JSON containing exactly these "
                f"missing fields: {json.dumps({f: _PROFILE_SCHEMA[f] for f in gaps})}\n\n"
                f"BUSINESS: {name}: {kind}\nPROFILE SO FAR:\n{json.dumps({k: v for k, v in p.items() if v})[:2500]}",
                model=model)
            if isinstance(fix, dict):
                filled = _clean_profile({**p, **{f: fix.get(f) for f in gaps if fix.get(f)}})
                if filled:
                    p.update({f: filled[f] for f in gaps})
            if not p.get("character_name"):   # last resort: the first capitalised word of the story
                m = re.search(r"\b[A-Z][a-z]{2,}\b", p.get("who_they_are") or "")
                p["character_name"] = m.group(0) if m else ""
            if missing_profile_fields(p):
                logger.warning("[BrandDNA] profile %r still missing %s", p.get("name"), missing_profile_fields(p))

        # Audience coverage: an audience counts only if its evidence quote really appears in the site text. If the
        # site verifiably addresses a non-customer audience that no profile covers, replace the last profile with one.
        def _norm(t: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (t or "").lower())).strip()

        site_norm = _norm(site)
        addressed = []
        for a in (data.get("audiences_addressed") or []) if isinstance(data, dict) else []:
            if not isinstance(a, dict):
                continue
            ev = _norm(str(a.get("evidence") or ""))
            atype = str(a.get("type") or "").strip().lower()
            addressed.append({"audience": str(a.get("audience") or "")[:160], "type": atype,
                              "evidence": str(a.get("evidence") or "")[:200],
                              "verified": bool(ev) and len(ev) >= 12 and ev in site_norm})
        # The focus audience: the one audience the three profiles are sub-types of. It counts as site-backed only when
        # it matches an audience whose evidence quote really appears in the site text.
        focus_raw = data.get("focus_audience") if isinstance(data, dict) and isinstance(data.get("focus_audience"), dict) else {}
        ftype = str(focus_raw.get("type") or "").strip().lower()
        ftype = ftype if ftype in AUDIENCE_TYPES else "customer"
        focus = {"audience": str(focus_raw.get("audience") or "")[:160], "type": ftype,
                 "why": str(focus_raw.get("why") or "")[:300],
                 "site_backed": any(x["verified"] and x["type"] == ftype for x in addressed)}
        for p in profiles:
            p["audience_type"] = ftype

        # The About summary is sometimes omitted by the model: ask for just the fields that are missing.
        about_gaps = [k for k in ABOUT_FIELDS if not str(about.get(k) or "").strip()]
        if about_gaps and profiles:
            fix = _llm_json(
                "Complete the About summary for the business below. Return ONLY JSON containing exactly these fields: "
                f"{json.dumps({k: _DNA_SCHEMA['about'][k] for k in about_gaps})}\n\n"
                f"BUSINESS: {name}: {kind}\nWHAT THE OWNER SAYS: {desc[:600]}\n"
                f"WEBSITE TEXT:\n{site[:4000]}", model=model)
            if isinstance(fix, dict):
                about = {**about, **{k: fix.get(k) for k in about_gaps if fix.get(k)}}

        if not profiles:
            logger.warning("[BrandDNA] no usable buyer profiles returned for %s; using fallback", name)
            return _fallback_dna(store)

        dna = {
            "voice_and_style": {
                "aesthetic_style": str(vs.get("aesthetic_style") or _fallback_dna(store)["voice_and_style"]["aesthetic_style"])[:900],
                "tone_of_voice": str(vs.get("tone_of_voice") or voice or "")[:900],
                "target_demographic": str(vs.get("target_demographic") or "")[:600],
            },
            "about": {
                "problem_solved": str(about.get("problem_solved") or desc[:600])[:900],
                "differentiation": str(about.get("differentiation") or "")[:900],
                "number_one_outcome": str(about.get("number_one_outcome") or "")[:600],
                "positioning": str(about.get("positioning") or "")[:600],
            },
            "audiences_addressed": addressed,
            "focus_audience": focus,
            "buyer_profiles": profiles,
        }
        logger.info("[BrandDNA] generated DNA with %d profiles for %s", len(profiles), name)
        return dna
    except Exception as e:
        logger.warning("[BrandDNA] generation failed for %s: %s", getattr(store, "store_name", "?"), e)
        return _fallback_dna(store)

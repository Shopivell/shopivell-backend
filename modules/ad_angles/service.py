"""
Ad angles — the bridge between market research and ad creation.

Turns a business profile plus its market research (competitors, keywords, trends)
into a few distinct advertising angles. Each angle starts from a real situation a
customer faces — their pain, the outcome they want, and the proof from the website
that this business resolves it — rather than restating a website feature. The
campaign builder generates one ad set per angle.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ANGLE_FIELDS = ("angle_name", "customer_pain", "desired_outcome", "hook", "value_proposition", "proof",
                "website_basis", "competitor_gap", "target_audience", "emotion", "keywords", "visual_direction",
                "leads_the_creative", "copy_variations")

_VARIATION_SCHEMA = {
    "approach": "which of the listed variation approaches this variation takes, e.g. 'loss aversion'",
    "primary_text": "70-150 words, short paragraphs separated by blank lines, first line under 125 chars",
    "headline": "<=40 chars, a complete phrase that stops the scroll",
    "description": "<=30 chars, teaser that ADDS to the headline instead of repeating it",
    "call_to_action": "one of: Learn More, Sign Up, Shop Now, Get Quote, Contact Us, Book Now, Get Offer",
    # Per-variation delivery: how THIS framing should be aimed and rendered. The campaign
    # builder turns these into distinct ad sets / creatives, so variations differ in more
    # than words — matching how real accounts test.
    "targeting_hint": {"interests": ["3-6 Facebook interest targets that match THIS approach's reader"],
                       "behaviors": ["0-3 Facebook behavior targets, e.g. 'Small business owners', 'Engaged shoppers'"]},
    "placement": "one of: automatic, facebook_feed, instagram_feed, instagram_stories, reels",
    "format": "one of: single_image, carousel, video",
    "optimization": "one of: conversions, leads, traffic, messages, awareness",
    "demographics": {"age_min": 18, "age_max": 65, "gender": "all — or 'male'/'female' only when the angle truly calls for it"},
    "image_direction": "one concrete scene for THIS variation's creative: subject, action, moment, in the customer's world",
    "benefit_chips": ["2-4 short proof stats for the image's benefit pills, verbatim from the website: "
                      "'500+ products', '10+ years', '2000+ clients', 'Same-day delivery in Harare', "
                      "'EcoCash & bank transfer', 'Full manufacturer warranty'"],
}

# Each angle gets 3 copy variations with DIFFERENT psychological approaches, so a campaign
# tests how the same offer is framed rather than three paraphrases of one idea.
_COPY_APPROACHES = (
    ("loss aversion", "what the reader is already losing or risking by doing nothing — the cost of the status quo"),
    ("aspiration", "the moment after it works: what their business or day looks like once the problem is solved"),
    ("us-vs-them", "the old way vs the new way: what everyone else accepts vs what this business does differently"),
)

# Fields every copy variation must carry, and the enum sets Meta (or our publisher) accepts.
_VARIATION_FIELDS = ("approach", "primary_text", "headline", "description", "call_to_action",
                     "targeting_hint", "placement", "format", "optimization", "demographics", "image_direction",
                     "benefit_chips")
_VARIATION_CTAS = ("Learn More", "Sign Up", "Shop Now", "Get Quote", "Contact Us", "Book Now", "Get Offer")
_VARIATION_PLACEMENTS = ("automatic", "facebook_feed", "instagram_feed", "instagram_stories", "reels")
_VARIATION_FORMATS = ("single_image", "carousel", "video")
_VARIATION_OPTIMIZATIONS = ("conversions", "leads", "traffic", "messages", "awareness")

_SCHEMA = {"angles": [{
    "angle_name": "short name for the customer situation",
    "customer_pain": "the situation or worry, in the customer's own words",
    "desired_outcome": "what they want to feel or achieve",
    "hook": "<=40 char headline speaking to the pain or outcome, never a feature name",
    "value_proposition": "how this business resolves it",
    "proof": "a concrete fact from the website excerpt that makes it believable",
    "website_basis": "the website value proposition or product this rests on",
    "competitor_gap": "names competitors from the list and the evidence, e.g. X is rated 3.9 stars",
    "target_audience": "specific persona in a situation, e.g. students buying a first laptop",
    "emotion": "the feeling the buyer wants: relief, confidence, pride, peace of mind",
    "keywords": ["3-6 of the customer searches above"],
    "visual_direction": "a real moment from the customer's situation for the ad image",
    "leads_the_creative": "set true on EXACTLY ONE angle - the one whose pain is sharpest and proof hardest; it leads the creative",
    # Meta ad-unit copy variations (one per psychological approach). These are what get
    # published; the other fields above remain the strategy the variations must stay true to.
    "copy_variations": [_VARIATION_SCHEMA] * 3,
}]}


def _fit(text: Any, limit: int) -> str:
    """Trim to `limit` characters at a word boundary so a headline or description is never cut mid-word."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut.rsplit(" ", 1)[0] if " " in cut and text[limit] != " " else cut).rstrip(" ,;:-")


def _fallback_variations(angle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Three publishable copy variations built from the angle's own fields, used when the
    model returns no (or malformed) copy_variations so every downstream consumer — saving,
    the ad_set stream event, publishing — can assume they exist."""
    hook = str(angle.get("hook") or angle.get("angle_name") or "")[:40]
    outcome = str(angle.get("desired_outcome") or "")
    vp = str(angle.get("value_proposition") or "")
    proof = str(angle.get("proof") or angle.get("website_basis") or "")
    audience = str(angle.get("target_audience") or "")
    kws = [str(k) for k in (angle.get("keywords") or [])][:6]
    bodies = (
        ("loss aversion", f"Still struggling with {audience.lower() or 'this'}?", "facebook_feed"),
        ("aspiration", outcome or vp, "instagram_feed"),
        ("us-vs-them", vp, "facebook_feed"),
    )
    return [
        {"approach": approach,
         "primary_text": "\n".join(p for p in (opening, outcome or vp, proof) if p),
         "headline": hook, "description": outcome[:30], "call_to_action": "Learn More",
         "targeting_hint": {"interests": kws, "behaviors": []},
         "placement": placement, "format": "single_image", "optimization": "conversions",
         "demographics": {"age_min": 18, "age_max": 65, "gender": "all"},
         "image_direction": str(angle.get("visual_direction") or "")[:400],
         "benefit_chips": [str(angle.get("proof") or "")[:40]] if angle.get("proof") else []}
        for approach, opening, placement in bodies
    ]


def detect_conversion_signals(website_html: str) -> Dict[str, Any]:
    """Deterministic scan of the site's own markup for the conversion capabilities that
    decide which Meta campaign objective is actually runnable. No LLM: these are literal
    fingerprints (pixel bootstrap scripts, checkout/platform strings, form tags, chat links)."""
    html = (website_html or "").lower()
    if not html:
        return {"pixel": False, "checkout": False, "lead_form": False, "whatsapp": False,
                "messenger": False, "tag_manager": False}
    return {
        "pixel": any(s in html for s in ("fbq(", "fbevents.js", "connect.facebook.net")),
        "checkout": any(s in html for s in ("checkout", "add-to-cart", "add_to_cart", "shopify",
                                            "woocommerce", "paynow", "paytoday", "stripe", "paypal")),
        "lead_form": "<form" in html,
        "whatsapp": any(s in html for s in ("wa.me/", "api.whatsapp.com", "whatsapp://", "chat.whatsapp.com")),
        "messenger": any(s in html for s in ("m.me/", "messenger.com")),
        "tag_manager": any(s in html for s in ("googletagmanager.com", "gtag(", "datalayer")),
    }


def recommend_campaign_objective(profile: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    """Media-buyer logic for the Meta campaign objective, decided by what the site can
    actually do: Sales needs a pixel firing purchase events on the site (best ROI);
    Leads runs as a Meta instant form with no pixel needed; chat flows map to Engagement
    click-to-message (the closest thing to a WhatsApp flow - click-to-WhatsApp is not
    available on our side yet); Traffic builds a retargeting pool; Awareness is the
    weakest choice for a business that can actually transact.
    Returns {recommended_objective, fallback_objective, rationale, signals}."""
    business = str(profile.get("company_name") or "This business")
    chat = signals.get("whatsapp") or signals.get("messenger")
    chat_kind = "WhatsApp" if signals.get("whatsapp") else "Messenger"
    if signals.get("pixel") and signals.get("checkout"):
        return {
            "recommended_objective": "sales",
            "fallback_objective": "leads" if signals.get("lead_form") else "traffic",
            "rationale": (f"{business} can transact online and a Meta pixel was found on the site, so Sales optimizes "
                          "for actual online orders - the best ROI when purchase events can fire."),
            "signals": signals,
        }
    if signals.get("checkout") or signals.get("lead_form"):
        what = "checkout" if signals.get("checkout") else "forms"
        extra = " Google tags are present, so adding purchase tracking later unlocks Sales." if signals.get("tag_manager") else ""
        if signals.get("pixel"):
            rationale = (f"{business} captures intent on-site ({what}) and a Meta pixel is present, so Leads optimizes "
                         "toward form submissions; Sales needs purchase events firing on a checkout, which this site "
                         "doesn't run." + extra)
        else:
            rationale = (f"{business} captures intent on-site ({what}) but no Meta pixel was found, so Leads runs as "
                         "a Meta instant form with no pixel needed." + extra)
        return {
            "recommended_objective": "leads",
            "fallback_objective": "traffic",
            "rationale": rationale,
            "signals": signals,
        }
    if chat:
        return {
            "recommended_objective": "engagement",
            "fallback_objective": "leads" if signals.get("lead_form") else "traffic",
            "rationale": (f"{business} invites buyers into a {chat_kind} chat but shows no measurable on-site conversion, "
                          f"so Engagement click-to-message meets them in chat - the closest thing to its {chat_kind} flow "
                          "(click-to-WhatsApp is not available on our side yet)."),
            "signals": signals,
        }
    return {
        "recommended_objective": "traffic",
        "fallback_objective": "awareness",
        "rationale": (f"{business}'s site shows no pixel, checkout, forms or chat to optimize toward, so Traffic is the "
                      "cheapest way to get people onto the site and start building a retargeting pool."),
        "signals": signals,
    }


# ---------- website text for the prompt (NEXT_STEPS.md section 4: clean text, bigger excerpt) ----------
# The prompt used to read the first 3,500 characters of whatever it was handed, and the agent handed it
# raw page HTML, so the model could be reading scripts and markup instead of the business. These helpers
# turn pages into clean text and build a bigger, better-chosen excerpt. Conversion-signal detection still
# reads the raw markup (pixel, checkout and form fingerprints only exist there).
EXCERPT_CAP = 12000       # total characters of website text sent to the prompt
_HOME_CAP = 4000          # share of the cap given to the homepage
_PAGE_CAP = 2000          # share for each extra page (about, services...)
_WANT_PAGES = re.compile(r"about|service|product|solution|why-|who-we|what-we|faq|pricing|plans|offer", re.I)
_SKIP_PAGES = re.compile(r"testimonial|blog|news|privacy|terms|cookie|login|cart|checkout|account|wp-|cdn-cgi|"
                         r"email-protection|contact|"
                         r"\.(jpg|jpeg|png|gif|pdf|zip)$", re.I)


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<(html|body|div|p|a|script|head)\b", (text or "")[:5000], re.I))


def clean_page_text(html: str) -> str:
    """Readable text from a page: scripts, styles and markup removed, repeated lines dropped."""
    if not html:
        return ""
    if not _looks_like_html(html):
        return re.sub(r"[ \t]+", " ", html).strip()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    seen, lines = set(), []
    for line in soup.get_text("\n", strip=True).split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 2 or line.lower() in seen:
            continue
        seen.add(line.lower())
        lines.append(line)
    return "\n".join(lines)


_MIN_SITE_CHARS = 5000   # below this a plain fetch has probably missed content that is built by JavaScript


def _clean_markdown(md: str) -> str:
    """Plain lines from a reader service's markdown: images, link syntax and markup removed, repeats dropped."""
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md or "")
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"^(Title|URL Source|Published Time|Markdown Content|Warning):.*$", "", md, flags=re.M)
    seen, lines = set(), []
    for line in re.sub(r"[#*_`>|]+", " ", md).split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 3 or line.lower() in seen:
            continue
        seen.add(line.lower())
        lines.append(line)
    return "\n".join(lines)


def _render_playwright(url: str, timeout: int = 45):
    """Page text and links after JavaScript has run, in a headless browser (needs the browser installed)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            text = page.inner_text("body")
            links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        finally:
            browser.close()
    return clean_page_text(text), links


def _render_jina(url: str, timeout: int = 45):
    """Rendered page as text through the public Jina reader (no browser needed; sends the public URL to it)."""
    import requests
    md = requests.get("https://r.jina.ai/" + url, headers={"Accept": "text/plain"}, timeout=timeout).text
    return _clean_markdown(md), re.findall(r"\]\((https?://[^)\s]+)\)", md)


def render_site(url: str, timeout: int = 45):
    """Text and links of a page whose content is built by JavaScript (client-side React/Vue/Next apps send a plain
    fetch an empty shell). Tries each renderer in SITE_RENDERERS (default 'playwright,jina') until one returns text.
    Set SITE_RENDERERS=playwright to keep every request on our own infrastructure."""
    for name in [n.strip() for n in os.getenv("SITE_RENDERERS", "playwright,jina").split(",") if n.strip()]:
        try:
            text, links = (_render_playwright if name == "playwright" else _render_jina)(url, timeout)
        except Exception as e:
            logger.info("[AdAngles] renderer %s failed for %s: %s", name, url, e)
            continue
        if len(text) > 300:
            return text, links
    return "", []


def _page_fact_score(text: str) -> int:
    """How much usable proof a page snippet holds: prices, percentages, figures and real offers."""
    figures = len(re.findall(r"[$€£]\s?\d|\d+\s?%|\b\d{2,}\b", text))
    offers = len(re.findall(r"tour|consultation|whatsapp|payment plan|deposit|instal|delivery|free |quote|book a|"
                            r"call us|enquire|warranty|guarantee", text, re.I))
    return figures + 3 * offers


def gather_site_text(homepage_html: str, base_url: str, max_extra_pages: int = 4, timeout: int = 12,
                     max_candidates: int = 20) -> str:
    """Clean text for the prompt: the homepage plus the pages that hold the most proof (prices,
    figures, offers), chosen from up to `max_candidates` internal pages that are fetched in parallel.
    Testimonial, blog and legal pages are skipped. Never raises; falls back to the homepage."""
    home = clean_page_text(homepage_html)
    parts = [home[:_HOME_CAP]]
    try:
        from concurrent.futures import ThreadPoolExecutor
        from urllib.parse import urljoin, urlparse
        import requests
        from bs4 import BeautifulSoup
        base = base_url if str(base_url).startswith("http") else f"https://{base_url}"
        host = urlparse(base).netloc.replace("www.", "")
        wanted, other = [], []
        for a in BeautifulSoup(homepage_html or "", "html.parser").find_all("a", href=True):
            u = urljoin(base, a["href"]).split("#")[0].split("?")[0]
            if urlparse(u).netloc.replace("www.", "") != host or u.rstrip("/") == base.rstrip("/"):
                continue
            if _SKIP_PAGES.search(u) or u in wanted or u in other:
                continue
            (wanted if _WANT_PAGES.search(urlparse(u).path) else other).append(u)
        candidates = (wanted + other)[:max_candidates]
        seen_lines = set(home.lower().split("\n"))
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128"}

        def fetch(u):
            try:
                text = "\n".join(l for l in clean_page_text(requests.get(u, timeout=timeout, headers=ua).text)
                                 .split("\n") if l.lower() not in seen_lines)
                return u, text[:_PAGE_CAP]
            except Exception as e:
                logger.info("[AdAngles] extra page %s skipped: %s", u, e)
                return u, ""

        with ThreadPoolExecutor(max_workers=5) as pool:
            fetched = [r for r in pool.map(fetch, candidates) if len(r[1]) > 200]
        fetched.sort(key=lambda r: _page_fact_score(r[1]), reverse=True)
        for u, text in fetched[:max_extra_pages]:
            parts.append(f"[{urlparse(u).path.strip('/') or 'page'}]\n{text}")
    except Exception as e:
        logger.info("[AdAngles] extra pages skipped: %s", e)
    text = "\n\n".join(p for p in parts if p)[:EXCERPT_CAP]
    if len(text) >= _MIN_SITE_CHARS:
        return text
    # Too little readable text: the site is probably built by JavaScript. Render it and its best pages.
    try:
        from concurrent.futures import ThreadPoolExecutor
        from urllib.parse import urlparse
        base = base_url if str(base_url).startswith("http") else f"https://{base_url}"
        host = urlparse(base).netloc.replace("www.", "")
        rendered, links = render_site(base)
        if len(rendered) <= len(text):
            return text
        wanted, other = [], []
        for u in links:
            u = u.split("#")[0].split("?")[0]
            if urlparse(u).netloc.replace("www.", "") != host or u.rstrip("/") == base.rstrip("/"):
                continue
            if _SKIP_PAGES.search(u) or u in wanted or u in other:
                continue
            (wanted if _WANT_PAGES.search(urlparse(u).path) else other).append(u)
        extra = (wanted + other)[:max_extra_pages]
        seen_lines = set(rendered.lower().split("\n"))
        with ThreadPoolExecutor(max_workers=3) as pool:
            pages = list(pool.map(lambda u: (u, render_site(u)[0]), extra))
        parts = [rendered[:_HOME_CAP]]
        for u, t in pages:
            t = "\n".join(l for l in t.split("\n") if l.lower() not in seen_lines)[:_PAGE_CAP]
            if len(t) > 200:
                parts.append(f"[{urlparse(u).path.strip('/') or 'page'}]\n{t}")
        logger.info("[AdAngles] rendered %s: %d chars (plain fetch gave %d)", base, sum(len(p) for p in parts), len(text))
        return "\n\n".join(parts)[:EXCERPT_CAP]
    except Exception as e:
        logger.info("[AdAngles] render fallback failed: %s", e)
        return text


def _prompt_excerpt(text: str) -> str:
    """Whatever we were given, as clean text within the cap."""
    return (clean_page_text(text) if _looks_like_html(text) else (text or ""))[:EXCERPT_CAP]


def generate_ad_angles(profile: Dict[str, Any], competitors: List[Dict[str, Any]],
                       keywords: List[Dict[str, Any]], trends: List[Dict[str, Any]],
                       count: int = 3, website_excerpt: str = "", clean_text: str = "") -> List[Dict[str, Any]]:
    """Distinct customer-first ad angles grounded in the research and website. Returns []
    when there is no LLM or no usable profile, so callers fall back to one ad set."""
    from modules.market_research.service import MarketResearchService

    svc = MarketResearchService()
    if not svc._llm_ready() or not (profile.get("business_type") or profile.get("company_name")):
        return []

    def as_list(value):
        return ", ".join(str(v.get("name") if isinstance(v, dict) else v) for v in (value or []) if v)

    # The store's Brand DNA (Voice & Style + About + Buyer Profiles) is the voice of
    # truth for HOW to speak; the website excerpt remains the only source of facts.
    dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else None
    dna_block = ""
    if dna:
        vs = dna.get("voice_and_style") or {}
        about = dna.get("about") or {}
        profiles = [p for p in (dna.get("buyer_profiles") or []) if isinstance(p, dict)]
        dna_block = (
            "\nBRAND VOICE & STYLE (the copy must sound like this):\n"
            f"Aesthetic: {vs.get('aesthetic_style', '')}\n"
            f"Tone of voice: {vs.get('tone_of_voice', '')}\n"
            f"Target demographic: {vs.get('target_demographic', '')}\n\n"
            "ABOUT (use for framing, never invent beyond it):\n"
            f"Problem solved: {about.get('problem_solved', '')}\n"
            f"Differentiation: {about.get('differentiation', '')}\n"
            f"#1 outcome: {about.get('number_one_outcome', '')}\n"
        )
        if profiles:
            profile_lines = "\n".join(
                f"- {p.get('name')}: {str(p.get('who_they_are', ''))[:220]}\n"
                f"  Deep pain: {str(p.get('deep_pain', ''))[:220]}\n"
                f"  Their words: {' | '.join(str(q) for q in (p.get('their_language') or [])[:4])}\n"
                f"  Objections: {' | '.join(str(o) for o in (p.get('objections') or [])[:3])}\n"
                f"  Targeting: {', '.join((p.get('targeting_hint') or {}).get('interests') or [])}"
                for p in profiles)
            dna_block += f"\nBUYER PROFILES (each angle should speak AS one of these people):\n{profile_lines}\n"

    location = profile.get("location") or profile.get("geographic_coverage") or ""
    excerpt = _prompt_excerpt(clean_text or website_excerpt)

    # What can this site actually convert on Meta? Detected from its own markup and turned
    # into media-buyer objective advice: the prompt recommends inside that reality, and the
    # same recommendation is stamped on every returned angle for the campaign builder.
    signals = detect_conversion_signals(website_excerpt or "")
    advice = recommend_campaign_objective(profile, signals)
    objective_block = (
        "\nCAMPAIGN OBJECTIVE REALITY (Meta can only optimize toward what this site can actually do):\n"
        f"Recommended objective: {advice['recommended_objective'].upper()} - {advice['rationale']}\n"
        f"Fallback if the recommendation is unavailable: {advice['fallback_objective']}.\n"
        f"Site signals: Meta pixel {'present' if signals['pixel'] else 'NOT found'}; "
        f"on-site checkout {'present' if signals['checkout'] else 'not found'}; "
        f"lead form {'present' if signals['lead_form'] else 'not found'}; "
        f"WhatsApp link {'present' if signals['whatsapp'] else 'not found'}; "
        f"Messenger {'present' if signals['messenger'] else 'not found'}.\n"
        "Make every variation's optimization coherent with these capabilities: never optimize conversions "
        "when no pixel was found; prefer leads (instant form, no pixel needed) or messages (chat flow); "
        "traffic builds a retargeting pool; awareness is the weakest choice for a business that can transact.\n"
        "Flag exactly ONE angle with leads_the_creative=true: the one whose pain is sharpest and proof "
        "hardest; it leads the creative.\n"
    )
    comp_lines = "\n".join(
        f"- {c.get('name', '')}"
        + (f" ({c['rating']}★, {c.get('reviews') or 0} reviews)" if c.get("rating") else "")
        + (f": {(c.get('description') or '')[:100]}" if c.get("description") else "")
        for c in competitors[:12]) or "- none found"
    trend_lines = "\n".join(f"- {t.get('title', '')}" for t in trends[:6]) or "- none found"

    data = svc._llm_json(
        f"You are a direct-response copywriter who deeply understands customers in {location or 'this market'}. "
        "Plan Facebook/Instagram ad angles.\n\n"
        f"BUSINESS: {profile.get('company_name') or 'unknown'} — {profile.get('business_type') or ''}\n"
        f"Location: {location}\n"
        f"Products/services: {as_list(profile.get('products') or profile.get('services_products'))}\n"
        f"Value propositions: {as_list(profile.get('value_propositions'))}\n"
        f"Audiences: {as_list(profile.get('target_audiences'))}\n\n"
        f"WEBSITE EXCERPT (the only source of facts and proof):\n{excerpt or 'not available'}\n\n"
        f"COMPETITORS:\n{comp_lines}\n\n"
        f"CUSTOMER SEARCHES: {', '.join(k.get('keyword', '') for k in keywords[:25]) or 'none found'}\n\n"
        f"MARKET TRENDS:\n{trend_lines}\n\n"
        + dna_block
        + objective_block
        + "\n"
        f"Return ONLY JSON shaped like:\n{json.dumps(_SCHEMA)}\n\n"
        f"Create exactly {count} angles. Each angle carries exactly 3 copy_variations that sell the SAME angle "
        "three different ways, in this order:\n"
        + "\n".join(f"{i + 1}. {name}: {desc}" for i, (name, desc) in enumerate(_COPY_APPROACHES))
        + "\n\n"
        "WHAT MAKES AN AD WORK\n"
        "1. The angles must be truly different from each other. List the different doors into this business: each "
        "product or service line, each type of customer, each moment when someone needs it. Pick the "
        f"{count} that are furthest apart, so no two angles sell the same product to the same person with the same "
        "feeling. Buyer profiles tell you how these people think and talk. Use them for voice and emotion, "
        "never as the only source of angles, and never paste their quotes in as hooks. If the business's "
        "headline selling point is one idea (one supplier, low price, speed, quality), that idea may drive at "
        "most one angle; the others must come from other products, customers or moments.\n"
        "2. Stop the scroll. Think like a creative director, not a template filler: find the one surprising, "
        "true-feeling observation about this customer's world that makes them stop and think 'that is me', and "
        "open on it as a vivid scene, a startling number or a bold challenge. Invent your own hooks from this "
        "business and its customers. Never open with the business name, a feature, or a generic question.\n"
        "3. Persuade. One idea per ad. Make a clear claim, raise the stakes of doing nothing, show the way out, "
        "then tell the reader exactly what to do. Be confident and state things as fact: no hedging, no "
        "'may', 'can help' or 'we strive'.\n"
        "4. Be bold, specific and creative. Anchor every ad in what this business really does, then go further: "
        "invent the vivid, believable specifics a great copywriter would use (numbers, times, places, named "
        "scenes, small details, the cost of waiting) so the ad feels real and concrete. Specific beats polished, "
        "and a confident claim beats a cautious one.\n"
        "5. Sound like a person. Mix short punchy lines with longer ones. 70 to 150 words, short paragraphs. "
        "Speak to 'you'. Match the brand voice above.\n"
        "6. Close with a direct instruction using an action this business really offers (call, WhatsApp, visit, "
        "book, order, request a quote). call_to_action must match that action.\n"
        "7. Never repeat a sentence, hook shape or proof point across the ads. Each ad leans on a different "
        "detail.\n"
        "8. No clichés, emojis, hashtags, em dashes or en dashes. Headline 40 characters or fewer and "
        "description 30 characters or fewer, both complete phrases that are never cut off.\n"
        "Pick keywords only from the searches listed. competitor_gap must name competitors from the list with "
        "the evidence, or be an empty string. benefit_chips are short proof stats taken from the website.",
        # Angles are customer-facing strategy, generated once per campaign: worth the
        # stronger writer (Claude clearly beat gpt-4o-mini on reliabletech.co.zw).
        model=os.getenv("AD_ANGLES_MODEL", "anthropic/claude-sonnet-4.6"))

    angles = data.get("angles") if isinstance(data, dict) else None
    if not isinstance(angles, list):
        logger.warning("[AdAngles] no angles returned")
        return []
    names = [str(c.get("name") or "").lower() for c in competitors if c.get("name")]
    clean = []
    for a in angles[:count]:
        if not (isinstance(a, dict) and a.get("angle_name") and a.get("value_proposition")):
            continue
        angle = {k: a.get(k) for k in ANGLE_FIELDS}
        angle_hook = str(angle.get("hook") or angle.get("angle_name") or "")[:40]
        # Keep well-formed copy variations, topped up from the angle's own fields so
        # downstream code can always rely on a full set of three; a set with nothing
        # usable falls back entirely.
        raw_vars = [v for v in (a.get("copy_variations") or []) if isinstance(v, dict) and v.get("primary_text")]
        clean_vars = []
        for v in raw_vars[:3]:
            variation = {k: v.get(k) for k in _VARIATION_FIELDS}
            # Trim each field to Meta's practical limits so nothing gets cut off at publish time.
            variation["headline"] = _fit(variation.get("headline") or angle_hook, 40)
            variation["description"] = _fit(variation.get("description"), 30)
            variation["primary_text"] = str(variation.get("primary_text") or "")
            cta = str(variation.get("call_to_action") or "Learn More")
            variation["call_to_action"] = next(
                (c for c in _VARIATION_CTAS if c.lower() == cta.strip().lower()), "Learn More")
            # Strip characters that look unprofessional in a feed or trip Meta's review.
            for f in ("primary_text", "headline", "description"):
                variation[f] = re.sub(r"[—–]", ", ", variation[f])
            # Delivery fields: enums clamped to accepted values, targeting capped, demo sanity.
            variation["placement"] = str(v.get("placement") or "automatic").strip().lower()
            if variation["placement"] not in _VARIATION_PLACEMENTS:
                variation["placement"] = "automatic"
            variation["format"] = str(v.get("format") or "single_image").strip().lower()
            if variation["format"] not in _VARIATION_FORMATS:
                variation["format"] = "single_image"
            variation["optimization"] = str(v.get("optimization") or "conversions").strip().lower()
            if variation["optimization"] not in _VARIATION_OPTIMIZATIONS:
                variation["optimization"] = "conversions"
            # Objective coherence: Meta can only optimize toward what the site supports.
            # Without a purchase pixel, Sales can't run - instant forms (leads) or chat
            # (messages) convert without a pixel; traffic is the safe floor.
            if variation["optimization"] == "conversions" and not signals.get("pixel"):
                variation["optimization"] = ("leads" if (signals.get("lead_form") or signals.get("checkout"))
                                             else "messages" if (signals.get("whatsapp") or signals.get("messenger"))
                                             else "traffic")
            hint = v.get("targeting_hint") if isinstance(v.get("targeting_hint"), dict) else {}
            variation["targeting_hint"] = {
                "interests": [str(t).strip()[:60] for t in (hint.get("interests") or []) if str(t).strip()][:6],
                "behaviors": [str(t).strip()[:60] for t in (hint.get("behaviors") or []) if str(t).strip()][:3],
            }
            demo = v.get("demographics") if isinstance(v.get("demographics"), dict) else {}
            try:
                age_min = max(18, min(65, int(demo.get("age_min") or 18)))
                age_max = max(age_min, min(65, int(demo.get("age_max") or 65)))
            except (TypeError, ValueError):
                age_min, age_max = 18, 65
            gender = str(demo.get("gender") or "all").strip().lower()
            variation["demographics"] = {
                "age_min": age_min, "age_max": age_max,
                "gender": gender if gender in ("all", "male", "female") else "all",
            }
            variation["image_direction"] = str(v.get("image_direction") or angle.get("visual_direction") or "")[:400]
            variation["benefit_chips"] = [str(c).strip()[:40] for c in (v.get("benefit_chips") or []) if str(c).strip()][:4]
            clean_vars.append(variation)
        if 0 < len(clean_vars) < 3:
            clean_vars += _fallback_variations(angle)[len(clean_vars):]
        angle["copy_variations"] = clean_vars[:3] or _fallback_variations(angle)
        # A gap naming no researched competitor is filler ("many competitors don't ...").
        gap = str(angle.get("competitor_gap") or "").lower()
        if not any(n.split()[0] in gap for n in names if n.split()):
            angle["competitor_gap"] = ""
        clean.append(angle)
    # Per-angle objective tag: every ad set carries the recommended Meta objective so the
    # campaign builder (and the user) can see what the ads should optimize toward.
    for a in clean:
        a["campaign_objective"] = advice["recommended_objective"]
    # Exactly one angle leads the creative (the "which angle leads?" pick a media buyer
    # asks for). The model may have flagged one; otherwise the first angle leads.
    def _is_true(x):
        return x is True or (isinstance(x, str) and x.strip().lower() in ("true", "yes", "1"))
    lead_idx = next((i for i, a in enumerate(clean) if _is_true(a.get("leads_the_creative"))), 0 if clean else None)
    for i, a in enumerate(clean):
        a["leads_the_creative"] = (i == lead_idx)
    logger.info("[AdAngles] generated %d angles for %s", len(clean), profile.get("company_name"))
    return clean

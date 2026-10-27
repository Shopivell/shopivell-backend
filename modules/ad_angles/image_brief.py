"""Image prompt for one ad: logo, theme and the exact text on the image. Brand-agnostic: everything comes from the
brand's own data (name, logo, colours, aesthetic, photos) and from the ad (headline, button, allocated facts).
"""
import re
from typing import Any, Dict, List, Optional

PROOF_MAX_CHARS = 48
PHONE = re.compile(r"\d[\d ()/+-]{7,}\d")
LAYOUTS = {
    "photo_grid": "a 2x2 grid of the brand's real photos in thin brand-colour frames, headline above the grid, "
                  "proof line under the headline, button below the grid",
    "split_panel": "split frame: a solid brand-colour text panel on one side with the headline, proof line and button; "
                   "the brand's best real photo filling the other side",
    "type_led": "bold typographic ad on a solid brand-colour field: the headline very large, one clean supporting "
                "graphic made only of simple shapes and brand colours, the proof line, and the button; no photographs",
}
TEXT_LED_LEVERS = {"urgency_scarcity", "objection_removal", "vivid_fear_moment"}


def proof_line(ad: Dict[str, Any], facts: List[Dict[str, Any]]) -> str:
    """Short proof text for the image, taken from the facts this ad already uses. Prefer a fact with a number; use its
    verbatim site quote when it fits, so nothing on the image is invented."""
    by_id = {f.get("id"): f for f in facts}
    used = [by_id[i] for i in (ad.get("facts_used") or []) if i in by_id]
    cands = []
    for f in used:
        for text in (f.get("quote"), f.get("fact")):
            t = re.sub(r"\s+", " ", str(text or "")).strip(" .")
            if 3 <= len(t) <= PROOF_MAX_CHARS and not PHONE.search(t):
                cands.append((0 if re.search(r"\d", t) else 1, len(t), t))
    return sorted(cands)[0][2] if cands else ""


def pick_layout(ad: Dict[str, Any], photo_count: int) -> str:
    if photo_count >= 3 and ad.get("lever") not in TEXT_LED_LEVERS:
        return "photo_grid"
    if photo_count >= 1:
        return "split_panel"
    return "type_led"


def aesthetic_line(brand_dna: Dict[str, Any], limit: int = 220) -> str:
    text = str(((brand_dna or {}).get("voice_and_style") or {}).get("aesthetic_style") or "").strip()
    first = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0] if text else ""
    return first[:limit].rstrip(" ,;.")


def build_image_prompt(brand: Dict[str, Any], ad: Dict[str, Any], facts: List[Dict[str, Any]],
                       photo_count: int = 0) -> Dict[str, Any]:
    """brand: {name, logo (bool: real logo attached), colors [hex], aesthetic (str)}. Returns the prompt and the
    pieces, so the tagger can record the layout as a scoreable element."""
    layout = pick_layout(ad, photo_count)
    headline = str(ad.get("headline") or "").strip()
    button = str(ad.get("button_label") or ad.get("meta_cta") or "Learn More").strip()
    proof = proof_line(ad, facts)
    colors = ", ".join(brand.get("colors") or [])
    text_items = [f'headline: "{headline}"'] + ([f'proof line: "{proof}"'] if proof else []) + [f'button: "{button}"']
    parts = [
        f"Design a finished square 1:1 social ad for {brand['name']}. It must look like agency-made work.",
        "LOGO: the first attached image is the brand's real logo. Place it exactly as given, clean, top-left, with "
        "clear space. Do not redraw, restyle or invent any other logo or wordmark." if brand.get("logo") else
        f"LOGO: no logo file is available. Show the name '{brand['name']}' as a small plain wordmark, top-left.",
        f"THEME: brand colours {colors}; the first colour leads, the second is the accent, neutrals fill the rest. "
        + (f"Mood only: {brand['aesthetic']}. Where this mentions colours, people or places, ignore that and use the brand "
           "colours and the layout below. " if brand.get("aesthetic") else "")
        + "One sans-serif family, high contrast, generous spacing.",
        f"LAYOUT: {LAYOUTS[layout]}.",
        "PHOTOS: " + (f"the {photo_count} attached real photos of the brand's own work are the imagery. Use them as "
                      "they are (crop and frame only); do not alter, repaint or add to what they show."
                      if layout != "type_led" else "none attached, so use no photographs and no people; do not "
                      "invent buildings, products, uniforms or signage."),
        "TEXT ON THE IMAGE, exactly these strings, spelled letter for letter, and nothing else: "
        + "; ".join(text_items) + ". The button is a solid rounded rectangle in the accent colour with the button text.",
        "RULES: no other words, numbers, slogans or fine print anywhere; no garbled letters; no invented logos; "
        "readable at thumbnail size; one clear focal point.",
    ]
    return {"layout": layout, "headline": headline, "proof": proof, "button": button, "prompt": "\n".join(parts)}

"""The store facts every advertising agent is grounded in.

Kept out of router.py so the asset and campaign services can load it without
importing the API module. Nothing here is intelligence: it reads what the owner
actually entered, uploaded or had scraped, so an agent can be told the real
business instead of guessing one.
"""
from __future__ import annotations

import logging
import hashlib
import json
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def logo_brand_color(logo_url: str) -> Optional[str]:
    from utils.brand import logo_brand_color as _color
    return _color(logo_url)


def _clean_palette(primary: Any, secondary: Any) -> list[str]:
    """Return a stable, de-duplicated palette with the primary colour first."""
    values = [primary]
    if isinstance(secondary, (list, tuple)):
        values.extend(secondary)
    elif secondary:
        values.extend(re.split(r"[,;]", str(secondary)))
    palette: list[str] = []
    seen = set()
    for value in values:
        colour = str(value or "").strip()
        if not colour:
            continue
        if re.fullmatch(r"#[0-9a-fA-F]{3}", colour):
            colour = "#" + "".join(ch * 2 for ch in colour[1:])
        elif re.fullmatch(r"[0-9a-fA-F]{6}", colour):
            colour = "#" + colour
        colour = colour.upper() if colour.startswith("#") else colour
        key = colour.lower()
        if key not in seen:
            palette.append(colour)
            seen.add(key)
    return palette


def build_visual_brand_contract(context: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize saved brand fields into the contract every image agent receives.

    The contract deliberately contains no invented defaults. If a font or colour is
    missing, the prompt says to keep one neutral choice across the campaign rather
    than independently guessing a new visual system for every creative.
    """
    context = context or {}
    dna = context.get("brand_dna") if isinstance(context.get("brand_dna"), dict) else {}
    voice_style = dna.get("voice_and_style") if isinstance(dna.get("voice_and_style"), dict) else {}
    palette = _clean_palette(context.get("color_theme"), context.get("secondary_colors"))
    logo_url = str(context.get("logo_url") or "").strip()
    real_assets = [str(url) for url in (context.get("real_asset_urls") or []) if str(url).strip()]
    contract: Dict[str, Any] = {
        "brand_name": context.get("store_name") or "",
        "brand_description": context.get("brand_description") or context.get("about") or "",
        "palette": {
            "primary": palette[0] if palette else "",
            "secondary": palette[1:],
            "all": palette,
        },
        "typography": {
            "heading": context.get("font_heading") or "",
            "body": context.get("font_body") or "",
        },
        "aesthetic_style": voice_style.get("aesthetic_style") or context.get("aesthetic_style") or "",
        "tone_of_voice": voice_style.get("tone_of_voice") or context.get("store_tone") or "",
        "logo": {
            "available": bool(logo_url),
            "url": logo_url,
            "placement": "top-left",
            "treatment": "Use the supplied logo exactly; never redraw, restyle, recolour, or replace it.",
        },
        "imagery": {
            "real_reference_assets": real_assets,
            "reference_count": len(real_assets),
            "treatment": "Keep supplied products, people, uniforms, vehicles, premises, and finishes faithful.",
        },
        "owner_creative_direction": context.get("owner_creative_prompt") or "",
        "consistency_rules": [
            "Use this same palette hierarchy in every creative: primary leads, secondary colours accent, neutrals support.",
            "Use the same heading and body typography across the campaign; if unspecified, choose one neutral sans-serif family and keep it fixed.",
            "Keep the logo top-left with consistent clear space and scale whenever a logo reference is supplied.",
            "Vary the scene and composition by ad angle without changing the brand's palette, typography, logo treatment, or imagery character.",
        ],
    }
    signature_source = {
        "brand_name": contract["brand_name"],
        "palette": contract["palette"],
        "typography": contract["typography"],
        "aesthetic_style": contract["aesthetic_style"],
        "logo_url": logo_url,
        "real_reference_assets": real_assets,
        "owner_creative_direction": contract["owner_creative_direction"],
    }
    contract["signature"] = hashlib.sha256(
        json.dumps(signature_source, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return contract


def build_brand_voice_contract(context: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the saved Brand DNA into one voice used by every copy angle."""
    context = context or {}
    dna = context.get("brand_dna") if isinstance(context.get("brand_dna"), dict) else {}
    voice_style = dna.get("voice_and_style") if isinstance(dna.get("voice_and_style"), dict) else {}
    about = dna.get("about") if isinstance(dna.get("about"), dict) else {}
    profiles = [p for p in (dna.get("buyer_profiles") or []) if isinstance(p, dict)]
    customer_language: list[str] = []
    for profile in profiles:
        for phrase in profile.get("their_language") or []:
            phrase = str(phrase or "").strip()
            if phrase and phrase not in customer_language:
                customer_language.append(phrase)
    contract: Dict[str, Any] = {
        "brand_name": context.get("store_name") or "",
        "tone_of_voice": voice_style.get("tone_of_voice") or context.get("store_voice")
                         or context.get("store_tone") or "",
        "target_demographic": voice_style.get("target_demographic") or "",
        "positioning": about.get("positioning") or "",
        "problem_solved": about.get("problem_solved") or "",
        "differentiation": about.get("differentiation") or "",
        "number_one_outcome": about.get("number_one_outcome") or "",
        "customer_language": customer_language[:12],
        "consistency_rules": [
            "Keep the same tone, vocabulary level, point of view, and positioning across every angle.",
            "Change the customer problem and motivation by angle without changing the brand personality.",
            "Prefer the saved customer language when it naturally fits the audience and message.",
        ],
    }
    contract["signature"] = hashlib.sha256(
        json.dumps(contract, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return contract


def load_brand_context(store_id: str) -> dict:
    """Everything the agents need to ground copy/imagery in this specific business
    rather than a generic stock-photo/marketing-copy default: the store's own
    scraped/entered profile (name, type, description, voice, color theme, owner's
    own creative-direction prompt) plus its real logo, homepage screenshot, and up
    to 5 genuinely uploaded (not AI-generated) photos - product shots, uniforms,
    storefronts, whatever the owner actually put in their Assets library.
    is_generated=False is the filter that keeps this from feeding a prior AI ad
    creative back in as a "real" reference."""
    ctx: Dict[str, Any] = {}
    if not store_id:
        return ctx
    try:
        from database import SessionLocal
        from modules.stores.models import Store
        from modules.assets.models import Asset, AssetType
        from sqlalchemy import or_
        _db = SessionLocal()
        try:
            store = _db.query(Store).filter(Store.id == store_id).first()
            if not store:
                return ctx
            ctx["store_name"] = store.store_name
            ctx["business_type"] = store.business_type
            ctx["about"] = store.store_description or store.store_voice
            ctx["color_theme"] = store.color_theme
            ctx["secondary_colors"] = store.secondary_colors or []
            ctx["font_heading"] = store.font_heading
            ctx["font_body"] = store.font_body
            ctx["brand_description"] = store.brand_description
            ctx["brand_dna"] = store.brand_dna or {}
            ctx["store_tone"] = store.store_tone
            ctx["owner_creative_prompt"] = store.ai_creative_prompt
            ctx["products"] = store.products_or_services or []
            ctx["link_url"] = store.store_link or (f"https://{store.domain}" if store.domain else None)
            ctx["country"] = store.store_country
            ctx["country_code"] = store.country_code
            ctx["logo_url"] = store.logo_url
            logo_color = logo_brand_color(store.logo_url)
            ctx["logo_derived_color"] = logo_color
            if logo_color and not ctx.get("color_theme"):
                ctx["color_theme"] = logo_color
            ctx["screenshot_url"] = store.screenshot_url
            ctx["banner_url"] = store.banner_url
            real_assets = (
                _db.query(Asset)
                .filter(Asset.store_id == store.id, Asset.file_type == AssetType.IMAGE,
                        Asset.is_active == True, Asset.is_generated == False,
                        Asset.source == "upload",
                        or_(Asset.original_filename.is_(None),
                            ~Asset.original_filename.like("ad\\_%", escape="\\")))
                .order_by(Asset.created_at.desc())
                .limit(5)
                .all()
            )
            ctx["real_asset_urls"] = [
                a.cloudinary_secure_url or a.cloudinary_url for a in real_assets
                if (a.cloudinary_secure_url or a.cloudinary_url)
            ]
            ctx["visual_brand_contract"] = build_visual_brand_contract(ctx)
            ctx["brand_voice_contract"] = build_brand_voice_contract(ctx)
        finally:
            _db.close()
    except Exception as e:
        logger.warning("Could not load brand context for store %s: %s", store_id, e)
    return ctx

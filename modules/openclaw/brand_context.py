"""The store facts every advertising agent is grounded in.

Kept out of router.py so the asset and campaign services can load it without
importing the API module. Nothing here is intelligence: it reads what the owner
actually entered, uploaded or had scraped, so an agent can be told the real
business instead of guessing one.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def logo_brand_color(logo_url: str) -> Optional[str]:
    from utils.brand import logo_brand_color as _color
    return _color(logo_url)


def load_brand_context(store_id: str) -> dict:
    """Everything the agents need to ground copy/imagery in this specific business
    rather than a generic stock-photo/marketing-copy default: the store's own
    scraped/entered profile (name, type, description, voice, color theme, owner's
    own creative-direction prompt) plus its real logo, homepage screenshot, and up
    to 3 genuinely uploaded (not AI-generated) photos - product shots, uniforms,
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
            ctx["owner_creative_prompt"] = store.ai_creative_prompt
            ctx["products"] = store.products_or_services or []
            ctx["link_url"] = store.store_link or (f"https://{store.domain}" if store.domain else None)
            ctx["country"] = store.store_country
            ctx["country_code"] = store.country_code
            ctx["logo_url"] = store.logo_url
            logo_color = logo_brand_color(store.logo_url)
            if logo_color:
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
                .limit(3)
                .all()
            )
            ctx["real_asset_urls"] = [
                a.cloudinary_secure_url or a.cloudinary_url for a in real_assets
                if (a.cloudinary_secure_url or a.cloudinary_url)
            ]
        finally:
            _db.close()
    except Exception as e:
        logger.warning("Could not load brand context for store %s: %s", store_id, e)
    return ctx

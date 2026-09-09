"""
OpenClaw API Router
Full API for frontend to interact with OpenClaw ad management
Add to Shopivell backend: modules/openclaw/router.py
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import httpx
import os
import logging

from app.database import get_db
from modules.stores.models import Store
from modules.users.auth_utils import get_current_user
from modules.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/openclaw", tags=["OpenClaw"])

# OpenClaw Gateway URL
OPENCLAW_GATEWAY = os.getenv("OPENCLAW_GATEWAY_URL", "http://openclaw:18789")
OPENCLAW_API_KEY = os.getenv("OPENCLAW_API_KEY", "")


async def call_openclaw(method: str, endpoint: str, data: dict = None) -> dict:
    """Call OpenClaw gateway API"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Authorization": f"Bearer {OPENCLAW_API_KEY}"}
        url = f"{OPENCLAW_GATEWAY}{endpoint}"

        if method == "GET":
            response = await client.get(url, headers=headers, params=data)
        elif method == "POST":
            response = await client.post(url, headers=headers, json=data)
        elif method == "PATCH":
            response = await client.patch(url, headers=headers, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        return response.json()


# ============ Request/Response Models ============

class AdSettingsUpdate(BaseModel):
    ads_enabled: Optional[bool] = None
    target_roas: Optional[float] = None
    target_cpa: Optional[float] = None
    target_cpql: Optional[float] = None


class GenerateCampaignRequest(BaseModel):
    product_id: Optional[str] = None
    product_name: str
    product_description: str
    product_price: Optional[float] = None
    campaign_goal: str = "conversions"
    brand_voice: str = "professional"
    budget: float = 20.0


class GenerateCTWARequest(BaseModel):
    product_name: str
    product_description: str
    whatsapp_number: str
    budget: float = 20.0


class GenerateImageRequest(BaseModel):
    product_name: str
    product_description: str
    style: str = "lifestyle"
    dimensions: str = "square"
    brand_colors: Optional[List[str]] = None


class GenerateCopyRequest(BaseModel):
    product_name: str
    product_description: str
    angle: str
    variations: int = 3


class OptimizerConfigUpdate(BaseModel):
    scale_winner: Optional[Dict[str, Any]] = None
    kill_loser: Optional[Dict[str, Any]] = None


# ============ Store Ad Settings ============

@router.get("/stores/{store_id}/ad-settings")
async def get_ad_settings(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get store ad settings"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    return {
        "ads_enabled": getattr(store, 'ads_enabled', False),
        "target_roas": getattr(store, 'target_roas', 2.5),
        "target_cpa": getattr(store, 'target_cpa', 10.0),
        "target_cpql": getattr(store, 'target_cpql', None),
        "zernio_profile_id": getattr(store, 'zernio_profile_id', None),
    }


@router.patch("/stores/{store_id}/ad-settings")
async def update_ad_settings(
    store_id: str,
    settings: AdSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update store ad settings"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if settings.ads_enabled is not None:
        store.ads_enabled = settings.ads_enabled
    if settings.target_roas is not None:
        store.target_roas = settings.target_roas
    if settings.target_cpa is not None:
        store.target_cpa = settings.target_cpa
    if settings.target_cpql is not None:
        store.target_cpql = settings.target_cpql

    db.commit()
    db.refresh(store)

    return {
        "ads_enabled": store.ads_enabled,
        "target_roas": store.target_roas,
        "target_cpa": store.target_cpa,
        "target_cpql": store.target_cpql,
        "zernio_profile_id": store.zernio_profile_id,
    }


# ============ Zernio Connection ============

@router.post("/stores/{store_id}/connect-zernio")
async def connect_zernio(
    store_id: str,
    redirect_url: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start Zernio OAuth flow to connect Meta ad account"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Create or get Zernio profile for this store
    result = await call_openclaw("POST", "/api/skills/zernio-ads/create_store_profile", {
        "store_id": store_id,
        "store_name": store.store_name
    })

    profile_id = result.get("profile_id")

    # Get OAuth URL
    oauth_result = await call_openclaw("POST", "/api/skills/zernio-ads/get_oauth_url", {
        "profile_id": profile_id,
        "redirect_url": redirect_url
    })

    return {
        "auth_url": oauth_result.get("auth_url"),
        "profile_id": profile_id
    }


@router.post("/stores/{store_id}/zernio-callback")
async def zernio_callback(
    store_id: str,
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Complete Zernio OAuth flow"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Exchange code for access (handled by Zernio)
    # The profile_id should have been stored during connect_zernio
    # For now, we'll update the store with the profile_id

    # In production, verify the code with Zernio API
    store.zernio_profile_id = store_id  # Placeholder
    store.ads_enabled = True
    db.commit()

    return {"success": True, "profile_id": store.zernio_profile_id}


@router.get("/stores/{store_id}/connected-accounts")
async def get_connected_accounts(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get connected Meta ad accounts for a store"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        return {"accounts": []}

    result = await call_openclaw("GET", "/api/skills/zernio-ads/list_connected_accounts", {
        "profile_id": store.zernio_profile_id
    })

    return {"accounts": result.get("accounts", [])}


# ============ Campaign Management ============

@router.get("/stores/{store_id}/campaigns")
async def get_campaigns(
    store_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all campaigns for a store"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        return {"campaigns": []}

    result = await call_openclaw("GET", "/api/skills/zernio-ads/list_campaigns", {
        "profile_id": store.zernio_profile_id,
        "status": status or "all"
    })

    return {"campaigns": result.get("campaigns", [])}


@router.get("/campaigns/{campaign_id}/insights")
async def get_campaign_insights(
    campaign_id: str,
    date_preset: str = "last_7d",
    current_user: User = Depends(get_current_user)
):
    """Get insights for a campaign"""
    result = await call_openclaw("GET", "/api/skills/zernio-ads/get_insights", {
        "ad_id": campaign_id,
        "date_preset": date_preset
    })
    return result


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    reason: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Pause a campaign"""
    result = await call_openclaw("POST", "/api/skills/zernio-ads/pause_ad", {
        "ad_id": campaign_id,
        "reason": reason
    })
    return {"success": True}


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: str,
    current_user: User = Depends(get_current_user)
):
    """Resume a paused campaign"""
    result = await call_openclaw("POST", "/api/skills/zernio-ads/update_campaign", {
        "ad_id": campaign_id,
        "updates": {"status": "ACTIVE"}
    })
    return {"success": True}


@router.post("/campaigns/{campaign_id}/scale")
async def scale_campaign_budget(
    campaign_id: str,
    percentage: float,
    max_budget: Optional[float] = None,
    current_user: User = Depends(get_current_user)
):
    """Scale campaign budget"""
    result = await call_openclaw("POST", "/api/skills/zernio-ads/scale_budget", {
        "ad_id": campaign_id,
        "percentage": percentage,
        "max_budget": max_budget
    })
    return result


# ============ AI Campaign Generation ============

@router.post("/stores/{store_id}/generate-campaign")
async def generate_campaign(
    store_id: str,
    request: GenerateCampaignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate a full campaign using AI"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    result = await call_openclaw("POST", "/api/skills/ad-creator/generate_full_campaign", {
        "product_name": request.product_name,
        "product_description": request.product_description,
        "product_price": request.product_price,
        "store_name": store.store_name,
        "target_country": store.country_code or "ZW",
        "campaign_goal": request.campaign_goal,
        "brand_voice": request.brand_voice,
        "brand_colors": [store.color_theme] if store.color_theme else None,
        "budget": request.budget
    })

    return result


@router.post("/stores/{store_id}/generate-ctwa-campaign")
async def generate_ctwa_campaign(
    store_id: str,
    request: GenerateCTWARequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate a Click-to-WhatsApp campaign"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Generate WhatsApp-specific copy
    copy_result = await call_openclaw("POST", "/api/skills/ad-creator/generate_whatsapp_copy", {
        "product_data": {
            "name": request.product_name,
            "description": request.product_description
        },
        "angle": {"name": "Conversation", "hook": "Chat with us!"},
        "store_name": store.store_name
    })

    # Generate image
    image_result = await call_openclaw("POST", "/api/skills/ad-creator/generate_image", {
        "product_name": request.product_name,
        "product_description": request.product_description,
        "style": "lifestyle",
        "dimensions": "square",
        "brand_colors": [store.color_theme] if store.color_theme else None
    })

    return {
        "copy": copy_result,
        "image": image_result,
        "whatsapp_number": request.whatsapp_number,
        "budget": request.budget,
        "ready_for_launch": True
    }


@router.post("/stores/{store_id}/launch-campaign")
async def launch_campaign(
    store_id: str,
    campaign_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Launch a generated campaign via Zernio"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected to Zernio")

    # Get ad account
    accounts = await call_openclaw("GET", "/api/skills/zernio-ads/list_connected_accounts", {
        "profile_id": store.zernio_profile_id
    })

    if not accounts.get("accounts"):
        raise HTTPException(status_code=400, detail="No ad account connected")

    ad_account_id = accounts["accounts"][0]["ad_account_id"]

    # Create campaign via Zernio
    result = await call_openclaw("POST", "/api/skills/zernio-ads/create_campaign", {
        "profile_id": store.zernio_profile_id,
        "ad_account_id": ad_account_id,
        **campaign_data
    })

    return {"success": True, "campaign_id": result.get("campaign_id")}


# ============ Creative Generation ============

@router.post("/generate-image")
async def generate_ad_image(
    request: GenerateImageRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate an ad image using GPT-Image-2.5"""
    result = await call_openclaw("POST", "/api/skills/ad-creator/generate_image", {
        "product_name": request.product_name,
        "product_description": request.product_description,
        "style": request.style,
        "dimensions": request.dimensions,
        "brand_colors": request.brand_colors
    })
    return result


@router.post("/generate-copy")
async def generate_ad_copy(
    request: GenerateCopyRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate ad copy variations"""
    result = await call_openclaw("POST", "/api/skills/ad-creator/generate_ad_copy", {
        "angle": {"name": request.angle},
        "product_data": {
            "name": request.product_name,
            "description": request.product_description
        },
        "format": "single_image",
        "variations": request.variations
    })
    return {"variations": result}


# ============ Optimizer ============

@router.get("/stores/{store_id}/optimizer/status")
async def get_optimizer_status(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get optimizer status for a store"""
    result = await call_openclaw("GET", "/api/plugins/optimizer/status", {
        "store_id": store_id
    })
    return result


@router.get("/stores/{store_id}/optimizer/history")
async def get_optimizer_history(
    store_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get optimizer action history"""
    result = await call_openclaw("GET", "/api/plugins/optimizer/history", {
        "store_id": store_id,
        "limit": limit
    })
    return result


@router.post("/stores/{store_id}/optimizer/config")
async def update_optimizer_config(
    store_id: str,
    config: OptimizerConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update optimizer configuration"""
    result = await call_openclaw("POST", "/api/plugins/optimizer/config", {
        "store_id": store_id,
        "rules": config.dict(exclude_none=True)
    })
    return result


# ============ Lead & Conversion Stats ============

@router.get("/stores/{store_id}/lead-stats")
async def get_lead_stats(
    store_id: str,
    date_range: str = "last_7d",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get lead statistics for CTWA campaigns"""
    # This would query the local database for lead scoring data
    # For now, return placeholder
    return {
        "total_leads": 0,
        "qualified_leads": 0,
        "hot_leads": 0,
        "conversion_rate": 0,
        "avg_lead_score": 0
    }


@router.get("/stores/{store_id}/conversion-stats")
async def get_conversion_stats(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get offline conversion statistics"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        return {"events_sent": 0, "events_matched": 0, "match_rate": 0, "by_event_type": {}}

    result = await call_openclaw("GET", "/api/skills/zernio-ads/get_conversion_stats", {
        "profile_id": store.zernio_profile_id,
        "date_range": "last_30d"
    })
    return result


# ============ CTWA Insights ============

@router.get("/campaigns/{campaign_id}/ctwa-insights")
async def get_ctwa_insights(
    campaign_id: str,
    date_preset: str = "last_7d",
    current_user: User = Depends(get_current_user)
):
    """Get Click-to-WhatsApp specific insights"""
    result = await call_openclaw("GET", "/api/skills/zernio-ads/get_ctwa_insights", {
        "campaign_id": campaign_id,
        "date_preset": date_preset
    })
    return result

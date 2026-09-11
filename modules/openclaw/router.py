"""
OpenClaw API Router
Full API for frontend to interact with OpenClaw ad management
Add to Shopivell backend: modules/openclaw/router.py
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import httpx
import os
import logging

from database import get_db
from modules.stores.models import Store
from utils.jwt_auth import get_current_user
from modules.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/openclaw", tags=["OpenClaw"])

# ---------------------------------------------------------------------------
# Zernio REST integration
#
# The original migration targeted an OpenClaw "gateway" REST API
# (http://openclaw:18789/api/skills/<skill>/<action>). The deployed OpenClaw
# image does not expose that API — it serves the OpenClaw Control UI. Meta Ads
# and Click-to-WhatsApp are provided directly by Zernio's REST API, so we call
# Zernio directly. `call_openclaw` is kept as a compatibility shim that routes
# each skill action to the service that actually provides it:
#   * skills/zernio-ads/* -> Zernio REST API (ads, CTWA, insights)
#   * skills/ad-creator/*  -> OpenAI (ad copy + image generation)
#   * plugins/optimizer/*, agents/* -> not deployed -> 501
# ---------------------------------------------------------------------------
ZERNIO_API_BASE = os.getenv("ZERNIO_API_BASE", "https://zernio.com/api/v1")
ZERNIO_API_KEY = os.getenv("ZERNIO_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def _first(d, *keys, default=None):
    """Return the first present, non-None key from a dict (defensive parsing)."""
    if isinstance(d, dict):
        for k in keys:
            if d.get(k) is not None:
                return d[k]
    return default


def _safe_json(text: str) -> dict:
    import json as _json
    import re as _re
    try:
        return _json.loads(text)
    except Exception:
        m = _re.search(r"\{.*\}", text or "", _re.S)
        if m:
            try:
                return _json.loads(m.group(0))
            except Exception:
                pass
    return {}


async def _zernio(method: str, path: str, json_body: dict = None, params: dict = None) -> dict:
    """Low-level Zernio REST call (Bearer API-key auth)."""
    if not ZERNIO_API_KEY:
        raise HTTPException(status_code=503, detail="ZERNIO_API_KEY is not configured on the backend.")
    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Authorization": f"Bearer {ZERNIO_API_KEY}", "Content-Type": "application/json"}
        resp = await client.request(method, f"{ZERNIO_API_BASE}{path}", headers=headers, json=json_body, params=params)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"Zernio API error ({resp.status_code}): {resp.text[:500]}")
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}


async def _openai(path: str, payload: dict, timeout: float = 60.0) -> dict:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured for ad creative generation.")
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"https://api.openai.com/v1{path}",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"OpenAI error ({resp.status_code}): {resp.text[:300]}")
        return resp.json()


_META_CTAS = {
    "LEARN_MORE", "SHOP_NOW", "SIGN_UP", "BOOK_TRAVEL", "CONTACT_US", "DOWNLOAD",
    "GET_OFFER", "GET_QUOTE", "SUBSCRIBE", "WATCH_MORE", "ADD_TO_CART", "APPLY_NOW",
    "BOOK_NOW", "BUY_NOW", "BUY_TICKETS", "DONATE", "DONATE_NOW", "GET_DIRECTIONS",
    "GET_SHOWTIMES", "LISTEN_NOW", "ORDER_NOW", "PLAY_GAME", "REQUEST_TIME",
    "SEE_MENU", "START_ORDER", "INSTALL_MOBILE_APP", "USE_APP",
}


def _cta(v, default="LEARN_MORE"):
    v = (str(v or "")).strip().upper().replace(" ", "_")
    return v if v in _META_CTAS else default


def _goal(v, default="traffic"):
    # Zernio Meta goals: engagement, traffic, awareness, video_views,
    # lead_generation, lead_conversion, conversions, app_promotion,
    # catalog_sales, page_likes.
    m = {
        "conversions": "conversions", "sales": "conversions", "outcome_sales": "conversions",
        "traffic": "traffic", "outcome_traffic": "traffic", "link_clicks": "traffic",
        "awareness": "awareness", "reach": "awareness", "outcome_awareness": "awareness",
        "leads": "lead_generation", "lead_generation": "lead_generation", "outcome_leads": "lead_generation",
        "engagement": "engagement", "outcome_engagement": "engagement",
        "video_views": "video_views", "app_promotion": "app_promotion",
        "catalog_sales": "catalog_sales", "page_likes": "page_likes",
    }
    return m.get((str(v or "")).strip().lower(), default)


def _ctwa_payload(d: dict) -> dict:
    # POST /ads/messaging (destination=whatsapp). Zernio locks CTA/destination.
    return {
        "accountId": _first(d, "account_id", "accountId"),
        "adAccountId": _first(d, "ad_account_id", "adAccountId"),
        "name": _first(d, "name", default=f"CTWA - {d.get('product_name', 'Campaign')}"),
        "headline": _first(d, "headline", default=""),
        "body": _first(d, "body", "primary_text", default=""),
        "imageUrl": _first(d, "image_url", "imageUrl", default=""),
        "budgetAmount": _first(d, "budget", "budgetAmount", default=20),
        "budgetType": _first(d, "budget_type", "budgetType", default="daily"),
        "currency": _first(d, "currency", default="USD"),
        "destination": "whatsapp",
        "countries": _first(d, "countries", default=["US"]),
    }


def _campaign_payload(d: dict) -> dict:
    # POST /ads/create. Requires accountId (Zernio account) + adAccountId (act_),
    # goal (not objective), linkUrl, imageUrl and callToAction.
    return {
        "accountId": _first(d, "account_id", "accountId"),
        "adAccountId": _first(d, "ad_account_id", "adAccountId"),
        "name": _first(d, "name", "product_name", default="Campaign"),
        "goal": _goal(_first(d, "goal", "objective", "campaign_goal")),
        "headline": _first(d, "headline", default=""),
        "body": _first(d, "body", "primary_text", default=""),
        "linkUrl": _first(d, "link_url", "linkUrl", "url", "destination_url", default=""),
        "imageUrl": _first(d, "image_url", "imageUrl", default=""),
        "callToAction": _cta(_first(d, "call_to_action", "callToAction", "conversion_button")),
        "budgetAmount": _first(d, "budget", "budgetAmount", default=20),
        "budgetType": _first(d, "budget_type", "budgetType", default="daily"),
        "currency": _first(d, "currency", default="USD"),
        "countries": _first(d, "countries", default=["US"]),
    }


async def _dispatch_zernio(action: str, d: dict) -> dict:
    d = d or {}
    if action == "list_connected_accounts":
        # /accounts lists the platform accounts connected under the API key/profile
        # (Facebook, WhatsApp, etc.). /ads/accounts needs a specific accountId, so
        # it can't be used to discover what's connected.
        res = await _zernio("GET", "/accounts")
        return {"accounts": _first(res, "accounts", "data", default=res if isinstance(res, list) else [])}
    if action == "create_store_profile":
        # Ads are scoped under a Zernio profile. Create one for the store. Zernio
        # returns the profile as a Mongo document whose id is `_id` (a 24-char
        # ObjectId) — do NOT fall back to our own store UUID, which Zernio rejects
        # as "Invalid profileId format".
        import re as _re
        name = d.get("store_name") or "Store"
        try:
            res = await _zernio("POST", "/profiles", json_body={"name": name})
            prof = res.get("profile") if isinstance(res, dict) and isinstance(res.get("profile"), dict) else res
            pid = _first(prof, "_id", "id", "profileId", "profile_id")
        except HTTPException as e:
            # Zernio profile names are unique. If one already exists it returns 409
            # with the existing profile id — reuse it rather than failing.
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            m = _re.search(r'"existingProfileId"\s*:\s*"([^"]+)"', detail)
            if m:
                pid = m.group(1)
            elif e.status_code == 409 or "already exists" in detail:
                # Fall back to looking the profile up by name.
                listing = await _zernio("GET", "/profiles")
                profs = listing.get("profiles", []) if isinstance(listing, dict) else (listing or [])
                match = next((p for p in profs if p.get("name") == name), None)
                pid = _first(match or {}, "_id", "id")
            else:
                raise
        if not pid:
            raise HTTPException(status_code=502, detail="Could not resolve a Zernio profile id.")
        return {"profile_id": pid}
    if action == "get_oauth_url":
        # Ask Zernio for the real provider OAuth URL. /connect/facebook/ads covers
        # Meta ads + page messaging; /connect/whatsapp connects a WhatsApp Business
        # account for conversational messaging. headless=true keeps the whole
        # experience white-labelled: after approval Zernio returns the user to our
        # redirect_url (app.shopivell.com) instead of showing Zernio's own UI.
        connect_path = "/connect/whatsapp" if d.get("connect_type") == "whatsapp" else "/connect/facebook/ads"
        params = {"profileId": d.get("profile_id"), "headless": "true"}
        if d.get("redirect_url"):
            params["redirect_url"] = d["redirect_url"]
        res = await _zernio("GET", connect_path, params=params)
        return {"auth_url": _first(res, "authUrl", "auth_url", "url", default=""), "raw": res}
    if action == "list_campaigns":
        acct = _first(d, "ad_account_id", "profile_id")
        res = await _zernio("GET", "/ads/tree", params={"adAccountId": acct})
        return {"campaigns": _first(res, "campaigns", "data", "tree", default=[])}
    if action in ("get_insights", "get_ctwa_insights"):
        params = {k: v for k, v in {
            "adId": d.get("ad_id"), "campaignId": d.get("campaign_id"),
            "datePreset": d.get("date_preset"),
        }.items() if v}
        return await _zernio("GET", "/ads/tree", params=params)
    if action == "get_all_store_insights":
        acct = _first(d, "ad_account_id", "profile_id")
        return await _zernio("GET", "/ads/tree", params={"adAccountId": acct, "datePreset": d.get("date_preset", "last_7d")})
    if action == "get_conversion_stats":
        acct = _first(d, "ad_account_id", "profile_id")
        return await _zernio("GET", "/ads/tree", params={"adAccountId": acct, "fields": "conversions,leads"})
    if action == "create_campaign":
        return await _zernio("POST", "/ads/create", json_body=_campaign_payload(d))
    if action == "create_ctwa_campaign":
        return await _zernio("POST", "/ads/messaging", json_body=_ctwa_payload(d))
    if action == "pause_ad":
        aid = _first(d, "ad_id", "campaign_id")
        return await _zernio("PATCH", f"/ads/{aid}", json_body={"status": "PAUSED"})
    if action == "update_campaign":
        cid = d.get("campaign_id")
        return await _zernio("PATCH", f"/ads/{cid}", json_body=_first(d, "updates", default={k: v for k, v in d.items() if k != "campaign_id"}))
    if action == "scale_budget":
        cid = d.get("campaign_id")
        return await _zernio("PATCH", f"/ads/{cid}", json_body={"budgetAmount": _first(d, "new_budget", "budget")})
    raise HTTPException(status_code=501, detail=f"Zernio action '{action}' is not implemented.")


async def _dispatch_ad_creator(action: str, d: dict) -> dict:
    d = d or {}
    if action in ("generate_ad_copy", "generate_whatsapp_copy"):
        name = d.get("product_name", "the product")
        desc = d.get("product_description", "")
        channel = ("for a Click-to-WhatsApp ad that gets the user to message the business on WhatsApp"
                   if action == "generate_whatsapp_copy" else "for a Meta conversion ad")
        prompt = (f"Write ad copy {channel}. Product: {name}. Details: {desc}. "
                  f'Return strict JSON with keys "headline" (max 40 chars) and "body" (max 125 chars).')
        res = await _openai("/chat/completions", {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are an expert Meta Ads copywriter. Reply with JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        })
        parsed = _safe_json(res["choices"][0]["message"]["content"])
        body = parsed.get("body", "")
        return {"headline": parsed.get("headline", ""), "body": body, "primary_text": body}
    if action == "generate_image":
        prompt = d.get("prompt") or (
            f"Professional, high-converting product marketing image for "
            f"{d.get('product_name', 'a product')}. {d.get('product_description', '')}")
        res = await _openai("/images/generations", {
            "model": "gpt-image-1", "prompt": prompt, "size": "1024x1024", "n": 1,
        }, timeout=120.0)
        item = (res.get("data") or [{}])[0]
        url = item.get("url") or (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else "")
        return {"image_url": url, "url": url}
    if action == "generate_full_campaign":
        copy = await _dispatch_ad_creator("generate_ad_copy", d)
        image = await _dispatch_ad_creator("generate_image", d)
        return {"copy": copy, "image": image}
    raise HTTPException(status_code=501, detail=f"ad-creator action '{action}' is not implemented.")


async def call_openclaw(method: str, endpoint: str, data: dict = None) -> dict:
    """Compatibility shim routing OpenClaw skill actions to real services.

    The OpenClaw gateway REST API the migration targeted does not exist on the
    deployed platform, so route each action to the service that provides it.
    """
    data = data or {}
    if "/skills/zernio-ads/" in endpoint:
        return await _dispatch_zernio(endpoint.rsplit("/", 1)[-1], data)
    if "/skills/ad-creator/" in endpoint:
        return await _dispatch_ad_creator(endpoint.rsplit("/", 1)[-1], data)
    raise HTTPException(
        status_code=501,
        detail="This OpenClaw feature (autonomous agents / optimizer plugin) is not available in the current deployment.",
    )


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

class FacebookPagesRequest(BaseModel):
    temp_token: str


class WhatsappNumbersRequest(BaseModel):
    profile_id: str
    temp_token: str


class ZernioFinalizeRequest(BaseModel):
    profile_id: str
    connect_token: str
    temp_token: Optional[str] = None
    user_profile: Optional[Any] = None
    platform: str = "facebook"          # "facebook" (ads) or "whatsapp"
    page_id: Optional[str] = None       # selected Facebook page id
    phone_number_id: Optional[str] = None  # selected WhatsApp number id
    waba_id: Optional[str] = None       # selected WhatsApp Business Account id


@router.post("/facebook-pages")
async def facebook_pages(
    payload: FacebookPagesRequest,
    current_user: User = Depends(get_current_user),
):
    """List the Facebook Pages available to a pending headless connection.

    In headless mode Zernio returns only the user's basic profile (not their
    pages) at the select_page step, so the frontend callback fetches the pages
    here using the temp token, then posts the chosen page id to /zernio-finalize.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://graph.facebook.com/v20.0/me/accounts",
            params={"access_token": payload.temp_token, "fields": "id,name,category"},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=f"Facebook pages error: {r.text[:200]}")
    return {"pages": r.json().get("data", [])}


@router.post("/whatsapp-numbers")
async def whatsapp_numbers(
    payload: WhatsappNumbersRequest,
    current_user: User = Depends(get_current_user),
):
    """List the WhatsApp phone numbers available to a pending headless connection.

    Headless WhatsApp returns step=select_phone_number with profileId + tempToken;
    the numbers are listed via GET /connect/whatsapp/select-phone-number, then the
    chosen phoneNumberId + wabaId are posted to /zernio-finalize.
    """
    res = await _zernio(
        "GET",
        "/connect/whatsapp/select-phone-number",
        params={"profileId": payload.profile_id, "tempToken": payload.temp_token},
    )
    numbers = _first(res, "numbers", "phoneNumbers", "data", default=res if isinstance(res, list) else [])
    return {"numbers": numbers}


@router.post("/stores/{store_id}/connect-zernio")
async def connect_zernio(
    store_id: str,
    redirect_url: str,
    connect_type: str = "ads",   # "ads" (Meta ads + CTWA) or "whatsapp"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start the headless white-label Zernio OAuth flow.

    Returns an auth_url the frontend redirects the user to. After the user
    approves on Facebook/WhatsApp, Zernio (headless mode) redirects them back to
    `redirect_url` (app.shopivell.com/...) with connect params, which the frontend
    then posts to /zernio-finalize.
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Reuse the store's Zernio profile if it already has a valid one. A valid
    # Zernio profile id is a 24-char hex ObjectId; a stored value containing "-"
    # is a stale store-UUID from an earlier bug — discard and recreate.
    profile_id = store.zernio_profile_id
    if not profile_id or "-" in str(profile_id):
        result = await call_openclaw("POST", "/api/skills/zernio-ads/create_store_profile", {
            "store_id": store_id,
            "store_name": store.store_name,
        })
        profile_id = result.get("profile_id")
        # Persist the profile now so the finalize step (and future connects) reuse it.
        store.zernio_profile_id = profile_id
        db.commit()

    oauth_result = await call_openclaw("POST", "/api/skills/zernio-ads/get_oauth_url", {
        "profile_id": profile_id,
        "redirect_url": redirect_url,
        "connect_type": connect_type,
    })

    return {"auth_url": oauth_result.get("auth_url"), "profile_id": profile_id}


@router.post("/stores/{store_id}/zernio-finalize")
async def zernio_finalize(
    store_id: str,
    payload: ZernioFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Finalize a headless Zernio connection.

    The frontend callback page collects the params Zernio appended to the
    redirect_url (connect_token, tempToken, userProfile) plus the page/number the
    user picked, and posts them here. We complete the connection with Zernio and
    mark the store connected.
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if payload.platform == "whatsapp":
        # WhatsApp finalize: POST /connect/whatsapp/select-phone-number with the
        # selected number + WABA and the temp token (no X-Connect-Token).
        path = "/connect/whatsapp/select-phone-number"
        body = {
            "profileId": payload.profile_id,
            "phoneNumberId": payload.phone_number_id,
            "wabaId": payload.waba_id,
            "tempToken": payload.temp_token,
        }
        headers = {"Authorization": f"Bearer {ZERNIO_API_KEY}", "Content-Type": "application/json"}
    else:
        # Facebook finalize: POST /connect/facebook/select-page with X-Connect-Token.
        path = "/connect/facebook/select-page"
        body = {
            "profileId": payload.profile_id,
            "tempToken": payload.temp_token,
            "userProfile": payload.user_profile,
            "pageId": payload.page_id,
        }
        headers = {
            "Authorization": f"Bearer {ZERNIO_API_KEY}",
            "X-Connect-Token": payload.connect_token,
            "Content-Type": "application/json",
        }
    body = {k: v for k, v in body.items() if v is not None}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{ZERNIO_API_BASE}{path}", headers=headers, json=body)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"Zernio finalize error ({resp.status_code}): {resp.text[:400]}")
        try:
            result = resp.json()
        except Exception:
            result = {"raw": resp.text}

    store.zernio_profile_id = payload.profile_id
    store.ads_enabled = True
    db.commit()
    return {"success": True, "profile_id": payload.profile_id, "platform": payload.platform, "result": result}


@router.get("/stores/{store_id}/connected-accounts")
async def get_connected_accounts(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get connected Meta ad accounts for a store"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return {"accounts": []}

    result = await call_openclaw("GET", "/api/skills/zernio-ads/list_connected_accounts", {
        "profile_id": store.zernio_profile_id
    })
    all_accounts = result.get("accounts", [])

    # Zernio returns every account on the API key. Prefer the ones bound to this
    # store's own profile, but everything here runs through ONE shared Zernio key
    # (free tier caps the whole key at 2 connected accounts), so a store whose
    # profile has nothing bound would otherwise wrongly show "not connected".
    # Fall back to all accounts on the key so a connection made under any store
    # is recognised everywhere.
    pid = str(store.zernio_profile_id or "")

    def _acc_profile(a):
        p = a.get("profileId") or a.get("profile")
        if isinstance(p, dict):
            return str(p.get("_id") or p.get("id") or "")
        return str(p or "")

    scoped = [a for a in all_accounts if pid and _acc_profile(a) == pid]
    return {"accounts": scoped or all_accounts}


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

    pid = str(store.zernio_profile_id)

    def _acc_profile(a):
        p = a.get("profileId") or a.get("profile")
        return str(p.get("_id") if isinstance(p, dict) else (p or ""))

    # Find this store's connected Meta account (Zernio account id). Prefer one
    # bound to this store's profile, but fall back to any Meta account on the
    # shared key (see get_connected_accounts) so a connection made under another
    # store still lets this store launch.
    listing = await _zernio("GET", "/accounts")
    accts = listing.get("accounts", []) if isinstance(listing, dict) else (listing or [])
    meta_accts = [a for a in accts if a.get("platform") in ("facebook", "metaads")]
    meta_acc = next((a for a in meta_accts if _acc_profile(a) == pid), None) or (meta_accts[0] if meta_accts else None)
    if not meta_acc:
        raise HTTPException(status_code=400, detail="No Meta (Facebook/ads) account connected to this store.")
    zernio_account_id = meta_acc.get("_id") or meta_acc.get("id")

    # Resolve the Meta ad account (act_...) under it.
    ad_accounts = await _zernio("GET", "/ads/accounts", params={"accountId": zernio_account_id})
    ad_list = ad_accounts.get("accounts", []) if isinstance(ad_accounts, dict) else (ad_accounts or [])
    if not ad_list:
        raise HTTPException(status_code=400, detail="No Meta ad account is available on the connected account.")
    ad_account_id = ad_list[0].get("id") or ad_list[0].get("accountId")

    # Assemble the create data with sensible store-derived defaults.
    is_ctwa = bool(
        campaign_data.get("whatsapp_number")
        or campaign_data.get("ctwa")
        or campaign_data.get("destination") == "whatsapp"
    )
    data = {
        "link_url": store.store_link or store.domain or "https://shopivell.com",
        "currency": store.currency or "USD",
        "countries": [store.country_code] if store.country_code else ["US"],
        **campaign_data,
        # These override any client-supplied values (resolved server-side).
        "account_id": zernio_account_id,
        "ad_account_id": ad_account_id,
    }
    action = "create_ctwa_campaign" if is_ctwa else "create_campaign"
    result = await call_openclaw("POST", f"/api/skills/zernio-ads/{action}", data)

    return {"success": True, "campaign_id": result.get("id") or result.get("campaign_id"), "result": result}


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


# ============ Autonomous Multi-Agent System ============

class AutonomousSessionRequest(BaseModel):
    auto_generate_goals: bool = True
    budget_limit: float = 500.0
    evaluation_interval_minutes: int = 60
    max_concurrent_tasks: int = 3
    time_limit_hours: Optional[float] = None
    pause_on_error: bool = True
    initial_goals: Optional[List[Dict[str, Any]]] = None


class GoalRequest(BaseModel):
    type: str  # maximize_roas, minimize_cpa, etc.
    description: str
    target_metric: str
    target_value: float
    deadline: Optional[str] = None
    priority: str = "high"  # critical, high, medium, low


# In-memory session storage (use Redis/DB in production)
_autonomous_sessions: Dict[str, dict] = {}


@router.post("/stores/{store_id}/autonomous/start")
async def start_autonomous_session(
    store_id: str,
    request: AutonomousSessionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Start an autonomous advertising session.

    The system will:
    1. Analyze current performance and generate goals (or use provided goals)
    2. Create execution plans for each goal
    3. Execute tasks (create campaigns, optimize, scale, etc.)
    4. Continuously evaluate and adjust until goals are achieved
    """
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store must be connected to Zernio first")

    # Get current performance
    try:
        insights = await call_openclaw("GET", "/api/skills/zernio-ads/get_all_store_insights", {
            "profile_id": store.zernio_profile_id,
            "date_preset": "last_7d"
        })
    except Exception:
        insights = {"campaigns": []}

    # Calculate performance snapshot
    campaigns = insights.get("campaigns", [])
    total_spend = sum(c.get("spend", 0) for c in campaigns)
    total_revenue = sum(c.get("revenue", 0) for c in campaigns)

    performance = {
        "roas": total_revenue / total_spend if total_spend > 0 else 0,
        "cpa": total_spend / max(sum(c.get("conversions", 0) for c in campaigns), 1),
        "ctr": sum(c.get("ctr", 0) for c in campaigns) / max(len(campaigns), 1),
        "conversion_rate": 0.03,  # Would calculate from actual data
        "total_spend": total_spend,
        "total_revenue": total_revenue,
        "active_campaigns": len([c for c in campaigns if c.get("status") == "ACTIVE"]),
        "date_range": "last_7d"
    }

    # Create session
    session_id = f"session-{store_id}-{int(datetime.utcnow().timestamp())}"

    session = {
        "id": session_id,
        "store_id": store_id,
        "config": request.dict(),
        "performance": performance,
        "state": "initializing",
        "goals": [],
        "plans": [],
        "completed_tasks": [],
        "failed_tasks": [],
        "total_spend": 0,
        "started_at": datetime.utcnow().isoformat(),
        "last_update": datetime.utcnow().isoformat()
    }

    _autonomous_sessions[session_id] = session

    # Start autonomous loop in background
    background_tasks.add_task(
        run_autonomous_loop,
        session_id,
        store.zernio_profile_id,
        performance,
        request
    )

    return {
        "session_id": session_id,
        "state": "initializing",
        "message": "Autonomous session started. Goals will be generated and executed."
    }


async def run_autonomous_loop(
    session_id: str,
    profile_id: str,
    performance: dict,
    config: AutonomousSessionRequest
):
    """Background task that runs the autonomous loop"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        return

    try:
        session["state"] = "running"

        # Step 1: Generate or use provided goals
        if config.initial_goals:
            goals = config.initial_goals
        else:
            # Call Goal Agent via OpenClaw
            goal_result = await call_openclaw("POST", "/api/agents/goal/generate", {
                "store_id": session["store_id"],
                "performance": performance,
                "constraints": {
                    "max_budget": config.budget_limit,
                    "max_daily_spend": config.budget_limit / 30
                }
            })
            goals = goal_result.get("goals", [])

        session["goals"] = goals
        session["last_update"] = datetime.utcnow().isoformat()

        # Step 2: For each goal, create and execute plan
        for goal in goals:
            if session["state"] != "running":
                break

            # Create plan
            plan_result = await call_openclaw("POST", "/api/agents/planner/create", {
                "goal": goal,
                "available_budget": config.budget_limit - session["total_spend"]
            })
            plan = plan_result.get("plan", {})
            session["plans"].append(plan)

            # Execute tasks
            for task in plan.get("tasks", []):
                if session["state"] != "running":
                    break

                try:
                    task_result = await call_openclaw("POST", "/api/agents/executor/run", {
                        "task": task
                    })

                    if task_result.get("success"):
                        session["completed_tasks"].append({
                            "task": task,
                            "result": task_result.get("result"),
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        if task_result.get("result", {}).get("spend"):
                            session["total_spend"] += task_result["result"]["spend"]
                    else:
                        session["failed_tasks"].append({
                            "task": task,
                            "error": task_result.get("error"),
                            "timestamp": datetime.utcnow().isoformat()
                        })

                except Exception as e:
                    session["failed_tasks"].append({
                        "task": task,
                        "error": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    })

                    if config.pause_on_error:
                        session["state"] = "paused"
                        break

                session["last_update"] = datetime.utcnow().isoformat()

            # Check budget limit
            if session["total_spend"] >= config.budget_limit:
                session["state"] = "completed"
                break

        if session["state"] == "running":
            session["state"] = "completed"

    except Exception as e:
        session["state"] = "failed"
        session["error"] = str(e)

    session["ended_at"] = datetime.utcnow().isoformat()


@router.get("/stores/{store_id}/autonomous/sessions")
async def list_autonomous_sessions(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all autonomous sessions for a store"""
    sessions = [
        s for s in _autonomous_sessions.values()
        if s.get("store_id") == store_id
    ]
    return {"sessions": sessions}


@router.get("/autonomous/{session_id}/status")
async def get_autonomous_session_status(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get status of an autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": session["id"],
        "state": session["state"],
        "goals": session.get("goals", []),
        "completed_tasks": len(session.get("completed_tasks", [])),
        "failed_tasks": len(session.get("failed_tasks", [])),
        "total_spend": session.get("total_spend", 0),
        "started_at": session.get("started_at"),
        "last_update": session.get("last_update"),
        "ended_at": session.get("ended_at")
    }


@router.post("/autonomous/{session_id}/pause")
async def pause_autonomous_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Pause an autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["state"] == "running":
        session["state"] = "paused"
        return {"success": True, "state": "paused"}

    return {"success": False, "message": f"Cannot pause session in state: {session['state']}"}


@router.post("/autonomous/{session_id}/resume")
async def resume_autonomous_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Resume a paused autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["state"] == "paused":
        session["state"] = "running"
        # Would need to resume the loop from last checkpoint
        return {"success": True, "state": "running"}

    return {"success": False, "message": f"Cannot resume session in state: {session['state']}"}


@router.post("/autonomous/{session_id}/stop")
async def stop_autonomous_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):
    """Stop an autonomous session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session["state"] = "completed"
    session["ended_at"] = datetime.utcnow().isoformat()
    return {"success": True, "state": "completed"}


@router.post("/autonomous/{session_id}/add-goal")
async def add_goal_to_session(
    session_id: str,
    goal: GoalRequest,
    current_user: User = Depends(get_current_user)
):
    """Add a new goal to a running session"""
    session = _autonomous_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["state"] not in ["running", "paused"]:
        raise HTTPException(status_code=400, detail="Cannot add goal to completed session")

    new_goal = {
        "id": f"goal-{int(datetime.utcnow().timestamp())}",
        "type": goal.type,
        "description": goal.description,
        "target_metric": goal.target_metric,
        "target_value": goal.target_value,
        "deadline": goal.deadline,
        "priority": goal.priority,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    session["goals"].append(new_goal)
    return {"success": True, "goal": new_goal}


# ============ Reporting ============

@router.get("/stores/{store_id}/report/weekly")
async def get_weekly_report(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get weekly performance report"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected")

    insights = await call_openclaw("GET", "/api/skills/zernio-ads/get_all_store_insights", {
        "profile_id": store.zernio_profile_id,
        "date_preset": "last_7d"
    })

    campaigns = insights.get("campaigns", [])

    return {
        "period": "last_7d",
        "summary": {
            "total_spend": sum(c.get("spend", 0) for c in campaigns),
            "total_impressions": sum(c.get("impressions", 0) for c in campaigns),
            "total_clicks": sum(c.get("clicks", 0) for c in campaigns),
            "total_conversions": sum(c.get("conversions", 0) for c in campaigns),
            "average_ctr": sum(c.get("ctr", 0) for c in campaigns) / max(len(campaigns), 1),
            "average_roas": sum(c.get("roas", 0) for c in campaigns) / max(len(campaigns), 1)
        },
        "campaigns": campaigns,
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/stores/{store_id}/report/demographics")
async def get_demographics_report(
    store_id: str,
    campaign_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get demographic breakdown of ad performance"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail="Store not connected")

    # Get insights with demographic breakdowns
    params = {
        "date_preset": "last_30d",
        "breakdowns": ["age", "gender"]
    }

    if campaign_id:
        params["ad_id"] = campaign_id

    insights = await call_openclaw("GET", "/api/skills/zernio-ads/get_insights", params)

    return {
        "demographics": insights,
        "generated_at": datetime.utcnow().isoformat()
    }


# ============ Zernio Webhook (inbound WhatsApp -> bot reply) ============
#
# Zernio delivers inbound messages over webhooks (event `message.received`),
# not through the REST inbox, so two-way WhatsApp needs a public receiver.
# Flow:
#   Zernio --message.received--> POST /v1/openclaw/zernio-webhook
#     -> resolve the store for business context
#     -> generate a reply with OpenAI
#     -> POST /inbox/conversations/{conversationId}/messages  (service reply,
#        allowed inside the 24h window the customer's inbound just opened)
#
# Register once with:
#   POST /webhooks/settings {name, url, events:["message.received"], secret}
# Signature: Zernio signs the raw body with HMAC-SHA256 -> X-Zernio-Signature.

ZERNIO_WEBHOOK_SECRET = os.getenv("ZERNIO_WEBHOOK_SECRET", "")
# Which store's persona the shared sandbox bot speaks as (the sandbox account is
# not bound to any store). Optional; falls back to the most recent ads store.
WHATSAPP_BOT_STORE_ID = os.getenv("WHATSAPP_BOT_STORE_ID", "")


def _verify_zernio_signature(raw: bytes, signature: str) -> bool:
    """Best-effort HMAC-SHA256 verification of a Zernio webhook body."""
    if not ZERNIO_WEBHOOK_SECRET:
        return True  # no secret configured -> accept (test mode)
    if not signature:
        return False
    import hmac as _hmac
    import hashlib as _hashlib
    digest = _hmac.new(ZERNIO_WEBHOOK_SECRET.encode(), raw, _hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if "=" in signature else signature
    return _hmac.compare_digest(digest, candidate.strip())


def _resolve_bot_store(db: Session, account: dict):
    """Pick the store whose business info the bot should answer with."""
    # 1) Account bound to a store's Zernio profile.
    prof = account.get("profileId") or account.get("profile") if isinstance(account, dict) else None
    pid = (prof.get("_id") if isinstance(prof, dict) else prof) or None
    if pid:
        s = db.query(Store).filter(Store.zernio_profile_id == str(pid)).first()
        if s:
            return s
    # 2) Explicitly configured store for the sandbox.
    if WHATSAPP_BOT_STORE_ID:
        s = db.query(Store).filter(Store.id == WHATSAPP_BOT_STORE_ID).first()
        if s:
            return s
    # 3) Best-effort: the most recently updated ads-enabled store.
    return (
        db.query(Store)
        .filter(Store.ads_enabled == True)  # noqa: E712
        .order_by(Store.updated_at.desc())
        .first()
    )


def _business_context(store) -> str:
    """Compact business brief for the bot's system prompt."""
    if not store:
        return "You are a helpful WhatsApp assistant for a Shopivell online store."
    parts = [f"Business name: {store.store_name}"]
    for label, val in [
        ("What they sell / category", store.store_category),
        ("Description", store.store_description),
        ("Products or services", ", ".join(store.products_or_services) if isinstance(store.products_or_services, list) else None),
        ("Address", store.store_address),
        ("City", store.store_city),
        ("Country", store.store_country),
        ("Currency", store.currency),
        ("Phone", store.store_phone),
        ("Email", store.store_email),
        ("Hours", str(store.operating_hours) if store.operating_hours else None),
        ("Brand voice", store.store_voice),
        ("Tone", store.store_tone),
        ("Store link", store.store_link),
    ]:
        if val:
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


async def _generate_bot_reply(user_text: str, store) -> str:
    context = _business_context(store)
    name = store.store_name if store else "the store"
    system = (
        "You are the customer-service assistant for a business on WhatsApp. "
        "Answer as the business, warmly and concisely (WhatsApp-length, 1-3 short "
        "sentences, no markdown). Use ONLY the business info below; if you don't "
        "know something, offer to connect the customer with the team. Never invent "
        "prices or stock.\n\n=== BUSINESS INFO ===\n" + context
    )
    try:
        res = await _openai("/chat/completions", {
            "model": os.getenv("WHATSAPP_BOT_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text or "Hi"},
            ],
            "max_tokens": 300,
            "temperature": 0.5,
        }, timeout=30.0)
        return (res["choices"][0]["message"]["content"] or "").strip() or \
            f"Thanks for messaging {name}! How can we help you today?"
    except Exception as e:  # never fail the webhook on the AI call
        logger.warning("bot reply generation failed: %s", e)
        return f"Thanks for reaching out to {name}! How can we help you today?"


async def _handle_inbound_whatsapp(payload: dict):
    """Background task: read an inbound message and reply via Zernio."""
    try:
        msg = payload.get("message") or {}
        if msg.get("direction") not in (None, "inbound", "in"):
            return  # ignore our own / outbound echoes
        if (msg.get("platform") or "").lower() not in ("whatsapp", ""):
            return
        conv_id = msg.get("conversationId") or (payload.get("conversation") or {}).get("id")
        account = payload.get("account") or {}
        account_id = account.get("id") or account.get("_id")
        user_text = msg.get("text") or ""
        if not conv_id or not account_id:
            logger.warning("inbound webhook missing conversationId/accountId: %s", payload)
            return

        db = SessionLocal()
        try:
            store = _resolve_bot_store(db, account)
            reply = await _generate_bot_reply(user_text, store)
        finally:
            db.close()

        await _zernio(
            "POST",
            f"/inbox/conversations/{conv_id}/messages",
            json_body={"accountId": account_id, "message": reply},
        )
        logger.info("Replied to WhatsApp conversation %s", conv_id)
    except Exception as e:
        logger.exception("Failed to handle inbound WhatsApp webhook: %s", e)


@router.post("/zernio-webhook")
async def zernio_webhook(request: Request, background_tasks: BackgroundTasks):
    """Public receiver for Zernio webhooks (no auth; verified via signature)."""
    raw = await request.body()
    sig = request.headers.get("X-Zernio-Signature", "")
    if not _verify_zernio_signature(raw, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = _safe_json(raw.decode("utf-8"))
    except Exception:
        payload = {}
    event = payload.get("event") or request.headers.get("X-Zernio-Event", "")
    if event == "message.received":
        background_tasks.add_task(_handle_inbound_whatsapp, payload)
    # Always 200 quickly so Zernio doesn't retry/disable the webhook.
    return {"ok": True, "event": event}


# Export router
openclaw_router = router

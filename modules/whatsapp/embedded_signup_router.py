"""
WhatsApp Embedded Signup API Router

Endpoints for connecting store owner's WhatsApp phone numbers.
"""

import os
import logging
from typing import Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from dependencies import get_current_user
from modules.users.models import User

from .embedded_signup import EmbeddedSignupService
from .models import WhatsAppAccount

logger = logging.getLogger(__name__)

# Router
embedded_signup_router = APIRouter(
    prefix="/whatsapp/connect",
    tags=["WhatsApp Connection"]
)

# Environment
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
META_APP_ID = os.getenv("META_APP_ID", "")
META_CONFIG_ID = os.getenv("META_WHATSAPP_CONFIG_ID", "")


# ============================================================================
# Schemas
# ============================================================================

class WhatsAppAccountResponse(BaseModel):
    id: UUID
    phone_number: str
    display_name: Optional[str] = None
    verified_name: Optional[str] = None
    quality_rating: Optional[str] = None
    is_enabled: bool
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WhatsAppAccountList(BaseModel):
    accounts: list[WhatsAppAccountResponse]
    total: int


class ConnectInitResponse(BaseModel):
    oauth_url: str
    state: str
    config_id: str
    app_id: str


class CompleteSignupRequest(BaseModel):
    code: str
    waba_id: str
    phone_number_id: str


class SetDefaultRequest(BaseModel):
    account_id: UUID


# ============================================================================
# OAuth Flow Endpoints
# ============================================================================

@embedded_signup_router.get("/init", response_model=ConnectInitResponse)
async def init_whatsapp_connection(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Initialize WhatsApp connection flow.
    Returns OAuth URL and state for the frontend to open.
    """
    # Verify user owns this store
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized for this store")

    service = EmbeddedSignupService(store_id, db)
    state = service.generate_oauth_state()

    redirect_uri = f"{BACKEND_URL}/v1/api/whatsapp/connect/callback"
    oauth_url = service.get_oauth_url(redirect_uri, state)

    return ConnectInitResponse(
        oauth_url=oauth_url,
        state=state,
        config_id=META_CONFIG_ID,
        app_id=META_APP_ID
    )


@embedded_signup_router.get("/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_reason: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """
    OAuth callback from Meta.
    This endpoint receives the authorization code after user completes signup.
    Redirects to frontend with status.
    """
    if error:
        logger.error(f"OAuth error: {error} - {error_description}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/settings/whatsapp?error={error}&message={error_description}"
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/settings/whatsapp?error=missing_params"
        )

    # Extract store_id from state
    try:
        store_id = state.split(":")[0]
    except:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/settings/whatsapp?error=invalid_state"
        )

    # Redirect to frontend with code and state for completion
    # The frontend will call /complete with additional WABA details
    return RedirectResponse(
        url=f"{FRONTEND_URL}/settings/whatsapp/complete?code={code}&state={state}"
    )


@embedded_signup_router.post("/complete", response_model=WhatsAppAccountResponse)
async def complete_whatsapp_connection(
    request: CompleteSignupRequest,
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Complete WhatsApp connection after OAuth.
    Frontend calls this with the code and selected WABA/phone details.
    """
    # Verify user owns this store
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized for this store")

    service = EmbeddedSignupService(store_id, db)
    redirect_uri = f"{BACKEND_URL}/v1/api/whatsapp/connect/callback"

    account, error = await service.complete_signup(
        code=request.code,
        redirect_uri=redirect_uri,
        waba_id=request.waba_id,
        phone_number_id=request.phone_number_id
    )

    if error:
        raise HTTPException(status_code=400, detail=error)

    return WhatsAppAccountResponse(
        id=account.id,
        phone_number=account.phone_number,
        display_name=account.display_name,
        verified_name=account.verified_name,
        quality_rating=account.quality_rating,
        is_enabled=account.is_enabled,
        is_default=account.is_default,
        created_at=account.created_at
    )


# ============================================================================
# Account Management Endpoints
# ============================================================================

@embedded_signup_router.get("/accounts", response_model=WhatsAppAccountList)
async def list_whatsapp_accounts(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all WhatsApp accounts connected to this store."""
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized for this store")

    service = EmbeddedSignupService(store_id, db)
    accounts = service.get_store_whatsapp_accounts()

    return WhatsAppAccountList(
        accounts=[
            WhatsAppAccountResponse(
                id=a.id,
                phone_number=a.phone_number,
                display_name=a.display_name,
                verified_name=a.verified_name,
                quality_rating=a.quality_rating,
                is_enabled=a.is_enabled,
                is_default=a.is_default,
                created_at=a.created_at
            )
            for a in accounts
        ],
        total=len(accounts)
    )


@embedded_signup_router.post("/accounts/set-default")
async def set_default_account(
    request: SetDefaultRequest,
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set a WhatsApp account as the default for this store."""
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized for this store")

    service = EmbeddedSignupService(store_id, db)
    account = service.set_default_account(request.account_id)

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return {"message": "Default account updated", "account_id": str(account.id)}


@embedded_signup_router.delete("/accounts/{account_id}")
async def disconnect_whatsapp_account(
    account_id: UUID,
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disconnect a WhatsApp account from this store."""
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized for this store")

    service = EmbeddedSignupService(store_id, db)
    success = service.disconnect_account(account_id)

    if not success:
        raise HTTPException(status_code=404, detail="Account not found")

    return {"message": "Account disconnected"}


# ============================================================================
# SDK Integration Endpoint (for Facebook JS SDK)
# ============================================================================

@embedded_signup_router.post("/sdk-callback")
async def sdk_callback(
    request: Request,
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Callback for Facebook JS SDK Embedded Signup.

    The frontend sends the response from FB.login() here.
    Expected body: {
        accessToken: string,
        data_access_expiration_time: number,
        expiresIn: number,
        code: string (optional, for system user token exchange)
    }
    """
    if not current_user.store_id or str(current_user.store_id) != str(store_id):
        raise HTTPException(status_code=403, detail="Not authorized for this store")

    body = await request.json()
    access_token = body.get("accessToken")
    waba_id = body.get("waba_id")
    phone_number_id = body.get("phone_number_id")

    if not access_token:
        raise HTTPException(status_code=400, detail="Missing accessToken")

    service = EmbeddedSignupService(store_id, db)

    # If WABA and phone number provided, complete the signup
    if waba_id and phone_number_id:
        # Get phone number details
        phone_numbers, error = await service.get_waba_phone_numbers(access_token, waba_id)
        if error:
            raise HTTPException(status_code=400, detail=f"Failed to get phone numbers: {error}")

        phone_data = None
        for pn in phone_numbers:
            if pn.get("id") == phone_number_id:
                phone_data = pn
                break

        if not phone_data:
            raise HTTPException(status_code=404, detail="Phone number not found")

        # Subscribe to webhooks
        await service.subscribe_to_webhooks(access_token, waba_id)

        # Check existing account
        existing = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.phone_number_id == phone_number_id
        ).first()

        if existing:
            existing.store_id = store_id
            existing.permanent_access_token = access_token
            existing.display_name = phone_data.get("verified_name")
            existing.verified_name = phone_data.get("verified_name")
            existing.quality_rating = phone_data.get("quality_rating")
            db.commit()
            db.refresh(existing)
            account = existing
        else:
            # Need to get or create FB business account
            from modules.business.models import FacebookBusinessAccount
            from modules.stores.models import Store
            import secrets

            fb_account = db.query(FacebookBusinessAccount).filter(
                FacebookBusinessAccount.business_id == waba_id
            ).first()

            if not fb_account:
                fb_account = FacebookBusinessAccount(
                    business_id=waba_id,
                    name=f"WABA-{waba_id}",
                    access_token=access_token,
                )
                db.add(fb_account)
                db.commit()
                db.refresh(fb_account)

            account = WhatsAppAccount(
                business_account_id=fb_account.id,
                store_id=store_id,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
                phone_number=phone_data.get("display_phone_number", ""),
                display_name=phone_data.get("verified_name"),
                verified_name=phone_data.get("verified_name"),
                quality_rating=phone_data.get("quality_rating"),
                permanent_access_token=access_token,
                is_enabled=True,
                is_default=True,
                webhook_verify_token=secrets.token_urlsafe(32),
            )
            db.add(account)
            db.commit()
            db.refresh(account)

        # Auto-fill WhatsApp Business Profile from store data
        from modules.stores.models import Store
        store = db.query(Store).filter(Store.id == store_id).first()
        if store:
            profile_success, profile_error = await service.update_business_profile(
                access_token, phone_number_id, store
            )
            if profile_error:
                logger.warning(f"Business profile update failed (non-fatal): {profile_error}")

        return WhatsAppAccountResponse(
            id=account.id,
            phone_number=account.phone_number,
            display_name=account.display_name,
            verified_name=account.verified_name,
            quality_rating=account.quality_rating,
            is_enabled=account.is_enabled,
            is_default=account.is_default,
            created_at=account.created_at
        )

    # If no WABA/phone, just return available WABAs for user to select
    wabas, error = await service.get_user_whatsapp_business_accounts(access_token)
    if error:
        raise HTTPException(status_code=400, detail=f"Failed to get WABAs: {error}")

    # Get phone numbers for each WABA
    result = []
    for waba in wabas:
        phone_numbers, _ = await service.get_waba_phone_numbers(access_token, waba["id"])
        result.append({
            "waba_id": waba["id"],
            "waba_name": waba.get("name"),
            "business_id": waba.get("business_id"),
            "business_name": waba.get("business_name"),
            "phone_numbers": phone_numbers or []
        })

    return {"wabas": result, "access_token": access_token}


# ============================================================================
# Info Endpoint
# ============================================================================

@embedded_signup_router.get("/info")
async def get_connection_info():
    """
    Get info needed for frontend to initialize Facebook SDK.
    Public endpoint - no auth required.
    """
    return {
        "app_id": META_APP_ID,
        "config_id": META_CONFIG_ID,
        "api_version": "v21.0",
        "scopes": [
            "whatsapp_business_management",
            "whatsapp_business_messaging",
            "business_management"
        ]
    }

"""
WhatsApp Embedded Signup Service

Handles Meta's Embedded Signup flow for WhatsApp Business API.
Allows store owners to connect their own phone numbers.

Flow:
1. Store owner clicks "Connect WhatsApp"
2. Meta OAuth popup opens
3. User logs into Facebook & grants permissions
4. User creates/selects WhatsApp Business Account
5. User verifies their phone number
6. Meta redirects with auth code
7. We exchange code for access token
8. We fetch phone number details & store credentials
"""

import os
import logging
import secrets
import httpx
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from .models import WhatsAppAccount
from modules.business.models import FacebookBusinessAccount
from modules.stores.models import Store

logger = logging.getLogger(__name__)

# Mapping of store business types to WhatsApp verticals
BUSINESS_TYPE_TO_VERTICAL = {
    # Retail & E-commerce
    "retail": "RETAIL",
    "ecommerce": "RETAIL",
    "e-commerce": "RETAIL",
    "shop": "RETAIL",
    "store": "RETAIL",
    "grocery": "GROCERY",
    "supermarket": "GROCERY",

    # Food & Beverage
    "restaurant": "RESTAURANT",
    "cafe": "RESTAURANT",
    "food": "RESTAURANT",
    "bakery": "RESTAURANT",
    "catering": "RESTAURANT",

    # Services
    "salon": "BEAUTY",
    "beauty": "BEAUTY",
    "spa": "BEAUTY",
    "barbershop": "BEAUTY",
    "fashion": "APPAREL",
    "clothing": "APPAREL",
    "apparel": "APPAREL",

    # Professional
    "consulting": "PROF_SERVICES",
    "professional": "PROF_SERVICES",
    "agency": "PROF_SERVICES",
    "legal": "PROF_SERVICES",
    "accounting": "PROF_SERVICES",

    # Health & Wellness
    "health": "HEALTH",
    "medical": "HEALTH",
    "pharmacy": "HEALTH",
    "fitness": "HEALTH",
    "gym": "HEALTH",

    # Travel & Hospitality
    "hotel": "HOTEL",
    "travel": "TRAVEL",
    "tourism": "TRAVEL",
    "lodge": "HOTEL",

    # Automotive
    "auto": "AUTO",
    "automotive": "AUTO",
    "car": "AUTO",
    "mechanic": "AUTO",

    # Education
    "education": "EDU",
    "school": "EDU",
    "training": "EDU",
    "tutoring": "EDU",

    # Entertainment
    "entertainment": "ENTERTAIN",
    "events": "EVENT_PLAN",
    "event": "EVENT_PLAN",

    # Finance
    "finance": "FINANCE",
    "insurance": "FINANCE",
    "banking": "FINANCE",

    # Security (specific to Shopivell use case)
    "security": "PROF_SERVICES",
    "electric_fence": "PROF_SERVICES",
    "alarm": "PROF_SERVICES",
    "cctv": "PROF_SERVICES",

    # Default
    "other": "OTHER",
}

# Meta App credentials (fall back to FACEBOOK_* if META_* not set)
META_APP_ID = os.getenv("META_APP_ID", "") or os.getenv("FACEBOOK_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "") or os.getenv("FACEBOOK_APP_SECRET", "")
META_CONFIG_ID = os.getenv("META_WHATSAPP_CONFIG_ID", "")  # WhatsApp Embedded Signup config ID

# OAuth URLs
META_OAUTH_URL = "https://www.facebook.com/v25.0/dialog/oauth"
META_TOKEN_URL = "https://graph.facebook.com/v25.0/oauth/access_token"
META_DEBUG_TOKEN_URL = "https://graph.facebook.com/v25.0/debug_token"
META_GRAPH_URL = "https://graph.facebook.com/v25.0"


class EmbeddedSignupService:
    """Service for handling WhatsApp Embedded Signup"""

    def __init__(self, store_id: UUID, db: Session):
        self.store_id = store_id
        self.db = db

    def generate_oauth_state(self) -> str:
        """Generate a secure state token for OAuth"""
        return f"{self.store_id}:{secrets.token_urlsafe(32)}"

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        """
        Generate the Meta OAuth URL for Embedded Signup.

        Required scopes for WhatsApp Business:
        - whatsapp_business_management
        - whatsapp_business_messaging
        - business_management
        """
        scopes = [
            "whatsapp_business_management",
            "whatsapp_business_messaging",
            "business_management",
        ]

        params = {
            "client_id": META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(scopes),
            "response_type": "code",
            "config_id": META_CONFIG_ID,  # WhatsApp Embedded Signup config
            "override_default_response_type": "true",
        }

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{META_OAUTH_URL}?{query_string}"

    async def exchange_code_for_token(
        self,
        code: str,
        redirect_uri: str = ""
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Exchange authorization code for access token.
        For JS SDK Embedded Signup (response_type: 'code'), redirect_uri is not needed.
        Returns: (access_token, error_message)
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params = {
                    "client_id": META_APP_ID,
                    "client_secret": META_APP_SECRET,
                    "code": code,
                }
                # Only include redirect_uri if provided (not needed for JS SDK flow)
                if redirect_uri:
                    params["redirect_uri"] = redirect_uri

                response = await client.get(META_TOKEN_URL, params=params)
                data = response.json()

                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    logger.error(f"Token exchange failed: {error_msg}")
                    return None, error_msg

                access_token = data.get("access_token")
                return access_token, None

        except Exception as e:
            logger.error(f"Token exchange error: {e}")
            return None, str(e)

    async def get_user_whatsapp_business_accounts(
        self,
        access_token: str
    ) -> Tuple[Optional[list], Optional[str]]:
        """
        Get WhatsApp Business Accounts the user has access to.
        Returns: (list of WABAs, error_message)
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # First get the user's business accounts
                response = await client.get(
                    f"{META_GRAPH_URL}/me/businesses",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,owned_whatsapp_business_accounts{id,name,currency,timezone_id}"
                    }
                )

                data = response.json()

                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    return None, error_msg

                wabas = []
                for business in data.get("data", []):
                    owned_wabas = business.get("owned_whatsapp_business_accounts", {}).get("data", [])
                    for waba in owned_wabas:
                        waba["business_id"] = business["id"]
                        waba["business_name"] = business["name"]
                        wabas.append(waba)

                return wabas, None

        except Exception as e:
            logger.error(f"Error fetching WABAs: {e}")
            return None, str(e)

    async def get_waba_phone_numbers(
        self,
        access_token: str,
        waba_id: str
    ) -> Tuple[Optional[list], Optional[str]]:
        """
        Get phone numbers registered to a WhatsApp Business Account.
        Returns: (list of phone numbers, error_message)
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{META_GRAPH_URL}/{waba_id}/phone_numbers",
                    params={
                        "access_token": access_token,
                        "fields": "id,display_phone_number,verified_name,quality_rating,code_verification_status,is_official_business_account,account_mode,certificate"
                    }
                )

                data = response.json()

                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    return None, error_msg

                return data.get("data", []), None

        except Exception as e:
            logger.error(f"Error fetching phone numbers: {e}")
            return None, str(e)

    async def register_phone_number(
        self,
        access_token: str,
        phone_number_id: str,
        pin: str = "123456"  # 6-digit PIN for 2FA
    ) -> Tuple[bool, Optional[str]]:
        """
        Register a phone number for WhatsApp Business API.
        This completes the phone number setup after user verification.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{META_GRAPH_URL}/{phone_number_id}/register",
                    params={"access_token": access_token},
                    json={
                        "messaging_product": "whatsapp",
                        "pin": pin
                    }
                )

                data = response.json()

                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    return False, error_msg

                return data.get("success", False), None

        except Exception as e:
            logger.error(f"Error registering phone number: {e}")
            return False, str(e)

    async def subscribe_to_webhooks(
        self,
        access_token: str,
        waba_id: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Subscribe the WABA to webhook events.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{META_GRAPH_URL}/{waba_id}/subscribed_apps",
                    params={"access_token": access_token}
                )

                data = response.json()

                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    return False, error_msg

                return data.get("success", False), None

        except Exception as e:
            logger.error(f"Error subscribing to webhooks: {e}")
            return False, str(e)

    def _get_vertical_from_business_type(self, business_type: Optional[str]) -> str:
        """Map store business type to WhatsApp vertical."""
        if not business_type:
            return "OTHER"

        business_type_lower = business_type.lower().strip()

        # Direct match
        if business_type_lower in BUSINESS_TYPE_TO_VERTICAL:
            return BUSINESS_TYPE_TO_VERTICAL[business_type_lower]

        # Partial match
        for key, vertical in BUSINESS_TYPE_TO_VERTICAL.items():
            if key in business_type_lower or business_type_lower in key:
                return vertical

        return "OTHER"

    async def update_business_profile(
        self,
        access_token: str,
        phone_number_id: str,
        store: Store
    ) -> Tuple[bool, Optional[str]]:
        """
        Update WhatsApp Business Profile with store information.

        Uses the store's existing data to auto-fill the WhatsApp Business Profile:
        - address: From store_address, store_city, store_country
        - description: From store_description or store_name + business_type
        - vertical: Mapped from business_type
        - email: From store_email
        - websites: From store_link/domain

        API: POST /v20.0/<PHONE_NUMBER_ID>/whatsapp_business_profile
        """
        try:
            # Build the address
            address_parts = []
            if store.store_address:
                address_parts.append(store.store_address)
            if store.store_city:
                address_parts.append(store.store_city)
            if store.store_country:
                address_parts.append(store.store_country)
            address = ", ".join(address_parts) if address_parts else None

            # Build description
            description = store.store_description
            if not description:
                description = f"{store.store_name}"
                if store.business_type:
                    description += f" - {store.business_type}"
                if store.products_or_services:
                    description += f". We offer: {', '.join(store.products_or_services[:3])}"

            # Get vertical from business type
            vertical = self._get_vertical_from_business_type(store.business_type)

            # Build websites list
            websites = []
            if store.store_link:
                websites.append(store.store_link if store.store_link.startswith("http") else f"https://{store.store_link}")
            if store.domain and store.domain not in websites:
                domain_url = store.domain if store.domain.startswith("http") else f"https://{store.domain}"
                if domain_url not in websites:
                    websites.append(domain_url)

            # Build payload
            payload = {
                "messaging_product": "whatsapp"
            }

            if address:
                payload["address"] = address[:256]  # Max 256 chars
            if description:
                payload["description"] = description[:512]  # Max 512 chars
            if vertical:
                payload["vertical"] = vertical
            if store.store_email:
                payload["email"] = store.store_email[:128]  # Max 128 chars
            if websites:
                payload["websites"] = websites[:2]  # Max 2 websites

            logger.info(f"Updating WhatsApp Business Profile for phone {phone_number_id}: {payload}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{META_GRAPH_URL}/{phone_number_id}/whatsapp_business_profile",
                    params={"access_token": access_token},
                    json=payload
                )

                data = response.json()

                if "error" in data:
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    logger.error(f"Failed to update business profile: {error_msg}")
                    return False, error_msg

                logger.info(f"Successfully updated WhatsApp Business Profile for store {store.store_name}")
                return True, None

        except Exception as e:
            logger.error(f"Error updating business profile: {e}")
            return False, str(e)

    async def complete_signup(
        self,
        code: str,
        redirect_uri: str,
        waba_id: str,
        phone_number_id: str
    ) -> Tuple[Optional[WhatsAppAccount], Optional[str]]:
        """
        Complete the Embedded Signup flow.

        1. Exchange code for token
        2. Fetch phone number details
        3. Subscribe to webhooks
        4. Save WhatsApp account to database
        5. Auto-fill WhatsApp Business Profile from store data
        """
        # Step 1: Exchange code for token
        access_token, error = await self.exchange_code_for_token(code, redirect_uri)
        if error:
            return None, f"Token exchange failed: {error}"

        # Step 2: Get phone number details
        phone_numbers, error = await self.get_waba_phone_numbers(access_token, waba_id)
        if error:
            return None, f"Failed to get phone numbers: {error}"

        # Find the specific phone number
        phone_data = None
        for pn in phone_numbers:
            if pn.get("id") == phone_number_id:
                phone_data = pn
                break

        if not phone_data:
            return None, f"Phone number {phone_number_id} not found in WABA"

        # Step 3: Subscribe to webhooks
        success, error = await self.subscribe_to_webhooks(access_token, waba_id)
        if error:
            logger.warning(f"Webhook subscription failed (non-fatal): {error}")

        # Step 4: Get or create Facebook Business Account record
        fb_account = self.db.query(FacebookBusinessAccount).filter(
            FacebookBusinessAccount.business_id == waba_id
        ).first()

        if not fb_account:
            fb_account = FacebookBusinessAccount(
                business_id=waba_id,
                name=f"WABA-{waba_id}",
                access_token=access_token,
            )
            self.db.add(fb_account)
            self.db.commit()
            self.db.refresh(fb_account)

        # Step 5: Check if WhatsApp account already exists
        existing = self.db.query(WhatsAppAccount).filter(
            WhatsAppAccount.phone_number_id == phone_number_id
        ).first()

        if existing:
            # Update existing account
            existing.store_id = self.store_id
            existing.permanent_access_token = access_token
            existing.display_name = phone_data.get("verified_name")
            existing.verified_name = phone_data.get("verified_name")
            existing.quality_rating = phone_data.get("quality_rating")
            existing.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing)

            # Step 5a: Auto-fill WhatsApp Business Profile from store data
            store = self.db.query(Store).filter(Store.id == self.store_id).first()
            if store:
                profile_success, profile_error = await self.update_business_profile(
                    access_token, phone_number_id, store
                )
                if profile_error:
                    logger.warning(f"Business profile update failed (non-fatal): {profile_error}")

            logger.info(f"Updated existing WhatsApp account {phone_number_id} for store {self.store_id}")
            return existing, None

        # Step 6: Create new WhatsApp account
        whatsapp_account = WhatsAppAccount(
            business_account_id=fb_account.id,
            store_id=self.store_id,
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

        self.db.add(whatsapp_account)
        self.db.commit()
        self.db.refresh(whatsapp_account)

        # Step 7: Auto-fill WhatsApp Business Profile from store data
        store = self.db.query(Store).filter(Store.id == self.store_id).first()
        if store:
            profile_success, profile_error = await self.update_business_profile(
                access_token, phone_number_id, store
            )
            if profile_error:
                logger.warning(f"Business profile update failed (non-fatal): {profile_error}")

        logger.info(f"Created new WhatsApp account {phone_number_id} for store {self.store_id}")
        return whatsapp_account, None

    def get_store_whatsapp_accounts(self) -> list:
        """Get all WhatsApp accounts for this store"""
        return self.db.query(WhatsAppAccount).filter(
            WhatsAppAccount.store_id == self.store_id
        ).all()

    def set_default_account(self, account_id: UUID) -> Optional[WhatsAppAccount]:
        """Set a WhatsApp account as the default for this store"""
        # First, unset any existing default
        self.db.query(WhatsAppAccount).filter(
            WhatsAppAccount.store_id == self.store_id,
            WhatsAppAccount.is_default == True
        ).update({"is_default": False})

        # Set the new default
        account = self.db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id,
            WhatsAppAccount.store_id == self.store_id
        ).first()

        if account:
            account.is_default = True
            self.db.commit()
            self.db.refresh(account)

        return account

    def disconnect_account(self, account_id: UUID) -> bool:
        """Disconnect (soft delete) a WhatsApp account from this store"""
        account = self.db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id,
            WhatsAppAccount.store_id == self.store_id
        ).first()

        if account:
            account.store_id = None
            account.is_enabled = False
            account.is_default = False
            self.db.commit()
            return True

        return False

# profile_service.py
"""
Service for fetching and managing WhatsApp contact profile pictures.

Meta's WhatsApp Business API provides limited access to contact profile pictures.
This service implements:
1. Fetching profile picture from Meta Graph API (when available)
2. Fallback to generated avatars using UI Avatars
3. Caching profile pictures to avoid repeated API calls
"""

import logging
import httpx
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Cache duration for profile pictures (Meta URLs expire)
PROFILE_PICTURE_CACHE_HOURS = 24


def get_customer_name_from_contacts(contacts: list) -> Optional[str]:
    """
    Extract customer name from webhook contacts array.

    Meta webhook provides contacts like:
    [{"profile": {"name": "John Doe"}, "wa_id": "1234567890"}]

    Args:
        contacts: List of contact objects from webhook

    Returns:
        Customer name if found, None otherwise
    """
    if not contacts:
        return None

    try:
        first_contact = contacts[0]
        profile = first_contact.get("profile", {})
        name = profile.get("name")
        return name if name else None
    except (IndexError, KeyError, TypeError) as e:
        logger.warning(f"Error extracting customer name: {e}")
        return None


async def fetch_profile_picture_from_meta(
    phone_number_id: str,
    contact_wa_id: str,
    access_token: str
) -> Optional[str]:
    """
    Fetch contact's profile picture from Meta Graph API.

    Note: Meta's API has limitations on profile picture access.
    The contact must have their privacy settings configured to share.

    Args:
        phone_number_id: WhatsApp Business phone number ID
        contact_wa_id: Contact's WhatsApp ID (phone number)
        access_token: Meta API access token

    Returns:
        Profile picture URL if available, None otherwise
    """
    try:
        # Meta Graph API endpoint for contacts
        # Note: This may not always return profile pictures due to privacy settings
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/contacts"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Request contact info
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                contacts = data.get("data", [])

                for contact in contacts:
                    if contact.get("wa_id") == contact_wa_id:
                        profile_pic = contact.get("profile_picture_url")
                        if profile_pic:
                            logger.info(f"Found profile picture for {contact_wa_id}")
                            return profile_pic
            else:
                logger.debug(f"Profile picture API returned {response.status_code}")

    except Exception as e:
        logger.warning(f"Error fetching profile picture from Meta: {e}")

    return None


def generate_avatar_url(
    name: Optional[str] = None,
    phone_number: Optional[str] = None,
    size: int = 128
) -> str:
    """
    Generate a fallback avatar URL using UI Avatars service.

    Uses name initials if available, otherwise uses last 2 digits of phone number.

    Args:
        name: Customer name (optional)
        phone_number: Phone number (optional)
        size: Avatar size in pixels

    Returns:
        URL to generated avatar image
    """
    if name:
        # Use name initials
        initials = "".join(word[0].upper() for word in name.split()[:2])
        display_name = quote(name)
    elif phone_number:
        # Use last 2 digits of phone number
        clean_number = phone_number.replace("+", "").replace(" ", "")
        initials = clean_number[-2:] if len(clean_number) >= 2 else clean_number
        display_name = initials
    else:
        initials = "?"
        display_name = "Unknown"

    # Generate color based on name/number for consistency
    if name:
        color_seed = sum(ord(c) for c in name)
    elif phone_number:
        color_seed = sum(ord(c) for c in phone_number)
    else:
        color_seed = 0

    # Generate a pleasant background color
    colors = [
        "667eea", "764ba2", "f093fb", "f5576c", "4facfe",
        "00f2fe", "43e97b", "38f9d7", "fa709a", "fee140",
        "30cfd0", "c471ed", "f64f59", "12c2e9", "c471ed"
    ]
    bg_color = colors[color_seed % len(colors)]

    # UI Avatars API - free avatar generation
    avatar_url = (
        f"https://ui-avatars.com/api/"
        f"?name={display_name}"
        f"&size={size}"
        f"&background={bg_color}"
        f"&color=ffffff"
        f"&bold=true"
        f"&format=png"
    )

    return avatar_url


async def get_profile_picture(
    phone_number_id: str,
    contact_wa_id: str,
    access_token: Optional[str],
    customer_name: Optional[str] = None,
    existing_url: Optional[str] = None,
    last_updated: Optional[datetime] = None
) -> Tuple[str, bool]:
    """
    Get profile picture for a contact with caching and fallback.

    Priority:
    1. Use cached URL if still valid (less than 24 hours old)
    2. Try to fetch from Meta API
    3. Fall back to generated avatar

    Args:
        phone_number_id: WhatsApp Business phone number ID
        contact_wa_id: Contact's WhatsApp ID
        access_token: Meta API access token
        customer_name: Customer name for avatar generation
        existing_url: Previously stored URL
        last_updated: When the URL was last fetched

    Returns:
        Tuple of (profile_picture_url, is_from_meta)
    """
    # Check if cached URL is still valid
    if existing_url and last_updated:
        cache_expiry = last_updated + timedelta(hours=PROFILE_PICTURE_CACHE_HOURS)
        if datetime.utcnow() < cache_expiry:
            # Check if it's a Meta URL (not our generated avatar)
            if "graph.facebook.com" in existing_url or "lookaside.fbsbx.com" in existing_url:
                return existing_url, True
            elif "ui-avatars.com" in existing_url:
                # Regenerate avatar if name might have changed
                pass  # Fall through to regenerate
            else:
                return existing_url, True

    # Try to fetch from Meta API
    if access_token:
        meta_url = await fetch_profile_picture_from_meta(
            phone_number_id=phone_number_id,
            contact_wa_id=contact_wa_id,
            access_token=access_token
        )
        if meta_url:
            return meta_url, True

    # Fall back to generated avatar
    avatar_url = generate_avatar_url(
        name=customer_name,
        phone_number=contact_wa_id
    )
    return avatar_url, False


def should_update_profile_picture(last_updated: Optional[datetime]) -> bool:
    """
    Check if profile picture should be refreshed.

    Args:
        last_updated: When the profile picture was last updated

    Returns:
        True if should update, False otherwise
    """
    if not last_updated:
        return True

    cache_expiry = last_updated + timedelta(hours=PROFILE_PICTURE_CACHE_HOURS)
    return datetime.utcnow() >= cache_expiry

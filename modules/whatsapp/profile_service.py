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
    Generate a professional avatar URL using UI Avatars API.

    Shows:
    - Name initials if name is provided (e.g., "JD" for John Doe)
    - Last 2 digits of phone number if no name (e.g., "99")

    Args:
        name: Customer name (optional)
        phone_number: Phone number (optional)
        size: Avatar size in pixels

    Returns:
        URL to generated avatar image
    """
    # Determine what to display
    if name:
        display_name = name.strip()
    elif phone_number:
        clean_number = phone_number.replace("+", "").replace(" ", "").replace("-", "")
        # Use last 2 digits as display
        display_name = clean_number[-2:] if len(clean_number) >= 2 else clean_number
    else:
        display_name = "?"

    # Modern WhatsApp-inspired color palette
    background_colors = [
        "25D366",  # WhatsApp green
        "128C7E",  # WhatsApp teal
        "075E54",  # WhatsApp dark green
        "34B7F1",  # WhatsApp blue
        "00A884",  # WhatsApp light green
        "667eea",  # Purple blue
        "764ba2",  # Purple
        "f093fb",  # Pink
        "4facfe",  # Sky blue
        "43e97b",  # Green
        "fa709a",  # Rose
        "30cfd0",  # Cyan
        "6366f1",  # Indigo
        "8b5cf6",  # Violet
        "ec4899",  # Pink
        "14b8a6",  # Teal
        "f59e0b",  # Amber
        "ef4444",  # Red
    ]

    # Generate consistent color based on name/phone
    color_seed = sum(ord(c) for c in (name or phone_number or "unknown"))
    bg_color = background_colors[color_seed % len(background_colors)]

    # UI Avatars - shows initials (JD for John Doe, or 99 for phone ending in 99)
    avatar_url = (
        f"https://ui-avatars.com/api/"
        f"?name={quote(display_name)}"
        f"&size={size}"
        f"&background={bg_color}"
        f"&color=ffffff"
        f"&bold=true"
        f"&rounded=true"
    )

    return avatar_url


def generate_gravatar_url(
    email: Optional[str] = None,
    name: Optional[str] = None,
    phone_number: Optional[str] = None,
    size: int = 128
) -> str:
    """
    Generate Gravatar URL with DiceBear fallback.

    If user has a Gravatar account, shows their real picture.
    Otherwise falls back to DiceBear avatar.
    """
    import hashlib

    if email:
        # Generate Gravatar hash
        email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()
        # Use DiceBear as default fallback
        fallback = generate_avatar_url(name=name, phone_number=phone_number, size=size)
        fallback_encoded = quote(fallback, safe='')
        return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d={fallback_encoded}"

    # No email, use DiceBear directly
    return generate_avatar_url(name=name, phone_number=phone_number, size=size)


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
            elif "ui-avatars.com" in existing_url or "dicebear.com" in existing_url:
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

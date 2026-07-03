# consent.py
"""
WhatsApp marketing consent & suppression helpers.

Meta's WhatsApp Business Messaging Policy requires:
  1. Opt-in before sending marketing (template) messages.
  2. Honoring opt-out requests ("STOP") immediately and permanently.

These helpers are the single source of truth for both rules. Every outbound
send path (bulk, template, text) must consult them before messaging.
"""
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .models import WhatsAppLead

logger = logging.getLogger(__name__)

# Keywords that constitute an opt-out request. Matched case-insensitively as
# whole words against inbound message text.
OPT_OUT_PATTERN = re.compile(
    r"^\s*(stop|unsubscribe|opt[\s-]?out|cancel|quit|stop all)\s*[.!]*\s*$",
    re.IGNORECASE,
)

# Keywords that re-establish opt-in after a previous opt-out.
OPT_IN_PATTERN = re.compile(
    r"^\s*(start|subscribe|opt[\s-]?in|unstop)\s*[.!]*\s*$",
    re.IGNORECASE,
)

OPT_OUT_CONFIRMATION = (
    "You have been unsubscribed and will no longer receive marketing messages "
    "from us. Reply START at any time to subscribe again."
)

OPT_IN_CONFIRMATION = (
    "You're subscribed again. Reply STOP at any time to unsubscribe."
)


def clean_phone(phone_number: str) -> str:
    """Normalize a phone number the same way the send paths do."""
    return phone_number.replace(" ", "").replace("+", "").strip()


def is_opt_out_message(text: Optional[str]) -> bool:
    return bool(text) and bool(OPT_OUT_PATTERN.match(text))


def is_opt_in_message(text: Optional[str]) -> bool:
    return bool(text) and bool(OPT_IN_PATTERN.match(text))


def get_or_create_lead(
    db: Session, whatsapp_account_id: uuid.UUID, phone_number: str
) -> WhatsAppLead:
    phone = clean_phone(phone_number)
    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.whatsapp_account_id == whatsapp_account_id,
        WhatsAppLead.phone_number == phone,
    ).first()
    if not lead:
        lead = WhatsAppLead(
            whatsapp_account_id=whatsapp_account_id,
            phone_number=phone,
            lead_score=0,
            lead_status="new",
        )
        db.add(lead)
        db.flush()
    return lead


def record_opt_out(
    db: Session, whatsapp_account_id: uuid.UUID, phone_number: str
) -> WhatsAppLead:
    """Permanently suppress a number for this WhatsApp account."""
    lead = get_or_create_lead(db, whatsapp_account_id, phone_number)
    lead.marketing_opt_in = False
    lead.opted_out_at = datetime.utcnow()
    db.commit()
    logger.info(
        f"Opt-out recorded for {lead.phone_number} on account {whatsapp_account_id}"
    )
    return lead


def record_opt_in(
    db: Session,
    whatsapp_account_id: uuid.UUID,
    phone_number: str,
    source: str,
) -> WhatsAppLead:
    """Record explicit marketing opt-in (clears any prior opt-out)."""
    lead = get_or_create_lead(db, whatsapp_account_id, phone_number)
    lead.marketing_opt_in = True
    lead.opt_in_source = source
    lead.opt_in_at = datetime.utcnow()
    lead.opted_out_at = None
    db.commit()
    logger.info(
        f"Opt-in ({source}) recorded for {lead.phone_number} on account {whatsapp_account_id}"
    )
    return lead


def is_suppressed(
    db: Session, whatsapp_account_id: uuid.UUID, phone_number: str
) -> bool:
    """True if the number opted out — NO outbound message may be sent."""
    phone = clean_phone(phone_number)
    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.whatsapp_account_id == whatsapp_account_id,
        WhatsAppLead.phone_number == phone,
    ).first()
    return bool(lead and lead.opted_out_at is not None)


def has_marketing_opt_in(
    db: Session, whatsapp_account_id: uuid.UUID, phone_number: str
) -> bool:
    """True only if the number explicitly opted in and has not opted out."""
    phone = clean_phone(phone_number)
    lead = db.query(WhatsAppLead).filter(
        WhatsAppLead.whatsapp_account_id == whatsapp_account_id,
        WhatsAppLead.phone_number == phone,
    ).first()
    return bool(lead and lead.marketing_opt_in and lead.opted_out_at is None)

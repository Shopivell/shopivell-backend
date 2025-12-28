"""
Store Router - Multi-Store Routing for Shared WhatsApp Numbers

This service routes incoming WhatsApp messages to the correct store
when using a single WhatsApp number for multiple stores.

Routing Priority:
1. Click-to-WhatsApp Ad referral data (highest priority)
2. Previous conversation context (if customer chatted before)
3. User selection (ask customer which store they're contacting)
4. Default store (fallback)
"""

import logging
from typing import Optional, Dict, Any, List, Tuple
from uuid import UUID
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import desc

from .models import (
    WhatsAppAccount, WhatsAppConversation, WhatsAppMessage,
    AdCampaign
)

logger = logging.getLogger(__name__)


class StoreRouter:
    """
    Routes WhatsApp messages to the correct store based on context.
    """

    def __init__(self, whatsapp_account_id: UUID, db: Session):
        self.whatsapp_account_id = whatsapp_account_id
        self.db = db
        self.whatsapp_account = self._get_account()

    def _get_account(self) -> WhatsAppAccount:
        """Get the WhatsApp account"""
        account = self.db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == self.whatsapp_account_id
        ).first()
        if not account:
            raise ValueError(f"WhatsApp account not found: {self.whatsapp_account_id}")
        return account

    def route_message(
        self,
        phone_number: str,
        message_data: Dict[str, Any]
    ) -> Tuple[Optional[UUID], str, Optional[WhatsAppConversation]]:
        """
        Route an incoming message to the correct store.

        Args:
            phone_number: Customer's phone number (cleaned)
            message_data: Raw message data from webhook (contains referral info)

        Returns:
            Tuple of (store_id, routing_method, conversation)
            - store_id: The store to route to (None if needs selection)
            - routing_method: How routing was determined
            - conversation: The conversation object (created or existing)
        """
        logger.info(f"Routing message from {phone_number}")

        # 1. Check for Click-to-WhatsApp referral data
        referral_data = self._extract_referral_data(message_data)
        if referral_data:
            store_id, campaign = self._route_by_referral(referral_data)
            if store_id:
                logger.info(f"Routed via ad campaign to store {store_id}")
                conversation = self._get_or_create_conversation(
                    phone_number=phone_number,
                    store_id=store_id,
                    routing_status="routed",
                    routed_via="ad_campaign",
                    campaign_id=campaign.id if campaign else None,
                    referral_data=referral_data
                )
                return store_id, "ad_campaign", conversation

        # 2. Check for existing conversation with this phone number
        existing_conversation = self._get_existing_conversation(phone_number)
        if existing_conversation and existing_conversation.store_id:
            logger.info(f"Routed via previous conversation to store {existing_conversation.store_id}")
            # Update last message time
            existing_conversation.last_message_at = datetime.utcnow()
            self.db.commit()
            return existing_conversation.store_id, "previous_conversation", existing_conversation

        # 3. Check if WhatsApp account has a default store
        if self.whatsapp_account.store_id:
            logger.info(f"Routed via default store {self.whatsapp_account.store_id}")
            conversation = self._get_or_create_conversation(
                phone_number=phone_number,
                store_id=self.whatsapp_account.store_id,
                routing_status="routed",
                routed_via="default"
            )
            return self.whatsapp_account.store_id, "default", conversation

        # 4. No routing found - need to ask user
        logger.info(f"No routing found for {phone_number}, needs store selection")
        conversation = self._get_or_create_conversation(
            phone_number=phone_number,
            store_id=None,
            routing_status="awaiting_selection",
            routed_via=None
        )
        return None, "needs_selection", conversation

    def _extract_referral_data(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract Click-to-WhatsApp referral data from message.

        Meta sends referral data in the message context when customer
        clicks a Click-to-WhatsApp ad.
        """
        # Check for referral in message context
        context = message_data.get("context", {})
        referral = context.get("referred_product", {}) or context.get("referral", {})

        if referral:
            return {
                "source_url": referral.get("source_url"),
                "source_type": referral.get("source_type"),
                "source_id": referral.get("source_id"),
                "headline": referral.get("headline"),
                "body": referral.get("body"),
                "ctwa_clid": referral.get("ctwa_clid"),  # Click-to-WhatsApp Click ID
                "media_type": referral.get("media_type"),
                "raw": referral
            }

        # Also check for referral at message level (some webhook formats)
        if "referral" in message_data:
            ref = message_data["referral"]
            return {
                "source_url": ref.get("source_url"),
                "source_type": ref.get("source_type"),
                "source_id": ref.get("source_id"),
                "headline": ref.get("headline"),
                "body": ref.get("body"),
                "ctwa_clid": ref.get("ctwa_clid"),
                "raw": ref
            }

        return None

    def _route_by_referral(self, referral_data: Dict[str, Any]) -> Tuple[Optional[UUID], Optional[AdCampaign]]:
        """
        Find store based on referral data from Click-to-WhatsApp ad.
        """
        # Try to match by ctwa_clid (most specific)
        ctwa_clid = referral_data.get("ctwa_clid")
        if ctwa_clid:
            campaign = self.db.query(AdCampaign).filter(
                AdCampaign.ctwa_clid == ctwa_clid,
                AdCampaign.whatsapp_account_id == self.whatsapp_account_id,
                AdCampaign.is_active == True
            ).first()
            if campaign:
                campaign.click_count += 1
                self.db.commit()
                return campaign.store_id, campaign

        # Try to match by source_id (ad ID or campaign ID)
        source_id = referral_data.get("source_id")
        if source_id:
            campaign = self.db.query(AdCampaign).filter(
                (AdCampaign.ad_id == source_id) | (AdCampaign.campaign_id == source_id),
                AdCampaign.whatsapp_account_id == self.whatsapp_account_id,
                AdCampaign.is_active == True
            ).first()
            if campaign:
                campaign.click_count += 1
                self.db.commit()
                return campaign.store_id, campaign

        # Try to match by source_url (might contain custom ref)
        source_url = referral_data.get("source_url", "")
        if source_url:
            # Extract custom ref from URL if present
            # Example: https://wa.me/123?text=ref_STORE123
            import re
            ref_match = re.search(r'ref[_=]([A-Za-z0-9_-]+)', source_url)
            if ref_match:
                custom_ref = ref_match.group(1)
                campaign = self.db.query(AdCampaign).filter(
                    AdCampaign.custom_ref == custom_ref,
                    AdCampaign.whatsapp_account_id == self.whatsapp_account_id,
                    AdCampaign.is_active == True
                ).first()
                if campaign:
                    campaign.click_count += 1
                    self.db.commit()
                    return campaign.store_id, campaign

        return None, None

    def _get_existing_conversation(self, phone_number: str) -> Optional[WhatsAppConversation]:
        """
        Get existing routed conversation for this phone number.
        Only returns conversations that have been successfully routed.
        """
        return self.db.query(WhatsAppConversation).filter(
            WhatsAppConversation.whatsapp_account_id == self.whatsapp_account_id,
            WhatsAppConversation.phone_number == phone_number,
            WhatsAppConversation.routing_status == "routed",
            WhatsAppConversation.store_id.isnot(None)
        ).order_by(desc(WhatsAppConversation.updated_at)).first()

    def _get_or_create_conversation(
        self,
        phone_number: str,
        store_id: Optional[UUID],
        routing_status: str,
        routed_via: Optional[str],
        campaign_id: Optional[UUID] = None,
        referral_data: Optional[Dict[str, Any]] = None
    ) -> WhatsAppConversation:
        """
        Get or create a conversation record.
        """
        # Look for existing conversation (any status)
        conversation = self.db.query(WhatsAppConversation).filter(
            WhatsAppConversation.whatsapp_account_id == self.whatsapp_account_id,
            WhatsAppConversation.phone_number == phone_number
        ).order_by(desc(WhatsAppConversation.updated_at)).first()

        if conversation:
            # Update existing conversation
            if store_id:
                conversation.store_id = store_id
            conversation.routing_status = routing_status
            conversation.routed_via = routed_via
            if campaign_id:
                conversation.campaign_id = campaign_id
            if referral_data:
                conversation.referral_data = referral_data
            conversation.last_message_at = datetime.utcnow()
            self.db.commit()
            return conversation

        # Create new conversation
        conversation = WhatsAppConversation(
            whatsapp_account_id=self.whatsapp_account_id,
            phone_number=phone_number,
            store_id=store_id,
            routing_status=routing_status,
            routed_via=routed_via,
            campaign_id=campaign_id,
            referral_data=referral_data,
            last_message_at=datetime.utcnow()
        )
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)

        # Update campaign conversation count
        if campaign_id:
            campaign = self.db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
            if campaign:
                campaign.conversation_count += 1
                self.db.commit()

        return conversation

    def route_to_store(
        self,
        phone_number: str,
        store_id: UUID,
        method: str = "user_selection"
    ) -> WhatsAppConversation:
        """
        Manually route a conversation to a specific store.
        Used when customer selects a store from the menu.
        """
        conversation = self._get_or_create_conversation(
            phone_number=phone_number,
            store_id=store_id,
            routing_status="routed",
            routed_via=method
        )
        logger.info(f"Manually routed {phone_number} to store {store_id} via {method}")
        return conversation

    def get_available_stores(self) -> List[Dict[str, Any]]:
        """
        Get all stores that have campaigns linked to this WhatsApp account.
        Used for building the store selection menu.
        """
        from modules.stores.models import Store

        # Get stores with active campaigns for this WhatsApp account
        campaigns = self.db.query(AdCampaign).filter(
            AdCampaign.whatsapp_account_id == self.whatsapp_account_id,
            AdCampaign.is_active == True
        ).all()

        store_ids = set(c.store_id for c in campaigns)

        # Also include the default store if set
        if self.whatsapp_account.store_id:
            store_ids.add(self.whatsapp_account.store_id)

        if not store_ids:
            return []

        stores = self.db.query(Store).filter(Store.id.in_(store_ids)).all()

        return [
            {
                "id": str(store.id),
                "name": store.store_name,
                "category": getattr(store, 'store_category', None),
                "description": getattr(store, 'store_description', None)
            }
            for store in stores
        ]

    def build_store_selection_message(self) -> Optional[str]:
        """
        Build a message asking customer to select a store.
        Returns None if only one store is available.
        """
        stores = self.get_available_stores()

        if not stores:
            return None

        if len(stores) == 1:
            # Auto-route to the only available store
            return None

        # Build selection message
        message = "Welcome! Which store would you like to contact?\n\n"
        for i, store in enumerate(stores, 1):
            name = store['name']
            category = store.get('category', '')
            message += f"{i}. {name}"
            if category:
                message += f" ({category})"
            message += "\n"

        message += "\nPlease reply with the number of your choice."
        return message

    def parse_store_selection(self, message_text: str) -> Optional[UUID]:
        """
        Parse customer's store selection from their reply.
        Returns store_id if valid selection, None otherwise.
        """
        stores = self.get_available_stores()
        if not stores:
            return None

        # Try to parse as number
        try:
            selection = int(message_text.strip())
            if 1 <= selection <= len(stores):
                return UUID(stores[selection - 1]['id'])
        except ValueError:
            pass

        # Try to match by store name (partial match)
        message_lower = message_text.lower().strip()
        for store in stores:
            if message_lower in store['name'].lower():
                return UUID(store['id'])

        return None

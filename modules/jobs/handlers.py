"""
Background job handlers. Imported by the worker at startup so the @handler
decorators register. Keep heavy imports inside the functions so importing this
module stays cheap.
"""

import logging
from uuid import UUID

from database import SessionLocal
from modules.jobs.queue import handler

logger = logging.getLogger(__name__)


@handler('poll_whatsapp_payment')
def poll_whatsapp_payment(payload: dict) -> dict:
    """Poll accepted mobile payments until a verified final result is known."""
    from modules.jobs.queue import enqueue
    from modules.whatsapp.models import WhatsAppOrder
    from modules.whatsapp.payment_service import WhatsAppPaymentService
    db = SessionLocal()
    try:
        order = db.query(WhatsAppOrder).filter(WhatsAppOrder.id == UUID(str(payload['order_id']))).first()
        if not order:
            return {'status': 'not_found'}
        if order.payment_status in ('paid', 'completed', 'failed', 'cancelled', 'refunded'):
            return {'status': order.payment_status}
        result = WhatsAppPaymentService(db).check_payment_status(str(order.id))
        outcome = result.get('status')
        if outcome in ('processing', 'unavailable', 'error', None):
            raise RuntimeError('Payment is still pending or the provider could not be checked')
        if outcome in ('paid', 'failed', 'cancelled', 'refunded'):
            if not enqueue('notify_whatsapp_payment', {'order_id': str(order.id), 'status': outcome}, max_attempts=8):
                raise RuntimeError('Could not schedule payment notification')
        return {'status': outcome}
    finally:
        db.close()


@handler('notify_whatsapp_payment')
async def notify_whatsapp_payment(payload: dict) -> dict:
    """Deliver a verified payment result; the job worker retries failures."""
    from modules.whatsapp.models import WhatsAppOrder
    from modules.whatsapp.router import _notify_payment_result
    db = SessionLocal()
    try:
        order = db.query(WhatsAppOrder).filter(WhatsAppOrder.id == UUID(str(payload['order_id']))).first()
        if not order or order.payment_status != payload.get('status'):
            return {'status': 'superseded'}
        await _notify_payment_result(db, order, payload['status'])
        return {'status': 'sent'}
    finally:
        db.close()


@handler("sync_store_knowledge")
def sync_store_knowledge(payload: dict) -> dict:
    """Embed a store's FAQs (and optionally products) into the knowledge base.
    Runs off the request path with retry, so the WhatsApp bot's knowledge stays
    in sync even if an embedding call transiently fails.

    payload:
      {"store_id": "<uuid>"}                    -> sync all active FAQs
      {"store_id": "<uuid>", "faq_id": "<uuid>"} -> sync just that FAQ
      {"store_id": "<uuid>", "include_products": true} -> also sync products
    """
    store_id = payload.get("store_id")
    if not store_id:
        return {"error": "missing store_id"}

    from modules.whatsapp.knowledge_service import KnowledgeService
    from modules.whatsapp.models import FAQ

    db = SessionLocal()
    try:
        ks = KnowledgeService(UUID(str(store_id)))

        # Single-FAQ sync (from FAQ create/update) — avoids re-embedding the
        # whole store on every edit.
        faq_id = payload.get("faq_id")
        if faq_id:
            faq = db.query(FAQ).filter(FAQ.id == UUID(str(faq_id))).first()
            if faq and faq.is_active:
                ks.sync_faq_to_knowledge(db, faq)
                return {"store_id": str(store_id), "faq_synced": str(faq_id)}
            return {"store_id": str(store_id), "skipped": "faq missing or inactive"}

        faqs = ks.sync_all_faqs_to_knowledge(db)
        products = 0
        if payload.get("include_products"):
            products = ks.sync_products_to_knowledge(db)
        logger.info(f"[jobs] sync_store_knowledge store={store_id} faqs={faqs} products={products}")
        return {"store_id": str(store_id), "faqs_synced": faqs, "products_synced": products}
    finally:
        db.close()


@handler("generate_campaign_images")
def generate_campaign_images(payload: dict) -> dict:
    """Generate the ad image(s) for a saved campaign off the creation path.

    Image generation takes ~60s per image, which held campaign creation at ~3-5
    minutes; the campaign now completes immediately and its images appear shortly
    after. Retried by the worker if the image model is briefly unavailable.

    payload: {"campaign_id": "<uuid>"}
    """
    campaign_id = payload.get("campaign_id")
    if not campaign_id:
        return {"error": "missing campaign_id"}

    import all_models  # noqa: F401  (register every ORM mapper for this worker thread)
    from modules.campaigns.models import UrlCampaign
    from modules.campaigns.service import CampaignService

    db = SessionLocal()
    try:
        campaign = db.query(UrlCampaign).filter(UrlCampaign.id == UUID(str(campaign_id))).first()
        if not campaign:
            return {"error": f"campaign {campaign_id} not found"}
        created = CampaignService(db).generate_campaign_images(campaign)
        return {"campaign_id": str(campaign_id), "images": created}
    finally:
        db.close()

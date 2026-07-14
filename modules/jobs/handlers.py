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

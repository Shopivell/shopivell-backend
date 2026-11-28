# modules/storefront/router.py
"""Public storefront API.

These endpoints serve the shopper-facing storefront (storefront.shopivell.com
and /store/<store_id> links) and therefore require no authentication. They only
expose published data: stores whose setup is complete and products whose status
is Active.
"""
from typing import Any, Dict, List, Optional
import uuid
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from modules.products.models import Product
from modules.stores.models import Store

storefront_router = APIRouter(prefix="/api/storefront", tags=["storefront"])
logger = logging.getLogger(__name__)

ACTIVE_PRODUCT_STATUS = "Active"


class StorefrontChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=3000)
    sender_email: Optional[EmailStr] = None


def _email_storefront_chat(recipient: str, store_name: str, sender_email: Optional[str], message: str, reply: str) -> None:
    from utils.Verification_Codes_Services import VerificationCodeService
    text = (
        f"Store: {store_name}\n"
        f"Shopper email: {sender_email or 'Not provided'}\n\n"
        f"Shopper message:\n{message}\n\n"
        f"Shopivell assistant reply:\n{reply}"
    )
    if not VerificationCodeService.send_email(recipient, f"New storefront chat: {store_name}", text):
        logger.warning("Storefront chat email notification to %s was not delivered", recipient)


def _store_payload(store: Store, product_count: Optional[int] = None) -> Dict[str, Any]:
    enabled_features = store.enabled_features or {}
    saved_design = enabled_features.get("design_config") or {}
    saved_appearance = saved_design.get("appearance") or {}
    secondary_colors = store.secondary_colors if isinstance(store.secondary_colors, list) else []
    primary = store.color_theme or "#111827"
    # The Design tab is the preferred source. Store-level brand fields are the
    # canonical fallback so older stores never render as an unrelated generic brand.
    appearance = {
        "template": "modern",
        "primaryColor": primary,
        "secondaryColor": secondary_colors[0] if secondary_colors else "#1F2937",
        "accentColor": secondary_colors[1] if len(secondary_colors) > 1 else primary,
        "fontFamily": store.font_heading or store.font_body or "Inter",
        "logoUrl": store.logo_url or "",
        "bannerUrl": store.banner_url or "",
        "borderRadius": "md",
        **saved_appearance,
    }
    # Empty Design values should not erase existing store branding.
    appearance["primaryColor"] = appearance.get("primaryColor") or primary
    appearance["logoUrl"] = appearance.get("logoUrl") or store.logo_url or ""
    appearance["bannerUrl"] = appearance.get("bannerUrl") or store.banner_url or ""
    appearance["fontFamily"] = appearance.get("fontFamily") or store.font_heading or store.font_body or "Inter"
    design_config = {
        **saved_design,
        "storefrontCards": saved_design.get("storefrontCards") or [],
        "appearance": appearance,
        "settings": saved_design.get("settings") or {},
    }
    return {
        "id": str(store.id),
        "name": store.store_name,
        "description": store.store_description or store.brand_description,
        "logo_url": store.logo_url,
        "banner_url": store.banner_url,
        "phone": store.store_phone,
        "email": store.store_email,
        "address": store.store_address,
        "city": store.store_city,
        "country": store.store_country,
        "category": store.store_category or store.business_type,
        "currency": store.currency or "USD",
        "color_theme": store.color_theme,
        "design": design_config,
        "delivery_enabled": bool(store.delivery_enabled),
        "pickup_enabled": bool(store.pickup_enabled),
        "delivery_fee": store.delivery_fee,
        "product_count": product_count if product_count is not None else 0,
    }


def _in_stock(product: Product) -> bool:
    if product.in_stock is not None:
        return bool(product.in_stock)
    if not product.inventory_tracked:
        return True
    return (product.available or 0) > 0


def _product_payload(product: Product, currency: str) -> Dict[str, Any]:
    return {
        "id": str(product.id),
        "title": product.title,
        "description": product.description,
        "category": product.category,
        "price": product.price,
        "currency": currency,
        "image_url": product.image_url,
        "in_stock": _in_stock(product),
        "tags": [t.strip() for t in (product.tags or "").split(",") if t.strip()],
    }


def _get_store_or_404(db: Session, store_id: uuid.UUID) -> Store:
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    return store


def _active_product_count(db: Session, store_id: uuid.UUID) -> int:
    return (
        db.query(func.count(Product.id))
        .filter(Product.store_id == store_id, Product.status == ACTIVE_PRODUCT_STATUS)
        .scalar()
        or 0
    )


@storefront_router.get("/stores")
async def list_stores(
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Store directory: completed stores that have at least one Active product."""
    counts = (
        db.query(Product.store_id, func.count(Product.id).label("product_count"))
        .filter(Product.status == ACTIVE_PRODUCT_STATUS)
        .group_by(Product.store_id)
        .subquery()
    )

    query = (
        db.query(Store, counts.c.product_count)
        .join(counts, counts.c.store_id == Store.id)
        .filter(Store.is_setup_completed.is_(True))
    )
    if search:
        like = f"%{search}%"
        query = query.filter(
            Store.store_name.ilike(like)
            | Store.store_city.ilike(like)
            | Store.store_category.ilike(like)
            | Store.business_type.ilike(like)
        )

    total = query.count()
    rows = (
        query.order_by(counts.c.product_count.desc(), Store.store_name.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "stores": [_store_payload(store, count) for store, count in rows],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@storefront_router.get("/stores/{store_id}")
async def get_store(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """Public store profile: branding and contact details."""
    store = _get_store_or_404(db, store_id)
    return _store_payload(store, _active_product_count(db, store.id))


@storefront_router.post("/stores/{store_id}/chat")
async def chat_with_store_assistant(
    store_id: uuid.UUID,
    body: StorefrontChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Answer a shopper using the store's sales bot and email the store the enquiry."""
    store = _get_store_or_404(db, store_id)
    if not store.is_setup_completed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enter a message")

    reply = None
    try:
        from modules.whatsapp.chatbot_engine import MultiTenantSalesBot
        bot = MultiTenantSalesBot(store_id=store.id, db=db)
        reply = await bot.generate_response(message, f"storefront:{body.conversation_id}")
    except Exception:
        logger.exception("Storefront assistant failed for store %s", store.id)
    if not reply:
        reply = f"Thanks for contacting {store.store_name}. I’ve sent your message to the store team so they can follow up."

    recipient = store.store_email or (store.owner.email if store.owner else None)
    if recipient:
        background_tasks.add_task(
            _email_storefront_chat,
            recipient,
            store.store_name,
            str(body.sender_email) if body.sender_email else None,
            message,
            reply,
        )
    return {"reply": reply, "email_notified": bool(recipient)}


@storefront_router.get("/stores/{store_id}/products")
async def list_store_products(
    store_id: uuid.UUID,
    search: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Product catalogue for one store (Active products only)."""
    store = _get_store_or_404(db, store_id)
    currency = store.currency or "USD"

    query = db.query(Product).filter(
        Product.store_id == store.id,
        Product.status == ACTIVE_PRODUCT_STATUS,
    )
    if category:
        query = query.filter(Product.category == category)
    if search:
        like = f"%{search}%"
        query = query.filter(Product.title.ilike(like) | Product.description.ilike(like))

    total = query.count()
    products = (
        query.order_by(Product.created_at.asc(), Product.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    categories: List[str] = [
        row[0]
        for row in db.query(Product.category)
        .filter(
            Product.store_id == store.id,
            Product.status == ACTIVE_PRODUCT_STATUS,
            Product.category.isnot(None),
        )
        .distinct()
        .order_by(Product.category.asc())
        .all()
        if row[0]
    ]

    return {
        "store": _store_payload(store, total),
        "products": [_product_payload(product, currency) for product in products],
        "categories": categories,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@storefront_router.get("/stores/{store_id}/products/{product_id}")
async def get_store_product(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """One public product page."""
    store = _get_store_or_404(db, store_id)
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.store_id == store.id,
            Product.status == ACTIVE_PRODUCT_STATUS,
        )
        .first()
    )
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    return {
        "store": _store_payload(store, _active_product_count(db, store.id)),
        "product": _product_payload(product, store.currency or "USD"),
    }

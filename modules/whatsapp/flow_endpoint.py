"""
WhatsApp Flows Data Endpoint.

Meta calls this endpoint during flow execution to get/send dynamic data.
All communication is encrypted (RSA + AES-128-GCM).

Actions:
  ping           → health check
  INIT           → first screen data (product list)
  data_exchange  → screen-to-screen navigation
  BACK           → back navigation refresh
"""

import json
import logging
import uuid as uuid_mod
from typing import Dict, Any, Optional
from uuid import UUID

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from modules.products.models import Product
from modules.stores.models import Store
from .flow_crypto import decrypt_request, encrypt_response, get_private_key_pem
from .flow_token import encode_flow_token, decode_flow_token
from .models import WhatsAppFlow, WhatsAppAccount

logger = logging.getLogger(__name__)

flow_router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp-flows"])


@flow_router.post("/flow-endpoint")
async def flow_data_endpoint(request: Request):
    """
    WhatsApp Flows encrypted data endpoint.

    Receives encrypted POST, processes action, returns encrypted response.
    """
    body = await request.json()

    # Decrypt
    try:
        private_key_pem = get_private_key_pem()
        payload, aes_key, iv = decrypt_request(body, private_key_pem)
    except Exception as e:
        logger.error(f"Flow decrypt error: {e}")
        return Response(status_code=500)

    action = payload.get("action", "")
    logger.info(f"Flow endpoint action={action}")

    db = SessionLocal()
    try:
        if action == "ping":
            response_data = {"data": {"status": "active"}}
        elif action == "INIT":
            response_data = _handle_init(payload, db)
        elif action == "data_exchange":
            response_data = _handle_data_exchange(payload, db)
        elif action == "BACK":
            response_data = _handle_back(payload, db)
        else:
            response_data = {"data": {"status": "active"}}

        encrypted = encrypt_response(response_data, aes_key, iv)
        return Response(content=encrypted, media_type="text/plain")

    except Exception as e:
        logger.error(f"Flow endpoint error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Return a generic error screen
        error_resp = {
            "screen": "PRODUCT_BROWSE",
            "data": {
                "products": [],
                "categories": [],
                "store_name": "Store",
                "cart_summary": "Something went wrong. Please try again.",
            },
        }
        encrypted = encrypt_response(error_resp, aes_key, iv)
        return Response(content=encrypted, media_type="text/plain")
    finally:
        db.close()


# ── Action handlers ───────────────────────────────────────


def _handle_init(payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """First screen — load products for the store."""
    flow_token = payload.get("flow_token", "")
    token_data = decode_flow_token(flow_token)
    store_id = token_data["store_id"]

    if token_data.get("purpose") == "delivery_address":
        return {"screen": "DELIVERY_ADDRESS", "data": {}}

    products, store_name = _get_products_and_store(db, store_id)
    categories = _get_categories(products)

    product_options = [
        {"id": str(p.id), "title": f"{p.title[:20]} - ${p.price:.0f}"}
        for p in products[:20]
    ]
    category_options = [{"id": c, "title": c} for c in categories[:10]]

    return {
        "screen": "PRODUCT_BROWSE",
        "data": {
            "products": product_options,
            "categories": category_options,
            "store_name": store_name,
            "cart_summary": "Your cart is empty",
        },
    }


def _handle_data_exchange(
    payload: Dict[str, Any], db: Session
) -> Dict[str, Any]:
    """Handle navigation between screens."""
    flow_token = payload.get("flow_token", "")
    token_data = decode_flow_token(flow_token)
    store_id = token_data["store_id"]
    if token_data.get("purpose") == "delivery_address":
        return {"screen": "DELIVERY_ADDRESS", "data": {}}

    data = payload.get("data", {})
    action_type = data.get("action_type", "")

    # Cart is passed in the flow data between screens
    cart = data.get("_cart", [])

    if action_type == "filter_category":
        return _action_filter_category(db, store_id, data, cart)
    elif action_type == "select_product":
        return _action_select_product(db, store_id, data, cart)
    elif action_type == "add_to_cart":
        return _action_add_to_cart(db, store_id, data, cart)
    elif action_type == "cart_action":
        return _action_cart_action(db, store_id, data, cart)
    elif action_type == "submit_delivery":
        return _action_submit_delivery(db, store_id, data, cart)
    elif action_type == "submit_payment":
        return _action_submit_payment(db, store_id, data, cart)
    else:
        # Unknown action — go back to browse
        return _handle_init(payload, db)


def _handle_back(payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """Handle back navigation — re-serve the previous screen data."""
    screen = payload.get("screen", "PRODUCT_BROWSE")
    flow_token = payload.get("flow_token", "")
    token_data = decode_flow_token(flow_token)
    store_id = token_data["store_id"]
    data = payload.get("data", {})
    cart = data.get("_cart", [])

    if screen == "PRODUCT_DETAIL":
        return _build_browse_response(db, store_id, cart)
    elif screen == "CART_REVIEW":
        return _build_browse_response(db, store_id, cart)
    elif screen == "DELIVERY_INFO":
        return _build_cart_review_response(cart)
    elif screen == "PAYMENT_METHOD":
        return _go_to_delivery(cart)
    elif screen == "ORDER_SUMMARY":
        return _go_to_payment(cart, data)
    else:
        return _build_browse_response(db, store_id, cart)


# ── Action implementations ────────────────────────────────


def _action_filter_category(
    db: Session, store_id: str, data: dict, cart: list
) -> Dict[str, Any]:
    """Filter products by category."""
    category = data.get("category")
    products, store_name = _get_products_and_store(db, store_id, category)
    categories = _get_categories_from_db(db, store_id)

    product_options = [
        {"id": str(p.id), "title": f"{p.title[:20]} - ${p.price:.0f}"}
        for p in products[:20]
    ]
    category_options = [{"id": c, "title": c} for c in categories[:10]]

    return {
        "screen": "PRODUCT_BROWSE",
        "data": {
            "products": product_options,
            "categories": category_options,
            "store_name": store_name,
            "cart_summary": _cart_summary_text(cart),
        },
    }


def _action_select_product(
    db: Session, store_id: str, data: dict, cart: list
) -> Dict[str, Any]:
    """User selected a product — show detail screen."""
    product_id = data.get("product_id")
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.store_id == store_id,
    ).first()

    if not product:
        return _build_browse_response(db, store_id, cart)

    description = (product.description or "No description available")[:300]

    return {
        "screen": "PRODUCT_DETAIL",
        "data": {
            "product_name": product.title,
            "product_price": f"${product.price:.2f}",
            "product_description": description,
            "product_id": str(product.id),
            "_cart": cart,
        },
    }


def _action_add_to_cart(
    db: Session, store_id: str, data: dict, cart: list
) -> Dict[str, Any]:
    """Add product to cart and show cart review."""
    product_id = data.get("product_id")
    quantity_str = data.get("quantity", "1")

    try:
        quantity = max(1, min(99, int(quantity_str)))
    except (ValueError, TypeError):
        quantity = 1

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return _build_browse_response(db, store_id, cart)

    # Check if product already in cart — update quantity
    existing = next((i for i in cart if i["id"] == str(product.id)), None)
    if existing:
        existing["qty"] += quantity
    else:
        cart.append({
            "id": str(product.id),
            "title": product.title,
            "price": float(product.price),
            "qty": quantity,
        })

    return _build_cart_review_response(cart)


def _action_cart_action(
    db: Session, store_id: str, data: dict, cart: list
) -> Dict[str, Any]:
    """Handle cart review action: checkout, add_more, clear."""
    action = data.get("cart_action", "")

    if action == "clear":
        return _build_cart_review_response([])
    elif action == "add_more":
        return _build_browse_response(db, store_id, cart)
    elif action == "checkout":
        if not cart:
            return _build_cart_review_response(cart)
        return _go_to_delivery(cart)
    else:
        return _build_cart_review_response(cart)


def _action_submit_delivery(
    db: Session, store_id: str, data: dict, cart: list
) -> Dict[str, Any]:
    """Delivery info submitted — go to payment."""
    # Pass delivery info along in data
    delivery_data = {
        "delivery_method": data.get("delivery_method", "delivery"),
        "customer_name": data.get("customer_name", ""),
        "phone": data.get("phone", ""),
        "address": data.get("address", ""),
    }

    total = sum(item["price"] * item["qty"] for item in cart)

    return {
        "screen": "PAYMENT_METHOD",
        "data": {
            "cart_total": f"Total: ${total:.2f}",
            "payment_options": [
                {"id": "ecocash", "title": "EcoCash"},
                {"id": "pay_on_delivery", "title": "Pay on Delivery"},
            ],
            "_cart": cart,
            "_delivery": delivery_data,
        },
    }


def _action_submit_payment(
    db: Session, store_id: str, data: dict, cart: list
) -> Dict[str, Any]:
    """Payment method submitted — show order summary for final confirmation."""
    delivery_data = data.get("_delivery", {})
    payment_method = data.get("payment_method", "pay_on_delivery")
    ecocash_number = data.get("ecocash_number", "")

    # Build summary text
    lines = ["Items:"]
    total = 0.0
    for item in cart:
        line_total = item["price"] * item["qty"]
        total += line_total
        lines.append(f"  {item['title']} x{item['qty']} — ${line_total:.2f}")

    lines.append("")
    lines.append(f"Delivery: {delivery_data.get('delivery_method', 'N/A')}")
    if delivery_data.get("address"):
        lines.append(f"Address: {delivery_data['address']}")
    lines.append(f"Name: {delivery_data.get('customer_name', 'N/A')}")
    lines.append(f"Phone: {delivery_data.get('phone', 'N/A')}")
    lines.append("")
    pm_label = "EcoCash" if payment_method == "ecocash" else "Pay on Delivery"
    lines.append(f"Payment: {pm_label}")
    if payment_method == "ecocash" and ecocash_number:
        lines.append(f"EcoCash #: {ecocash_number}")

    return {
        "screen": "ORDER_SUMMARY",
        "data": {
            "summary_text": "\n".join(lines),
            "total_text": f"Total: ${total:.2f}",
            "_cart": cart,
            "_delivery": delivery_data,
            "_payment_method": payment_method,
            "_ecocash_number": ecocash_number,
        },
    }


# ── Helpers ───────────────────────────────────────────────


def _get_products_and_store(
    db: Session, store_id: str, category: Optional[str] = None
):
    """Fetch active products and store name."""
    store = db.query(Store).filter(Store.id == store_id).first()
    store_name = store.store_name if store else "Store"

    query = db.query(Product).filter(
        Product.store_id == store_id,
        Product.status.ilike("active"),
    )
    if category:
        query = query.filter(Product.category == category)

    products = query.order_by(Product.title).limit(20).all()
    return products, store_name


def _get_categories(products) -> list:
    """Extract unique categories from product list."""
    cats = set()
    for p in products:
        if p.category:
            cats.add(p.category)
    return sorted(cats)


def _get_categories_from_db(db: Session, store_id: str) -> list:
    """Get all categories for a store."""
    products = db.query(Product.category).filter(
        Product.store_id == store_id,
        Product.status.ilike("active"),
        Product.category.isnot(None),
    ).distinct().all()
    return sorted(set(p.category for p in products if p.category))


def _cart_summary_text(cart: list) -> str:
    """Build a short cart summary string."""
    if not cart:
        return "Your cart is empty"
    count = sum(item["qty"] for item in cart)
    total = sum(item["price"] * item["qty"] for item in cart)
    return f"Cart: {count} item(s) — ${total:.2f}"


def _build_browse_response(
    db: Session, store_id: str, cart: list
) -> Dict[str, Any]:
    """Build the PRODUCT_BROWSE screen response."""
    products, store_name = _get_products_and_store(db, store_id)
    categories = _get_categories(products)

    return {
        "screen": "PRODUCT_BROWSE",
        "data": {
            "products": [
                {"id": str(p.id), "title": f"{p.title[:20]} - ${p.price:.0f}"}
                for p in products[:20]
            ],
            "categories": [{"id": c, "title": c} for c in categories[:10]],
            "store_name": store_name,
            "cart_summary": _cart_summary_text(cart),
            "_cart": cart,
        },
    }


def _build_cart_review_response(cart: list) -> Dict[str, Any]:
    """Build the CART_REVIEW screen response."""
    if not cart:
        return {
            "screen": "CART_REVIEW",
            "data": {
                "cart_items": "Your cart is empty.",
                "cart_total": "Total: $0.00",
                "is_empty": True,
                "_cart": [],
            },
        }

    lines = []
    total = 0.0
    for item in cart:
        line_total = item["price"] * item["qty"]
        total += line_total
        lines.append(f"{item['title']} x{item['qty']} — ${line_total:.2f}")

    return {
        "screen": "CART_REVIEW",
        "data": {
            "cart_items": "\n".join(lines),
            "cart_total": f"Total: ${total:.2f}",
            "is_empty": False,
            "_cart": cart,
        },
    }


def _go_to_delivery(cart: list) -> Dict[str, Any]:
    """Navigate to DELIVERY_INFO screen."""
    return {
        "screen": "DELIVERY_INFO",
        "data": {
            "delivery_options": [
                {"id": "delivery", "title": "Delivery"},
                {"id": "pickup", "title": "Pickup"},
            ],
            "_cart": cart,
        },
    }


def _go_to_payment(cart: list, data: dict) -> Dict[str, Any]:
    """Navigate to PAYMENT_METHOD screen."""
    total = sum(item["price"] * item["qty"] for item in cart)
    return {
        "screen": "PAYMENT_METHOD",
        "data": {
            "cart_total": f"Total: ${total:.2f}",
            "payment_options": [
                {"id": "ecocash", "title": "EcoCash"},
                {"id": "pay_on_delivery", "title": "Pay on Delivery"},
            ],
            "_cart": cart,
            "_delivery": data.get("_delivery", {}),
        },
    }


# ── Store Admin Endpoint ──────────────────────────────────


@flow_router.post("/store/{store_id}/enable-ordering-flow")
async def enable_ordering_flow(
    store_id: uuid_mod.UUID,
    db: Session = Depends(get_db),
):
    """
    Create and publish a WhatsApp Flow for the store.

    Call this when a store owner enables WhatsApp ordering.
    Requires the store to have a WhatsApp account with waba_id and access token.
    """
    # Check for existing published flow
    existing = db.query(WhatsAppFlow).filter(
        WhatsAppFlow.store_id == store_id,
        WhatsAppFlow.status == "published",
    ).first()
    if existing:
        return {"flow_id": existing.flow_id, "status": "already_published"}

    # Get store info
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Get WhatsApp account for this store
    wa_account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.store_id == store_id,
    ).first()
    if not wa_account:
        # Try default account
        wa_account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.is_default == True,
        ).first()
    if not wa_account or not wa_account.waba_id:
        raise HTTPException(
            status_code=400,
            detail="No WhatsApp Business Account found for this store",
        )

    access_token = wa_account.permanent_access_token
    if not access_token:
        raise HTTPException(status_code=400, detail="No access token for WhatsApp account")

    # Create and publish
    from .flow_manager import WhatsAppFlowManager

    manager = WhatsAppFlowManager(
        waba_id=wa_account.waba_id,
        access_token=access_token,
    )

    try:
        flow_id = manager.create_and_publish_store_flow(
            store_id=store_id,
            store_name=store.store_name or store.name or "Store",
            db=db,
        )
        return {"flow_id": flow_id, "status": "published"}
    except Exception as e:
        logger.error(f"Failed to create flow for store {store_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to create flow: {str(e)}")

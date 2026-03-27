"""
WhatsApp Flow Completion Handler.

Called when a customer completes an ordering Flow (nfm_reply webhook).
Creates the CustomerOrder, initiates EcoCash payment if needed,
and sends a confirmation message.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from modules.orders.models import CustomerOrder
from modules.stores.models import Store
from modules.whatsapp.models import WhatsAppConversation, WhatsAppAccount
from modules.whatsapp.interactive_messages import build_text_message, build_button_message
from .flow_token import decode_flow_token

logger = logging.getLogger(__name__)


def handle_flow_completion(
    response_json: Dict[str, Any],
    flow_token: str,
    whatsapp_account: WhatsAppAccount,
    from_number: str,
    db: Session,
    access_token: str,
    send_message_fn=None,
):
    """
    Process a completed WhatsApp Flow.

    response_json: the data from the final screen's "complete" action payload
    flow_token: the token we encoded when sending the flow message
    send_message_fn: callable(message_type, message_data) to send WhatsApp messages
    """
    # Decode token
    try:
        token_data = decode_flow_token(flow_token)
        store_id = token_data["store_id"]
    except ValueError as e:
        logger.error(f"Invalid flow token: {e}")
        return

    # Get store
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        logger.error(f"Store not found: {store_id}")
        return

    currency = getattr(store, "currency", "USD") or "USD"

    # Extract order data from the flow response
    cart = response_json.get("_cart", [])
    delivery_data = response_json.get("_delivery", {})
    payment_method = response_json.get("_payment_method", "pay_on_delivery")
    ecocash_number = response_json.get("_ecocash_number", "")

    if not cart:
        logger.warning("Flow completed with empty cart")
        return

    # Calculate totals
    items_total = sum(item["price"] * item["qty"] for item in cart)
    total_qty = sum(item["qty"] for item in cart)
    product_names = ", ".join(f"{i['title']} x{i['qty']}" for i in cart)

    delivery_method = delivery_data.get("delivery_method", "delivery")
    delivery_fee = 0.0
    if delivery_method == "delivery" and hasattr(store, "delivery_fee") and store.delivery_fee:
        try:
            delivery_fee = float(store.delivery_fee)
        except (ValueError, TypeError):
            pass

    total_amount = items_total + delivery_fee

    # Generate order number
    from modules.orders.router import generate_order_number
    order_number = generate_order_number(db, store_id)

    # Build notes
    customer_name = delivery_data.get("customer_name", from_number)
    phone = delivery_data.get("phone", from_number)
    address = delivery_data.get("address", "")

    notes = [
        f"Delivery: {'Pickup' if delivery_method == 'pickup' else 'Delivery'}",
    ]
    if address:
        notes.append(f"Address: {address}")
    notes.append(f"WhatsApp: {from_number}")
    notes.append(f"Phone: {phone}")
    notes.append(f"Payment: {payment_method}")
    notes.append("Source: WhatsApp Flow")

    # Determine payment status
    payment_status = "pending" if payment_method == "ecocash" else "unpaid"

    # Create order
    order = CustomerOrder(
        store_id=store_id,
        order_number=order_number,
        customer_name=customer_name,
        phone=phone,
        product_name=product_names,
        quantity=total_qty,
        total_amount=total_amount,
        status="pending",
        payment_status=payment_status,
        delivery_status="pending" if delivery_method == "delivery" else "pickup",
        payment_method=payment_method,
        customer_profile="\n".join(notes),
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    logger.info(f"Order created from Flow: {order_number} for {from_number}")

    # Update conversation state
    conversation = db.query(WhatsAppConversation).filter(
        WhatsAppConversation.whatsapp_account_id == whatsapp_account.id,
        WhatsAppConversation.phone_number == from_number,
    ).first()

    # Build response messages
    messages = []

    if payment_method == "ecocash" and ecocash_number:
        # Initiate EcoCash payment
        poll_url = _initiate_ecocash_payment(
            db=db,
            store=store,
            order=order,
            phone_number=from_number,
            ecocash_number=ecocash_number,
            total=total_amount,
        )

        if poll_url and conversation:
            # Save payment state for follow-up polling
            conversation.order_flow_state = {
                "awaiting_payment": True,
                "payment_poll_url": poll_url,
                "order_id": str(order.id),
                "order_number": order_number,
            }
            conversation.order_flow_active = True
            db.commit()

            messages.append(build_text_message(
                f"Order *{order_number}* created!\n\n"
                f"EcoCash payment of {currency} {total_amount:.2f} "
                f"sent to {ecocash_number}.\n\n"
                f"Please approve the payment on your phone, "
                f"then tap 'Check Payment' below."
            ))
            messages.append(build_button_message(
                body="Payment status:",
                buttons=[
                    {"id": "check_payment", "title": "Check Payment"},
                    {"id": "cancel_payment", "title": "Cancel"},
                ],
            ))
        else:
            # EcoCash initiation failed — order still created
            if conversation:
                conversation.order_flow_active = False
                conversation.order_flow_state = None
                db.commit()

            messages.append(build_text_message(
                f"Order *{order_number}* created!\n\n"
                f"We couldn't initiate EcoCash payment automatically. "
                f"Please contact us to arrange payment.\n\n"
                f"Total: {currency} {total_amount:.2f}"
            ))
    else:
        # Pay on delivery
        if conversation:
            conversation.order_flow_active = False
            conversation.order_flow_state = None
            db.commit()

        lines = [
            f"*Order Confirmed!* ✅\n",
            f"Order: *{order_number}*",
            f"Items: {product_names}",
            f"Total: {currency} {total_amount:.2f}",
            f"Payment: Pay on Delivery",
            f"Delivery: {delivery_method.title()}",
        ]
        if address:
            lines.append(f"Address: {address}")
        lines.append(f"\nThank you for your order! 🙏")

        messages.append(build_text_message("\n".join(lines)))

    return messages


def _initiate_ecocash_payment(
    db: Session,
    store: Any,
    order: CustomerOrder,
    phone_number: str,
    ecocash_number: str,
    total: float,
) -> Optional[str]:
    """Initiate EcoCash payment. Returns poll_url or None."""
    try:
        from utils.payment_service import PaymentService
        from modules.payment.models import PaymentTransaction, PaymentMethod, PaymentStatus

        currency = getattr(store, "currency", "USD") or "USD"
        reference = f"WA-{phone_number[-6:]}-{int(datetime.utcnow().timestamp())}"

        transaction = PaymentTransaction(
            reference=reference,
            amount=total,
            currency=currency,
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.PENDING,
            store_id=store.id,
            user_id=store.user_id,
            payment_metadata={
                "order_id": str(order.id),
                "order_number": order.order_number,
                "source": "whatsapp_flow",
                "phone": phone_number,
            },
        )
        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        payment_service = PaymentService()
        result, error = payment_service.initiate_ecocash_payment(
            transaction=transaction,
            mobile_number=ecocash_number,
            email=f"{phone_number}@whatsapp.shopivell.com",
        )

        if error:
            logger.error(f"EcoCash initiation failed: {error}")
            return None

        # Save poll URL to transaction
        if result and result.get("poll_url"):
            transaction.poll_url = result["poll_url"]
            if result.get("paynow_reference"):
                transaction.paynow_reference = result["paynow_reference"]
            db.commit()
            return result["poll_url"]

        return None

    except Exception as e:
        logger.error(f"EcoCash payment error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

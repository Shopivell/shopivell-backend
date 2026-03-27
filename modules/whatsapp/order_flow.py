"""
WhatsApp Order Flow — Interactive ordering via WhatsApp messages.

State machine for guiding customers through:
browse → select → quantity → cart → delivery → payment → confirmation

All within WhatsApp — no browser needed.
"""

import logging
import math
import os
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime

from sqlalchemy.orm import Session

from modules.products.models import Product
from modules.orders.models import CustomerOrder
from modules.stores.models import Store
from modules.whatsapp.models import WhatsAppConversation, WhatsAppAccount
from modules.whatsapp.interactive_messages import (
    build_text_message,
    build_button_message,
    build_list_message,
)

logger = logging.getLogger(__name__)

PRODUCTS_PER_PAGE = 10


class OrderState:
    IDLE = "idle"
    BROWSING = "browsing"
    PRODUCT_SELECTED = "product_selected"
    CART_REVIEW = "cart_review"
    DELIVERY_METHOD = "delivery_method"
    AWAITING_ADDRESS = "awaiting_address"
    PAYMENT_METHOD = "payment_method"
    AWAITING_ECOCASH_NUMBER = "awaiting_ecocash_number"
    PAYMENT_PENDING = "payment_pending"
    CONFIRMED = "confirmed"


def _empty_state() -> Dict[str, Any]:
    return {
        "step": OrderState.IDLE,
        "cart": [],
        "current_page": 0,
        "selected_product_id": None,
        "delivery_method": None,
        "delivery_address": None,
        "payment_method": None,
        "ecocash_number": None,
        "payment_poll_url": None,
        "order_id": None,
    }


class OrderFlowManager:
    """Manages the WhatsApp ordering conversation state machine."""

    def __init__(
        self,
        store_id: UUID,
        whatsapp_account: WhatsAppAccount,
        conversation: WhatsAppConversation,
        db: Session,
        access_token: str,
    ):
        self.store_id = store_id
        self.whatsapp_account = whatsapp_account
        self.conversation = conversation
        self.db = db
        self.access_token = access_token
        self.phone_number = conversation.phone_number
        self.state: Dict[str, Any] = conversation.order_flow_state or _empty_state()

    def _save_state(self):
        self.conversation.order_flow_state = self.state
        self.conversation.order_flow_active = self.state["step"] != OrderState.IDLE
        self.db.commit()

    def _get_store(self) -> Optional[Store]:
        return self.db.query(Store).filter(Store.id == self.store_id).first()

    # ── Public API ───────────────────────────────────────────────

    def start_flow(self) -> List[Dict[str, Any]]:
        """Start the ordering flow. Returns messages to send."""
        self.state = _empty_state()
        self.state["step"] = OrderState.BROWSING
        self.state["current_page"] = 0
        self._save_state()
        return self._build_product_list(0)

    def handle_message(
        self, message_type: str, message_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Handle an incoming message within the active flow."""
        step = self.state.get("step", OrderState.IDLE)

        # Cancel from any step
        text = _extract_text(message_type, message_data)
        if text and text.lower().strip() in ("cancel", "cancel order", "stop"):
            return self._cancel("Order cancelled. How else can I help you?")

        handlers = {
            OrderState.BROWSING: self._handle_browsing,
            OrderState.PRODUCT_SELECTED: self._handle_quantity,
            OrderState.CART_REVIEW: self._handle_cart_review,
            OrderState.DELIVERY_METHOD: self._handle_delivery_method,
            OrderState.AWAITING_ADDRESS: self._handle_address,
            OrderState.PAYMENT_METHOD: self._handle_payment_method,
            OrderState.AWAITING_ECOCASH_NUMBER: self._handle_ecocash_number,
            OrderState.PAYMENT_PENDING: self._handle_payment_pending,
        }

        handler = handlers.get(step)
        if not handler:
            return self._cancel("Something went wrong. Let's start over.")

        result = handler(message_type, message_data)
        self._save_state()
        return result

    def _cancel(self, msg: str) -> List[Dict[str, Any]]:
        self.state = _empty_state()
        self._save_state()
        return [build_text_message(msg)]

    # ── State Handlers ───────────────────────────────────────────

    def _handle_browsing(self, msg_type: str, msg_data: dict) -> list:
        interactive = _extract_interactive_reply(msg_type, msg_data)

        if interactive:
            reply_id = interactive.get("id", "")

            if reply_id == "next_page":
                self.state["current_page"] += 1
                return self._build_product_list(self.state["current_page"])
            if reply_id == "prev_page":
                self.state["current_page"] = max(0, self.state["current_page"] - 1)
                return self._build_product_list(self.state["current_page"])
            if reply_id == "view_cart":
                if not self.state["cart"]:
                    return [build_text_message("Your cart is empty. Select a product first.")]
                self.state["step"] = OrderState.CART_REVIEW
                return self._build_cart_review()
            if reply_id.startswith("product_"):
                product_id = reply_id.replace("product_", "")
                product = self.db.query(Product).filter(
                    Product.id == product_id, Product.store_id == self.store_id
                ).first()
                if not product:
                    return [build_text_message("That product is no longer available.")]

                self.state["selected_product_id"] = str(product.id)
                self.state["step"] = OrderState.PRODUCT_SELECTED

                store = self._get_store()
                currency = store.currency if store else "USD"
                desc_text = f"\n{product.description[:200]}" if product.description else ""
                msg = (
                    f"*{product.title}*\n"
                    f"Price: {currency} {product.price:.2f}{desc_text}\n\n"
                    f"How many would you like? Reply with a number (e.g. 1, 2, 3)"
                )
                return [build_text_message(msg)]

        return [build_text_message("Please select a product from the list, or type *cancel* to exit.")]

    def _handle_quantity(self, msg_type: str, msg_data: dict) -> list:
        text = _extract_text(msg_type, msg_data)
        if not text or not text.strip().isdigit():
            return [build_text_message("Please enter a number for quantity (e.g. 1, 2, 3)")]

        qty = int(text.strip())
        if qty < 1 or qty > 100:
            return [build_text_message("Please enter a quantity between 1 and 100.")]

        product = self.db.query(Product).filter(
            Product.id == self.state["selected_product_id"]
        ).first()
        if not product:
            self.state["step"] = OrderState.BROWSING
            return [build_text_message("Product no longer available.")] + self._build_product_list(0)

        # Add to cart or update quantity
        cart = self.state["cart"]
        existing = next((i for i in cart if i["product_id"] == str(product.id)), None)
        if existing:
            existing["qty"] += qty
        else:
            cart.append({
                "product_id": str(product.id),
                "title": product.title,
                "price": float(product.price),
                "qty": qty,
                "image_url": product.image_url,
            })

        self.state["selected_product_id"] = None
        self.state["step"] = OrderState.CART_REVIEW
        return self._build_cart_review()

    def _handle_cart_review(self, msg_type: str, msg_data: dict) -> list:
        interactive = _extract_interactive_reply(msg_type, msg_data)
        if interactive:
            reply_id = interactive.get("id", "")
            if reply_id == "checkout":
                self.state["step"] = OrderState.DELIVERY_METHOD
                return self._build_delivery_buttons()
            if reply_id == "add_more":
                self.state["step"] = OrderState.BROWSING
                return self._build_product_list(0)
            if reply_id == "clear_cart":
                self.state["cart"] = []
                self.state["step"] = OrderState.BROWSING
                return [build_text_message("Cart cleared.")] + self._build_product_list(0)
        return self._build_cart_review()

    def _handle_delivery_method(self, msg_type: str, msg_data: dict) -> list:
        interactive = _extract_interactive_reply(msg_type, msg_data)
        if interactive:
            reply_id = interactive.get("id", "")
            if reply_id == "delivery":
                self.state["delivery_method"] = "delivery"
                self.state["step"] = OrderState.AWAITING_ADDRESS
                return [build_text_message("Please type your delivery address (street, area, city):")]
            if reply_id == "pickup":
                self.state["delivery_method"] = "pickup"
                self.state["step"] = OrderState.PAYMENT_METHOD
                return self._build_payment_buttons()
        return self._build_delivery_buttons()

    def _handle_address(self, msg_type: str, msg_data: dict) -> list:
        text = _extract_text(msg_type, msg_data)
        if not text or len(text.strip()) < 5:
            return [build_text_message("Please enter a valid delivery address:")]
        self.state["delivery_address"] = text.strip()
        self.state["step"] = OrderState.PAYMENT_METHOD
        return self._build_payment_buttons()

    def _handle_payment_method(self, msg_type: str, msg_data: dict) -> list:
        interactive = _extract_interactive_reply(msg_type, msg_data)
        if interactive:
            reply_id = interactive.get("id", "")
            if reply_id == "ecocash":
                self.state["payment_method"] = "ecocash"
                self.state["step"] = OrderState.AWAITING_ECOCASH_NUMBER
                phone = self.phone_number
                return [build_text_message(
                    f"Enter your EcoCash number.\n"
                    f"Reply *yes* to use {phone}, or type a different number."
                )]
            if reply_id == "pay_on_delivery":
                self.state["payment_method"] = "pay_on_delivery"
                return self._create_order("unpaid", "pay_on_delivery")
        return self._build_payment_buttons()

    def _handle_ecocash_number(self, msg_type: str, msg_data: dict) -> list:
        text = _extract_text(msg_type, msg_data)
        if not text:
            return [build_text_message("Please enter your EcoCash number:")]

        clean = text.strip().lower()
        if clean in ("yes", "y"):
            number = self.phone_number
        else:
            number = clean.replace(" ", "").replace("+", "").replace("-", "")
            if not number.isdigit() or len(number) < 9:
                return [build_text_message("Please enter a valid mobile number (e.g. 0771234567):")]

        self.state["ecocash_number"] = number
        return self._initiate_ecocash(number)

    def _handle_payment_pending(self, msg_type: str, msg_data: dict) -> list:
        interactive = _extract_interactive_reply(msg_type, msg_data)
        text = _extract_text(msg_type, msg_data)

        reply_id = interactive.get("id", "") if interactive else ""
        check = reply_id == "check_payment" or (text and text.strip().lower() in ("check", "done", "paid"))

        if check:
            return self._check_ecocash_status()
        if reply_id == "cancel_payment":
            return self._cancel("Payment cancelled. Order not placed.")

        return [build_text_message(
            "Waiting for your EcoCash payment.\nReply *check* after paying, or *cancel* to cancel."
        )]

    # ── Message Builders ─────────────────────────────────────────

    def _build_product_list(self, page: int) -> list:
        products = self.db.query(Product).filter(
            Product.store_id == self.store_id,
            Product.status == "active",
        ).order_by(Product.title).all()

        if not products:
            self.state = _empty_state()
            self._save_state()
            return [build_text_message("Sorry, no products are available right now.")]

        total_pages = math.ceil(len(products) / PRODUCTS_PER_PAGE)
        page = min(page, total_pages - 1)
        start = page * PRODUCTS_PER_PAGE
        page_products = products[start : start + PRODUCTS_PER_PAGE]

        store = self._get_store()
        store_name = store.store_name if store else "Store"
        currency = store.currency if store else "USD"

        rows = []
        for p in page_products:
            price_str = f"{currency} {p.price:.2f}"
            desc = p.description[:60] if p.description else "Tap to select"
            rows.append({
                "id": f"product_{p.id}",
                "title": p.title[:24],
                "description": f"{price_str} - {desc}"[:72],
            })

        cart_count = sum(i["qty"] for i in self.state["cart"])
        body = f"Page {page + 1}/{total_pages}"
        if cart_count:
            cart_total = sum(i["price"] * i["qty"] for i in self.state["cart"])
            body += f" | Cart: {cart_count} items ({currency} {cart_total:.2f})"
        body += "\n\nSelect a product. Type *cancel* to exit."

        result = [build_list_message(
            body=body,
            button_text="View Products",
            sections=[{"title": store_name, "rows": rows}],
            header=f"Order from {store_name}",
        )]

        # Navigation buttons (max 3)
        nav = []
        if page > 0:
            nav.append({"id": "prev_page", "title": "Previous Page"})
        if page < total_pages - 1:
            nav.append({"id": "next_page", "title": "Next Page"})
        if cart_count:
            nav.append({"id": "view_cart", "title": f"Cart ({cart_count})"})

        if nav:
            result.append(build_button_message("Options:", nav[:3]))

        return result

    def _build_cart_review(self) -> list:
        cart = self.state["cart"]
        if not cart:
            self.state["step"] = OrderState.BROWSING
            return [build_text_message("Cart is empty.")] + self._build_product_list(0)

        store = self._get_store()
        currency = store.currency if store else "USD"

        lines = ["*Your Cart:*\n"]
        total = 0.0
        for i, item in enumerate(cart, 1):
            line_total = item["price"] * item["qty"]
            total += line_total
            lines.append(f"{i}. {item['title']} x{item['qty']} — {currency} {line_total:.2f}")

        # Add delivery fee if applicable
        delivery_fee = 0.0
        if store and store.delivery_fee:
            try:
                delivery_fee = float(store.delivery_fee)
            except (ValueError, TypeError):
                pass

        lines.append(f"\n*Subtotal: {currency} {total:.2f}*")

        return [build_button_message(
            body="\n".join(lines),
            buttons=[
                {"id": "checkout", "title": "Checkout"},
                {"id": "add_more", "title": "Add More"},
                {"id": "clear_cart", "title": "Clear Cart"},
            ],
        )]

    def _build_delivery_buttons(self) -> list:
        store = self._get_store()
        buttons = []
        parts = ["How would you like to receive your order?\n"]

        if not store or store.delivery_enabled:
            fee = "0"
            if store and store.delivery_fee:
                fee = store.delivery_fee
            parts.append(f"Delivery — fee: {store.currency if store else 'USD'} {fee}")
            buttons.append({"id": "delivery", "title": "Delivery"})

        if store and store.pickup_enabled:
            addr = store.store_address or "our store"
            parts.append(f"Pickup — collect from {addr}")
            buttons.append({"id": "pickup", "title": "Pickup"})

        if not buttons:
            buttons.append({"id": "delivery", "title": "Delivery"})

        return [build_button_message("\n".join(parts), buttons)]

    def _build_payment_buttons(self) -> list:
        store = self._get_store()
        currency = store.currency if store else "USD"
        cart_total = sum(i["price"] * i["qty"] for i in self.state["cart"])

        delivery_fee = 0.0
        if self.state["delivery_method"] == "delivery" and store and store.delivery_fee:
            try:
                delivery_fee = float(store.delivery_fee)
            except (ValueError, TypeError):
                pass

        total = cart_total + delivery_fee
        body = (
            f"*Order Total: {currency} {total:.2f}*\n\n"
            f"How would you like to pay?"
        )
        return [build_button_message(body, [
            {"id": "ecocash", "title": "EcoCash"},
            {"id": "pay_on_delivery", "title": "Pay on Delivery"},
        ])]

    # ── Order Creation ───────────────────────────────────────────

    def _create_order(self, payment_status: str, payment_method: str) -> list:
        store = self._get_store()
        currency = store.currency if store else "USD"

        cart = self.state["cart"]
        product_names = ", ".join(f"{i['title']} x{i['qty']}" for i in cart)
        items_total = sum(i["price"] * i["qty"] for i in cart)
        total_qty = sum(i["qty"] for i in cart)

        delivery_fee = 0.0
        if self.state["delivery_method"] == "delivery" and store and store.delivery_fee:
            try:
                delivery_fee = float(store.delivery_fee)
            except (ValueError, TypeError):
                pass

        total_amount = items_total + delivery_fee

        # Generate order number
        from modules.orders.router import generate_order_number
        order_number = generate_order_number(self.db, self.store_id)

        # Build notes
        notes = []
        dm = self.state["delivery_method"] or "delivery"
        notes.append(f"Delivery: {'Pickup' if dm == 'pickup' else 'Delivery'}")
        if self.state["delivery_address"]:
            notes.append(f"Address: {self.state['delivery_address']}")
        notes.append(f"WhatsApp: {self.phone_number}")
        notes.append(f"Payment: {payment_method}")

        customer_name = self.conversation.customer_name or self.phone_number

        order = CustomerOrder(
            store_id=self.store_id,
            order_number=order_number,
            customer_name=customer_name,
            phone=self.phone_number,
            product_name=product_names,
            quantity=total_qty,
            total_amount=total_amount,
            status="pending",
            payment_status=payment_status,
            delivery_status="pending" if dm == "delivery" else "pickup",
            payment_method=payment_method,
            customer_profile="\n".join(notes),
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)

        self.state["order_id"] = str(order.id)
        self.state["step"] = OrderState.CONFIRMED
        self.state = _empty_state()  # Reset
        self._save_state()

        # Confirmation message
        lines = [
            f"*Order Confirmed!* ✅\n",
            f"Order: *{order_number}*",
            f"Items: {product_names}",
            f"Total: {currency} {total_amount:.2f}",
            f"Payment: {payment_method.replace('_', ' ').title()}",
            f"Delivery: {dm.title()}",
        ]
        if self.state.get("delivery_address"):
            lines.append(f"Address: {self.state['delivery_address']}")
        lines.append(f"\nThank you for your order! 🙏")

        return [build_text_message("\n".join(lines))]

    # ── EcoCash Payment ──────────────────────────────────────────

    def _initiate_ecocash(self, mobile_number: str) -> list:
        try:
            from utils.payment_service import PaymentService
            from modules.payment.models import PaymentTransaction, PaymentMethod, PaymentStatus

            store = self._get_store()
            cart_total = sum(i["price"] * i["qty"] for i in self.state["cart"])
            delivery_fee = 0.0
            if self.state["delivery_method"] == "delivery" and store and store.delivery_fee:
                try:
                    delivery_fee = float(store.delivery_fee)
                except (ValueError, TypeError):
                    pass
            total = cart_total + delivery_fee

            # Create payment transaction
            reference = f"WA-{self.phone_number[-6:]}-{int(datetime.utcnow().timestamp())}"
            transaction = PaymentTransaction(
                reference=reference,
                amount=total,
                currency=store.currency if store else "USD",
                payment_method=PaymentMethod.ECOCASH,
                status=PaymentStatus.PENDING,
                mobile_number=mobile_number,
            )
            self.db.add(transaction)
            self.db.commit()
            self.db.refresh(transaction)

            payment_service = PaymentService(self.db)
            result, error = payment_service.initiate_ecocash_payment(
                transaction=transaction,
                mobile_number=mobile_number,
                email=f"{self.phone_number}@whatsapp.order",
            )

            if error:
                return [build_text_message(f"Payment error: {error}\nPlease try again or choose Pay on Delivery.")]

            self.state["payment_poll_url"] = result.get("poll_url")
            self.state["step"] = OrderState.PAYMENT_PENDING
            self._save_state()

            instruction = result.get("instruction", "Check your phone for the EcoCash prompt.")
            return [
                build_text_message(
                    f"*EcoCash Payment Initiated*\n\n"
                    f"Amount: {store.currency if store else 'USD'} {total:.2f}\n"
                    f"Number: {mobile_number}\n\n"
                    f"{instruction}\n\n"
                    f"After paying, reply *check* to confirm."
                ),
                build_button_message("Payment status:", [
                    {"id": "check_payment", "title": "Check Payment"},
                    {"id": "cancel_payment", "title": "Cancel"},
                ]),
            ]

        except Exception as e:
            logger.error(f"EcoCash initiation error: {e}")
            return [build_text_message(
                "Could not initiate EcoCash payment. Please try again or choose Pay on Delivery."
            )]

    def _check_ecocash_status(self) -> list:
        poll_url = self.state.get("payment_poll_url")
        if not poll_url:
            return self._create_order("unpaid", "ecocash")

        try:
            from utils.payment_service import PaymentService
            payment_service = PaymentService(self.db)
            result = payment_service.check_payment_status(poll_url)

            if result and result.get("paid"):
                return self._create_order("paid", "ecocash")

            status = result.get("status", "pending") if result else "pending"
            return [
                build_text_message(
                    f"Payment status: *{status}*\n\n"
                    f"If you've already paid, wait a moment and reply *check* again."
                ),
                build_button_message("Options:", [
                    {"id": "check_payment", "title": "Check Again"},
                    {"id": "cancel_payment", "title": "Cancel"},
                ]),
            ]

        except Exception as e:
            logger.error(f"EcoCash status check error: {e}")
            return [build_text_message("Could not check payment status. Reply *check* to try again.")]


# ── Helpers ──────────────────────────────────────────────────────

def _extract_text(msg_type: str, msg_data: dict) -> Optional[str]:
    """Extract text body from any message type."""
    if msg_type == "text":
        return msg_data.get("text", {}).get("body")
    if msg_type == "interactive":
        interactive = msg_data.get("interactive", {})
        itype = interactive.get("type")
        if itype == "button_reply":
            return interactive.get("button_reply", {}).get("title")
        if itype == "list_reply":
            return interactive.get("list_reply", {}).get("title")
    return None


def _extract_interactive_reply(msg_type: str, msg_data: dict) -> Optional[Dict[str, str]]:
    """Extract interactive reply ID and title."""
    if msg_type == "interactive":
        interactive = msg_data.get("interactive", {})
        itype = interactive.get("type")
        if itype == "button_reply":
            return interactive.get("button_reply", {})
        if itype == "list_reply":
            return interactive.get("list_reply", {})
    return None

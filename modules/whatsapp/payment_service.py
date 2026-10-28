"""
WhatsApp Order Payment Service - Handles mobile money payments via Paynow
"""
import os
import uuid
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class WhatsAppPaymentService:
    """Service for processing WhatsApp order payments via Paynow."""

    def __init__(self, db: Session):
        self.db = db
        self.paynow = None
        self._init_paynow()

    def _init_paynow(self):
        """Initialize PayNow integration."""
        try:
            from paynow import Paynow

            integration_id = os.getenv("PAYNOW_INTEGRATION_ID", "")
            integration_key = os.getenv("PAYNOW_INTEGRATION_KEY", "")
            return_url = os.getenv("PAYNOW_RETURN_URL", "https://shopivell.com/payment/return")
            result_url = (os.getenv("WHATSAPP_PAYNOW_RESULT_URL")
                          or os.getenv("PAYNOW_RESULT_URL", "https://shopivell.com/api/v1/payment/callback"))

            if not integration_id or not integration_key:
                logger.warning("PayNow credentials not configured for WhatsApp payments.")
                self.paynow = None
                return

            self.paynow = Paynow(
                integration_id,
                integration_key,
                return_url,
                result_url
            )
            logger.info("PayNow initialized for WhatsApp payments")
        except ImportError:
            logger.warning("PayNow library not installed.")
            self.paynow = None
        except Exception as e:
            logger.error(f"Failed to initialize PayNow: {e}")
            self.paynow = None

    def initiate_mobile_payment(
        self,
        order_id: str,
        order_number: str,
        amount: float,
        customer_phone: str,
        payment_provider: str,  # ecocash, onemoney, innbucks
        customer_email: str = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Initiate a mobile money payment for a WhatsApp order.

        Args:
            order_id: The order UUID
            order_number: The order number (e.g., PP-20241014-ABCD)
            amount: Total payment amount in USD
            customer_phone: Customer's mobile number for payment
            payment_provider: ecocash, onemoney, or innbucks
            customer_email: Optional email for receipt

        Returns:
            Tuple of (result dict, error message)
        """
        try:
            provider = payment_provider.lower()
            email = customer_email or f"{customer_phone}@whatsapp.order"

            if not self.paynow:
                # A simulated request must never be reported as a real payment.
                self._update_order_payment(order_id, payment_provider=provider, payment_status="failed")
                return None, "Mobile payments are not configured."

            # Create PayNow payment
            payment = self.paynow.create_payment(
                f"Order {order_number}",
                email
            )

            # Add order as line item
            payment.add(f"Order {order_number}", amount)

            # Map provider to Paynow method
            paynow_method = {
                "ecocash": "ecocash",
                "onemoney": "onemoney",
                "innbucks": "innbucks"
            }.get(provider, "ecocash")

            # Send payment request to mobile
            response = self.paynow.send_mobile(payment, customer_phone, paynow_method)

            logger.info(f"PayNow {provider} response - success: {response.success}")

            # SDK success indicates request acceptance, not settlement. Reject
            # malformed/failed provider responses even if the SDK labels them
            # successful, and require a poll URL to track the payment.
            provider_status = str(getattr(response, 'status', '')).strip().lower()
            poll_url = getattr(response, 'poll_url', None)
            if response.success is True and provider_status == 'ok' and isinstance(poll_url, str) and poll_url:
                paynow_ref = self._extract_reference(response)
                instructions = self._get_instructions(response, provider)

                # Update order with payment details
                self._update_order_payment(
                    order_id,
                    payment_provider=provider,
                    payment_status="processing",
                    payment_reference=paynow_ref,
                    payment_poll_url=poll_url
                )
                # Paynow may accept the request before the wallet later rejects
                # it, and a callback is not guaranteed to arrive promptly.
                from modules.jobs.queue import enqueue
                if not enqueue('poll_whatsapp_payment', {'order_id': str(order_id)}, max_attempts=12, delay_seconds=20):
                    logger.error('Could not schedule payment status check for order %s', order_number)

                return {
                    "success": True,
                    "poll_url": poll_url,
                    "reference": paynow_ref,
                    "instructions": instructions,
                    "order_number": order_number
                }, None
            else:
                error_msg = self._extract_error(response)
                self._update_order_payment(
                    order_id,
                    payment_provider=provider,
                    payment_status="failed"
                )
                return None, error_msg

        except Exception as e:
            logger.error(f"Error initiating mobile payment: {e}", exc_info=True)
            return None, str(e)

    def _simulate_payment(
        self,
        order_id: str,
        order_number: str,
        amount: float,
        customer_phone: str,
        provider: str
    ) -> Tuple[Dict[str, Any], None]:
        """Simulate payment for testing when PayNow is not configured."""
        sim_ref = f"SIM-{uuid.uuid4().hex[:8].upper()}"
        poll_url = f"https://demo.paynow.co.zw/poll/{sim_ref}"

        # Get provider-specific instructions
        instructions = {
            "ecocash": f"Dial *151*2# on your EcoCash phone to approve the payment of ${amount:.2f}",
            "onemoney": f"Check your OneMoney phone for a payment request of ${amount:.2f}",
            "innbucks": f"Open your InnBucks app to approve the payment of ${amount:.2f}"
        }.get(provider, "Check your phone for a payment prompt")

        # Update order with simulated payment details
        self._update_order_payment(
            order_id,
            payment_provider=provider,
            payment_status="processing",
            payment_reference=sim_ref,
            payment_poll_url=poll_url
        )

        logger.info(f"Simulated {provider} payment for order {order_number}: {sim_ref}")

        return {
            "success": True,
            "poll_url": poll_url,
            "reference": sim_ref,
            "instructions": instructions,
            "order_number": order_number,
            "simulated": True
        }, None

    def check_payment_status(self, order_id: str) -> Dict[str, Any]:
        """
        Check the payment status for an order.

        Returns dict with: status, paid (bool), reference
        """
        try:
            result = self.db.execute(text("""
                SELECT payment_status, payment_reference, payment_poll_url, total_amount, order_number
                FROM whatsapp_orders
                WHERE id = :order_id
            """), {"order_id": order_id}).fetchone()

            if not result:
                return {"status": "not_found", "paid": False}

            current_status = result[0]
            poll_url = result[2]

            # If already completed or failed, return current status
            if current_status in ("completed", "paid"):
                return {"status": "paid", "paid": True, "reference": result[1]}
            if current_status in ("failed", "cancelled", "canceled", "refunded"):
                return {"status": current_status, "paid": False, "reference": result[1]}

            # Check with PayNow if we have a poll URL
            if poll_url and self.paynow:
                try:
                    # The Paynow SDK's polling method does not verify the
                    # response hash. Verify the raw provider response before
                    # using it to change an order or tell a customer it paid.
                    import hashlib, hmac, requests
                    from decimal import Decimal
                    from urllib.parse import parse_qsl, urlparse
                    host = (urlparse(poll_url).hostname or '').lower()
                    if urlparse(poll_url).scheme != 'https' or not (host == 'paynow.co.zw' or host.endswith('.paynow.co.zw')):
                        raise ValueError('Invalid payment status URL')
                    response = requests.post(poll_url, data={}, timeout=10, allow_redirects=False)
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError('Unexpected payment status response')
                    fields = parse_qsl(response.text, keep_blank_values=True, strict_parsing=True)
                    names = [name.lower() for name, _ in fields]
                    if len(names) != len(set(names)) or names.count('hash') != 1:
                        raise ValueError('Invalid payment status response')
                    values = {name.lower(): value for name, value in fields}
                    key = os.getenv('PAYNOW_INTEGRATION_KEY', '')
                    signature = hashlib.sha512((''.join(value for name, value in fields if name.lower() != 'hash') + key).encode()).hexdigest().upper()
                    if not key or not hmac.compare_digest(signature, values.get('hash', '').upper()):
                        raise ValueError('Invalid payment status signature')
                    if values.get('reference') not in (f'Order {result[4]}', f'Order+{result[4]}') or Decimal(values.get('amount', '')) != Decimal(str(result[3])).quantize(Decimal('0.01')):
                        raise ValueError('Payment status does not match the order')
                    if result[1] and not str(result[1]).startswith('PNW-') and values.get('paynowreference') != str(result[1]):
                        raise ValueError('Payment reference does not match the order')
                    paynow_status = values.get('status', '').strip().lower()

                    if paynow_status in ('paid', 'awaiting delivery', 'delivered'):
                        # Payment completed
                        self._update_order_payment(
                            order_id,
                            payment_status="paid"
                        )
                        # Update order status
                        self.db.execute(text("""
                            UPDATE whatsapp_orders
                            SET status = 'confirmed', confirmed_at = NOW(), updated_at = NOW()
                            WHERE id = :order_id
                        """), {"order_id": order_id})
                        self.db.execute(text("""
                            UPDATE customer_orders SET status = 'confirmed'
                            WHERE id = :order_id AND status = 'pending'
                        """), {"order_id": order_id})
                        self.db.commit()

                        return {"status": "paid", "paid": True, "reference": result[1]}

                    if paynow_status in ('cancelled', 'canceled', 'failed'):
                        final_status = 'failed' if paynow_status == 'failed' else 'cancelled'
                        self._update_order_payment(order_id, payment_status=final_status)
                        return {"status": final_status, "paid": False}

                except Exception as e:
                    logger.error(f"Error checking PayNow status: {e}")
                    return {"status": "unavailable", "paid": False, "reference": result[1]}

            # Still processing
            return {"status": "processing", "paid": False, "reference": result[1]}

        except Exception as e:
            logger.error(f"Error checking payment status: {e}")
            return {"status": "error", "paid": False, "error": str(e)}

    def _update_order_payment(self, order_id: str, **updates):
        """Update payment fields on the order."""
        try:
            set_clauses = ["updated_at = NOW()"]
            params = {"order_id": order_id}

            for key, value in updates.items():
                set_clauses.append(f"{key} = :val_{key}")
                params[f"val_{key}"] = value

            self.db.execute(text(f"""
                UPDATE whatsapp_orders
                SET {', '.join(set_clauses)}
                WHERE id = :order_id
            """), params)
            if "payment_status" in updates:
                payment_status = updates["payment_status"]
                display_status = ("paid" if payment_status in ("paid", "completed")
                                  else "refunded" if payment_status == "refunded"
                                  else payment_status if payment_status in ("failed", "cancelled")
                                  else "unpaid")
                self.db.execute(text("""
                    UPDATE customer_orders SET payment_status = :status
                    WHERE id = :order_id
                """), {"order_id": order_id, "status": display_status})
            self.db.commit()
            if updates.get("payment_status") in ("paid", "completed"):
                try:
                    from modules.orders.models import CustomerOrder
                    from modules.customers.paid_order import link_paid_order_customer
                    order = self.db.query(CustomerOrder).filter(CustomerOrder.id == uuid.UUID(str(order_id))).first()
                    if order:
                        link_paid_order_customer(self.db, order)
                        self.db.commit()
                        from utils.cache import cache
                        cache.invalidate_pattern("cust:*")
                except Exception:
                    self.db.rollback()
                    logger.exception("Payment succeeded but customer linking failed for order %s", order_id)

        except Exception as e:
            logger.error(f"Error updating order payment: {e}")
            self.db.rollback()

    def _extract_reference(self, response) -> str:
        """Extract PayNow reference from response."""
        data = getattr(response, 'data', None)
        if isinstance(data, dict):
            ref = data.get('paynowreference') or data.get('paynow_reference')
            if ref and str(ref).strip():
                return str(ref).strip()
        for attr in ['paynow_reference', 'reference', 'paynowreference']:
            if hasattr(response, attr):
                ref = getattr(response, attr)
                if ref and str(ref).strip():
                    return str(ref).strip()
        return f"PNW-{uuid.uuid4().hex[:8].upper()}"

    def _extract_error(self, response) -> str:
        """Extract error message from response."""
        data = getattr(response, 'data', None)
        if isinstance(data, dict):
            for key in ('error', 'message', 'error_message'):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for attr in ['error', 'message', 'error_message']:
            if hasattr(response, attr):
                val = getattr(response, attr)
                if val and not isinstance(val, type):
                    return str(val)
        return "Payment initiation failed"

    def _get_instructions(self, response, provider: str) -> str:
        """Get payment instructions for the customer."""
        # Try to get from response first
        raw = getattr(response, 'instructions', None) or getattr(response, 'instruction', None)
        if raw and not isinstance(raw, type) and str(raw).strip():
            return str(raw)

        # Default instructions by provider
        defaults = {
            "ecocash": "Dial *151*2# on your EcoCash phone to approve the payment.",
            "onemoney": "Check your OneMoney phone for a payment request.",
            "innbucks": "Open your InnBucks app to approve the payment."
        }
        return defaults.get(provider, "Check your phone for a payment prompt.")


def get_order_by_number(db: Session, order_number: str) -> Optional[Dict]:
    """Get order details by order number."""
    try:
        result = db.execute(text("""
            SELECT id, store_id, order_number, customer_phone, customer_name,
                   customer_address, branch, items, subtotal, delivery_fee,
                   total_amount, collection_method, payment_method, payment_provider,
                   payment_status, payment_reference, status
            FROM whatsapp_orders
            WHERE order_number = :order_number
        """), {"order_number": order_number}).fetchone()

        if result:
            return {
                "id": str(result[0]),
                "store_id": str(result[1]),
                "order_number": result[2],
                "customer_phone": result[3],
                "customer_name": result[4],
                "customer_address": result[5],
                "branch": result[6],
                "items": result[7],
                "subtotal": result[8],
                "delivery_fee": result[9],
                "total_amount": result[10],
                "collection_method": result[11],
                "payment_method": result[12],
                "payment_provider": result[13],
                "payment_status": result[14],
                "payment_reference": result[15],
                "status": result[16]
            }
    except Exception as e:
        logger.error(f"Error getting order: {e}")
    return None

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
            result_url = os.getenv("PAYNOW_RESULT_URL", "https://shopivell.com/api/v1/payment/callback")

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
                # Simulate payment for testing
                return self._simulate_payment(order_id, order_number, amount, customer_phone, provider)

            # Create PayNow payment
            payment = self.paynow.create_payment(
                f"Platinum Pharmacy Order {order_number}",
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

            if response.success:
                poll_url = getattr(response, 'poll_url', None)
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
                SELECT payment_status, payment_reference, payment_poll_url, total_amount
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
            if current_status == "failed":
                return {"status": "failed", "paid": False, "reference": result[1]}

            # Check with PayNow if we have a poll URL
            if poll_url and self.paynow:
                try:
                    status = self.paynow.check_transaction_status(poll_url)

                    if hasattr(status, 'paid') and status.paid:
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
                        self.db.commit()

                        return {"status": "paid", "paid": True, "reference": result[1]}

                    paynow_status = getattr(status, 'status', 'unknown').lower()
                    if paynow_status in ('cancelled', 'failed'):
                        self._update_order_payment(order_id, payment_status="failed")
                        return {"status": "failed", "paid": False}

                except Exception as e:
                    logger.error(f"Error checking PayNow status: {e}")

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
            self.db.commit()

        except Exception as e:
            logger.error(f"Error updating order payment: {e}")
            self.db.rollback()

    def _extract_reference(self, response) -> str:
        """Extract PayNow reference from response."""
        for attr in ['paynow_reference', 'reference', 'paynowreference']:
            if hasattr(response, attr):
                ref = getattr(response, attr)
                if ref and str(ref).strip():
                    return str(ref).strip()
        return f"PNW-{uuid.uuid4().hex[:8].upper()}"

    def _extract_error(self, response) -> str:
        """Extract error message from response."""
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

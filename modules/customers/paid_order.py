"""Create or link a store customer when an order is actually paid."""
import re

from sqlalchemy import func, text

from modules.customers.models import Customer


def normalize_customer_phone(phone):
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('00263'):
        digits = digits[2:]
    if len(digits) == 12 and digits.startswith('263'):
        return '0' + digits[3:]
    return digits


def link_paid_order_customer(db, order):
    """Link a paid order to a customer, leaving the caller to commit the transaction."""
    if (order.payment_status or '').lower() != 'paid' or order.customer_id:
        return None
    phone = normalize_customer_phone(order.phone)
    if not phone:
        return None  # No reliable identity to match or create.
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:store), hashtext(:phone))'),
                   {'store': str(order.store_id), 'phone': phone})
        digits = func.regexp_replace(Customer.phone, '[^0-9]', '', 'g')
        variants = [phone]
        if len(phone) == 10 and phone.startswith('0'):
            variants.extend(['263' + phone[1:], '00263' + phone[1:]])
        matches = db.query(Customer).filter(Customer.store_id == order.store_id,
                                             digits.in_(variants)).all()
    else:
        matches = [c for c in db.query(Customer).filter(Customer.store_id == order.store_id).all()
                   if normalize_customer_phone(c.phone) == phone]
    # Do not guess which of multiple existing customers is correct.
    if len(matches) > 1:
        return None
    if matches:
        customer = matches[0]
    else:
        name = (order.customer_name or '').strip() or 'Customer'
        first, _, last = name.partition(' ')
        customer = Customer(store_id=order.store_id, first_name=first[:100],
                            last_name=last.strip()[:100], email=None, phone=phone[:20])
        db.add(customer)
        db.flush()
    order.customer_id = customer.id
    return customer

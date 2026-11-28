"""Create or link a store customer when an order is actually paid."""
import re

from sqlalchemy import func, text

from modules.customers.models import (
    Customer,
    CustomerSegment,
    CustomerSegmentMembership,
)


def _sync_paid_customer_segments(db, order, customer):
    def assign(name, description):
        segment = db.query(CustomerSegment).filter(
            CustomerSegment.store_id == order.store_id,
            CustomerSegment.name == name,
        ).first()
        if not segment:
            segment = CustomerSegment(
                store_id=order.store_id,
                name=name,
                description=description,
                criteria=description,
                type="purchase_behavior",
                created_by="storefront",
                is_active=True,
            )
            db.add(segment)
            db.flush()
        exists = db.query(CustomerSegmentMembership.id).filter(
            CustomerSegmentMembership.customer_id == customer.id,
            CustomerSegmentMembership.segment_id == segment.id,
        ).first()
        if not exists:
            db.add(CustomerSegmentMembership(customer_id=customer.id, segment_id=segment.id))
        segment.customer_count = db.query(CustomerSegmentMembership).filter(
            CustomerSegmentMembership.segment_id == segment.id,
        ).count()

    assign("Customers who have purchased at least once", "Customers with at least one paid order.")
    paid_order_count = db.query(order.__class__).filter(
        order.__class__.store_id == order.store_id,
        order.__class__.customer_id == customer.id,
        order.__class__.payment_status == "paid",
    ).count()
    if paid_order_count >= 2:
        assign("Repeat Buyers", "Customers with at least two paid orders.")

    abandoned = db.query(CustomerSegment).filter(
        CustomerSegment.store_id == order.store_id,
        CustomerSegment.name.in_(["Cart Abandoners", "Abandoned checkouts in the last 30 days"]),
    ).all()
    for segment in abandoned:
        db.query(CustomerSegmentMembership).filter(
            CustomerSegmentMembership.customer_id == customer.id,
            CustomerSegmentMembership.segment_id == segment.id,
        ).delete(synchronize_session=False)
        segment.customer_count = db.query(CustomerSegmentMembership).filter(
            CustomerSegmentMembership.segment_id == segment.id,
        ).count()
    if customer.customer_type == "abandoned_cart":
        customer.customer_type = "purchaser"


def normalize_customer_phone(phone):
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('00263'):
        digits = digits[2:]
    if len(digits) == 12 and digits.startswith('263'):
        return '0' + digits[3:]
    return digits


def link_paid_order_customer(db, order):
    """Link a paid order to a customer, leaving the caller to commit the transaction."""
    if (order.payment_status or '').lower() != 'paid':
        return None
    if order.customer_id:
        customer = db.query(Customer).filter(
            Customer.id == order.customer_id,
            Customer.store_id == order.store_id,
        ).first()
        if customer:
            _sync_paid_customer_segments(db, order, customer)
        return customer
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
    _sync_paid_customer_segments(db, order, customer)
    return customer

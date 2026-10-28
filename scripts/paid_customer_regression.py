"""Verify customers are created only after payment and matched by phone."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from modules.customers.models import Customer
from modules.orders.models import CustomerOrder
from modules.customers.paid_order import link_paid_order_customer

engine = create_engine('sqlite:///:memory:')
Customer.__table__.create(engine)
CustomerOrder.__table__.create(engine)
store_id = uuid4()
with Session(engine) as db:
    first = CustomerOrder(id=uuid4(), store_id=store_id, order_number='A', total_amount=10,
        status='confirmed', customer_name='Tinotenda Cosmas Nyaruwanga', phone='+263 77 123 4567', payment_status='paid')
    db.add(first)
    customer = link_paid_order_customer(db, first)
    db.commit()
    assert customer and customer.email is None and customer.last_name == 'Cosmas Nyaruwanga'
    second = CustomerOrder(id=uuid4(), store_id=store_id, order_number='B', total_amount=10,
        status='pending', customer_name='Tinotenda', phone='0771234567', payment_status='paid')
    db.add(second)
    assert link_paid_order_customer(db, second).id == customer.id
    unpaid = CustomerOrder(id=uuid4(), store_id=store_id, order_number='C', total_amount=10,
        status='pending', customer_name='Someone', phone='0770000000', payment_status='unpaid')
    db.add(unpaid)
    assert link_paid_order_customer(db, unpaid) is None
print('PASS: paid customer creation, phone matching and unpaid guard')

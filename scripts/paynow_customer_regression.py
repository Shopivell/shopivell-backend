"""Test signed Paynow updates without contacting a payment provider."""
import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4
from unittest.mock import patch

os.environ['PAYNOW_INTEGRATION_KEY'] = 'test-integration-key'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from modules.users.models import User
from modules.stores.models import Store
from modules.customers.models import Customer
from modules.orders.models import CustomerOrder
from modules.whatsapp.models import WhatsAppOrder
from modules.whatsapp.router import whatsapp_router
from middleware.whatsapp_access import WhatsAppAccessMiddleware

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
for table in (User.__table__, Store.__table__, Customer.__table__, CustomerOrder.__table__, WhatsAppOrder.__table__):
    table.create(engine)
Testing = sessionmaker(bind=engine, autoflush=False)
owner_id, store_id, order_id = uuid4(), uuid4(), uuid4()
with Testing() as db:
    db.add_all([
        User(id=owner_id, email='owner@example.com'),
        Store(id=store_id, owner_id=owner_id, store_name='Shop', store_phone='123'),
        WhatsAppOrder(id=order_id, store_id=store_id, order_number='PP-123', customer_phone='263771234567',
                      items=[], total_amount=15, payment_reference='PAY-1', payment_status='processing', status='pending'),
        CustomerOrder(id=order_id, store_id=store_id, order_number='PP-123', total_amount=15,
                      status='pending', customer_name='Jane Doe', phone='0771234567', payment_status='unpaid'),
    ])
    db.commit()
app = FastAPI(); app.add_middleware(WhatsAppAccessMiddleware); app.include_router(whatsapp_router, prefix='/v1')
def get_test_db():
    with Testing() as db:
        yield db
app.dependency_overrides[get_db] = get_test_db
client = TestClient(app)
def form(amount='15.00', signature=True, status='Paid'):
    fields = [('reference', 'Order PP-123'), ('paynowreference', 'PAY-1'), ('amount', amount), ('status', status)]
    digest = hashlib.sha512((''.join(value for _, value in fields) + os.environ['PAYNOW_INTEGRATION_KEY']).encode()).hexdigest().upper()
    return urlencode(fields + [('hash', digest if signature else 'BAD')])
url = '/v1/api/whatsapp/paynow-callback'
with patch('modules.jobs.queue.enqueue', return_value='job-id') as notify:
    assert client.post(url, content=form(signature=False)).status_code == 403
    assert client.post(url, content=form(amount='14.00')).status_code == 400
    assert client.post(url, content=form(status='Failed')).status_code == 200
    with Testing() as db:
        assert db.query(WhatsAppOrder).first().payment_status == 'failed'
        assert db.query(CustomerOrder).first().payment_status == 'failed'
        assert db.query(Customer).count() == 0
    assert client.post(url, content=form()).status_code == 200
    assert client.post(url, content=form()).status_code == 200
    assert client.post(url, content=form(status='Failed')).status_code == 200
    assert notify.call_count == 2
with Testing() as db:
    assert db.query(WhatsAppOrder).first().payment_status == 'paid'
    assert db.query(CustomerOrder).first().payment_status == 'paid'
    assert db.query(CustomerOrder).first().customer_id is not None
    assert db.query(Customer).count() == 1
print('PASS: signed payment creates one customer; invalid signature and amount are rejected')

"""Exercise store messaging permissions without sending a real message."""
import os
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime

os.environ['ALLOW_PLAINTEXT_TOKENS'] = 'true'  # Synthetic token in in-memory SQLite only.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
import database
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from modules.users.models import User, UserRole, StoreMember
from modules.stores.models import Store
from modules.business.models import FacebookBusinessAccount
from modules.whatsapp.models import WhatsAppAccount, WhatsAppMessage
from modules.whatsapp.router import whatsapp_router
from middleware.whatsapp_access import WhatsAppAccessMiddleware
from utils.jwt_auth import jwt_auth

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
for table in (User.__table__, Store.__table__, StoreMember.__table__, FacebookBusinessAccount.__table__,
              WhatsAppAccount.__table__, WhatsAppMessage.__table__):
    table.create(engine)
Testing = sessionmaker(bind=engine, autoflush=False)
database.SessionLocal = Testing
owner_id, user_id, store_id, business_id, account_id, other_store, other_account = [uuid4() for _ in range(7)]
with Testing() as db:
    db.add_all([
        User(id=owner_id, email='owner@example.com', role=UserRole.OWNER, is_active=True),
        User(id=user_id, email='staff@example.com', role=UserRole.STAFF, is_active=True),
        Store(id=store_id, owner_id=owner_id, store_name='Shop', store_phone='123'),
        StoreMember(store_id=store_id, user_id=user_id, role='staff', permissions=['messages'], is_active=True),
        FacebookBusinessAccount(id=business_id, business_account_id='f', business_name='x', access_token='test', user_id='u'),
        WhatsAppAccount(id=account_id, business_account_id=business_id, store_id=store_id,
                        waba_id='w', phone_number_id='p', phone_number='123', is_enabled=True),
        Store(id=other_store, owner_id=owner_id, store_name='Other shop', store_phone='456'),
        WhatsAppAccount(id=other_account, business_account_id=business_id, store_id=other_store,
                        waba_id='w2', phone_number_id='p2', phone_number='456', is_enabled=True),
        *[WhatsAppMessage(whatsapp_account_id=account_id, message_id=f'm{i}', from_number='0771234567',
                          to_number='123', message_type='text', direction='inbound', message_text=f'message {i}')
          for i in range(210)],
        WhatsAppMessage(whatsapp_account_id=account_id, message_id='international', from_number='+442012345678',
                        to_number='123', message_type='text', direction='inbound', message_text='international', timestamp=datetime(2020, 1, 1)),
        WhatsAppMessage(whatsapp_account_id=other_account, message_id='other', from_number='447000000000',
                        to_number='456', message_type='text', direction='inbound', message_text='private'),
    ])
    db.commit()
app = FastAPI()
app.add_middleware(WhatsAppAccessMiddleware)
app.include_router(whatsapp_router, prefix='/v1')
def get_test_db():
    with Testing() as db:
        yield db
app.dependency_overrides[get_db] = get_test_db
client = TestClient(app)
auth = {'Authorization': 'Bearer ' + jwt_auth.create_access_token(str(user_id), 'staff@example.com', 'staff', str(store_id))}
accounts = client.get(f'/v1/api/whatsapp/store/{store_id}/accounts', headers=auth)
assert accounts.status_code == 200, accounts.text
messages = client.get(f'/v1/api/whatsapp/accounts/{account_id}/messages', headers=auth)
assert messages.status_code == 200, messages.text
summaries = client.get(f'/v1/api/whatsapp/accounts/{account_id}/conversation-summaries', headers=auth)
assert summaries.status_code == 200, summaries.text
contacts = {c['phone_number']: c for c in summaries.json()['conversations']}
assert set(contacts) == {'0771234567', '442012345678'}, contacts.keys()
assert contacts['0771234567']['unread_count'] == 210
filtered = client.get(f'/v1/api/whatsapp/accounts/{account_id}/messages', params={'phone_number': '263771234567', 'limit': 1000}, headers=auth)
assert filtered.status_code == 200 and filtered.json()['total_count'] == 210, filtered.text
assert client.get(f'/v1/api/whatsapp/accounts/{other_account}/conversation-summaries', headers=auth).status_code == 403
service_reply = client.post(f'/v1/api/whatsapp/accounts/{account_id}/send-text', headers=auth,
                            json={'to': '+1 646 589 4168', 'body': 'Hello'})
assert service_reply.status_code == 403, service_reply.text
service_attachment = client.post(f'/v1/api/whatsapp/accounts/{account_id}/send-attachment', headers=auth,
                                 data={'to': '+1 646 589 4168'}, files={'file': ('test.txt', b'test', 'text/plain')})
assert service_attachment.status_code == 403, service_attachment.text
assert client.get(f'/v1/api/whatsapp/accounts/{account_id}/messages').status_code == 401
with Testing() as db:
    member = db.query(StoreMember).first(); member.permissions = []; db.commit()
assert client.get(f'/v1/api/whatsapp/accounts/{account_id}/messages', headers=auth).status_code == 403
print('PASS: assigned messaging access works and permission removal blocks messages')

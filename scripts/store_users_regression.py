"""Exercise store membership, ownership and revoked staff access in memory."""
import sys
from pathlib import Path
from uuid import uuid4

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
from modules.stores.models import Store, StoreSetupSession
from modules.delivery.models import DeliveryZone
from modules.users.auth_router import auth_router
from modules.stores.router import store_router
from modules.delivery.router import delivery_router
from utils.jwt_auth import jwt_auth

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
for table in (User.__table__, Store.__table__, StoreMember.__table__, StoreSetupSession.__table__, DeliveryZone.__table__):
    table.create(engine)
Testing = sessionmaker(bind=engine, autoflush=False)
database.SessionLocal = Testing
with Testing() as db:
    owner = User(id=uuid4(), email='owner@example.com', role=UserRole.OWNER, name='Owner', is_active=True)
    store = Store(id=uuid4(), owner_id=owner.id, store_name='Store', store_phone='123', is_setup_completed=True)
    db.add_all([owner, store]); db.commit()
    owner_id, store_id = owner.id, store.id

app = FastAPI()
for router in (auth_router, store_router, delivery_router):
    app.include_router(router)
def get_test_db():
    with Testing() as db:
        yield db
app.dependency_overrides[get_db] = get_test_db
client = TestClient(app)
def token(user_id, email, role):
    return {'Authorization': 'Bearer ' + jwt_auth.create_access_token(str(user_id), email, role, str(store_id))}
owner_auth = token(owner_id, 'owner@example.com', 'owner')
payload = {'name': 'Staff', 'email': 'staff@example.com', 'role': 'staff', 'permissions': ['deliveries']}
created = client.post(f'/api/auth/stores/{store_id}/members', json=payload, headers=owner_auth)
assert created.status_code == 201, created.text
staff_id, member_id = created.json()['user_id'], created.json()['id']
staff_auth = token(staff_id, 'staff@example.com', 'staff')
assert client.get(f'/api/delivery/zones/store/{store_id}', headers=staff_auth).status_code == 200
assert client.get(f'/api/auth/stores/{store_id}/members', headers=staff_auth).status_code == 403
assert client.post('/api/stores/setup/start', json={'user_id': staff_id}, headers=staff_auth).status_code == 403
assert client.get(f'/api/delivery/zones/store/{store_id}').status_code == 401
updated = client.put(f'/api/auth/stores/{store_id}/members/{member_id}',
                     json={'role': 'staff', 'permissions': ['deliveries'], 'is_active': False}, headers=owner_auth)
assert updated.status_code == 200
assert client.get(f'/api/delivery/zones/store/{store_id}', headers=staff_auth).status_code == 403
print('PASS: owner creates staff, permissions enforced, revoked token denied')

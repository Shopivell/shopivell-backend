"""Exercise password sign-in, lockout and store membership."""
import sys
from pathlib import Path
from unittest.mock import PropertyMock, patch
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from modules.users.models import User, UserRole, StoreMember
from modules.stores.models import Store, StoreSetupSession
from modules.users.auth_router import auth_router
from utils.jwt_auth import get_password_hash
from utils.cache import cache

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
for table in (User.__table__, Store.__table__, StoreMember.__table__, StoreSetupSession.__table__):
    table.create(engine)
with engine.begin() as con:
    con.execute(text('CREATE TABLE agencies (id TEXT, owner_id TEXT)'))
Session = sessionmaker(bind=engine)
owner_id, staff_id, store_id = uuid4(), uuid4(), uuid4()
with Session() as db:
    db.add_all([User(id=owner_id, email='owner@example.com', is_active=True, is_verified=True),
                User(id=staff_id, email='staff@example.com', role=UserRole.STAFF, is_active=True,
                     is_verified=True, password_hash=get_password_hash('secret-pass')),
                Store(id=store_id, owner_id=owner_id, store_name='Shop', store_phone='123', is_setup_completed=True),
                StoreMember(user_id=staff_id, store_id=store_id, role='staff', permissions=['messages'], is_active=True)])
    db.commit()
app = FastAPI(); app.include_router(auth_router)
def get_test_db():
    with Session() as db:
        yield db
app.dependency_overrides[get_db] = get_test_db
client = TestClient(app)
class Counter:
    count = 0
    def eval(self, *args):
        self.count += 1
        return self.count
counter = Counter()
with patch.object(type(cache), 'is_connected', new_callable=PropertyMock, return_value=True), patch.object(cache, '_client', counter):
    payload = {'email':'staff@example.com', 'password':'wrong'}
    assert client.post('/api/auth/password-login', json=payload).status_code == 401
    payload['password'] = 'secret-pass'
    response = client.post('/api/auth/password-login', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['permissions'] == ['messages']
    assert response.json()['store_id'] == str(store_id)
    counter.count = 10
    assert client.post('/api/auth/password-login', json=payload).status_code == 429
with patch.object(type(cache), 'is_connected', new_callable=PropertyMock, return_value=False):
    assert client.post('/api/auth/password-login', json=payload).status_code == 503
print('PASS: password sign-in, permissions, rate limit and unavailable limiter')

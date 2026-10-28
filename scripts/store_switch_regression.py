"""Switch stores and confirm the refreshed token uses the selected store."""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
import database
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from modules.users.models import User, UserRole, StoreMember
from modules.stores.models import Store, StoreSetupSession
from modules.users.auth_router import auth_router
from utils.jwt_auth import jwt_auth
engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
for table in (User.__table__, Store.__table__, StoreMember.__table__, StoreSetupSession.__table__): table.create(engine)
with engine.begin() as c: c.execute(text('CREATE TABLE agencies (id TEXT, owner_id TEXT)'))
Session = sessionmaker(bind=engine, autoflush=False)
database.SessionLocal = Session
owner, first, second = uuid4(), uuid4(), uuid4()
with Session() as db:
    db.add(User(id=owner, email='owner@example.com', role=UserRole.OWNER, is_active=True))
    db.add_all([Store(id=first, owner_id=owner, store_name='First', store_phone='123', is_setup_completed=True),
                Store(id=second, owner_id=owner, store_name='Second', store_phone='123', is_setup_completed=True)])
    db.commit()
app=FastAPI(); app.include_router(auth_router)
def get_test_db():
    with Session() as db: yield db
app.dependency_overrides[get_db]=get_test_db
client=TestClient(app)
tokens=jwt_auth.create_tokens(user_id=str(owner),email='owner@example.com',role='owner',store_id=str(first))
response=client.patch('/api/auth/active-store',json={'store_id':str(second)},headers={'Authorization':'Bearer '+tokens.access_token})
assert response.status_code == 200, response.text
assert jwt_auth.verify_token(response.json()['access_token'],token_type='access')['store_id'] == str(second)
response=client.post('/api/auth/refresh',json={'refresh_token':tokens.refresh_token})
assert response.status_code == 200, response.text
assert jwt_auth.verify_token(response.json()['access_token'],token_type='access')['store_id'] == str(second)
assert client.patch('/api/auth/active-store',json={'store_id':str(uuid4())},headers={'Authorization':'Bearer '+tokens.access_token}).status_code == 404
staff = uuid4()
with Session() as db:
    db.add(User(id=staff, email='staff@example.com', role=UserRole.STAFF, is_active=True))
    db.add_all([StoreMember(user_id=staff, store_id=first, role='staff', permissions=['messages'], is_active=True),
                StoreMember(user_id=staff, store_id=second, role='manager', permissions=['orders'], is_active=True)])
    db.commit()
staff_tokens=jwt_auth.create_tokens(user_id=str(staff),email='staff@example.com',role='staff',store_id=str(first))
switched=client.patch('/api/auth/active-store',json={'store_id':str(second)},headers={'Authorization':'Bearer '+staff_tokens.access_token})
assert switched.status_code == 200, switched.text
assert switched.json()['permissions'] == ['orders']
assert jwt_auth.verify_token(switched.json()['access_token'],token_type='access')['store_id'] == str(second)
print('PASS: store selection persists, refresh uses it, and inaccessible stores are rejected')

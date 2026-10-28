"""Exercise profile password changes without touching real accounts."""
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from database import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from modules.users.models import User
from modules.users.user_router import user_router
from utils.jwt_auth import get_current_user, get_password_hash, verify_password

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
User.__table__.create(engine)
Session = sessionmaker(bind=engine)
uid, other_id = uuid4(), uuid4()
with Session() as db:
    db.add(User(id=uid, email='person@example.com', is_active=True, password_hash=get_password_hash('old password')))
    db.commit()
app = FastAPI()
app.include_router(user_router)
def db_override():
    with Session() as db:
        yield db
app.dependency_overrides[get_db] = db_override
app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uid)
client = TestClient(app)
assert client.get(f'/api/users/{uid}/password-status').json()['has_password'] is True
assert client.post(f'/api/users/{other_id}/password', json={'new_password':'new password'}).status_code == 403
assert client.post(f'/api/users/{uid}/password', json={'current_password':'wrong', 'new_password':'new password'}).status_code == 400
assert client.post(f'/api/users/{uid}/password', json={'current_password':'old password', 'new_password':'new password'}).status_code == 200
with Session() as db:
    assert verify_password('new password', db.query(User).filter(User.id == uid).one().password_hash)
print('PASS: only account owner can change password; old password is verified')

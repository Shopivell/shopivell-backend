"""Voice calls remain scoped to the selected store and cannot dial another store's number."""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import get_db
from modules.users.models import User, UserRole, StoreMember
from modules.stores.models import Store
from modules.voice import router
from utils.jwt_auth import jwt_auth

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
for table in (User.__table__, Store.__table__, StoreMember.__table__): table.create(engine)
Session = sessionmaker(bind=engine)
owner, other, store_id, other_store = [uuid4() for _ in range(4)]
with Session() as db:
    db.add_all([User(id=owner, email='voice@example.com', role=UserRole.OWNER, is_active=True),
                User(id=other, email='other@example.com', role=UserRole.OWNER, is_active=True),
                Store(id=store_id, owner_id=owner, store_name='First', store_phone='123', zernio_profile_id='first'),
                Store(id=other_store, owner_id=other, store_name='Second', store_phone='456', zernio_profile_id='second')])
    db.commit()
requests = []
async def fake_request(method, path, **kwargs):
    requests.append((method, path, kwargs))
    if path == '/phone-numbers':
        return {'numbers': [{'_id':'own', 'profileId':'first', 'phoneNumber':'+14155550100', 'pstnVoiceEnabled':True, 'pstnForwardTo':'sip:agent@example.com'},
                            {'_id':'other', 'profileId':'second', 'phoneNumber':'+14155550200', 'pstnVoiceEnabled':True, 'pstnForwardTo':'sip:other@example.com'}]}
    if path == '/voice/calls': return {'callId':'test', 'status':'dialing'}
    return {'perMinuteUsd':0.1}
router._request = fake_request
app=FastAPI(); app.include_router(router.voice_router)
def db_override():
    with Session() as db: yield db
app.dependency_overrides[get_db]=db_override
client=TestClient(app)
auth={'Authorization':'Bearer '+jwt_auth.create_access_token(str(owner),'voice@example.com','owner',str(store_id))}
base=f'/api/voice/stores/{store_id}'
r=client.get(base+'/numbers',headers=auth); assert r.status_code==200 and [x['id'] for x in r.json()['numbers']]==['own'],r.text
payload={'number_id':'other','to':'+263771234567','request_id':str(uuid4())}
assert client.post(base+'/calls',headers=auth,json=payload).status_code==404
assert client.get(f'/api/voice/stores/{other_store}/numbers',headers=auth).status_code==403
assert client.get(base+'/numbers').status_code==401
payload['number_id']='own'; r=client.post(base+'/calls',headers=auth,json=payload)
assert r.status_code==200 and r.json()['status']=='dialing',r.text
call=requests[-1]; assert call[2]['body']['fromNumber']=='+14155550100' and str(call[2]['idempotency_key'])==payload['request_id']
assert client.post(base+'/calls',headers=auth,json={**payload,'to':'0771234567'}).status_code==400
print('PASS: store isolation, number ownership, E.164 validation and call idempotency')

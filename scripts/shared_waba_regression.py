"""Separate phone numbers in the same WABA must remain owned by their stores."""
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4
os.environ['ALLOW_PLAINTEXT_TOKENS'] = 'true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import all_models  # noqa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from modules.users.models import User, UserRole
from modules.stores.models import Store
from modules.business.models import FacebookBusinessAccount
from modules.whatsapp.models import WhatsAppAccount
from modules.openclaw import router

engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
for table in (User.__table__,Store.__table__,FacebookBusinessAccount.__table__,WhatsAppAccount.__table__): table.create(engine)
Session=sessionmaker(bind=engine,expire_on_commit=False)
owner=uuid4(); sid1=uuid4();sid2=uuid4()
with Session() as db:
 db.add(User(id=owner,email='owner@example.com',role=UserRole.OWNER,is_active=True))
 db.add_all([Store(id=sid1,owner_id=owner,store_name='One',store_phone='1',zernio_profile_id='one'),Store(id=sid2,owner_id=owner,store_name='Two',store_phone='2',zernio_profile_id='two')]);db.commit()
 s1=db.query(Store).filter_by(id=sid1).one();s2=db.query(Store).filter_by(id=sid2).one()
 a1={'platform':'whatsapp','_id':'z1','metadata':{'wabaId':'shared','phoneNumberId':'phone1','displayPhoneNumber':'+263771111111'}}
 a2={'platform':'whatsapp','_id':'z2','metadata':{'wabaId':'shared','phoneNumberId':'phone2','displayPhoneNumber':'+263772222222'}}
 one=router._ensure_sandbox_wa_account(db,s1,a1);two=router._ensure_sandbox_wa_account(db,s2,a2);db.commit()
 assert one.id!=two.id and one.store_id==sid1 and two.store_id==sid2
 try: router._ensure_sandbox_wa_account(db,s2,a1); raise AssertionError('cross-store reassignment allowed')
 except ValueError: pass
 router.SessionLocal=Session
 async def lookup(method,path,**kwargs): return {'accounts':[a1,a2]}
 router._zernio=lookup
 assert asyncio.run(router._zernio_account_id_for_wa(two))=='z2'
 print('PASS: shared WABA numbers remain isolated and send through their own phone account')

"""Recover a store inbox from its Zernio account; dry-run by default.

Moves only message IDs verified in the provider's selected account and only from
an explicitly named source store. Existing conversation IDs are preserved.
"""
import argparse
import asyncio
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from database import SessionLocal
from modules.stores.models import Store
from modules.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage
from modules.openclaw.router import _ensure_sandbox_wa_account, _persist_sandbox_message, _zernio

async def pages(path, params):
    result=[]; cursor=None; seen=set()
    while True:
        query={**params}
        if cursor: query['cursor']=cursor
        data=await _zernio('GET',path,params=query)
        rows=data.get('data') or data.get('messages') or []
        if not isinstance(rows,list): raise RuntimeError('Unexpected provider response')
        result.extend(rows)
        pagination=data.get('pagination') or {}; next_cursor=pagination.get('nextCursor')
        if not pagination.get('hasMore'): break
        if not next_cursor or next_cursor in seen: raise RuntimeError('Invalid pagination cursor')
        seen.add(next_cursor);cursor=next_cursor
    return result

async def run(args):
    db=SessionLocal()
    try:
        store=db.query(Store).filter(Store.id==args.store_id).one()
        listing=await _zernio('GET','/accounts',params={'profileId':store.zernio_profile_id})
        accounts=[a for a in listing.get('accounts',[]) if a.get('platform')=='whatsapp']
        if len(accounts)!=1: raise RuntimeError('Expected exactly one connected WhatsApp account')
        account=accounts[0]; aid=account.get('_id') or account.get('id'); meta=account.get('metadata') or {}
        profile=account.get('profileId') or account.get('profile')
        if isinstance(profile,dict): profile=profile.get('_id') or profile.get('id')
        if str(profile)!=str(store.zernio_profile_id) or not aid or not meta.get('wabaId') or not meta.get('phoneNumberId'):
            raise RuntimeError('Provider account identity could not be verified')
        conversations=await pages('/inbox/conversations',{'platform':'whatsapp','limit':50,'accountId':aid})
        all_messages=[]; phones=set()
        for conv in conversations:
            owner=conv.get('accountId')
            if isinstance(owner,dict): owner=owner.get('_id') or owner.get('id')
            if str(owner)!=str(aid): raise RuntimeError('Provider returned another account conversation')
            cid=conv.get('id'); phone=(conv.get('participantId') or conv.get('participantUsername') or '').lstrip('+')
            if not cid or not phone: raise RuntimeError('Conversation missing identity')
            phones.add(phone)
            for msg in await pages(f'/inbox/conversations/{cid}/messages',{'limit':200,'accountId':aid}):
                if msg.get('accountId') and str(msg['accountId'])!=str(aid): raise RuntimeError('Provider returned another account message')
                if not (msg.get('id') or msg.get('platformMessageId')): raise RuntimeError('Message missing provider identity')
                all_messages.append((conv,phone,msg))
        wa=_ensure_sandbox_wa_account(db,store,account)
        source_accounts=db.query(WhatsAppAccount).filter(WhatsAppAccount.store_id==args.source_store_id,WhatsAppAccount.waba_id==wa.waba_id).all()
        source_ids=[a.id for a in source_accounts]
        message_ids={str(m.get('id') or m.get('platformMessageId')) for _,_,m in all_messages}
        moved=0
        for msg in db.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_account_id.in_(source_ids),WhatsAppMessage.message_id.in_(message_ids)).all():
            if db.query(WhatsAppMessage.id).filter(WhatsAppMessage.whatsapp_account_id==wa.id,WhatsAppMessage.message_id==msg.message_id).first():
                raise RuntimeError('Message already exists in target and source; review required')
            msg.whatsapp_account_id=wa.id
            business='+'+re.sub(r'\D','',wa.phone_number or '')
            if msg.direction=='inbound': msg.to_number=business
            elif msg.direction=='outbound': msg.from_number=business
            moved+=1
        relocated=0
        for conv in db.query(WhatsAppConversation).filter(WhatsAppConversation.store_id==store.id,WhatsAppConversation.whatsapp_account_id.in_(source_ids)).all():
            if conv.phone_number.lstrip('+') not in phones: continue
            if db.query(WhatsAppConversation.id).filter(WhatsAppConversation.whatsapp_account_id==wa.id,WhatsAppConversation.phone_number==conv.phone_number).first():
                raise RuntimeError('Conversation already exists in target; review required')
            conv.whatsapp_account_id=wa.id;relocated+=1
        db.flush()
        before=db.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_account_id==wa.id).count()
        for conv,phone,msg in all_messages:
            direction='inbound' if msg.get('direction') in ('incoming','in','inbound') else 'outbound'
            date=msg.get('createdAt') or msg.get('sentAt'); ts=None
            if date: ts=datetime.fromisoformat(str(date).replace('Z','+00:00')).replace(tzinfo=None)
            _persist_sandbox_message(db,wa,phone,conv.get('participantName') or '',direction,msg.get('message') or msg.get('text') or '',msg.get('id') or msg.get('platformMessageId'),ts)
        db.flush()
        total=db.query(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_account_id==wa.id).count()
        print(f"{'Applied' if args.apply else 'Dry run'}: {len(conversations)} provider conversations, {len(all_messages)} provider messages; {moved} matched messages and {relocated} conversation records moved; {total-before} messages imported; {total} messages in target")
        if args.apply: db.commit()
        else: db.rollback()
    except Exception:
        db.rollback(); raise
    finally: db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--store-id',type=uuid.UUID,required=True)
    parser.add_argument('--source-store-id',type=uuid.UUID,required=True)
    parser.add_argument('--apply',action='store_true')
    asyncio.run(run(parser.parse_args()))

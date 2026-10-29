"""Store-scoped regular phone calling through Zernio."""
import re
import uuid
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from modules.stores.models import Store
from modules.whatsapp.faq_router import check_store_access
from modules.whatsapp.router import _authorize_message_store
from utils.jwt_auth import get_current_user

voice_router = APIRouter(prefix='/api/voice', tags=['Voice'])


def _store(db, user, store_id, *, manage=False):
    if manage:
        if not check_store_access(db, user, store_id):
            raise HTTPException(status_code=403, detail='Not authorized to manage voice settings')
    else:
        _authorize_message_store(db, user, store_id)
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail='Store not found')
    if not store.zernio_profile_id:
        raise HTTPException(status_code=400, detail='Connect a Zernio profile for this store first')
    return store


async def _request(method, path, *, params=None, body=None, idempotency_key=None):
    from modules.openclaw.router import ZERNIO_API_BASE, ZERNIO_API_KEY
    if not ZERNIO_API_KEY:
        raise HTTPException(status_code=503, detail='Zernio is not configured')
    headers = {'Authorization': f'Bearer {ZERNIO_API_KEY}'}
    if idempotency_key:
        headers['Idempotency-Key'] = str(idempotency_key)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, f'{ZERNIO_API_BASE}{path}', headers=headers, params=params, json=body)
        if response.status_code >= 400:
            try:
                detail = response.json().get('error') or 'Voice provider request failed'
            except ValueError:
                detail = 'Voice provider request failed'
            raise HTTPException(status_code=response.status_code, detail=str(detail)[:300])
        return response.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail='Could not reach the voice provider')


async def _numbers(profile_id):
    payload = await _request('GET', '/phone-numbers', params={'profileId': profile_id})
    rows = payload.get('numbers')
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail='Unexpected response from voice provider')
    def belongs(row):
        profile = row.get('profileId')
        if isinstance(profile, dict):
            profile = profile.get('_id') or profile.get('id')
        return str(profile or '') == str(profile_id)
    return [row for row in rows if isinstance(row, dict) and belongs(row)]


async def _number(profile_id, number_id):
    for number in await _numbers(profile_id):
        if str(number.get('_id') or number.get('id') or '') == number_id:
            return number
    raise HTTPException(status_code=404, detail='Phone number not found for this store')


class VoiceDestination(BaseModel):
    forward_to: str = Field(min_length=5, max_length=500)


class VoiceCall(BaseModel):
    number_id: str = Field(min_length=1, max_length=100)
    to: str = Field(min_length=8, max_length=16)
    request_id: uuid.UUID


@voice_router.get('/stores/{store_id}/numbers')
async def list_numbers(store_id: uuid.UUID, db: Session = Depends(get_db), user=Depends(get_current_user)):
    store = _store(db, user, store_id)
    rows = await _numbers(store.zernio_profile_id)
    return {'numbers': [{'id': str(n.get('_id') or n.get('id') or ''),
                         'phone_number': n.get('phoneNumber'), 'status': n.get('status'),
                         'voice_enabled': bool(n.get('pstnVoiceEnabled')),
                         'forward_to': n.get('pstnForwardTo') or None} for n in rows]}


@voice_router.put('/stores/{store_id}/numbers/{number_id}/destination')
async def set_destination(store_id: uuid.UUID, number_id: str, data: VoiceDestination,
                          db: Session = Depends(get_db), user=Depends(get_current_user)):
    store = _store(db, user, store_id, manage=True)
    await _number(store.zernio_profile_id, number_id)
    destination = data.forward_to.strip()
    if not (re.fullmatch(r'tel:\+[1-9]\d{7,14}', destination) or
            re.fullmatch(r'sip:[^\s<>]{3,495}', destination) or
            re.fullmatch(r'wss://[^\s<>]{3,490}', destination)):
        raise HTTPException(status_code=400, detail='Use a tel:+number, sip: address or wss:// address')
    result = await _request('POST', f'/phone-numbers/{quote(number_id, safe="")}/voice', body={'forwardTo': destination})
    return {'voice_enabled': bool(result.get('enabled')), 'forward_to': result.get('pstnForwardTo')}


@voice_router.get('/stores/{store_id}/estimate')
async def estimate_call(store_id: uuid.UUID, to: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _store(db, user, store_id)
    if not re.fullmatch(r'\+[1-9]\d{7,14}', to):
        raise HTTPException(status_code=400, detail='Enter a phone number in international format, e.g. +263...')
    return await _request('GET', '/voice/calls/estimate', params={'to': to, 'minutes': 1})


@voice_router.post('/stores/{store_id}/calls')
async def place_call(store_id: uuid.UUID, data: VoiceCall, db: Session = Depends(get_db), user=Depends(get_current_user)):
    store = _store(db, user, store_id, manage=True)
    if not re.fullmatch(r'\+[1-9]\d{7,14}', data.to):
        raise HTTPException(status_code=400, detail='Enter a phone number in international format, e.g. +263...')
    number = await _number(store.zernio_profile_id, data.number_id)
    if not number.get('pstnVoiceEnabled') or not number.get('pstnForwardTo') or not number.get('phoneNumber'):
        raise HTTPException(status_code=400, detail='Set up a voice-enabled number and destination first')
    result = await _request('POST', '/voice/calls', body={'fromNumber': number['phoneNumber'], 'to': data.to}, idempotency_key=data.request_id)
    return {'call_id': result.get('callId'), 'status': result.get('status')}

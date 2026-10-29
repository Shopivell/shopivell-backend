"""Do not let WhatsApp service notifications trigger bot replies."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa
from modules.openclaw import router
from modules.whatsapp.system_contacts import is_whatsapp_service_number

assert is_whatsapp_service_number('+1 646 589 4168')
assert is_whatsapp_service_number('0016465894168')
assert not is_whatsapp_service_number('+263771234567')
class DB:
    def close(self): pass
    def rollback(self): pass
router.SessionLocal = DB
router._is_message_duplicate = lambda _: False
router._resolve_bot_store = lambda db, account: SimpleNamespace(id='store')
router._ensure_sandbox_wa_account = lambda db, store, account: None
async def forbidden(*args, **kwargs): raise AssertionError('Service notification reached the bot or provider')
router._zernio = forbidden
router._generate_bot_reply = forbidden
payload={'message':{'id':'service-test','platform':'whatsapp','direction':'incoming',
                    'conversationId':'conversation','text':'Continue setting up your account',
                    'sender':{'phoneNumber':'+1 646 589 4168','name':'WhatsApp Business'}},
         'account':{'id':'account'}}
asyncio.run(router._handle_inbound_whatsapp(payload))
print('PASS: service notification does not reach bot generation or outbound messaging')

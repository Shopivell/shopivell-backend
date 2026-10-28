"""Automatic status checks schedule notifications only for final outcomes."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from modules.jobs.handlers import poll_whatsapp_payment, notify_whatsapp_payment

order = SimpleNamespace(id=uuid4(), payment_status='processing')
class DB:
    def query(self, *args): return self
    def filter(self, *args): return self
    def first(self): return order
    def close(self): pass
class Service:
    result = 'processing'
    def __init__(self, db): pass
    def check_payment_status(self, order_id):
        if self.result != 'processing': order.payment_status = self.result
        return {'status': self.result}
payload = {'order_id': str(order.id)}
with patch('modules.jobs.handlers.SessionLocal', return_value=DB()), \
     patch('modules.whatsapp.payment_service.WhatsAppPaymentService', Service), \
     patch('modules.jobs.queue.enqueue', return_value='job') as enqueue:
    try:
        poll_whatsapp_payment(payload)
        raise AssertionError('Pending must be retried')
    except RuntimeError:
        pass
    assert not enqueue.called
    Service.result = 'cancelled'
    assert poll_whatsapp_payment(payload)['status'] == 'cancelled'
    assert enqueue.call_args.args[1]['status'] == 'cancelled'
    assert poll_whatsapp_payment(payload)['status'] == 'cancelled'
    assert enqueue.call_count == 1
    with patch('modules.whatsapp.router._notify_payment_result', new_callable=AsyncMock) as notify:
        assert asyncio.run(notify_whatsapp_payment({**payload, 'status':'cancelled'}))['status'] == 'sent'
        assert notify.await_count == 1
print('PASS: pending payments retry, terminal results schedule a notification once')

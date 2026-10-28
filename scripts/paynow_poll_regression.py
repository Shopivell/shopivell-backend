"""Reject forged polling responses and distinguish payment outcomes."""
import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.whatsapp.payment_service import WhatsAppPaymentService

os.environ['PAYNOW_INTEGRATION_KEY'] = 'test-key'
class DB:
    def execute(self, *args):
        return SimpleNamespace(fetchone=lambda: ('processing', '123', 'https://www.paynow.co.zw/poll/123', 15, 'PP-123'))
    def commit(self): pass
class Response:
    status_code = 200
    def __init__(self, status, signature=True):
        fields = [('reference', 'Order PP-123'), ('paynowreference', '123'), ('amount', '15.00'), ('status', status)]
        digest = hashlib.sha512((''.join(v for _, v in fields) + 'test-key').encode()).hexdigest().upper()
        self.text = urlencode(fields + [('hash', digest if signature else 'BAD')])
    def raise_for_status(self): pass
service = WhatsAppPaymentService.__new__(WhatsAppPaymentService)
service.db, service.paynow = DB(), object()
updates = []
service._update_order_payment = lambda order_id, **kwargs: updates.append(kwargs)
with patch('requests.post', return_value=Response('Paid', False)):
    assert service.check_payment_status('id')['status'] == 'unavailable'
    assert not updates
with patch('requests.post', return_value=Response('Failed')):
    assert service.check_payment_status('id')['status'] == 'failed'
    assert updates[-1]['payment_status'] == 'failed'
with patch('requests.post', return_value=Response('Paid')):
    assert service.check_payment_status('id')['paid'] is True
    assert updates[-1]['payment_status'] == 'paid'
print('PASS: signed paid/failed statuses are distinguished and forged status is rejected')

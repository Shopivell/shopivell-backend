"""Provider acceptance is not the same as a successful payment."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.whatsapp.payment_service import WhatsAppPaymentService

class Payment:
    def add(self, *args): pass
class Provider:
    def __init__(self, response): self.response = response
    def create_payment(self, *args): return Payment()
    def send_mobile(self, *args): return self.response

service = WhatsAppPaymentService.__new__(WhatsAppPaymentService)
updates = []
service._update_order_payment = lambda order_id, **data: updates.append(data)
for response, accepted in [
    (SimpleNamespace(success=True, status='Ok', poll_url='https://paynow.example/poll', data={}, instruction='Approve on phone'), True),
    (SimpleNamespace(success=True, status='Failed', poll_url='https://paynow.example/poll', data={'error':'Wallet rejected the request'}), False),
    (SimpleNamespace(success=True, status='Ok', poll_url=None, data={}), False),
    (SimpleNamespace(success=False, status='Error', data={'error':'Insufficient funds'}), False),
]:
    service.paynow = Provider(response)
    with patch('modules.jobs.queue.enqueue', return_value='job-id'):
        result, error = service.initiate_mobile_payment('id', 'order', 10, '0771234567', 'ecocash')
    assert bool(result) is accepted
    assert updates[-1]['payment_status'] == ('processing' if accepted else 'failed')
    if not accepted and 'error' in response.data:
        assert error == response.data['error']
print('PASS: rejected or untrackable provider requests are not reported as accepted')

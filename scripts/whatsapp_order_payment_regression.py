"""Check that payment updates are reflected in the Orders view."""
import ast
import logging
import sys
import types
import uuid
from pathlib import Path

from sqlalchemy import text

source = ast.parse((Path(__file__).resolve().parents[1] / 'modules/whatsapp/payment_service.py').read_text(encoding='utf-8'))
cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and any(
    isinstance(m, ast.FunctionDef) and m.name == '_update_order_payment' for m in n.body))
method = next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == '_update_order_payment')
order_models = types.ModuleType('modules.orders.models')
order_models.CustomerOrder = type('CustomerOrder', (), {'id': object()})
customer_service = types.ModuleType('modules.customers.paid_order')
customer_service.link_paid_order_customer = lambda *args: None
cache_module = types.ModuleType('utils.cache')
cache_module.cache = types.SimpleNamespace(invalidate_pattern=lambda *args: None)
for name in ('modules', 'modules.orders', 'modules.customers', 'utils'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules['modules.orders.models'] = order_models
sys.modules['modules.customers.paid_order'] = customer_service
sys.modules['utils.cache'] = cache_module
namespace = {'text': text, 'logger': logging.getLogger(__name__), 'uuid': uuid}
exec(compile(ast.Module(body=[method], type_ignores=[]), '<payment>', 'exec'), namespace)

class DB:
    def __init__(self):
        self.calls = []
        self.committed = False
    def execute(self, statement, params): self.calls.append((str(statement), params))
    def commit(self): self.committed = True
    def rollback(self): raise AssertionError('Unexpected rollback')
    def query(self, *args): return self
    def filter(self, *args): return self
    def first(self): return None

for status, expected in [('processing', 'unpaid'), ('failed', 'failed'), ('cancelled', 'cancelled'), ('paid', 'paid'), ('refunded', 'refunded')]:
    db = DB()
    service = type('Service', (), {'db': db})()
    namespace['_update_order_payment'](service, str(uuid.uuid4()), payment_status=status)
    assert db.committed and len(db.calls) == 2
    assert 'customer_orders' in db.calls[1][0] and db.calls[1][1]['status'] == expected

print('PASS: payment state in Orders follows the verified WhatsApp payment state')

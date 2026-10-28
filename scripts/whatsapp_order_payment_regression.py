"""Check that payment updates are reflected in the Orders view."""
import ast
import logging
from pathlib import Path

from sqlalchemy import text

source = ast.parse((Path(__file__).resolve().parents[1] / 'modules/whatsapp/payment_service.py').read_text(encoding='utf-8'))
cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and any(
    isinstance(m, ast.FunctionDef) and m.name == '_update_order_payment' for m in n.body))
method = next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == '_update_order_payment')
namespace = {'text': text, 'logger': logging.getLogger(__name__)}
exec(compile(ast.Module(body=[method], type_ignores=[]), '<payment>', 'exec'), namespace)

class DB:
    def __init__(self):
        self.calls = []
        self.committed = False
    def execute(self, statement, params): self.calls.append((str(statement), params))
    def commit(self): self.committed = True
    def rollback(self): raise AssertionError('Unexpected rollback')

for status, expected in [('processing', 'unpaid'), ('failed', 'unpaid'), ('paid', 'paid'), ('refunded', 'refunded')]:
    db = DB()
    service = type('Service', (), {'db': db})()
    namespace['_update_order_payment'](service, 'order-id', payment_status=status)
    assert db.committed and len(db.calls) == 2
    assert 'customer_orders' in db.calls[1][0] and db.calls[1][1]['status'] == expected

print('PASS: payment state in Orders follows the verified WhatsApp payment state')

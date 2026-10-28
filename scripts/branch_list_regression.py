"""Branch FAQ entries must supplement, not fabricate, catalogue branches."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from modules.openclaw.router import _listed_store_branches

answer = '''We have four branches:
1. Express Care Pharmacy Newlands - Shop 1 Newlands
2. Express Care Pharmacy Avenues - Harare
3. Bonda Pharmacy - Nyanga
4. Express Care Pharmacy Murambinda - Murambinda'''
class Query:
    def filter(self, *args): return self
    def order_by(self, *args): return self
    def all(self): return [SimpleNamespace(question='Where are your branches?', answer=answer)]
class DB:
    def query(self, *args): return Query()
store = SimpleNamespace(id=uuid4(), store_name='Express Care Pharmacy')
with patch('modules.openclaw.router._store_branches', return_value=['Murambinda', 'Newlands']):
    assert _listed_store_branches(DB(), store) == ['Newlands', 'Avenues', 'Bonda Pharmacy', 'Murambinda']
print('PASS: all FAQ branches are listed and catalogue branches are not duplicated')

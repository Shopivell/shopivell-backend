"""General product answers should reflect the selected store's catalogue."""
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from modules.openclaw.router import _catalogue_categories_reply, _is_general_catalogue_request

class DB:
    def __init__(self, entries): self.entries = entries
    def execute(self, query, params):
        entries = [(title, content) for title, content, branch in self.entries
                   if not params.get('branch') or branch.lower() == params['branch'].lower()]
        return SimpleNamespace(fetchall=lambda: entries)
store = SimpleNamespace(id=uuid4())
entries = [('DOVE BABY SHAMPOO', 'baby shampoo', 'Newlands'),
           ('COLGATE TOOTHPASTE', 'toothpaste', 'Newlands'),
           ('LISTERINE MOUTHWASH', 'mouthwash', 'Newlands'),
           ('BODY LOTION', 'lotion', 'Murambinda')]
assert _is_general_catalogue_request('What products do you sell?')
assert _is_general_catalogue_request('Hi, what do you offer?')
assert not _is_general_catalogue_request('What medicine should I take for a headache?')
reply = _catalogue_categories_reply(DB(entries), store, 'Newlands')
assert 'Baby products' in reply and 'Oral care' in reply and 'Haircare' in reply
assert 'First aid' not in reply and 'Vitamins and supplements' not in reply
assert 'no online product list' in _catalogue_categories_reply(DB(entries), store, 'Avenues').lower().replace('don’t have an', 'no')
print('PASS: general categories come from the selected branch catalogue')

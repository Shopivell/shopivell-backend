"""Verify a bot order and its delivery are committed together, without a database."""
import ast, logging, sys, types, uuid
from pathlib import Path
source = ast.parse((Path(__file__).resolve().parents[1] / 'modules/openclaw/router.py').read_text(encoding='utf-8'))
node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == '_create_order')
class Delivery:
    def __init__(self, **kw): self.__dict__.update(kw); self.id = uuid.uuid4()
class Tracking:
    def __init__(self, **kw): self.__dict__.update(kw)
module = types.ModuleType('modules.delivery.models')
module.Delivery, module.DeliveryTracking = Delivery, Tracking
module.DeliveryStatus = types.SimpleNamespace(PENDING='PENDING')
sys.modules['modules.delivery.models'] = module
class CustomerOrder:
    def __init__(self, **kw): self.__dict__.update(kw)
order_module = types.ModuleType('modules.orders.models')
order_module.CustomerOrder = CustomerOrder
sys.modules['modules.orders.models'] = order_module
class DB:
    def __init__(self): self.added=[]; self.committed=False; self.rolled_back=False
    def execute(self, *args): pass
    def add(self, item): self.added.append(item)
    def flush(self): pass
    def commit(self): self.committed=True
    def rollback(self): self.rolled_back=True
ns={'Session':object,'Dict':dict,'Optional':__import__('typing').Optional,
    '_order_prefix':lambda *args:'PP','_dry_run_store':lambda:None,
    '_update_order_state':lambda *args,**kw:None,'logger':logging.getLogger(__name__)}
exec(compile(ast.Module(body=[node],type_ignores=[]),'<order>','exec'),ns)
db=DB(); data={'customer_name':'Jane Doe','customer_address':'86 Carrick Greagh Road, Harare',
                'delivery_phone':'0771234567','collection_method':'delivery',
                'items':[{'product_name':'Nivea','quantity':1}]}
number=ns['_create_order'](db,str(uuid.uuid4()),'263771111111',data)
assert number and db.committed and len(db.added)==3
assert db.added[0].order_number==number and db.added[0].payment_status=='unpaid'
assert db.added[0].product_name=='Nivea x1' and db.added[0].phone=='0771234567'
assert db.added[1].tracking_number==number and db.added[1].customer_phone=='0771234567'
assert db.added[1].order_id==db.added[0].id
assert db.added[2].delivery_id==db.added[1].id
walk=DB(); ns['_create_order'](walk,str(uuid.uuid4()),'263771111111',dict(data,collection_method='walkin'))
assert walk.committed and len(walk.added)==1 and walk.added[0].delivery_status is None
print('PASS: bot orders appear in Orders, delivery orders also create deliveries')

"""Offline regression checks for checkout retries; no database or model calls."""
import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.openclaw import pharmacy_rules as rules

source = ast.parse((Path(__file__).resolve().parents[1] / 'modules/openclaw/router.py').read_text(encoding='utf-8'))
names = {'_execute_pharmacy_tool', '_resume_checkout', '_delivery_next_state', '_strip_phone_from_text', '_phone_in_text', '_checkout_choice_reply'}
namespace = dict(vars(rules))
namespace.update(logger=__import__("logging").getLogger(__name__), Tuple=__import__("typing").Tuple, List=list, Session=object, Dict=dict, Optional=__import__('typing').Optional, re=re)
state = {'cart_items': [{'product_name': 'Product A', 'price': 20, 'quantity': 1}, {'product_name': 'Product B', 'price': 30, 'quantity': 1}]}
namespace['_get_order_state'] = lambda *args: dict(state)
def update(*args, **values):
    state.update(values)
    return True
namespace['_update_order_state'] = update
for node in source.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'_CHECKOUT_STATES', '_CHECKOUT_COLLECTION_WORDS', '_CHECKOUT_PAYMENT_WORDS'} for t in node.targets):
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<constants>', 'exec'), namespace)
namespace['last_assistant_message'] = lambda history: history[-1]['content']
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names], type_ignores=[]), '<checkout>', 'exec'), namespace)
store = SimpleNamespace(id='platinum', store_name='Platinum Pharmacy')
async def call(tool, **args):
    return await namespace['_execute_pharmacy_tool'](None, store, '263771234567', tool, args)
async def main():
    state['current_state'] = 'awaiting_collection'
    reply = await namespace['_checkout_choice_reply'](True, store, '2', '263771234567',
        [{'role': 'assistant', 'content': '1. Walk-in pick up\n2. Delivery'}])
    assert state['collection_method'] == 'delivery' and 'full name' in reply
    reply = await call('set_collection_method', method='delivery')
    assert 'full name' in reply
    result = await call('set_delivery_details', customer_name='Jane Doe', phone='123', address='670 Ushewekunze Street, Mabelreign, Harare')
    assert 'INCOMPLETE' in result
    assert state['customer_name'] == 'Jane Doe' and state['customer_address']
    await call('set_delivery_details', phone='0771234567')
    assert state['current_state'] == 'payment'
    await call('set_payment_method', method='ecocash', mobile_number='0779876543')
    for tool, args in [('start_checkout', {}), ('set_collection_method', {'method': 'delivery'}), ('start_checkout', {})]:
        result = await call(tool, **args)
        assert 'ORDER SUMMARY' in result and '$50' in result, result
        assert state['current_state'] == 'confirm'
        assert state['payment_phone'] == '0779876543'
        assert state['customer_phone_delivery'] == '0771234567'
    await call('set_delivery_details', phone='0771112222')
    assert state['payment_phone'] == '0779876543'
    state.update(current_state='delivery_step_address', collection_method='delivery',
                 customer_name='Tinotenda Cosmas Nyaruwanga', customer_phone_delivery=None,
                 customer_address=None, payment_method=None, payment_provider=None)
    result = await call('update_delivery_address', address='86 Carrick Greagh Road, Harare')
    assert state['current_state'] == 'delivery_step_phone', (state, result)
    result = await call('set_payment_method', method='cash')
    assert state['current_state'] == 'delivery_step_phone' and 'phone' in result.lower(), result
    result = await call('confirm_order')
    assert 'DELIVERY PHONE MISSING' in result, result
    assert rules.looks_like_person_name('Tinotenda Cosmas Nyaruwanga')
    assert rules.looks_like_person_name('Christopher Moyo')
    print('PASS: missing delivery phone blocks payment summary and confirmation; full names accepted')
    print('PASS: partial details, corrected phone, separate wallet, repeated checkout and delivery selection')
asyncio.run(main())

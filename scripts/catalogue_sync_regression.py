"""Exercise branch-specific product and bot-catalogue synchronization."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from modules.products.models import Product
from modules.products.catalogue_sync import parse_catalogue_content, sync_product_to_bot
from modules.whatsapp.models import CompanyKnowledge

engine = create_engine('sqlite:///:memory:')
Product.__table__.create(engine)
CompanyKnowledge.__table__.create(engine)
store_id, knowledge_id = uuid4(), uuid4()
content = 'Product: NIVEA\nPrice: $15.00\nCategory: COSMETICS\nStock Code: 123\nBranch: Rezende'
parsed = parse_catalogue_content(content)
assert parsed['in_stock'] is None and parsed['price'] == 15
with Session(engine) as db:
    product = Product(id=knowledge_id, store_id=store_id, branch='Rezende', inventory_tracked=False,
                      status='Active', **parsed)
    entry = CompanyKnowledge(id=knowledge_id, store_id=store_id, source_id=knowledge_id,
        content_type='product', content=content, title='NIVEA', branch='Rezende', is_active=True)
    db.add_all([product, entry]); db.commit()
    product.price, product.in_stock = 16, False
    sync_product_to_bot(db, product); db.commit()
    assert 'Price: $16.00' in entry.content and 'In Stock: No' in entry.content
    assert entry.branch == 'Rezende'
    product.in_stock = None
    sync_product_to_bot(db, product); db.commit()
    assert 'In Stock:' not in entry.content
print('PASS: branch catalogue preserves price and unknown stock')

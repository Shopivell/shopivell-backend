"""Keep a product and its bot catalogue entry in the same transaction."""
import re
from datetime import datetime
from sqlalchemy.orm import load_only

from modules.whatsapp.models import CompanyKnowledge


def sync_product_to_bot(db, product):
    entry = db.query(CompanyKnowledge).options(load_only(
        CompanyKnowledge.id, CompanyKnowledge.store_id, CompanyKnowledge.content_type,
        CompanyKnowledge.source_id, CompanyKnowledge.title, CompanyKnowledge.content,
        CompanyKnowledge.branch, CompanyKnowledge.is_active, CompanyKnowledge.updated_at)).filter(
        CompanyKnowledge.store_id == product.store_id,
        CompanyKnowledge.content_type == 'product',
        CompanyKnowledge.source_id == product.id).first()
    fields = {
        'Product': product.title,
        'Description': product.description,
        'Price': f'${product.price:.2f}',
        'Category': product.category,
        'Stock Code': product.sku if product.sku and product.sku != 'No SKU' else None,
        'Barcode': product.barcode,
        'Branch': product.branch,
        'In Stock': ('Yes' if product.in_stock else 'No') if product.in_stock is not None else None,
    }
    if not entry:
        content = '\n'.join(f'{key}: {value}' for key, value in fields.items() if value is not None)
        entry = CompanyKnowledge(store_id=product.store_id, source_id=product.id,
            content_type='product', category='product', title=product.title,
            content=content, branch=product.branch, is_active=product.status.lower() == 'active')
        db.add(entry)
    else:
        lines = entry.content.splitlines()
        matched = set()
        result = []
        for line in lines:
            label, separator, _ = line.partition(':')
            if separator and label in fields:
                matched.add(label)
                value = fields[label]
                if value is not None:
                    result.append(f'{label}: {value}')
            else:
                result.append(line)
        result.extend(f'{label}: {value}' for label, value in fields.items()
                      if label not in matched and value is not None)
        entry.title = product.title
        entry.content = '\n'.join(result)
        entry.branch = product.branch
        entry.is_active = (product.status or '').lower() == 'active'
        entry.updated_at = datetime.utcnow()
    return entry


def parse_catalogue_content(content, fallback_title=None):
    values = {}
    for line in (content or '').splitlines():
        key, separator, value = line.partition(':')
        if separator:
            values[key.strip().lower()] = value.strip()
    name = values.get('product') or fallback_title
    raw_price = (values.get('price') or '').replace('$', '').replace(',', '').strip()
    if not name or not re.fullmatch(r'\d+(?:\.\d+)?', raw_price):
        return None
    stock = (values.get('in stock') or '').lower()
    return {'title': name[:255], 'price': float(raw_price), 'description': values.get('description'),
            'category': (values.get('category') or '')[:100] or None,
            'sku': (values.get('stock code') or values.get('sku') or 'No SKU')[:100],
            'barcode': (values.get('barcode') or '')[:100] or None,
            'in_stock': True if stock in ('yes', 'true') else False if stock in ('no', 'false') else None}

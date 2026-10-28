"""Copy existing WhatsApp orders into Orders for one store.

Dry run by default. Use --apply to commit; existing order IDs and numbers are
left untouched. Run against the same configured database as the application.
"""
import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store-id', required=True, type=uuid.UUID)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT w.id, w.order_number, w.customer_name, w.customer_phone,
                   w.customer_address, w.items, w.total_amount, w.collection_method,
                   w.payment_method, w.payment_provider, w.payment_status, w.status,
                   w.created_at,
                   (SELECT d.status FROM deliveries d
                    WHERE d.store_id = w.store_id AND d.tracking_number = w.order_number
                    ORDER BY d.created_at DESC LIMIT 1) AS delivery_status
            FROM whatsapp_orders w
            WHERE w.store_id = :store_id
              AND NOT EXISTS (SELECT 1 FROM customer_orders c
                              WHERE c.id = w.id OR
                              (c.store_id = w.store_id AND c.order_number = w.order_number))
        """), {'store_id': args.store_id}).mappings().all()
        inserted = 0
        for row in rows:
            items = row['items'] or []
            if isinstance(items, str):
                items = json.loads(items)
            items = items if isinstance(items, list) else []
            items = [item for item in items if isinstance(item, dict)]
            summary = ', '.join(f"{item.get('product_name') or 'Item'} x{item.get('quantity') or 1}" for item in items)
            def quantity(item):
                try:
                    return max(0, int(item.get('quantity') or 1))
                except (ValueError, TypeError):
                    return 1
            payment = (row['payment_status'] or '').lower()
            delivery = str(row['delivery_status'] or '').lower()
            delivery = {'assigned': 'pending', 'picked_up': 'in_transit',
                        'cancelled': 'failed', 'returned': 'failed'}.get(delivery, delivery)
            if delivery not in ('pending', 'in_transit', 'out_for_delivery', 'delivered', 'failed'):
                delivery = None
            result = db.execute(text("""
                INSERT INTO customer_orders
                    (id, store_id, order_number, customer_name, phone, total_amount,
                     status, order_date, product_name, quantity, payment_status,
                     payment_method, delivery_status, tracking_info)
                VALUES (:id, :store_id, :number, :name, :phone, :total, :status,
                        :date, :products, :quantity, :payment_status, :payment_method,
                        :delivery_status, :address)
                ON CONFLICT DO NOTHING
            """), {'id': row['id'], 'store_id': args.store_id, 'number': row['order_number'],
                  'name': row['customer_name'] or 'Customer', 'phone': row['customer_phone'],
                  'total': row['total_amount'] or 0, 'status': row['status'] or 'pending',
                  'date': row['created_at'] or datetime.utcnow(), 'products': summary[:255] or None,
                  'quantity': sum(quantity(item) for item in items),
                  'payment_status': 'paid' if payment in ('paid', 'completed') else 'refunded' if payment == 'refunded' else 'unpaid',
                  'payment_method': row['payment_provider'] or row['payment_method'],
                  'delivery_status': delivery if row['collection_method'] == 'delivery' else None,
                  'address': row['order_number'] if row['collection_method'] == 'delivery' else None})
            inserted += result.rowcount
        linked = db.execute(text("""
            UPDATE deliveries d SET order_id = c.id
            FROM customer_orders c JOIN whatsapp_orders w
              ON c.id = w.id AND c.store_id = w.store_id
            WHERE d.store_id = :store_id AND d.store_id = w.store_id
              AND d.tracking_number = w.order_number AND d.order_id IS NULL
        """), {'store_id': args.store_id}).rowcount
        if args.apply:
            db.commit()
            print(f'Created {inserted} order records and linked {linked} deliveries.')
        else:
            db.rollback()
            print(f'Dry run: {inserted} order records and {linked} delivery links would be created.')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()

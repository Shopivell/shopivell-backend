"""Link a store's previously paid orders to customers. Dry run by default."""
import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401 - register ORM relationships
from database import SessionLocal
from modules.customers.paid_order import link_paid_order_customer
from modules.orders.models import CustomerOrder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store-id', required=True, type=uuid.UUID)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    db = SessionLocal()
    try:
        orders = db.query(CustomerOrder).filter(CustomerOrder.store_id == args.store_id,
            CustomerOrder.payment_status == 'paid', CustomerOrder.customer_id.is_(None)).all()
        linked = sum(1 for order in orders if link_paid_order_customer(db, order))
        if args.apply:
            db.commit()
            from utils.cache import cache
            cache.invalidate_pattern('cust:*')
            print(f'Linked {linked} paid orders; {len(orders) - linked} need manual review.')
        else:
            db.rollback()
            print(f'Dry run: {linked} paid orders would be linked; {len(orders) - linked} need manual review.')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()

"""Link existing bot catalogue entries to Products for one store (dry-run default)."""
import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import all_models  # noqa: F401
from database import SessionLocal
from modules.products.catalogue_sync import parse_catalogue_content
from modules.products.models import Product
from modules.whatsapp.models import CompanyKnowledge
from sqlalchemy.orm import load_only


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store-id', required=True, type=uuid.UUID)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    db = SessionLocal()
    try:
        rows = db.query(CompanyKnowledge).options(load_only(
            CompanyKnowledge.id, CompanyKnowledge.store_id, CompanyKnowledge.branch,
            CompanyKnowledge.title, CompanyKnowledge.content, CompanyKnowledge.source_id)).filter(CompanyKnowledge.store_id == args.store_id,
            CompanyKnowledge.content_type == 'product', CompanyKnowledge.is_active.is_(True),
            CompanyKnowledge.source_id.is_(None)).all()
        inserted = skipped = 0
        for entry in rows:
            parsed = parse_catalogue_content(entry.content, entry.title)
            if not parsed or db.query(Product.id).filter(Product.id == entry.id).first():
                skipped += 1
                continue
            product = Product(id=entry.id, store_id=args.store_id, branch=entry.branch,
                              inventory_tracked=False, status='Active', **parsed)
            db.add(product)
            entry.source_id = product.id
            inserted += 1
        db.flush()
        if args.apply:
            db.commit()
            from utils.cache import cache_invalidator
            cache_invalidator.invalidate_product()
            print(f'Created and linked {inserted} products; {skipped} need review.')
        else:
            db.rollback()
            print(f'Dry run: {inserted} products would be created and linked; {skipped} need review.')
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    main()

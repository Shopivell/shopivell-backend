#!/usr/bin/env python3
"""Import the Express Care product API as the store's sellable catalogue.

expresscare.co.zw exposes its own product database:

    GET https://expresscare.co.zw/api/products/            (paginated)
    GET https://expresscare.co.zw/api/products/categories/

Each product carries a name, price, category and branch. This script turns that
into `company_knowledge` rows (the table the pharmacy tools search, price and
sell from), REPLACING whatever product rows the store had, so the bot sells
exactly what the website sells.

Usage
-----
    python scripts/import_expresscare_catalogue.py --sql /tmp/expresscare.sql
    python scripts/import_expresscare_catalogue.py --apply
"""

import argparse
import json
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_branch_catalogue import (  # noqa: E402  (same folder, shared SQL writer)
    _sql_literal, apply_statements,
)

STORE_ID = "76624a45-d935-4479-9706-2efcca8d1589"  # Express Care Pharmacy
DEFAULT_BASE_URL = "https://expresscare.co.zw"
USER_AGENT = "ShopivellCatalogueImporter/1.0"


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def fetch_all(base_url: str):
    """Every product page, plus the category list for the report."""
    products, url, page = [], f"{base_url.rstrip('/')}/api/products/", 0
    while url:
        payload = fetch_json(url)
        page += 1
        products.extend(payload.get("results") or [])
        url = payload.get("next")
        print(f"  page {page}: {len(products)} products so far")
    categories = fetch_json(f"{base_url.rstrip('/')}/api/products/categories/")
    return products, (categories.get("results") if isinstance(categories, dict) else categories) or []


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _price(value):
    try:
        price = round(float(str(value).replace(",", "").replace("$", "").strip()), 2)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _branch_name(slug: str) -> str:
    """'newlands' -> 'Newlands'. The bot and the tools use this exact label."""
    return _clean(slug).title()


def build_catalogue(products):
    """Products grouped by branch, de-duplicated by name within a branch."""
    by_branch, skipped, seen = {}, {"no_name": 0, "no_price": 0, "no_branch": 0,
                                    "duplicate": 0}, set()
    for product in products:
        name = _clean(product.get("name"))
        if not name:
            skipped["no_name"] += 1
            continue
        price = _price(product.get("price"))
        if price is None:
            skipped["no_price"] += 1
            continue
        branch = _branch_name(product.get("branch"))
        if not branch:
            skipped["no_branch"] += 1
            continue
        key = (branch.lower(), name.lower())
        if key in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(key)

        category = _clean((product.get("category") or {}).get("name")) or "General"
        image = _clean(product.get("image_url") or product.get("image"))
        by_branch.setdefault(branch, []).append({
            "name": name[:255],
            "price": price,
            "stock": None,          # the API has no stock field: everything it lists is sellable
            "code": _clean(product.get("id")),
            "barcode": "",
            "category": category[:100],
            "image": image,
            "branch": branch,
        })
    return by_branch, skipped


def content_for(product) -> str:
    lines = [
        f"Product: {product['name']}",
        f"Price: ${product['price']:.2f}",
        f"Category: {product['category']}",
    ]
    if product["code"]:
        lines.append(f"Stock Code: {product['code']}")
    if product.get("image"):
        lines.append(f"Image: {product['image']}")
    lines.append(f"Branch: {product['branch']}")
    return "\n".join(lines)


def build_statements(by_branch):
    """Replace every product row for this store, then insert the API catalogue."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    statements = ["BEGIN",
                  # The API is the store's whole online range: drop old rows from
                  # branches that no longer appear as well as the current ones.
                  "DELETE FROM company_knowledge"
                  f" WHERE store_id = {_sql_literal(STORE_ID)}"
                  "   AND content_type = 'product'"]
    for branch, products in by_branch.items():
        for product in products:
            statements.append(
                "INSERT INTO company_knowledge "
                "(id, store_id, title, content, category, content_type, branch, "
                "is_active, priority, created_at, updated_at) VALUES ("
                f"{_sql_literal(str(uuid.uuid4()))}, {_sql_literal(STORE_ID)}, "
                f"{_sql_literal(product['name'])}, "
                f"{_sql_literal(content_for(product))}, "
                f"{_sql_literal(product['category'])}, 'product', "
                f"{_sql_literal(branch)}, true, 1.0, "
                f"{_sql_literal(now)}, {_sql_literal(now)})"
            )
    statements.append("COMMIT")
    return statements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--sql", help="write the import as a .sql file")
    parser.add_argument("--apply", action="store_true",
                        help="run the import against DATABASE_URL / DB_* settings")
    args = parser.parse_args()

    print(f"Fetching {args.base_url}/api/products/ ...")
    products, categories = fetch_all(args.base_url)
    by_branch, skipped = build_catalogue(products)

    for branch, rows in sorted(by_branch.items()):
        print(f"[{branch}] {len(rows)} products")
    print(f"Categories in API: {len(categories)}")

    total = sum(len(rows) for rows in by_branch.values())
    print(f"Total: {total} products "
          f"(skipped: no price {skipped['no_price']}, duplicate {skipped['duplicate']}, "
          f"no branch {skipped['no_branch']}, no name {skipped['no_name']})")

    statements = build_statements(by_branch)
    header = (f"-- Generated by scripts/import_expresscare_catalogue.py\n"
              f"-- store {STORE_ID}\n-- source {args.base_url}/api/products/\n")
    sql = header + (";\n-- @@\n").join(statements) + ";\n"

    if args.sql:
        with open(Path(args.sql).expanduser(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(sql)
        print(f"SQL written to {args.sql}")
    if args.apply:
        apply_statements(statements)
        print("Applied.")
    if not (args.sql or args.apply):
        print("\nDry run only - pass --sql or --apply to write the catalogue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

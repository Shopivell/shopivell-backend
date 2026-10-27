#!/usr/bin/env python3
"""Import a branch's cosmetics-and-OTC Excel export as the ONLY sellable catalogue.

Platinum Pharmacy's stock system exports one workbook per branch. This script
reads those workbooks and produces (or applies) catalogue rows in
`company_knowledge` - the table every pharmacy search/cart/price path reads:

    Product: PANADOL EXTRA TABS 20S
    Price: $3.50
    Category: OTC
    Stock Code: 4471
    Barcode: 6001234567890
    In Stock: Yes

The import REPLACES the branch's existing product rows, so whatever is in the
workbook is exactly what the bot can sell at that branch.

Usage
-----
    # Write a .sql file to run against the shop database
    python scripts/import_branch_catalogue.py --source ~/Downloads/excel/excel \
        --sql /tmp/branch_catalogue.sql

    # Apply directly using DATABASE_URL / DB_* settings
    python scripts/import_branch_catalogue.py --source ~/Downloads/excel/excel --apply

    # Dry run: parse only, print what would be imported
    python scripts/import_branch_catalogue.py --source ~/Downloads/excel/excel
"""

import argparse
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover - guidance instead of a traceback
    sys.exit("openpyxl is required: pip install openpyxl")

STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"

# branch -> (workbook filename, sheet with cosmetics + OTC in one table)
BRANCH_FILES = {
    "Angwa": ("ANGWA_Cosmetics_and_OTC_Products.xlsx", "Cosmetics_and_OTC"),
    "Bulawayo": ("Bulawayo_Cosmetics_and_OTC_Products.xlsx", "Combined"),
    "Gweru": ("GWERU_Cosmetics_and_OTC_Only.xlsx", "Cosmetics + OTC"),
    "Rezende": ("REZENDE_Cosmetics_and_OTC_Products.xlsx", "Cosmetics_and_OTC"),
}

# Column headings differ between branch exports; accept all of the spellings.
COLUMN_ALIASES = {
    "name": ("descr", "description", "product", "product_name", "item"),
    "price": ("retail", "stock_retail", "retail_price", "price", "selling_price"),
    "stock": ("stockoh", "stock_oh", "stock_on_hand", "on_hand", "qty", "quantity"),
    "code": ("stockcd", "stock_code", "stockcode", "code", "sku"),
    "barcode": ("barcode", "bar_code", "ean"),
    "category": ("depdescr", "category", "department", "dept"),
}


def _norm(value) -> str:
    """Collapse whitespace and drop the 'nan' openpyxl returns for empty cells."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return "" if text.lower() in ("nan", "none", "") else text


def _price(value):
    """Retail price as a float, or None when the cell is empty/unusable."""
    if value is None or str(value).strip() == "":
        return None
    try:
        price = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return round(price, 2) if price > 0 else None


def _stock(value):
    """Units on hand, or None when the export has no stock column."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _columns(header):
    """Map our field names to the column index used by this workbook."""
    found = {}
    normalized = [str(h).strip().lower().replace(" ", "_") if h else "" for h in header]
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                found[field] = normalized.index(alias)
                break
    return found


def read_branch(source: Path, branch: str, filename: str, sheet: str):
    """Products for one branch, de-duplicated by name (first row wins)."""
    path = source / filename
    if not path.exists():
        raise FileNotFoundError(f"{branch}: {path} not found")

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet]
        rows = worksheet.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            return []
        columns = _columns(header)
        if "name" not in columns or "price" not in columns:
            raise ValueError(f"{branch}: could not find name/price columns in {filename}")

        products, seen, skipped = [], set(), {"no_name": 0, "no_price": 0, "duplicate": 0}
        for row in rows:
            def cell(field):
                index = columns.get(field)
                return row[index] if index is not None and index < len(row) else None

            name = _norm(cell("name"))
            if not name:
                skipped["no_name"] += 1
                continue
            price = _price(cell("price"))
            if price is None:
                skipped["no_price"] += 1
                continue
            key = name.lower()
            if key in seen:
                skipped["duplicate"] += 1
                continue
            seen.add(key)

            products.append({
                "branch": branch,
                "name": name[:255],
                "price": price,
                "stock": _stock(cell("stock")),
                "code": _norm(cell("code")),
                "barcode": _norm(cell("barcode")),
                "category": _norm(cell("category")) or "OTC",
            })
        return products, skipped
    finally:
        workbook.close()


def content_for(product) -> str:
    """The knowledge entry the pharmacy tools parse (Product / Price / ...)."""
    lines = [
        f"Product: {product['name']}",
        f"Price: ${product['price']:.2f}",
        f"Category: {product['category']}",
    ]
    if product["code"]:
        lines.append(f"Stock Code: {product['code']}")
    if product["barcode"]:
        lines.append(f"Barcode: {product['barcode']}")
    # No stock column at all (the Rezende report) means "sold here", not "in stock".
    if product["stock"] is not None:
        lines.append(f"In Stock: {'Yes' if product['stock'] > 0 else 'No'}")
    lines.append(f"Branch: {product['branch']}")
    return "\n".join(lines)


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


# Statement separator. The entry content contains real newlines, so SQL cannot be
# split on lines; psql treats this marker as a comment, --apply splits on it.
STATEMENT_MARKER = "-- @@"


def build_statements(products_by_branch: dict, store_id: str = STORE_ID,
                     content_types=("product", "manual"), all_branches: bool = False):
    """The SQL statements that atomically replace each branch's catalogue."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    branches = ", ".join(_sql_literal(b) for b in products_by_branch)
    types = ", ".join(_sql_literal(t) for t in content_types)
    branch_clause = "" if all_branches else f"   AND branch IN ({branches})\n"
    statements = ["BEGIN", (
        "DELETE FROM company_knowledge"
        f" WHERE store_id = {_sql_literal(store_id)}\n"
        + branch_clause +
        f"   AND content_type IN ({types})"
    )]
    for branch, products in products_by_branch.items():
        for product in products:
            statements.append(
                "INSERT INTO company_knowledge "
                "(id, store_id, title, content, category, content_type, branch, "
                "is_active, priority, created_at, updated_at) VALUES ("
                f"{_sql_literal(str(uuid.uuid4()))}, {_sql_literal(store_id)}, "
                f"{_sql_literal(product['name'][:255])}, "
                f"{_sql_literal(content_for(product))}, "
                f"{_sql_literal(product['category'][:100])}, 'product', "
                f"{_sql_literal(branch)}, true, 1.0, "
                f"{_sql_literal(now)}, {_sql_literal(now)})"
            )
    statements.append("COMMIT")
    return statements


def build_sql(products_by_branch: dict, store_id: str = STORE_ID, **kwargs) -> str:
    header = ("-- Generated by scripts/import_branch_catalogue.py\n"
              f"-- store {store_id}\n")
    # Each statement carries its own ';' so psql can execute the file directly.
    return header + (";\n-- @@\n").join(
        build_statements(products_by_branch, store_id, **kwargs)) + ";\n"


def apply_statements(statements):
    """Run the generated statements through the app's own database settings."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlalchemy import text
    from database import engine

    # A single transaction, so a half-written branch can never go live.
    with engine.begin() as connection:
        for statement in statements:
            if statement in ("BEGIN", "COMMIT"):
                continue
            connection.execute(text(statement.rstrip().rstrip(";")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help="directory holding the four branch .xlsx exports")
    parser.add_argument("--sql", help="write the import as a .sql file")
    parser.add_argument("--apply", action="store_true",
                        help="run the import against DATABASE_URL / DB_* settings")
    parser.add_argument("--store-id", default=STORE_ID)
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    products_by_branch, totals = {}, {}
    for branch, (filename, sheet) in BRANCH_FILES.items():
        products, skipped = read_branch(source, branch, filename, sheet)
        products_by_branch[branch] = products
        totals[branch] = (len(products), skipped)
        print(f"[{branch}] {len(products)} sellable rows "
              f"(skipped: no price {skipped['no_price']}, duplicate {skipped['duplicate']}, "
              f"no name {skipped['no_name']})")

    total = sum(len(p) for p in products_by_branch.values())
    print(f"Total: {total} products across {len(products_by_branch)} branches")

    statements = build_statements(products_by_branch, args.store_id)
    if args.sql:
        # newline="\n" matters: CRLF would end up inside the content strings and
        # the product/price parser reads lines by "\n".
        with open(Path(args.sql).expanduser(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(build_sql(products_by_branch, args.store_id))
        print(f"SQL written to {args.sql}")
    if args.apply:
        apply_statements(statements)
        print("Applied.")
    if not (args.sql or args.apply):
        print("\nDry run only - pass --sql or --apply to write the catalogue.")
        print(statements[2][:400] + "\n...")
    return 0


if __name__ == "__main__":
    sys.exit(main())

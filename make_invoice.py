"""Generate a Shopivell invoice for domain + web hosting."""
from datetime import datetime
from utils.invoice_pdf import generate_invoice_pdf

receipt = {
    "receipt_number": "INV-2026-0001",
    "transaction_reference": "SHP-DOMHOST-0001",
    "store_name": "ThinkValley",
    "currency": "USD",
    "completed_at": datetime.now().isoformat(),
    "billing_period": "annual",
    "payment_method": "cash",
    "line_items": [
        {"description": "Domain Name", "subtext": "Domain registration (1 year)",
         "quantity": 1, "unit_price": 2.00},
        {"description": "Web Hosting", "subtext": "Website hosting plan (1 year)",
         "quantity": 1, "unit_price": 3.00},
    ],
}
# Total the generator computes from line items; keep amount in sync for any
# legacy consumers.
receipt["amount"] = sum(i["unit_price"] * i["quantity"] for i in receipt["line_items"])

pdf = generate_invoice_pdf(receipt)
with open("shopivell_invoice.pdf", "wb") as f:
    f.write(pdf)
print(f"Wrote shopivell_invoice.pdf ({len(pdf):,} bytes) — total ${receipt['amount']:.2f}")

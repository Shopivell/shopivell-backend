"""Generate PDF invoice for subscription payments using reportlab."""
import io
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import Color, black, white, HexColor
from reportlab.pdfgen import canvas


LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "shopivell_logo.png")

PAGE_W, PAGE_H = A4
M = 22 * mm
RX = PAGE_W - M
CW = PAGE_W - 2 * M

# Brand palette
BLACK = HexColor("#111111")
DARK = HexColor("#1A1A1A")
BODY = HexColor("#374151")
MUTED = HexColor("#6B7280")
LIGHT_GRAY = HexColor("#F9FAFB")
BORDER = HexColor("#E5E7EB")
GREEN = HexColor("#059669")
GREEN_BG = HexColor("#ECFDF5")
GREEN_TEXT = HexColor("#065F46")
ACCENT = HexColor("#111111")


def _fmt(amount: float, currency: str = "USD") -> str:
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _draw_line(c, x1, y, x2, color=BORDER, width=0.5):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(x1, y, x2, y)


def generate_invoice_pdf(receipt: dict) -> bytes:
    """Return raw PDF bytes for the given receipt dict."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    currency = receipt.get("currency", "USD")

    # ── Top bar ──
    c.setFillColor(BLACK)
    c.rect(0, PAGE_H - 3 * mm, PAGE_W, 3 * mm, fill=1, stroke=0)

    y = PAGE_H - 22 * mm

    # ── Header ──
    logo_sz = 14 * mm
    if os.path.exists(LOGO_PATH):
        try:
            c.drawImage(LOGO_PATH, M, y - logo_sz + 4 * mm, logo_sz, logo_sz,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(BLACK)
    c.drawString(M + logo_sz + 4 * mm, y, "Shopivell")

    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(M + logo_sz + 4 * mm, y - 5 * mm, "shopivell.com")

    # Invoice label (right)
    c.setFont("Helvetica-Bold", 28)
    c.setFillColor(HexColor("#D1D5DB"))
    c.drawRightString(RX, y - 1 * mm, "INVOICE")

    y -= 22 * mm
    _draw_line(c, M, y, RX)
    y -= 14 * mm

    # ── Two-column: Bill To + Invoice Details ──
    mid = M + CW * 0.5

    # Left: Bill To
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(M, y, "BILL TO")
    y -= 5 * mm

    store_name = receipt.get("store_name") or "Customer"
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(DARK)
    c.drawString(M, y, store_name)

    if receipt.get("customer_email"):
        y -= 5 * mm
        c.setFont("Helvetica", 9)
        c.setFillColor(BODY)
        c.drawString(M, y, receipt["customer_email"])

    # Right: Invoice details
    detail_y = y + 10 * mm

    def draw_detail(label, value):
        nonlocal detail_y
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawRightString(RX - 55 * mm, detail_y, label)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(DARK)
        c.drawRightString(RX, detail_y, str(value))
        detail_y -= 6 * mm

    draw_detail("Invoice No.", receipt.get("receipt_number", "—"))
    draw_detail("Reference", receipt.get("transaction_reference", "—"))

    if receipt.get("completed_at"):
        try:
            dt = datetime.fromisoformat(receipt["completed_at"])
            date_str = dt.strftime("%B %d, %Y")
        except Exception:
            date_str = str(receipt["completed_at"])[:10]
        draw_detail("Date", date_str)

    billing = "Annual" if receipt.get("billing_period") == "annual" else "Monthly"
    draw_detail("Billing", billing)

    y = min(y, detail_y) - 12 * mm

    # ── Table ──
    col_desc = M
    col_qty = RX - 68 * mm
    col_unit = RX - 34 * mm
    col_amount = RX

    # Build line items. Supports either a multi-item `line_items` list or the
    # legacy single-package receipt (rendered as one row).
    line_items = receipt.get("line_items")
    if not line_items:
        plan_name = receipt.get("package_name", "").capitalize()
        line_items = [{
            "description": f"{plan_name} Plan — {billing}",
            "subtext": receipt.get("package_description"),
            "quantity": 1,
            "unit_price": receipt["amount"],
        }]

    multi = len(line_items) > 1 or receipt.get("line_items")

    # Normalise amounts
    for it in line_items:
        qty = it.get("quantity", 1)
        it["quantity"] = qty
        it.setdefault("unit_price", it.get("amount", 0) / qty if qty else 0)
        it.setdefault("amount", it["unit_price"] * qty)

    # Table header
    hdr_h = 10 * mm
    c.setFillColor(LIGHT_GRAY)
    c.rect(M, y - 2 * mm, CW, hdr_h, fill=1, stroke=0)
    _draw_line(c, M, y - 2 * mm, RX, BORDER, 0.75)
    _draw_line(c, M, y + hdr_h - 2 * mm, RX, BORDER, 0.75)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(MUTED)
    c.drawString(col_desc + 4 * mm, y + 2 * mm, "DESCRIPTION")
    if multi:
        c.drawCentredString(col_qty, y + 2 * mm, "QTY")
        c.drawRightString(col_unit, y + 2 * mm, "UNIT PRICE")
    c.drawRightString(col_amount - 4 * mm, y + 2 * mm, "AMOUNT")

    y -= hdr_h + 4 * mm

    # Table rows
    subtotal = 0.0
    for it in line_items:
        c.setFont("Helvetica-Bold", 10.5)
        c.setFillColor(DARK)
        c.drawString(col_desc + 4 * mm, y + 2 * mm, str(it["description"]))

        if it.get("subtext"):
            c.setFont("Helvetica", 8)
            c.setFillColor(MUTED)
            c.drawString(col_desc + 4 * mm, y - 4 * mm, str(it["subtext"]))

        if multi:
            c.setFont("Helvetica", 9.5)
            c.setFillColor(BODY)
            c.drawCentredString(col_qty, y + 2 * mm, str(it["quantity"]))
            c.drawRightString(col_unit, y + 2 * mm, _fmt(it["unit_price"], currency))

        c.setFont("Helvetica-Bold", 10.5)
        c.setFillColor(DARK)
        c.drawRightString(col_amount - 4 * mm, y + 2 * mm, _fmt(it["amount"], currency))

        subtotal += it["amount"]
        y -= 13 * mm if it.get("subtext") else 9 * mm
        if it is not line_items[-1]:
            _draw_line(c, M, y + 6 * mm, RX, BORDER, 0.4)

    y -= 6 * mm
    _draw_line(c, M, y, RX)
    y -= 8 * mm

    # Subtotal
    c.setFont("Helvetica", 9.5)
    c.setFillColor(BODY)
    c.drawRightString(RX - 40 * mm, y, "Subtotal")
    c.setFont("Helvetica", 9.5)
    c.setFillColor(DARK)
    c.drawRightString(RX - 4 * mm, y, _fmt(subtotal, currency))
    y -= 6 * mm

    c.setFont("Helvetica", 9.5)
    c.setFillColor(BODY)
    c.drawRightString(RX - 40 * mm, y, "Tax")
    c.drawRightString(RX - 4 * mm, y, "$0.00")
    y -= 8 * mm

    _draw_line(c, M + CW * 0.5, y, RX, BLACK, 1)
    y -= 8 * mm

    # Total
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(DARK)
    c.drawRightString(RX - 40 * mm, y, "Total")
    c.drawRightString(RX - 4 * mm, y, _fmt(subtotal, currency))

    y -= 16 * mm

    # ── Payment status card ──
    card_h = 14 * mm
    c.setFillColor(GREEN_BG)
    c.roundRect(M, y - 4 * mm, CW, card_h, 2 * mm, fill=1, stroke=0)
    c.setStrokeColor(HexColor("#A7F3D0"))
    c.roundRect(M, y - 4 * mm, CW, card_h, 2 * mm, fill=0, stroke=1)

    # Green check circle
    cx = M + 8 * mm
    cy = y + card_h / 2 - 4 * mm
    c.setFillColor(GREEN)
    c.circle(cx, cy, 3 * mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(white)
    c.drawCentredString(cx, cy - 1 * mm, "\u2713")

    # Payment text
    method_label = receipt.get("payment_method", "").replace("_", " ").title()
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(GREEN_TEXT)
    c.drawString(cx + 6 * mm, cy + 1.5 * mm, "Payment Successful")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(BODY)
    c.drawString(cx + 6 * mm, cy - 3.5 * mm, f"Paid via {method_label}")

    if receipt.get("paynow_reference"):
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawRightString(RX - 5 * mm, cy, f"Ref: {receipt['paynow_reference']}")

    y -= card_h + 8 * mm

    # ── Features section ──
    features = receipt.get("features") or []
    if features:
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(DARK)
        c.drawString(M, y, "What's Included")
        y -= 8 * mm

        col1_x = M
        col2_x = M + CW * 0.5
        per_col = (len(features) + 1) // 2

        for i, feat in enumerate(features):
            fx = col1_x if i < per_col else col2_x
            fy = y - (i % per_col) * 6 * mm

            # Check icon
            c.setFillColor(GREEN)
            c.circle(fx + 2.5 * mm, fy + 1 * mm, 1.8 * mm, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 6)
            c.setFillColor(white)
            c.drawCentredString(fx + 2.5 * mm, fy + 0.2 * mm, "\u2713")

            c.setFont("Helvetica", 8.5)
            c.setFillColor(BODY)
            c.drawString(fx + 7 * mm, fy, feat)

        y -= (per_col) * 6 * mm + 6 * mm

    # ── Footer ──
    footer_y = 28 * mm

    _draw_line(c, M, footer_y + 8 * mm, RX)

    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, footer_y + 1 * mm,
                        "Thank you for your business!")

    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, footer_y - 5 * mm,
                        "Shopivell  \u2022  shopivell.com  \u2022  support@shopivell.com")

    # Bottom bar
    c.setFillColor(BLACK)
    c.rect(0, 0, PAGE_W, 2.5 * mm, fill=1, stroke=0)

    c.showPage()
    c.save()
    return buf.getvalue()

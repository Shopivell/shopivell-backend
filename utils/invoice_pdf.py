"""Generate PDF invoice for subscription payments using reportlab."""
import io
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import Color, black, white, HexColor
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String


LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "shopivell_logo.png")

PAGE_W, PAGE_H = A4  # 595.27, 841.89 points
M = 20 * mm  # margin
RX = PAGE_W - M  # right edge
CW = PAGE_W - 2 * M  # content width

# Brand palette
PRIMARY = HexColor("#1E293B")
ACCENT = HexColor("#3B82F6")
DARK = HexColor("#0F172A")
MUTED = HexColor("#64748B")
LIGHT = HexColor("#F1F5F9")
DIVIDER = HexColor("#E2E8F0")


def _fmt(amount: float, currency: str = "USD") -> str:
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _rounded_rect(c, x, y, w, h, r, fill=True, stroke=False, fill_color=None, stroke_color=None):
    """Draw a rounded rectangle. y is bottom-left in reportlab coords."""
    if fill_color:
        c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
    c.roundRect(x, y, w, h, r, fill=int(fill), stroke=int(stroke))


def generate_invoice_pdf(receipt: dict) -> bytes:
    """Return raw PDF bytes for the given receipt dict."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    currency = receipt.get("currency", "USD")

    # ── Top accent bar ──
    c.setFillColor(PRIMARY)
    c.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, fill=1, stroke=0)

    y = PAGE_H - 18 * mm

    # ── Header: Logo + brand ──
    logo_sz = 13 * mm
    if os.path.exists(LOGO_PATH):
        try:
            c.drawImage(LOGO_PATH, M, y - logo_sz + 3 * mm, logo_sz, logo_sz, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(DARK)
    c.drawString(M + logo_sz + 3 * mm, y - 1 * mm, "Shopivell")
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(M + logo_sz + 3 * mm, y - 6 * mm, "shopivell.com")

    # Invoice badge (right side)
    badge_w = 36 * mm
    badge_h = 10 * mm
    _rounded_rect(c, RX - badge_w, y - 4 * mm, badge_w, badge_h, 2 * mm, fill=True, fill_color=PRIMARY)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(white)
    c.drawCentredString(RX - badge_w / 2, y - 0.5 * mm, "INVOICE")

    y -= 20 * mm

    # ── Thin divider ──
    c.setStrokeColor(DIVIDER)
    c.line(M, y, RX, y)
    y -= 8 * mm

    # ── Bill To (left) + Invoice info (right) ──
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(MUTED)
    c.drawString(M, y, "BILL TO")
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(DARK)
    c.drawString(M, y, receipt.get("store_name") or "\u2014")
    bill_to_y = y

    # Right info
    iy = bill_to_y + 8 * mm
    def info_label(label, value):
        nonlocal iy
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawRightString(RX, iy, label)
        iy -= 4 * mm
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(DARK)
        c.drawRightString(RX, iy, value)
        iy -= 6 * mm

    info_label("Receipt #", receipt["receipt_number"])
    info_label("Reference", receipt["transaction_reference"])
    if receipt.get("completed_at"):
        try:
            dt = datetime.fromisoformat(receipt["completed_at"])
            date_str = dt.strftime("%B %d, %Y")
        except Exception:
            date_str = receipt["completed_at"][:10]
        info_label("Date", date_str)

    y = min(y, iy) - 8 * mm

    # ── Table ──
    col_desc = M
    col_billing = M + CW * 0.52
    col_amount = RX

    # Header row
    hdr_h = 9 * mm
    _rounded_rect(c, M, y - 2 * mm, CW, hdr_h, 1.5 * mm, fill=True, fill_color=PRIMARY)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(white)
    c.drawString(col_desc + 4 * mm, y + 2 * mm, "DESCRIPTION")
    c.drawString(col_billing, y + 2 * mm, "BILLING")
    c.drawRightString(col_amount - 4 * mm, y + 2 * mm, "AMOUNT")
    y -= hdr_h + 2 * mm

    # Data row
    row_h = 14 * mm
    _rounded_rect(c, M, y - 3 * mm, CW, row_h, 1 * mm, fill=True, fill_color=LIGHT)

    plan_name = receipt["package_name"].capitalize()
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(DARK)
    c.drawString(col_desc + 4 * mm, y + 4 * mm, f"{plan_name} Plan")

    if receipt.get("package_description"):
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(col_desc + 4 * mm, y - 1 * mm, receipt["package_description"])

    billing = "Annual" if receipt.get("billing_period") == "annual" else "Monthly"
    c.setFont("Helvetica", 9.5)
    c.setFillColor(DARK)
    c.drawString(col_billing, y + 4 * mm, billing)

    c.setFont("Helvetica-Bold", 9.5)
    c.drawRightString(col_amount - 4 * mm, y + 4 * mm, _fmt(receipt["amount"], currency))
    y -= row_h + 4 * mm

    # ── Total row ──
    c.setStrokeColor(DIVIDER)
    c.line(M, y, RX, y)
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.setFillColor(MUTED)
    c.drawString(col_billing, y, "Total Due")
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(DARK)
    c.drawRightString(col_amount - 4 * mm, y, _fmt(receipt["amount"], currency))
    y -= 12 * mm

    # ── Payment info card ──
    card_h = 18 * mm
    _rounded_rect(c, M, y - 6 * mm, CW, card_h, 2 * mm, fill=True, fill_color=LIGHT)
    _rounded_rect(c, M, y - 6 * mm, CW, card_h, 2 * mm, fill=False, stroke=True, stroke_color=DIVIDER)

    # PAID badge
    paid_w = 20 * mm
    paid_h = 7 * mm
    _rounded_rect(c, M + 4 * mm, y - 1 * mm, paid_w, paid_h, 1.5 * mm, fill=True, fill_color=PRIMARY)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(white)
    c.drawCentredString(M + 4 * mm + paid_w / 2, y + 1.5 * mm, "PAID")

    # Payment method
    method_label = receipt["payment_method"].replace("_", " ").title()
    c.setFont("Helvetica", 9)
    c.setFillColor(DARK)
    c.drawString(M + paid_w + 8 * mm, y + 1.5 * mm, f"Paid via {method_label}")

    if receipt.get("paynow_reference"):
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawRightString(RX - 4 * mm, y + 1.5 * mm, f"Ref: {receipt['paynow_reference']}")

    y -= card_h + 4 * mm

    # ── Features card ──
    features = receipt.get("features") or []
    if features:
        feat_line_h = 5.5 * mm
        feat_h = 8 * mm + len(features) * feat_line_h + 4 * mm
        _rounded_rect(c, M, y - feat_h + 6 * mm, CW, feat_h, 2 * mm, fill=True, fill_color=LIGHT)

        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(DARK)
        c.drawString(M + 5 * mm, y, "What's Included")
        fy = y - 6 * mm

        for feat in features:
            # Grey check circle
            c.setFillColor(PRIMARY)
            c.circle(M + 7 * mm, fy + 1 * mm, 1.5 * mm, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 6)
            c.setFillColor(white)
            c.drawCentredString(M + 7 * mm, fy + 0.3 * mm, "\u2713")

            c.setFont("Helvetica", 8.5)
            c.setFillColor(DARK)
            c.drawString(M + 12 * mm, fy, feat)
            fy -= feat_line_h

        y -= feat_h + 2 * mm

    # ── Footer ──
    footer_y = min(y - 10 * mm, 30 * mm)
    c.setFillColor(LIGHT)
    c.rect(0, 0, PAGE_W, footer_y + 12 * mm, fill=1, stroke=0)

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, footer_y + 4 * mm, "Thank you for subscribing to Shopivell!")
    c.setFont("Helvetica", 8)
    c.drawCentredString(PAGE_W / 2, footer_y - 1 * mm, "shopivell.com  |  support@shopivell.com")

    # Bottom accent bar
    c.setFillColor(PRIMARY)
    c.rect(0, 0, PAGE_W, 3 * mm, fill=1, stroke=0)

    c.showPage()
    c.save()
    return buf.getvalue()

"""Plain, human-looking names for campaigns: no pipe separators, no em/en dashes."""


def clean_ad_name(name):
    """'Brand | Offer | 28-Day Trial | $20 Cap' -> 'Brand: Offer - 28-Day Trial - $20 Cap'.
    Pipes read as machine-made and em/en dashes are unwanted in customer-facing text, so the
    first separator becomes a colon and later ones a plain hyphen."""
    text = str(name or "")
    text = text.replace(chr(8212), " - ").replace(chr(8211), " - ")
    if "|" in text:
        parts = [p.strip() for p in text.split("|") if p.strip()]
        text = parts[0] + (": " + " - ".join(parts[1:]) if len(parts) > 1 else "") if parts else ""
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()

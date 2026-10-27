"""Brand helpers shared by the campaign engine and the OpenClaw agents."""
import io
import colorsys
import logging
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


def logo_brand_color(logo_url: str) -> Optional[str]:
    """Dominant saturated colour of a logo as #RRGGBB. Store.color_theme is only the
    onboarding picker's default unless the owner changed it; the logo is the reliable
    source. Ignores transparent, near-white, near-black and grey pixels."""
    if not logo_url:
        return None
    try:
        from PIL import Image
        import requests
        r = requests.get(logo_url, timeout=10)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img.thumbnail((96, 96))
        counts: Counter = Counter()
        for (rr, gg, bb, aa) in img.getdata():
            if aa < 200:
                continue
            _h, s, v = colorsys.rgb_to_hsv(rr / 255, gg / 255, bb / 255)
            if s < 0.25 or v < 0.2 or v > 0.95:
                continue
            counts[(rr // 24 * 24, gg // 24 * 24, bb // 24 * 24)] += 1
        if not counts:
            return None
        rr, gg, bb = counts.most_common(1)[0][0]
        return "#{:02X}{:02X}{:02X}".format(min(rr + 12, 255), min(gg + 12, 255), min(bb + 12, 255))
    except Exception as e:
        logger.info("could not derive brand colour from logo %s: %s", logo_url, e)
        return None

# ad_image_composer.py - Add text overlays to AI-generated ad images
"""
This module takes an AI-generated base image and adds professional ad overlays:
- Top header bar with headline (brand color)
- Individual bullet point strips
- Bottom footer bar with CTA (brand color)
- Optional logo/badge

Creates complete ad creatives like professional marketing images.
Style inspired by professional security/business ads.
"""

import io
import base64
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Default colors
DEFAULT_BRAND_COLOR = (255, 215, 0)  # Yellow/Gold
DEFAULT_HEADER_TEXT_COLOR = (0, 0, 0)  # Black text on yellow
DEFAULT_BULLET_BG_COLOR = (0, 0, 0, 220)  # Black with transparency
DEFAULT_BULLET_TEXT_COLOR = (255, 255, 255)  # White


class AdImageComposer:
    """
    Composes complete ad images by adding text overlays to base images.
    Professional style with header bar, bullet strips, and footer CTA.
    """

    def __init__(self):
        self.font_bold_large = None
        self.font_bold = None
        self.font_regular = None
        self._load_fonts()

    def _load_fonts(self):
        """Load fonts for text rendering"""
        font_paths_bold = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]

        for path in font_paths_bold:
            try:
                self.font_bold_large = ImageFont.truetype(path, 52)
                self.font_bold = ImageFont.truetype(path, 36)
                self.font_regular = ImageFont.truetype(path, 28)
                logger.info(f"[AdImageComposer] Loaded font: {path}")
                return
            except (IOError, OSError):
                continue

        logger.warning("[AdImageComposer] Using default font")
        self.font_bold_large = ImageFont.load_default()
        self.font_bold = ImageFont.load_default()
        self.font_regular = ImageFont.load_default()

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _get_text_size(self, draw: ImageDraw, text: str, font: ImageFont) -> Tuple[int, int]:
        """Get text bounding box size"""
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _get_contrast_color(self, bg_color: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Get contrasting text color (black or white) based on background"""
        # Calculate luminance
        luminance = (0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]) / 255
        return (0, 0, 0) if luminance > 0.5 else (255, 255, 255)

    def _fetch_logo(self, logo_url: str) -> Optional[Image.Image]:
        """Fetch and return logo image"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/*,*/*',
            }
            response = requests.get(logo_url, headers=headers, timeout=10)
            if response.status_code == 200 and len(response.content) > 500:
                logo = Image.open(io.BytesIO(response.content))
                return logo.convert("RGBA")
        except Exception as e:
            logger.warning(f"[AdImageComposer] Failed to fetch logo: {e}")
        return None

    def compose_ad_image(
        self,
        base_image: bytes,
        headline: str,
        bullet_points: List[str] = None,
        cta_text: str = "Learn More",
        logo_url: str = None,
        brand_color: str = "#FFD700",  # Default yellow
        sub_headline: str = None
    ) -> Dict[str, Any]:
        """
        Compose a complete ad image with professional overlays.

        Style: Yellow/brand color header and footer bars, black bullet strips.

        Args:
            base_image: Base image bytes (from AI generation)
            headline: Main headline text (top bar)
            bullet_points: List of benefit bullet points
            cta_text: Call-to-action text (bottom bar)
            logo_url: URL to company logo
            brand_color: Hex color for header/footer bars (e.g., "#FFD700")
            sub_headline: Optional sub-headline below main headline

        Returns:
            Dict with 'success', 'image_base64', 'error'
        """
        try:
            # Load base image
            img = Image.open(io.BytesIO(base_image)).convert("RGBA")
            width, height = img.size

            # Create overlay layer
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Determine brand color
            brand_rgb = self._hex_to_rgb(brand_color) if brand_color else DEFAULT_BRAND_COLOR
            text_color = self._get_contrast_color(brand_rgb)

            # === TOP HEADER BAR ===
            header_height = 80
            draw.rectangle(
                [(0, 0), (width, header_height)],
                fill=brand_rgb + (255,)  # Solid color
            )

            # Headline text - centered, with truncation if too long
            headline_upper = headline.upper()
            max_headline_width = width - 40  # Leave 20px padding on each side

            # Try to fit the headline, truncate if necessary
            headline_font = self.font_bold_large
            text_width, text_height = self._get_text_size(draw, headline_upper, headline_font)

            # If text is too wide, try smaller font first
            if text_width > max_headline_width:
                headline_font = self.font_bold  # Use smaller font
                text_width, text_height = self._get_text_size(draw, headline_upper, headline_font)

            # If still too wide, truncate
            if text_width > max_headline_width:
                while text_width > max_headline_width and len(headline_upper) > 10:
                    headline_upper = headline_upper[:-4] + "..."
                    text_width, text_height = self._get_text_size(draw, headline_upper, headline_font)

            x = (width - text_width) // 2
            y = (header_height - text_height) // 2
            draw.text((x, y), headline_upper, font=headline_font, fill=text_color)

            # === BULLET POINTS (individual strips) ===
            if bullet_points:
                bullet_start_y = header_height + 30
                bullet_x = width * 0.4  # Start bullets on right side

                for i, point in enumerate(bullet_points[:4]):  # Max 4 bullets
                    # Calculate text size
                    text_w, text_h = self._get_text_size(draw, point, self.font_regular)

                    # Draw black strip behind text
                    strip_padding = 12
                    strip_y = bullet_start_y + (i * 50)

                    draw.rectangle(
                        [(bullet_x - strip_padding, strip_y - 5),
                         (width - 20, strip_y + text_h + 10)],
                        fill=(0, 0, 0, 220)
                    )

                    # Draw bullet text
                    draw.text(
                        (bullet_x, strip_y),
                        point,
                        font=self.font_regular,
                        fill=(255, 255, 255)
                    )

            # === BOTTOM FOOTER BAR (CTA) ===
            footer_height = 70
            footer_y = height - footer_height

            draw.rectangle(
                [(0, footer_y), (width, height)],
                fill=brand_rgb + (255,)  # Solid color
            )

            # CTA text - centered
            cta_upper = cta_text.upper()
            cta_width, cta_height = self._get_text_size(draw, cta_upper, self.font_bold)
            cta_x = (width - cta_width) // 2
            cta_y = footer_y + (footer_height - cta_height) // 2
            draw.text((cta_x, cta_y), cta_upper, font=self.font_bold, fill=text_color)

            # === LOGO (bottom left or as badge) ===
            if logo_url:
                logo = self._fetch_logo(logo_url)
                if logo:
                    # Resize logo (max 100px)
                    max_size = 100
                    ratio = min(max_size / logo.width, max_size / logo.height)
                    new_width = int(logo.width * ratio)
                    new_height = int(logo.height * ratio)
                    logo = logo.resize((new_width, new_height), Image.Resampling.LANCZOS)

                    # Position on left side, below header
                    logo_x = 30
                    logo_y = header_height + 30

                    # Optional: Add circular background for badge effect
                    # For now, just paste the logo
                    overlay.paste(logo, (logo_x, logo_y), logo)

            # Composite overlay onto base image
            result = Image.alpha_composite(img, overlay)
            result_rgb = result.convert("RGB")

            # Save to bytes
            output_buffer = io.BytesIO()
            result_rgb.save(output_buffer, format="PNG", quality=95)
            output_buffer.seek(0)

            image_base64 = base64.b64encode(output_buffer.read()).decode('utf-8')

            logger.info("[AdImageComposer] Successfully composed ad image")
            return {
                "success": True,
                "image_base64": image_base64,
                "error": None
            }

        except Exception as e:
            logger.error(f"[AdImageComposer] Error composing image: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "image_base64": None,
                "error": str(e)
            }


def compose_ad_from_base64(
    base_image_b64: str,
    headline: str,
    bullet_points: List[str] = None,
    cta_text: str = "Learn More",
    logo_url: str = None,
    brand_color: str = "#FFD700"
) -> Dict[str, Any]:
    """
    Convenience function to compose ad from base64 image.
    """
    composer = AdImageComposer()
    image_bytes = base64.b64decode(base_image_b64)
    return composer.compose_ad_image(
        base_image=image_bytes,
        headline=headline,
        bullet_points=bullet_points,
        cta_text=cta_text,
        logo_url=logo_url,
        brand_color=brand_color
    )

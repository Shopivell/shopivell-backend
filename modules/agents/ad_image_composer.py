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

import os
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
        self._font_path = None
        self._find_font_path()

    def _find_font_path(self):
        """Find a usable font file path"""
        font_paths = [
            # Liberation (installed in Docker via fonts-liberation)
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            # DejaVu (common on Linux)
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            # Noto (common fallback)
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            # Windows
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            # macOS
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        for path in font_paths:
            try:
                ImageFont.truetype(path, 20)
                self._font_path = path
                logger.info(f"[AdImageComposer] Found font: {path}")
                return
            except (IOError, OSError):
                continue
        logger.warning("[AdImageComposer] No TrueType font found, will use default")

    def _load_fonts_for_size(self, width: int, height: int):
        """Load fonts scaled proportionally to image dimensions."""
        # Scale fonts to image size (percentages of image height)
        size = min(width, height)
        headline_px = max(int(size * 0.07), 48)     # ~7% of image = 72px on 1024
        bold_large_px = max(int(size * 0.06), 40)    # ~6% = 61px on 1024
        bold_px = max(int(size * 0.045), 32)          # ~4.5% = 46px on 1024
        regular_px = max(int(size * 0.035), 26)       # ~3.5% = 36px on 1024

        if self._font_path:
            try:
                self.font_headline = ImageFont.truetype(self._font_path, headline_px)
                self.font_bold_large = ImageFont.truetype(self._font_path, bold_large_px)
                self.font_bold = ImageFont.truetype(self._font_path, bold_px)
                self.font_regular = ImageFont.truetype(self._font_path, regular_px)
                return
            except (IOError, OSError):
                pass

        self.font_headline = ImageFont.load_default()
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
        """Fetch and return logo image from URL or local file path"""
        try:
            # Handle local file paths
            if os.path.isfile(logo_url):
                logo = Image.open(logo_url)
                return logo.convert("RGBA")

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

    def _wrap_text(self, text: str, font: ImageFont, max_width: int, draw: ImageDraw) -> List[str]:
        """Word-wrap text to fit within max_width pixels."""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            text_w, _ = self._get_text_size(draw, test_line, font)
            if text_w <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines if lines else [text]

    def compose_modern_ad_image(
        self,
        base_image: bytes,
        headline: str,
        bullet_points: List[str] = None,
        cta_text: str = "Learn More",
        brand_name: str = None,
        brand_color: str = "#FFD700",
        logo_url: str = None
    ) -> Dict[str, Any]:
        """
        Compose a modern full-bleed ad image with professional text overlay.

        Layout: full-bleed scene, strong left-side dark panel for text,
        brand name top-left, large headline, bullet points with check icons,
        bold CTA button at bottom-right.
        """
        try:
            # Load base image as RGBA, full-bleed background
            img = Image.open(io.BytesIO(base_image)).convert("RGBA")
            width, height = img.size

            # Load fonts scaled to image dimensions
            self._load_fonts_for_size(width, height)

            # Create overlay layer
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Determine brand color
            brand_rgb = self._hex_to_rgb(brand_color) if brand_color else DEFAULT_BRAND_COLOR
            cta_text_color = self._get_contrast_color(brand_rgb)

            # === LEFT PANEL: Dark gradient for text readability ===
            # Strong dark panel on the left ~50% of image, fading to transparent on right
            panel_width = int(width * 0.55)
            for x in range(panel_width):
                if x < int(panel_width * 0.75):
                    # Solid dark area (left 75% of panel)
                    alpha = 190
                else:
                    # Fade out (right 25% of panel)
                    fade_progress = (x - int(panel_width * 0.75)) / (panel_width * 0.25)
                    alpha = int(190 * (1.0 - fade_progress))
                draw.line([(x, 0), (x, height)], fill=(0, 0, 0, alpha))

            # === BOTTOM GRADIENT for CTA button area ===
            gradient_start = int(height * 0.75)
            for y in range(gradient_start, height):
                progress = (y - gradient_start) / (height - gradient_start)
                alpha = int(160 * progress)
                draw.line([(panel_width, y), (width, y)], fill=(0, 0, 0, alpha))

            # Layout margins
            margin_x = int(width * 0.06)
            margin_top = int(height * 0.06)

            # === LOGO (top-left, only if high-quality) ===
            current_y = margin_top
            if logo_url:
                logo = self._fetch_logo(logo_url)
                if logo:
                    # Skip tiny logos (< 64px) and oversized crops (> 300px wide = screenshot header)
                    if (logo.width < 64 and logo.height < 64) or (logo.width > 250 and logo.height < logo.width * 0.4):
                        logger.warning(f"[AdImageComposer] Logo unsuitable ({logo.width}x{logo.height}), using brand name only")
                        logo = None

                if logo:
                    max_logo_h = max(int(height * 0.08), 60)
                    max_logo_w = max(int(width * 0.18), 120)
                    ratio = min(max_logo_w / logo.width, max_logo_h / logo.height, 1.5)
                    new_w = int(logo.width * ratio)
                    new_h = int(logo.height * ratio)
                    logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    overlay.paste(logo, (margin_x, current_y), logo)
                    current_y += new_h + int(height * 0.02)

            # === BRAND NAME (uppercase, brand color, below logo) ===
            if brand_name:
                draw.text(
                    (margin_x, current_y),
                    brand_name.upper(),
                    font=self.font_bold,
                    fill=brand_rgb + (255,)
                )
                _, brand_h = self._get_text_size(draw, brand_name.upper(), self.font_bold)
                current_y += brand_h + int(height * 0.01)

            # === ACCENT LINE (brand color bar) ===
            line_y = current_y + int(height * 0.015)
            draw.rectangle(
                [(margin_x, line_y), (margin_x + int(width * 0.12), line_y + 4)],
                fill=brand_rgb + (255,)
            )
            current_y = line_y + int(height * 0.04)

            # === HEADLINE (large bold white, word-wrapped within panel) ===
            max_text_width = int(panel_width * 0.80)
            headline_lines = self._wrap_text(headline.upper(), self.font_headline, max_text_width, draw)

            for line in headline_lines[:3]:  # Max 3 lines
                draw.text(
                    (margin_x, current_y),
                    line,
                    font=self.font_headline,
                    fill=(255, 255, 255, 255)
                )
                _, line_h = self._get_text_size(draw, line, self.font_headline)
                current_y += line_h + int(height * 0.01)

            current_y += int(height * 0.03)

            # === BULLET POINTS (with checkmark icons) ===
            if bullet_points:
                for point in bullet_points[:4]:
                    bullet_text = f"\u2713  {point}"
                    draw.text(
                        (margin_x + int(width * 0.01), current_y),
                        bullet_text,
                        font=self.font_regular,
                        fill=(255, 255, 255, 240)
                    )
                    _, point_h = self._get_text_size(draw, bullet_text, self.font_regular)
                    current_y += point_h + int(height * 0.018)

            # === CTA BUTTON (rounded pill, bottom-right, brand color) ===
            cta_upper = cta_text.upper()
            cta_w, cta_h = self._get_text_size(draw, cta_upper, self.font_bold)
            btn_padding_x = int(width * 0.04)
            btn_padding_y = int(height * 0.02)
            btn_width = cta_w + btn_padding_x * 2
            btn_height = cta_h + btn_padding_y * 2

            btn_x = width - btn_width - int(width * 0.06)
            btn_y = height - btn_height - int(height * 0.06)

            # Button shadow
            draw.rounded_rectangle(
                [(btn_x + 2, btn_y + 2), (btn_x + btn_width + 2, btn_y + btn_height + 2)],
                radius=btn_height // 2,
                fill=(0, 0, 0, 100)
            )
            # Button fill
            draw.rounded_rectangle(
                [(btn_x, btn_y), (btn_x + btn_width, btn_y + btn_height)],
                radius=btn_height // 2,
                fill=brand_rgb + (255,)
            )
            # CTA text centered
            cta_text_x = btn_x + (btn_width - cta_w) // 2
            cta_text_y = btn_y + (btn_height - cta_h) // 2
            draw.text(
                (cta_text_x, cta_text_y),
                cta_upper,
                font=self.font_bold,
                fill=cta_text_color
            )

            # Alpha-composite overlay onto base, return base64 PNG
            result = Image.alpha_composite(img, overlay)
            result_rgb = result.convert("RGB")

            output_buffer = io.BytesIO()
            result_rgb.save(output_buffer, format="PNG", quality=95)
            output_buffer.seek(0)

            image_base64 = base64.b64encode(output_buffer.read()).decode('utf-8')

            logger.info("[AdImageComposer] Successfully composed modern ad image")
            return {
                "success": True,
                "image_base64": image_base64,
                "error": None
            }

        except Exception as e:
            logger.error(f"[AdImageComposer] Error composing modern image: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "image_base64": None,
                "error": str(e)
            }

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

            # Load fonts scaled to image dimensions
            self._load_fonts_for_size(width, height)

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


def compose_modern_ad_from_base64(
    base_image_b64: str,
    headline: str,
    bullet_points: List[str] = None,
    cta_text: str = "Learn More",
    brand_name: str = None,
    brand_color: str = "#FFD700",
    logo_url: str = None
) -> Dict[str, Any]:
    """
    Convenience function to compose a modern full-bleed ad from base64 image.
    """
    composer = AdImageComposer()
    image_bytes = base64.b64decode(base_image_b64)
    return composer.compose_modern_ad_image(
        base_image=image_bytes,
        headline=headline,
        bullet_points=bullet_points,
        cta_text=cta_text,
        brand_name=brand_name,
        brand_color=brand_color,
        logo_url=logo_url
    )

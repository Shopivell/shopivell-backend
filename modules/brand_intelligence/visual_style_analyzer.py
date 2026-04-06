# visual_style_analyzer.py - Analyze visual/photography style of a brand
"""
Analyzes the visual style of a brand's images to understand:
- Photography style (studio, candid, documentary, etc.)
- Color treatment (saturated, muted, warm, cool, etc.)
- Composition style (centered, rule of thirds, etc.)
- Overall aesthetic (professional, casual, luxury, etc.)
- Design elements (shapes, patterns, graphics)

This information is used to generate images that match the brand's visual DNA.
"""

import os
import logging
import base64
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class VisualStyleAnalyzer:
    """
    Analyzes brand visual style from images using Vision AI.
    Produces a detailed style profile for image generation.
    """

    def __init__(self):
        self.openai = None
        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _fetch_image_base64(self, url: str, timeout: int = 10) -> Optional[str]:
        """Fetch image and convert to base64."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            logger.debug(f"[VisualStyleAnalyzer] Failed to fetch {url}: {e}")
            return None

    def _get_mime_type(self, url: str) -> str:
        """Determine MIME type from URL."""
        url_lower = url.lower()
        if '.png' in url_lower:
            return 'image/png'
        elif '.gif' in url_lower:
            return 'image/gif'
        elif '.webp' in url_lower:
            return 'image/webp'
        else:
            return 'image/jpeg'

    def analyze_visual_style(
        self,
        categorized_images: Dict[str, Any],
        domain: str
    ) -> Dict[str, Any]:
        """
        Analyze visual style from categorized images.

        Args:
            categorized_images: Output from AssetCategorizer
            domain: Website domain

        Returns:
            Dict with complete visual style analysis
        """
        if not self.openai:
            logger.warning("[VisualStyleAnalyzer] OpenAI not available")
            return self._default_style()

        # Select best images for style analysis (prioritize hero, team, product)
        analysis_images = []

        # Get up to 2 hero images
        for img in categorized_images.get('hero', [])[:2]:
            if isinstance(img, dict):
                analysis_images.append(img['url'])

        # Get up to 2 team images
        for img in categorized_images.get('team', [])[:2]:
            if isinstance(img, dict):
                analysis_images.append(img['url'])

        # Get 1 product/service image
        for img in categorized_images.get('product', [])[:1]:
            if isinstance(img, dict):
                analysis_images.append(img['url'])

        # Get 1 office image
        for img in categorized_images.get('office', [])[:1]:
            if isinstance(img, dict):
                analysis_images.append(img['url'])

        # If we don't have enough, add from other categories
        if len(analysis_images) < 3:
            for img in categorized_images.get('other', [])[:3]:
                if isinstance(img, dict) and img['url'] not in analysis_images:
                    analysis_images.append(img['url'])

        if not analysis_images:
            logger.warning("[VisualStyleAnalyzer] No images to analyze")
            return self._default_style()

        # Limit to 5 images for API efficiency
        analysis_images = analysis_images[:5]

        logger.info(f"[VisualStyleAnalyzer] Analyzing {len(analysis_images)} images for style")

        # Build vision API request with images
        content = [
            {
                "type": "text",
                "text": f"""Analyze the visual style of these images from {domain} to understand the brand's visual DNA.

I need you to extract the EXACT visual style so we can generate new images that look like they came from the same source.

Analyze and provide:

1. PHOTOGRAPHY_STYLE (choose one):
   - professional_studio: Clean backgrounds, perfect lighting, posed subjects
   - lifestyle_candid: Natural moments, real environments, authentic feel
   - documentary: Action shots, real situations, journalistic feel
   - product_focused: Clean product shots, minimal backgrounds
   - environmental: Subjects in their work environment
   - corporate_portrait: Professional headshots and group photos

2. COLOR_TREATMENT (choose one):
   - high_contrast_saturated: Vivid colors, strong contrast
   - soft_muted: Pastel or desaturated colors, gentle feel
   - warm_tones: Orange/yellow bias, inviting feel
   - cool_tones: Blue bias, professional feel
   - natural_balanced: True-to-life colors
   - dramatic_dark: Dark backgrounds, dramatic lighting

3. COMPOSITION_STYLE (choose one):
   - centered_subjects: Main subject in center
   - rule_of_thirds: Subjects placed on third lines
   - full_bleed: Edge-to-edge imagery
   - negative_space: Lots of empty space
   - dynamic_diagonal: Diagonal lines, movement
   - symmetrical: Balanced, mirrored compositions

4. LIGHTING_STYLE (choose one):
   - bright_even: Well-lit, minimal shadows
   - dramatic_contrast: Strong shadows, directional light
   - natural_soft: Soft daylight, gentle shadows
   - studio_controlled: Perfect studio lighting
   - moody_atmospheric: Dark, atmospheric lighting

5. OVERALL_AESTHETIC (choose one):
   - professional_corporate: Business-like, trustworthy
   - modern_minimal: Clean, simple, contemporary
   - luxury_premium: High-end, exclusive feel
   - friendly_approachable: Warm, welcoming
   - bold_energetic: Dynamic, exciting
   - technical_precise: Detailed, accurate, informative

6. BRAND_COLORS: List the 3-5 main colors you see (as hex codes)

7. UNIFORM_DETAILS (if staff visible):
   - Color of uniforms
   - Style (formal, tactical, casual, etc.)
   - Visible badges, logos, or branding
   - Accessories (hats, equipment, etc.)

8. VEHICLE_DETAILS (if vehicles visible):
   - Vehicle types
   - Color scheme
   - Branding placement
   - Fleet consistency

9. QUALITY_LEVEL (choose one):
   - premium: High-end professional photography
   - professional: Good quality, standard commercial
   - amateur: Lower quality, possibly stock or casual

10. IMAGE_GENERATION_INSTRUCTIONS:
    Write 2-3 sentences describing EXACTLY how to recreate this visual style when generating new images. Be specific about lighting, colors, composition, and mood.

Respond in this exact JSON format:
{{
  "photography_style": "...",
  "color_treatment": "...",
  "composition_style": "...",
  "lighting_style": "...",
  "overall_aesthetic": "...",
  "brand_colors": ["#hex1", "#hex2", ...],
  "uniform_details": {{
    "colors": ["..."],
    "style": "...",
    "badges_logos": "...",
    "accessories": "..."
  }},
  "vehicle_details": {{
    "types": ["..."],
    "color_scheme": "...",
    "branding": "..."
  }},
  "quality_level": "...",
  "image_generation_instructions": "..."
}}"""
            }
        ]

        # Add images
        for img_url in analysis_images:
            img_base64 = self._fetch_image_base64(img_url)
            if img_base64:
                mime_type = self._get_mime_type(img_url)
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{img_base64}",
                        "detail": "high"
                    }
                })

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",  # Cost-optimized for internal analysis
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=2000,
                temperature=0.2
            )

            result_text = response.choices[0].message.content

            # Parse JSON from response
            import json
            # Find JSON in response
            json_match = result_text
            if '```json' in result_text:
                json_match = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                json_match = result_text.split('```')[1].split('```')[0]

            style_data = json.loads(json_match.strip())

            logger.info(f"[VisualStyleAnalyzer] Style analysis complete:")
            logger.info(f"  Photography: {style_data.get('photography_style')}")
            logger.info(f"  Aesthetic: {style_data.get('overall_aesthetic')}")
            logger.info(f"  Colors: {style_data.get('brand_colors')}")

            return style_data

        except Exception as e:
            logger.error(f"[VisualStyleAnalyzer] Analysis error: {e}")
            return self._default_style()

    def _default_style(self) -> Dict[str, Any]:
        """Return default style when analysis fails."""
        return {
            "photography_style": "professional_studio",
            "color_treatment": "natural_balanced",
            "composition_style": "centered_subjects",
            "lighting_style": "bright_even",
            "overall_aesthetic": "professional_corporate",
            "brand_colors": ["#000000", "#FFFFFF"],
            "uniform_details": {
                "colors": [],
                "style": "unknown",
                "badges_logos": "unknown",
                "accessories": ""
            },
            "vehicle_details": {
                "types": [],
                "color_scheme": "unknown",
                "branding": "unknown"
            },
            "quality_level": "professional",
            "image_generation_instructions": "Create professional, well-lit images with clean compositions suitable for corporate marketing."
        }

    def generate_style_prompt(self, style_data: Dict[str, Any]) -> str:
        """
        Generate a detailed prompt section for image generation based on style analysis.

        Args:
            style_data: Output from analyze_visual_style()

        Returns:
            String to include in image generation prompts
        """
        prompt_parts = []

        # Photography style
        photo_style = style_data.get('photography_style', 'professional_studio')
        photo_descriptions = {
            'professional_studio': 'Professional studio photography with clean backgrounds and perfect lighting',
            'lifestyle_candid': 'Natural lifestyle photography capturing authentic moments',
            'documentary': 'Documentary-style action photography showing real situations',
            'product_focused': 'Clean product photography with minimal distractions',
            'environmental': 'Environmental photography showing subjects in their work setting',
            'corporate_portrait': 'Professional corporate portrait photography',
        }
        prompt_parts.append(f"PHOTOGRAPHY STYLE: {photo_descriptions.get(photo_style, photo_style)}")

        # Color treatment
        color_treatment = style_data.get('color_treatment', 'natural_balanced')
        color_descriptions = {
            'high_contrast_saturated': 'Use vivid, saturated colors with strong contrast',
            'soft_muted': 'Use soft, muted colors with gentle tones',
            'warm_tones': 'Apply warm color toning with orange/yellow bias',
            'cool_tones': 'Apply cool color toning with blue bias',
            'natural_balanced': 'Use natural, true-to-life colors',
            'dramatic_dark': 'Use dramatic lighting with dark backgrounds',
        }
        prompt_parts.append(f"COLOR TREATMENT: {color_descriptions.get(color_treatment, color_treatment)}")

        # Brand colors
        brand_colors = style_data.get('brand_colors', [])
        if brand_colors:
            prompt_parts.append(f"BRAND COLORS: Use these colors as the primary palette: {', '.join(brand_colors[:3])}")

        # Composition
        composition = style_data.get('composition_style', 'centered_subjects')
        comp_descriptions = {
            'centered_subjects': 'Center the main subject in the frame',
            'rule_of_thirds': 'Place subjects on rule-of-thirds grid lines',
            'full_bleed': 'Use edge-to-edge imagery that fills the frame',
            'negative_space': 'Include generous negative space around subjects',
            'dynamic_diagonal': 'Use diagonal lines to create dynamic movement',
            'symmetrical': 'Create balanced, symmetrical compositions',
        }
        prompt_parts.append(f"COMPOSITION: {comp_descriptions.get(composition, composition)}")

        # Lighting
        lighting = style_data.get('lighting_style', 'bright_even')
        light_descriptions = {
            'bright_even': 'Use bright, even lighting with minimal shadows',
            'dramatic_contrast': 'Use dramatic directional lighting with strong shadows',
            'natural_soft': 'Use soft natural daylight with gentle shadows',
            'studio_controlled': 'Use controlled studio lighting setup',
            'moody_atmospheric': 'Create moody atmosphere with selective lighting',
        }
        prompt_parts.append(f"LIGHTING: {light_descriptions.get(lighting, lighting)}")

        # Uniform details
        uniform = style_data.get('uniform_details', {})
        if uniform.get('colors') or uniform.get('style') != 'unknown':
            uniform_desc = []
            if uniform.get('colors'):
                uniform_desc.append(f"colors: {', '.join(uniform['colors'])}")
            if uniform.get('style') and uniform['style'] != 'unknown':
                uniform_desc.append(f"style: {uniform['style']}")
            if uniform.get('badges_logos') and uniform['badges_logos'] != 'unknown':
                uniform_desc.append(f"badges/logos: {uniform['badges_logos']}")
            prompt_parts.append(f"UNIFORMS: Staff should wear uniforms with {'; '.join(uniform_desc)}")

        # Vehicle details
        vehicle = style_data.get('vehicle_details', {})
        if vehicle.get('types') or vehicle.get('color_scheme') != 'unknown':
            vehicle_desc = []
            if vehicle.get('types'):
                vehicle_desc.append(f"types: {', '.join(vehicle['types'])}")
            if vehicle.get('color_scheme') and vehicle['color_scheme'] != 'unknown':
                vehicle_desc.append(f"colors: {vehicle['color_scheme']}")
            if vehicle.get('branding') and vehicle['branding'] != 'unknown':
                vehicle_desc.append(f"branding: {vehicle['branding']}")
            prompt_parts.append(f"VEHICLES: Company vehicles should have {'; '.join(vehicle_desc)}")

        # Quality
        quality = style_data.get('quality_level', 'professional')
        prompt_parts.append(f"QUALITY: Generate {quality}-quality imagery")

        # Custom instructions
        custom_instructions = style_data.get('image_generation_instructions', '')
        if custom_instructions:
            prompt_parts.append(f"STYLE GUIDE: {custom_instructions}")

        return "\n".join(prompt_parts)

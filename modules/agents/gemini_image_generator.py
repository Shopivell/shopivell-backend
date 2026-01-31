# gemini_image_generator.py - Generate ad images using Gemini with reference images
"""
This module generates ad images using Google's Gemini API.
It passes reference images (logo, uniforms, vehicles) alongside the prompt
to ensure brand consistency in generated images.

Supported models:
- gemini-2.5-flash-image (fast, efficient)
- gemini-3-pro-image-preview (high quality, supports up to 14 reference images)
"""

import os
import io
import base64
import requests
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Check for Google Generative AI SDK
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("[GeminiImageGenerator] google-genai package not installed. Run: pip install google-genai")

# Try PIL for image handling
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class GeminiImageGenerator:
    """
    Generate ad images using Gemini API with reference images for brand consistency.

    Supports passing:
    - Logo image (for brand consistency)
    - Uniform images (for accurate staff representation)
    - Vehicle images (for accurate fleet representation)
    - Equipment images (for accurate equipment representation)
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.client = None

        if not GEMINI_AVAILABLE:
            logger.error("[GeminiImageGenerator] google-genai package not available")
            return

        if not self.api_key:
            logger.error("[GeminiImageGenerator] No API key provided. Set GOOGLE_API_KEY or GEMINI_API_KEY")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
            logger.info("[GeminiImageGenerator] Initialized successfully")
        except Exception as e:
            logger.error(f"[GeminiImageGenerator] Failed to initialize: {e}")

    def _fetch_image_from_url(self, url: str, timeout: int = 15) -> Optional[bytes]:
        """Fetch image bytes from URL with proper browser-like headers"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': url.rsplit('/', 1)[0] + '/',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'same-origin',
                'Connection': 'keep-alive',
            }
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            response.raise_for_status()

            # Verify we got image content
            content_type = response.headers.get('Content-Type', '')
            if 'image' in content_type or len(response.content) > 1000:
                logger.info(f"[GeminiImageGenerator] Successfully fetched image: {url[:80]}...")
                return response.content
            else:
                logger.warning(f"[GeminiImageGenerator] Response is not an image: {content_type}")
                return None
        except Exception as e:
            logger.warning(f"[GeminiImageGenerator] Failed to fetch image from {url}: {e}")
            return None

    def _get_mime_type(self, url: str) -> str:
        """Determine MIME type from URL"""
        url_lower = url.lower()
        if '.png' in url_lower:
            return 'image/png'
        elif '.svg' in url_lower:
            return 'image/svg+xml'
        elif '.gif' in url_lower:
            return 'image/gif'
        elif '.webp' in url_lower:
            return 'image/webp'
        else:
            return 'image/jpeg'

    def _create_image_part(self, url: str) -> Optional[Any]:
        """Create a Gemini Part object from image URL"""
        image_bytes = self._fetch_image_from_url(url)
        if not image_bytes:
            return None

        mime_type = self._get_mime_type(url)

        # For SVG, we might need to handle differently
        if mime_type == 'image/svg+xml':
            logger.warning(f"[GeminiImageGenerator] SVG images may not render correctly: {url}")

        try:
            return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        except Exception as e:
            logger.error(f"[GeminiImageGenerator] Failed to create image part: {e}")
            return None

    async def generate_ad_image(
        self,
        prompt: str,
        logo_url: str = None,
        reference_images: List[Dict[str, str]] = None,
        output_path: str = None,
        aspect_ratio: str = "1:1",
        model: str = "gemini-2.5-flash-image"
    ) -> Dict[str, Any]:
        """
        Generate an ad image using Gemini with reference images.

        Args:
            prompt: The image generation prompt
            logo_url: URL to the company logo (will be included as reference)
            reference_images: List of dicts with 'url' and 'type' (uniform, vehicle, equipment)
            output_path: Path to save the generated image (optional)
            aspect_ratio: Image aspect ratio (default "1:1" for social media)
            model: Gemini model to use

        Returns:
            Dict with 'success', 'image_path', 'image_base64', 'error'
        """
        if not self.client:
            return {
                "success": False,
                "error": "Gemini client not initialized. Check API key.",
                "image_path": None,
                "image_base64": None
            }

        # Build content list with prompt and reference images
        content_parts = []

        # Build enhanced prompt that instructs Gemini to use reference images
        enhanced_prompt = f"""Generate a professional advertisement image based on this description:

{prompt}

IMPORTANT INSTRUCTIONS FOR REFERENCE IMAGES:
"""

        # Add logo as reference
        if logo_url:
            logo_part = self._create_image_part(logo_url)
            if logo_part:
                content_parts.append(logo_part)
                enhanced_prompt += """
- LOGO: Use the provided logo image EXACTLY as shown. Place it subtly in the bottom-right corner of the generated image. Do not modify or recreate the logo - use the exact image provided.
"""
                logger.info(f"[GeminiImageGenerator] Added logo reference: {logo_url}")

        # Add other reference images (uniforms, vehicles, equipment)
        uniform_count = 0
        vehicle_count = 0
        equipment_count = 0

        if reference_images:
            for ref_img in reference_images:
                img_url = ref_img.get('url')
                img_type = ref_img.get('type', 'scene')

                if not img_url:
                    continue

                img_part = self._create_image_part(img_url)
                if img_part:
                    content_parts.append(img_part)

                    if img_type == 'uniform' or 'uniform' in img_url.lower():
                        uniform_count += 1
                        enhanced_prompt += f"""
- UNIFORM REFERENCE #{uniform_count}: Use the provided uniform image as reference. Any staff/employees in the generated image should wear uniforms that EXACTLY match this reference (same colors, style, badges).
"""
                    elif img_type == 'vehicle' or 'vehicle' in img_url.lower() or 'car' in img_url.lower() or 'truck' in img_url.lower():
                        vehicle_count += 1
                        enhanced_prompt += f"""
- VEHICLE REFERENCE #{vehicle_count}: Use the provided vehicle image as reference. Any company vehicles in the generated image should match this reference (same colors, branding, vehicle type).
"""
                    elif img_type == 'equipment':
                        equipment_count += 1
                        enhanced_prompt += f"""
- EQUIPMENT REFERENCE #{equipment_count}: Use the provided equipment image as reference for any security/business equipment shown.
"""
                    elif img_type == 'screenshot' or img_type == 'scene':
                        enhanced_prompt += """
- WEBSITE REFERENCE: This is a screenshot of the company's website. Use anything useful from it as reference - any images, colors, vehicles, uniforms, equipment, products, or any other visual assets. Copy them as closely as possible. Match the color scheme and overall aesthetic.
"""
                    else:
                        enhanced_prompt += """
- REFERENCE IMAGE: Use this image as a direct visual reference. Copy the visual elements, style, and assets shown in it.
"""
                    logger.info(f"[GeminiImageGenerator] Added {img_type} reference: {img_url}")

        # Add the enhanced prompt as first element
        content_parts.insert(0, enhanced_prompt)

        logger.info(f"[GeminiImageGenerator] Generating image with {len(content_parts) - 1} reference images")

        try:
            # Generate image with Gemini
            response = self.client.models.generate_content(
                model=model,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    response_modalities=['IMAGE', 'TEXT'],
                )
            )

            # Extract generated image
            image_data = None
            response_text = None

            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    response_text = part.text
                elif hasattr(part, 'inline_data') and part.inline_data:
                    image_data = part.inline_data.data

            if not image_data:
                return {
                    "success": False,
                    "error": f"No image generated. Response: {response_text or 'No response'}",
                    "image_path": None,
                    "image_base64": None
                }

            # Save image if output path provided
            image_path = None
            if output_path:
                # Ensure directory exists
                os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

                with open(output_path, 'wb') as f:
                    f.write(base64.b64decode(image_data) if isinstance(image_data, str) else image_data)
                image_path = output_path
                logger.info(f"[GeminiImageGenerator] Image saved to: {output_path}")

            # Return base64 encoded image
            image_base64 = base64.b64encode(image_data).decode('utf-8') if isinstance(image_data, bytes) else image_data

            return {
                "success": True,
                "image_path": image_path,
                "image_base64": image_base64,
                "response_text": response_text,
                "model": model,
                "reference_images_used": len(content_parts) - 1
            }

        except Exception as e:
            logger.error(f"[GeminiImageGenerator] Error generating image: {e}")
            return {
                "success": False,
                "error": str(e),
                "image_path": None,
                "image_base64": None
            }

    async def generate_ad_image_with_sections(
        self,
        prompt: str,
        screenshot_sections: List[Dict[str, Any]],
        company_name: str = "Company",
        primary_color: str = "#1A233A",
        accent_color: str = "#FFB800",
        what_they_do: str = "",
        has_pil_logo: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate ad image using cropped screenshot sections as multi-image references.

        Instead of passing a single full-page screenshot, this method accepts
        pre-cropped sections (header, content areas) so Gemini can see fine
        details like logos, uniforms, vehicles, and products.

        Args:
            prompt: Stripped scene prompt (no text overlay directives)
            screenshot_sections: List of {"label": str, "bytes": bytes} dicts
            company_name: Business name
            primary_color: Brand primary color hex
            accent_color: Brand accent color hex
            what_they_do: Business description
            has_pil_logo: If True, instruct Gemini not to add standalone logos

        Returns:
            Dict with 'success', 'image_base64', 'model', 'error'
        """
        if not GEMINI_AVAILABLE or not self.client:
            return {"success": False, "image_base64": None, "error": "Gemini not available"}

        # Build enhanced prompt (ported from test script generate_scene)
        enhanced = f"""I am attaching CROPPED SECTIONS of {company_name}'s website homepage so you can see the details clearly.

{company_name} does: {what_they_do}

YOUR TASK: Generate a professional advertising image for {company_name}.

Study each attached image carefully. Use any useful VISUAL assets you find - uniforms, vehicles, equipment, products, colors, branding VISUALS - and copy them EXACTLY as they appear into the generated image. Same colors, same style, same details.

CRITICAL: Only copy VISUAL elements (uniforms, vehicles, equipment, colors, physical objects). Do NOT copy any TEXT you see in the screenshots - no company names, no slogans, no product names, no headings, no labels, no watermarks. Text will be added separately.

"""
        if has_pil_logo:
            enhanced += "DO NOT add any standalone logo graphic or company name text overlay to the image. However, if vehicles, uniforms, or equipment from the screenshot already have branding on them, keep that branding as it appears. The real logo will be added separately.\n"
        else:
            enhanced += "Include the company logo as it appears on the screenshot. Copy it exactly.\n"

        enhanced += f"""
Match the website's color scheme: background {primary_color}, accents {accent_color}.

SCENE TO GENERATE:
{prompt}

RULES:
- ABSOLUTELY NO TEXT of any kind in the generated image. No headlines, no labels, no company names, no product names, no slogans, no buttons, no bullet text, no watermarks, no signs with text. The image must contain ZERO readable text.
- Do NOT reproduce any text you see in the screenshot reference images. Only copy visual/physical elements.
- People can be in the FOREGROUND as main subjects, but NEVER place small people or faces in the background - they will appear distorted
- ONLY generate the photorealistic scene with NO text whatsoever
"""

        # Build content parts: text prompt + cropped section images
        content_parts = [enhanced]
        for section in screenshot_sections:
            try:
                part = types.Part.from_bytes(data=section["bytes"], mime_type="image/png")
                content_parts.append(part)
            except Exception as e:
                logger.warning(f"[GeminiImageGenerator] Failed to create part for section {section.get('label')}: {e}")

        logger.info(f"[GeminiImageGenerator] Passing {len(screenshot_sections)} cropped sections to Gemini")

        # Try models in order
        models = ["gemini-3-pro-image-preview", "gemini-2.0-flash-exp-image-generation"]

        for model_name in models:
            try:
                logger.info(f"[GeminiImageGenerator] Trying {model_name} with sections...")
                resp = self.client.models.generate_content(
                    model=model_name,
                    contents=content_parts,
                    config=types.GenerateContentConfig(
                        response_modalities=['IMAGE', 'TEXT'],
                        temperature=0.8,
                    )
                )

                img_data = None
                resp_text = None
                for part in resp.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        resp_text = part.text
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        img_data = part.inline_data.data

                if img_data:
                    b64 = base64.b64encode(img_data).decode() if isinstance(img_data, bytes) else img_data
                    raw = base64.b64decode(b64) if isinstance(img_data, str) else img_data
                    logger.info(f"[GeminiImageGenerator] {model_name} generated {len(raw):,} bytes")
                    return {
                        "success": True,
                        "image_base64": b64,
                        "model": model_name,
                        "error": None
                    }
                else:
                    logger.warning(f"[GeminiImageGenerator] No image from {model_name}")

            except Exception as e:
                logger.warning(f"[GeminiImageGenerator] {model_name} failed: {str(e)[:200]}")

        return {"success": False, "image_base64": None, "model": None, "error": "All models failed"}

    async def generate_ad_image_with_profile(
        self,
        prompt: str,
        logo_url: str = None,
        visual_profile: Dict[str, Any] = None,
        output_dir: str = "generated_images",
        ad_set_name: str = "ad"
    ) -> Dict[str, Any]:
        """
        Generate ad image using visual profile containing reference images.

        Args:
            prompt: The image generation prompt
            logo_url: URL to company logo
            visual_profile: Dict containing reference_images list
            output_dir: Directory to save generated images
            ad_set_name: Name for the output file

        Returns:
            Dict with generation results
        """
        # Extract reference images from visual profile
        reference_images = []
        if visual_profile:
            reference_images = visual_profile.get('reference_images', [])

        # Generate timestamp for unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in ad_set_name)
        output_path = os.path.join(output_dir, f"{safe_name}_{timestamp}.png")

        return await self.generate_ad_image(
            prompt=prompt,
            logo_url=logo_url,
            reference_images=reference_images,
            output_path=output_path
        )


# Convenience function
async def generate_ad_image(
    prompt: str,
    logo_url: str = None,
    reference_images: List[Dict[str, str]] = None,
    output_path: str = None
) -> Dict[str, Any]:
    """
    Quick function to generate an ad image with Gemini.

    Args:
        prompt: Image generation prompt
        logo_url: Company logo URL
        reference_images: List of reference image URLs
        output_path: Where to save the generated image

    Returns:
        Dict with 'success', 'image_path', 'image_base64', 'error'
    """
    generator = GeminiImageGenerator()
    return await generator.generate_ad_image(
        prompt=prompt,
        logo_url=logo_url,
        reference_images=reference_images,
        output_path=output_path
    )

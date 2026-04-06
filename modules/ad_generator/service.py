import os
import base64
import logging
from typing import Optional, Dict, Any, Tuple
from io import BytesIO

from .schemas import (
    GenerateAdRequest, GenerateAdResponse, AdStyle, AdFormat, AdPlatform
)

# Import OpenRouter integration
try:
    from modules.openrouter import (
        OpenRouterClient,
        LUXURY_CREATIVE_GUIDELINES,
        FACEBOOK_AD_TYPES,
        OPENROUTER_API_KEY
    )
    OPENROUTER_AVAILABLE = bool(OPENROUTER_API_KEY)
except ImportError:
    OPENROUTER_AVAILABLE = False
    LUXURY_CREATIVE_GUIDELINES = {}
    FACEBOOK_AD_TYPES = {}

logger = logging.getLogger(__name__)

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Use OpenRouter by default if available
USE_OPENROUTER = os.getenv("USE_OPENROUTER", "true").lower() == "true"


class AdGeneratorService:
    """Service for generating ads using OpenRouter or Google Gemini API"""

    def __init__(self):
        self.client = None
        self.openrouter_client = None
        self._init_clients()

    def _init_clients(self):
        """Initialize AI clients (OpenRouter preferred, Gemini fallback)"""
        # Try OpenRouter first
        if USE_OPENROUTER and OPENROUTER_AVAILABLE:
            try:
                self.openrouter_client = OpenRouterClient()
                logger.info("[AdGenerator] OpenRouter client initialized successfully")
            except Exception as e:
                logger.warning(f"[AdGenerator] Failed to initialize OpenRouter: {e}")
                self.openrouter_client = None

        # Initialize Gemini as fallback
        try:
            if not GEMINI_API_KEY:
                logger.warning("[AdGenerator] GEMINI_API_KEY not configured")
                return

            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("[AdGenerator] Gemini client initialized successfully")
        except ImportError:
            logger.warning("[AdGenerator] google-genai library not installed")
            self.client = None
        except Exception as e:
            logger.error(f"[AdGenerator] Failed to initialize Gemini client: {str(e)}")
            self.client = None

    def _build_ad_prompt(self, request: GenerateAdRequest) -> str:
        """Build a detailed prompt for ad generation"""

        # Style descriptions
        style_prompts = {
            AdStyle.MODERN: "clean, contemporary design with bold typography and minimalist elements",
            AdStyle.MINIMALIST: "ultra-clean, lots of white space, simple and elegant",
            AdStyle.VIBRANT: "colorful, energetic, eye-catching with dynamic elements",
            AdStyle.PROFESSIONAL: "corporate, trustworthy, polished business aesthetic",
            AdStyle.PLAYFUL: "fun, cheerful, whimsical with rounded shapes and bright colors",
            AdStyle.ELEGANT: "luxurious, sophisticated, premium feel with refined details",
            AdStyle.BOLD: "striking, high contrast, impactful visual statements",
            AdStyle.VINTAGE: "retro, nostalgic, classic design elements with aged textures"
        }

        # Platform-specific guidelines
        platform_guidelines = {
            AdPlatform.INSTAGRAM: "Instagram-optimized, visually striking, scroll-stopping",
            AdPlatform.FACEBOOK: "Facebook ad style, clear messaging, engaging",
            AdPlatform.TWITTER: "Twitter-friendly, concise, shareable",
            AdPlatform.WHATSAPP: "WhatsApp status style, personal, relatable",
            AdPlatform.TIKTOK: "TikTok aesthetic, trendy, youthful",
            AdPlatform.WEBSITE: "Website banner style, professional, brand-focused",
            AdPlatform.GENERAL: "versatile, works across multiple platforms"
        }

        # Build the prompt
        prompt_parts = [
            f"Create a professional advertisement image for: {request.product_name}",
            f"\nProduct Description: {request.product_description}",
            f"\nVisual Style: {style_prompts.get(request.style, 'modern and professional')}",
            f"\nPlatform: {platform_guidelines.get(request.platform, 'general marketing')}"
        ]

        if request.target_audience:
            prompt_parts.append(f"\nTarget Audience: {request.target_audience}")

        if request.key_benefits:
            benefits_text = ", ".join(request.key_benefits)
            prompt_parts.append(f"\nKey Benefits to highlight: {benefits_text}")

        if request.brand_colors:
            colors_text = ", ".join(request.brand_colors)
            prompt_parts.append(f"\nUse these brand colors: {colors_text}")

        if request.include_text_overlay:
            prompt_parts.append(f"\nInclude text overlay with the product name '{request.product_name}' and call-to-action '{request.call_to_action}'")
            prompt_parts.append("\nEnsure text is legible, well-placed, and professionally designed")
        else:
            prompt_parts.append("\nCreate a purely visual ad without text overlay")

        if request.custom_prompt:
            prompt_parts.append(f"\nAdditional instructions: {request.custom_prompt}")

        # Add luxury creative guidelines if available
        if LUXURY_CREATIVE_GUIDELINES:
            prompt_parts.extend([
                "\n\nLUXURY AD CREATIVE GUIDELINES:",
                f"- Background: {LUXURY_CREATIVE_GUIDELINES.get('backgroundTone', 'neutral backdrop')}",
                f"- Surface: {LUXURY_CREATIVE_GUIDELINES.get('surfaceType', 'premium materials')}",
                f"- Accent: {LUXURY_CREATIVE_GUIDELINES.get('accentProp', 'minimal luxury prop')}",
                f"- Lighting: {LUXURY_CREATIVE_GUIDELINES.get('lighting', 'soft diffused light')}",
                f"- Composition: {LUXURY_CREATIVE_GUIDELINES.get('composition', 'asymmetrical with breathing room')}",
                f"- Colors: {', '.join(LUXURY_CREATIVE_GUIDELINES.get('colorPalette', ['champagne', 'ivory']))}",
                f"- Texture: {LUXURY_CREATIVE_GUIDELINES.get('textureEmphasis', 'tactile quality')}"
            ])

        # Add quality instructions
        prompt_parts.extend([
            "\n\nIMPORTANT REQUIREMENTS:",
            "- High quality, professional marketing image",
            "- Clean composition with clear focal point",
            "- Suitable for commercial advertising",
            "- Visually appealing and attention-grabbing",
            "- No watermarks or stock photo indicators",
            "- Premium, sophisticated aesthetic"
        ])

        return "".join(prompt_parts)

    def _build_ad_copy(self, request: GenerateAdRequest) -> str:
        """Generate ad copy text to accompany the image"""

        copy_parts = []

        # Headline
        copy_parts.append(f"✨ {request.product_name}")

        # Description
        if request.key_benefits:
            for benefit in request.key_benefits[:3]:
                copy_parts.append(f"✓ {benefit}")

        # Call to action
        copy_parts.append(f"\n👉 {request.call_to_action}")

        return "\n".join(copy_parts)

    async def generate_ad(self, request: GenerateAdRequest) -> GenerateAdResponse:
        """Generate an ad image using OpenRouter (preferred) or Gemini API"""
        # Use agent prompt if provided, otherwise build our own
        if request.agent_prompt:
            prompt = request.agent_prompt
            logger.info("[AdGenerator] Using agent-generated prompt for image creation")
        else:
            prompt = self._build_ad_prompt(request)

        logger.info(f"[AdGenerator] Generating ad with prompt: {prompt[:200]}...")

        # Try OpenRouter first if available
        if self.openrouter_client:
            result = await self._generate_with_openrouter(request, prompt)
            if result.success:
                return result
            logger.warning("[AdGenerator] OpenRouter failed, trying Gemini fallback")

        # Fall back to Gemini
        if self.client:
            result = await self._generate_with_gemini(request, prompt)
            if result.success:
                return result

        # Final fallback to simulated generation
        logger.info("[AdGenerator] No AI client available, returning simulated response")
        return self._simulate_ad_generation(request)

    async def _generate_with_openrouter(self, request: GenerateAdRequest, prompt: str) -> GenerateAdResponse:
        """Generate an ad image using OpenRouter API"""
        try:
            logger.info("[AdGenerator] Generating with OpenRouter...")

            # Generate using OpenRouter
            result = await self.openrouter_client.generate_image(
                prompt=prompt,
                apply_luxury_guidelines=True
            )

            # Extract content from response
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '')

            # Try to extract base64 image from response
            image_base64 = self._extract_image_from_openrouter_response(content)

            if image_base64:
                return GenerateAdResponse(
                    success=True,
                    image_base64=image_base64,
                    ad_copy=self._build_ad_copy(request),
                    prompt_used=prompt,
                    format=request.format.value
                )

            # If no image, generate ad copy instead
            ad_copy_result = await self.openrouter_client.generate_ad_copy(
                product_info={
                    "product_name": request.product_name,
                    "description": request.product_description,
                    "target_audience": request.target_audience or "General audience",
                    "benefits": request.key_benefits or []
                },
                ad_type="facebook-ad"
            )

            return GenerateAdResponse(
                success=True,
                image_base64=None,
                ad_copy=ad_copy_result.get('primary_text', self._build_ad_copy(request)),
                prompt_used=prompt,
                format=request.format.value
            )

        except Exception as e:
            logger.error(f"[AdGenerator] OpenRouter error: {str(e)}", exc_info=True)
            return GenerateAdResponse(
                success=False,
                error=str(e),
                format=request.format.value
            )

    def _extract_image_from_openrouter_response(self, content: Any) -> Optional[str]:
        """Extract base64 image data from OpenRouter response"""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and 'image' in item:
                    return item['image'].get('data')
        elif isinstance(content, str):
            # Check if it's a data URL
            if content.startswith('data:image'):
                return content.split(',')[1] if ',' in content else None
            # Check if it looks like base64
            if len(content) > 100 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in content[:100]):
                return content
        return None

    async def _generate_with_gemini(self, request: GenerateAdRequest, prompt: str) -> GenerateAdResponse:
        """Generate an ad image using Gemini Banana Pro"""
        try:
            logger.info("[AdGenerator] Generating with Gemini Banana Pro (gemini-2.0-flash-exp-image-generation)...")

            # Generate the image using Gemini Banana Pro
            from google.genai import types

            response = self.client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                )
            )

            # Extract image and text from response
            image_base64 = None
            generated_text = None

            # Access through candidates for proper response structure
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text is not None:
                        generated_text = part.text
                    elif hasattr(part, 'inline_data') and part.inline_data is not None:
                        image_data = part.inline_data.data
                        image_base64 = base64.b64encode(image_data).decode('utf-8')

            if image_base64:
                logger.info("[AdGenerator] Gemini Banana Pro image generation successful")
                return GenerateAdResponse(
                    success=True,
                    image_base64=image_base64,
                    ad_copy=generated_text or self._build_ad_copy(request),
                    prompt_used=prompt,
                    format=request.format.value
                )
            else:
                # Try with Imagen model
                logger.warning("[AdGenerator] No image from Gemini Banana Pro, trying Imagen 3")
                return await self._generate_with_imagen(request, prompt)

        except Exception as e:
            error_str = str(e)
            logger.error(f"[AdGenerator] Gemini Banana Pro error: {error_str}", exc_info=True)

            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                logger.info("[AdGenerator] API quota exhausted")

            return GenerateAdResponse(
                success=False,
                error=error_str,
                format=request.format.value
            )

    async def _generate_with_imagen(self, request: GenerateAdRequest, prompt: str) -> GenerateAdResponse:
        """Fallback to Imagen 3 model for image generation"""
        try:
            from google.genai import types

            logger.info("[AdGenerator] Generating with Imagen 3...")

            # Map format to aspect ratio
            format_to_ar = {
                "1:1": "1:1",
                "square": "1:1",
                "9:16": "9:16",
                "portrait": "9:16",
                "16:9": "16:9",
                "landscape": "16:9",
                "4:5": "4:5",
                "facebook_ad": "4:5",
                "banner": "16:9"
            }
            aspect_ratio = format_to_ar.get(request.format.value, "1:1")

            # Use Imagen 3 model
            response = self.client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=aspect_ratio,
                    safety_filter_level="BLOCK_MEDIUM_AND_ABOVE"
                )
            )

            if response.generated_images:
                image = response.generated_images[0]
                image_base64 = base64.b64encode(image.image.image_bytes).decode('utf-8')

                logger.info("[AdGenerator] Imagen 3 image generation successful")
                return GenerateAdResponse(
                    success=True,
                    image_base64=image_base64,
                    ad_copy=self._build_ad_copy(request),
                    prompt_used=prompt,
                    format=request.format.value
                )
            else:
                return GenerateAdResponse(
                    success=False,
                    error="No image was generated by Imagen 3",
                    format=request.format.value
                )

        except Exception as e:
            logger.error(f"[AdGenerator] Imagen 3 error: {str(e)}", exc_info=True)
            return GenerateAdResponse(
                success=False,
                error=str(e),
                format=request.format.value
            )

    def _simulate_ad_generation(self, request: GenerateAdRequest) -> GenerateAdResponse:
        """Simulate ad generation for testing when API is not available"""
        # Create a simple placeholder image
        try:
            from PIL import Image, ImageDraw, ImageFont

            # Determine dimensions based on format
            dimensions = {
                AdFormat.SQUARE: (1080, 1080),
                AdFormat.PORTRAIT: (1080, 1920),
                AdFormat.LANDSCAPE: (1920, 1080),
                AdFormat.FACEBOOK_AD: (1080, 1350),
                AdFormat.BANNER: (1200, 400)
            }

            width, height = dimensions.get(request.format, (1080, 1080))

            # Create image with gradient background
            img = Image.new('RGB', (width, height), color='#4F46E5')
            draw = ImageDraw.Draw(img)

            # Add text
            try:
                font = ImageFont.truetype("arial.ttf", 48)
                small_font = ImageFont.truetype("arial.ttf", 24)
            except:
                font = ImageFont.load_default()
                small_font = font

            # Center text
            text = request.product_name
            draw.text((width//2, height//2 - 50), text, fill='white', anchor='mm', font=font)
            draw.text((width//2, height//2 + 50), request.call_to_action, fill='#FFD700', anchor='mm', font=small_font)
            draw.text((width//2, height - 50), "[SIMULATED - API Key Required]", fill='#ffffff80', anchor='mm', font=small_font)

            # Convert to base64
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            # Use agent prompt if provided
            prompt_used = request.agent_prompt if request.agent_prompt else self._build_ad_prompt(request)

            return GenerateAdResponse(
                success=True,
                image_base64=image_base64,
                ad_copy=self._build_ad_copy(request),
                prompt_used=prompt_used,
                format=request.format.value
            )

        except Exception as e:
            logger.error(f"Error simulating ad: {str(e)}")
            return GenerateAdResponse(
                success=False,
                error=f"Simulation failed: {str(e)}",
                format=request.format.value
            )

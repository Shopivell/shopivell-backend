import os
import base64
import logging
from typing import Optional, Dict, Any, Tuple
from io import BytesIO

from .schemas import (
    GenerateAdRequest, GenerateAdResponse, AdStyle, AdFormat, AdPlatform
)

logger = logging.getLogger(__name__)

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class AdGeneratorService:
    """Service for generating ads using Google Gemini API"""

    def __init__(self):
        self.client = None
        self._init_gemini()

    def _init_gemini(self):
        """Initialize the Gemini client"""
        try:
            if not GEMINI_API_KEY:
                logger.warning("GEMINI_API_KEY not configured")
                return

            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("Gemini client initialized successfully")
        except ImportError:
            logger.warning("google-genai library not installed. Run: pip install google-genai")
            self.client = None
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {str(e)}")
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

        # Add quality instructions
        prompt_parts.extend([
            "\n\nIMPORTANT REQUIREMENTS:",
            "- High quality, professional marketing image",
            "- Clean composition with clear focal point",
            "- Suitable for commercial advertising",
            "- Visually appealing and attention-grabbing",
            "- No watermarks or stock photo indicators"
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
        """Generate an ad image using Gemini API"""
        try:
            if not self.client:
                # Return a simulated response for testing
                logger.info("Gemini client not available, returning simulated response")
                return self._simulate_ad_generation(request)

            # Use agent prompt if provided, otherwise build our own
            if request.agent_prompt:
                prompt = request.agent_prompt
                logger.info("Using agent-generated prompt for image creation")
            else:
                prompt = self._build_ad_prompt(request)
            logger.info(f"Generating ad with prompt: {prompt[:200]}...")

            # Generate the image using Gemini
            from google.genai import types

            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",  # Using the experimental model with image generation
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                )
            )

            # Extract image and text from response
            image_base64 = None
            generated_text = None

            for part in response.parts:
                if hasattr(part, 'text') and part.text is not None:
                    generated_text = part.text
                elif hasattr(part, 'inline_data') and part.inline_data is not None:
                    # Get the image data
                    image_data = part.inline_data.data
                    image_base64 = base64.b64encode(image_data).decode('utf-8')

            if image_base64:
                return GenerateAdResponse(
                    success=True,
                    image_base64=image_base64,
                    ad_copy=generated_text or self._build_ad_copy(request),
                    prompt_used=prompt,
                    format=request.format.value
                )
            else:
                # If no image was generated, try with a different approach
                logger.warning("No image generated, trying alternative method")
                return await self._generate_with_imagen(request, prompt)

        except Exception as e:
            error_str = str(e)
            logger.error(f"Error generating ad: {error_str}", exc_info=True)

            # Fall back to simulated generation on API errors (rate limits, quota, etc.)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                logger.info("API quota exhausted, falling back to simulated generation")
                return self._simulate_ad_generation(request)

            return GenerateAdResponse(
                success=False,
                error=error_str,
                format=request.format.value
            )

    async def _generate_with_imagen(self, request: GenerateAdRequest, prompt: str) -> GenerateAdResponse:
        """Fallback to Imagen model for image generation"""
        try:
            from google.genai import types

            # Use Imagen 3 model
            response = self.client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=request.format.value,
                    safety_filter_level="BLOCK_MEDIUM_AND_ABOVE"
                )
            )

            if response.generated_images:
                image = response.generated_images[0]
                image_base64 = base64.b64encode(image.image.image_bytes).decode('utf-8')

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
                    error="No image was generated",
                    format=request.format.value
                )

        except Exception as e:
            logger.error(f"Error with Imagen generation: {str(e)}", exc_info=True)
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

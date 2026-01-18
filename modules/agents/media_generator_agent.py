# media_generator_agent.py - AI Agent for Image and Video Generation
"""
Multi-provider media generation agent supporting:
- Images: Gemini Banana Pro (via OpenRouter), Imagen 3, DALL-E 3, Stability AI, Replicate (Flux)
- Videos: Google Veo 2, Replicate (Stable Video Diffusion), Runway ML, Luma AI

Primary Providers:
- IMAGE: Gemini Banana Pro (google/gemini-3-pro-image-preview via OpenRouter) - Best quality with native text
- VIDEO: Veo 2 (veo-2.0-generate-001) - Up to 8-second clips with audio
"""

import os
import base64
import logging
import httpx
import asyncio
import uuid
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from io import BytesIO
from dotenv import load_dotenv

# Import vision compliance service for image moderation
from .vision_compliance_service import vision_compliance_service, VisionComplianceResult

# Cloudinary imports
try:
    import cloudinary
    import cloudinary.uploader
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)

# Cloudinary configuration
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

CLOUDINARY_CONFIGURED = (
    CLOUDINARY_AVAILABLE and
    CLOUDINARY_CLOUD_NAME and
    CLOUDINARY_API_KEY and
    CLOUDINARY_API_SECRET and
    CLOUDINARY_CLOUD_NAME != "your_cloud_name"
)

if CLOUDINARY_CONFIGURED:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True
    )
    logger.info("[MediaGeneratorAgent] Cloudinary configured successfully")


class ImageProvider(Enum):
    GEMINI_BANANA = "gemini_banana"  # Gemini Banana Pro - Primary (native image gen + text)
    IMAGEN = "imagen"                # Imagen 3 - Fallback
    DALLE = "dalle"                  # OpenAI DALL-E 3
    STABILITY = "stability"          # Stability AI SD3
    REPLICATE = "replicate"          # Replicate Flux
    OPENROUTER = "openrouter"        # OpenRouter models


class VideoProvider(Enum):
    VEO = "veo"                  # Google Veo 2 - Primary video provider
    REPLICATE = "replicate"      # Replicate SVD/AnimateDiff
    RUNWAY = "runway"            # Runway Gen-3
    LUMA = "luma"                # Luma Dream Machine


class MediaGeneratorAgent:
    """
    AI Agent for generating images and videos using multiple providers.

    Supports automatic fallback between providers for reliability.
    """

    # Luxury Creative Guidelines for varied asset generation
    BACKGROUND_TONES = [
        "warm champagne gradient with soft golden highlights",
        "cool marble white with subtle grey veining",
        "rich burgundy velvet with deep shadows",
        "soft blush pink with cream undertones",
        "midnight navy with silver accents",
        "ivory silk with pearl shimmer",
        "dusty rose with mauve shadows",
        "charcoal grey with metallic bronze hints"
    ]

    SURFACE_TYPES = [
        "polished Carrara marble slab",
        "draped ivory satin fabric",
        "brushed gold metallic tray",
        "raw linen textile with natural texture",
        "black lacquered wood surface",
        "frosted glass pedestal",
        "white sculptural ceramic plate",
        "aged bronze mirror surface"
    ]

    ACCENT_PROPS = [
        "single white peony bloom",
        "gold-leafed sculptural hand",
        "crystal perfume stopper",
        "silk ribbon in muted tone",
        "fresh eucalyptus sprig",
        "vintage brass magnifying glass",
        "mother-of-pearl shell",
        "dried pampas grass stem",
        "porcelain figurine",
        "antique gold frame corner",
        "velvet jewelry box",
        "crystal chandelier drop"
    ]

    LIGHTING_STYLES = [
        "soft diffused natural window light from left",
        "dramatic spotlight with deep shadows",
        "golden hour warm backlighting",
        "cool studio softbox from above",
        "moody candlelit ambiance",
        "bright airy high-key lighting",
        "cinematic rim lighting with soft fill",
        "ethereal foggy diffusion"
    ]

    CAMERA_ANGLES = [
        "elegant 45-degree overhead angle",
        "intimate eye-level straight on",
        "dramatic low angle looking up",
        "artistic bird's eye flat lay",
        "sophisticated three-quarter view",
        "close-up macro detail shot",
        "wide establishing shot with depth",
        "tilted Dutch angle for intrigue"
    ]

    OVERLAY_TEXT_STYLES = [
        {"type": "cta", "examples": ["Discover Elegance", "Experience Luxury", "Elevate Your World", "Indulge Now"]},
        {"type": "launch", "examples": ["Now Available", "Introducing", "The New Standard", "Unveiled"]},
        {"type": "exclusive", "examples": ["By Invitation Only", "Limited Edition", "For the Discerning", "Exclusively Yours"]},
        {"type": "aspirational", "examples": ["Where Dreams Reside", "The Art of Living", "Beyond Ordinary", "Timeless Beauty"]}
    ]

    # ==================== INDUSTRY-SPECIFIC META-SAFE TEMPLATES ====================
    # These templates are designed to be Meta Ads compliant - NO weapons, violence, AI faces, etc.

    INDUSTRY_TEMPLATES = {
        "security": {
            "description": "Security services (NO weapons, NO armed personnel)",
            "backgrounds": [
                "modern office building lobby with glass walls",
                "smart home interior with ambient lighting",
                "clean data center with server racks",
                "corporate reception area with security desk"
            ],
            "subjects": [
                "security camera mounted on wall",
                "access control panel with keypad",
                "monitoring dashboard with multiple screens",
                "smart lock on modern door",
                "security badge and lanyard on desk"
            ],
            "props": [
                "abstract shield icon graphic",
                "padlock icon",
                "checkmark symbol",
                "24/7 badge graphic"
            ],
            "color_schemes": ["navy blue and white", "charcoal and silver", "dark blue and gold"],
            "mood": "professional, trustworthy, reliable",
            "avoid": ["weapons", "guns", "armed guards", "military", "violence", "threatening imagery"]
        },
        "food_restaurant": {
            "description": "Food and restaurant businesses",
            "backgrounds": [
                "rustic wooden table with natural light",
                "marble countertop with soft shadows",
                "restaurant interior with warm lighting",
                "outdoor cafe setting with greenery"
            ],
            "subjects": [
                "beautifully plated dish from above",
                "fresh ingredients artfully arranged",
                "chef's hands preparing food (no face)",
                "sizzling pan with steam rising"
            ],
            "props": [
                "fresh herbs and garnishes",
                "vintage silverware",
                "cloth napkin",
                "wine glass (empty or with water)"
            ],
            "color_schemes": ["warm earth tones", "white and green", "rustic browns and creams"],
            "mood": "appetizing, warm, inviting",
            "avoid": ["raw meat in unsafe conditions", "health claims", "before/after weight loss"]
        },
        "retail_ecommerce": {
            "description": "Retail and e-commerce stores",
            "backgrounds": [
                "clean white studio background",
                "minimalist shelf display",
                "lifestyle setting showing product in use",
                "gradient background matching brand colors"
            ],
            "subjects": [
                "product hero shot with clean composition",
                "product flatlay arrangement",
                "product being unboxed",
                "multiple products in collection display"
            ],
            "props": [
                "branded packaging",
                "gift ribbon",
                "shopping bag",
                "price tag or sale badge"
            ],
            "color_schemes": ["brand colors", "white and accent color", "neutral with pop of color"],
            "mood": "aspirational, clean, desirable",
            "avoid": ["competitor logos", "misleading sizing", "false scarcity claims"]
        },
        "tech_saas": {
            "description": "Technology and SaaS products",
            "backgrounds": [
                "modern desk setup with clean workspace",
                "abstract geometric gradient",
                "dark mode interface mockup",
                "minimalist office with plants"
            ],
            "subjects": [
                "laptop showing clean interface (no real data)",
                "smartphone with app mockup",
                "abstract data visualization",
                "team collaboration scene (no AI faces)"
            ],
            "props": [
                "wireless mouse and keyboard",
                "coffee cup",
                "sticky notes with icons (not text)",
                "abstract tech icons"
            ],
            "color_schemes": ["blue and white", "dark mode (blacks and purples)", "gradient tech colors"],
            "mood": "innovative, efficient, modern",
            "avoid": ["fake statistics", "competitor bashing", "unrealistic performance claims"]
        },
        "beauty_cosmetics": {
            "description": "Beauty and cosmetics products",
            "backgrounds": [
                "soft pink gradient with rose petals",
                "marble surface with golden accents",
                "bathroom vanity with soft lighting",
                "spa setting with candles (unlit appearance)"
            ],
            "subjects": [
                "product bottle/packaging hero shot",
                "texture swatch on neutral background",
                "ingredients display (botanicals, oils)",
                "product lineup arrangement"
            ],
            "props": [
                "fresh flowers or petals",
                "dropper with product",
                "makeup brushes",
                "decorative stones or crystals"
            ],
            "color_schemes": ["soft pink and gold", "clean white and rose", "nude tones"],
            "mood": "elegant, luxurious, self-care",
            "avoid": ["before/after transformations", "miracle claims", "unrealistic skin results", "AI faces"]
        },
        "health_fitness": {
            "description": "Health and fitness (NO before/after, NO miracle claims)",
            "backgrounds": [
                "modern gym with equipment",
                "outdoor park or trail setting",
                "yoga studio with natural light",
                "home workout space"
            ],
            "subjects": [
                "fitness equipment arrangement",
                "healthy meal prep (no people)",
                "workout gear flatlay",
                "water bottle and towel setup"
            ],
            "props": [
                "dumbbells and weights",
                "yoga mat and blocks",
                "resistance bands",
                "fitness tracker (generic)"
            ],
            "color_schemes": ["energetic orange and black", "calming blue and white", "natural greens"],
            "mood": "energetic, motivating, healthy",
            "avoid": ["before/after body shots", "miracle weight loss claims", "specific results promises", "supplements with health claims"]
        },
        "real_estate": {
            "description": "Real estate and property",
            "backgrounds": [
                "bright living room with large windows",
                "modern kitchen with island",
                "aerial neighborhood view",
                "home exterior with landscaping"
            ],
            "subjects": [
                "empty room staged for showing",
                "architectural details and features",
                "outdoor living space",
                "key and sold sign"
            ],
            "props": [
                "house key with keychain",
                "floor plan diagram",
                "potted plants",
                "welcome mat"
            ],
            "color_schemes": ["warm neutrals", "white and wood tones", "blue sky and green lawn"],
            "mood": "aspirational, welcoming, new beginning",
            "avoid": ["discriminatory neighborhood descriptions", "misleading property sizes"]
        },
        "professional_services": {
            "description": "Professional services (legal, consulting, finance)",
            "backgrounds": [
                "modern office with city view",
                "conference room with clean table",
                "professional desk setup",
                "abstract geometric pattern"
            ],
            "subjects": [
                "handshake (hands only, no faces)",
                "documents and contracts (blurred text)",
                "professional workspace",
                "abstract growth chart icon"
            ],
            "props": [
                "pen and notepad",
                "business card stack",
                "glasses and coffee",
                "laptop closed on desk"
            ],
            "color_schemes": ["navy and gold", "grey and blue", "white and forest green"],
            "mood": "trustworthy, professional, expert",
            "avoid": ["guaranteed results", "specific financial promises", "regulatory claims without disclaimers"]
        },
        "education": {
            "description": "Education and online courses",
            "backgrounds": [
                "modern library or study space",
                "laptop on desk with books",
                "classroom setting (empty)",
                "home office learning setup"
            ],
            "subjects": [
                "stack of books and notebooks",
                "laptop showing course interface (mockup)",
                "graduation cap and diploma",
                "certificate or badge graphic"
            ],
            "props": [
                "pencils and highlighters",
                "sticky notes with icons",
                "plant on study desk",
                "coffee and snacks"
            ],
            "color_schemes": ["academic blue and gold", "green and white", "warm yellows"],
            "mood": "inspiring, achievable, growth-oriented",
            "avoid": ["guaranteed job placement", "specific salary promises", "fake testimonials"]
        },
        "automotive": {
            "description": "Automotive and car services",
            "backgrounds": [
                "clean showroom with spotlights",
                "scenic road with beautiful landscape",
                "professional garage/workshop",
                "driveway of modern home"
            ],
            "subjects": [
                "car exterior detail shot",
                "interior dashboard and steering wheel",
                "tire and wheel closeup",
                "car keys with fob"
            ],
            "props": [
                "car cleaning supplies",
                "tool set organized",
                "car air freshener",
                "leather care products"
            ],
            "color_schemes": ["metallic silver and black", "red and white", "blue and grey"],
            "mood": "premium, reliable, freedom",
            "avoid": ["dangerous driving scenes", "speeding implications", "competitor disparagement"]
        }
    }

    def __init__(self):
        # API Keys
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        self.stability_api_key = os.getenv("STABILITY_API_KEY")
        self.replicate_api_key = os.getenv("REPLICATE_API_TOKEN")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.runway_api_key = os.getenv("RUNWAY_API_KEY")
        self.luma_api_key = os.getenv("LUMA_API_KEY")
        self.fal_api_key = os.getenv("FAL_API_KEY")

        # Determine available providers
        self.available_image_providers = self._get_available_image_providers()
        self.available_video_providers = self._get_available_video_providers()

        logger.info(f"[MediaGeneratorAgent] Initialized with image providers: {self.available_image_providers}")
        logger.info(f"[MediaGeneratorAgent] Initialized with video providers: {self.available_video_providers}")

    def _get_available_image_providers(self) -> List[ImageProvider]:
        """Get list of available image providers based on API keys.

        Priority order:
        1. GEMINI_BANANA (Gemini Banana Pro via OpenRouter) - Best quality with native text rendering
        2. IMAGEN (Imagen 3) - High-quality fallback
        3. DALLE (DALL-E 3) - OpenAI alternative
        4. REPLICATE (Flux) - Good quality
        5. STABILITY (SD3) - Stable Diffusion
        """
        providers = []
        # Priority 1: Gemini Banana Pro via OpenRouter - Best for ads with text
        if self.openrouter_api_key:
            providers.append(ImageProvider.GEMINI_BANANA)
        # Priority 2: Imagen 3 (requires Gemini API key)
        if self.gemini_api_key:
            providers.append(ImageProvider.IMAGEN)
        # Priority 3: DALL-E 3
        if self.openai_api_key:
            providers.append(ImageProvider.DALLE)
        # Priority 4: Replicate/Flux
        if self.replicate_api_key:
            providers.append(ImageProvider.REPLICATE)
        if self.fal_api_key and ImageProvider.REPLICATE not in providers:
            providers.append(ImageProvider.REPLICATE)
        # Priority 5: Stability AI
        if self.stability_api_key:
            providers.append(ImageProvider.STABILITY)
        return providers

    def _get_available_video_providers(self) -> List[VideoProvider]:
        """Get list of available video providers based on API keys.

        Priority order:
        1. VEO (Google Veo 2) - Up to 8-sec clips with native audio
        2. RUNWAY (Gen-3) - High quality video generation
        3. LUMA (Dream Machine) - Alternative provider
        4. REPLICATE (SVD/AnimateDiff) - Basic fallback
        """
        providers = []
        # Priority 1: Google Veo 3 - Best quality + native audio
        if self.gemini_api_key:
            providers.append(VideoProvider.VEO)
        # Priority 2: Runway ML Gen-3
        if self.runway_api_key:
            providers.append(VideoProvider.RUNWAY)
        # Priority 3: Luma AI Dream Machine
        if self.luma_api_key:
            providers.append(VideoProvider.LUMA)
        # Priority 4: Replicate (SVD/AnimateDiff)
        if self.replicate_api_key:
            providers.append(VideoProvider.REPLICATE)
        if self.fal_api_key and VideoProvider.REPLICATE not in providers:
            providers.append(VideoProvider.REPLICATE)
        return providers

    # ==================== CLOUDINARY UPLOAD ====================

    def upload_to_cloudinary(
        self,
        image_base64: str,
        folder: str = "shopivell/generated",
        resource_type: str = "image"
    ) -> Dict[str, Any]:
        """
        Upload a base64 image to Cloudinary.

        Args:
            image_base64: Base64 encoded image data
            folder: Cloudinary folder path
            resource_type: 'image' or 'video'

        Returns:
            Dict with cloudinary_url, public_id, and metadata
        """
        if not CLOUDINARY_CONFIGURED:
            logger.warning("[MediaGeneratorAgent] Cloudinary not configured, skipping upload")
            return {
                "uploaded": False,
                "error": "Cloudinary not configured"
            }

        try:
            # Prepare the data URI
            data_uri = f"data:image/png;base64,{image_base64}"

            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                data_uri,
                folder=folder,
                resource_type=resource_type,
                public_id=f"generated_{uuid.uuid4().hex[:12]}",
                overwrite=True,
                eager=[
                    {"width": 300, "height": 300, "crop": "fill", "format": "jpg"}  # Thumbnail
                ],
                eager_async=False
            )

            # Extract thumbnail URL
            thumbnail_url = None
            if result.get("eager") and len(result["eager"]) > 0:
                thumbnail_url = result["eager"][0].get("secure_url")

            logger.info(f"[MediaGeneratorAgent] Uploaded to Cloudinary: {result.get('secure_url')}")

            return {
                "uploaded": True,
                "public_id": result.get("public_id"),
                "url": result.get("url"),
                "secure_url": result.get("secure_url"),
                "cloudinary_url": result.get("secure_url"),
                "thumbnail_url": thumbnail_url,
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
                "bytes": result.get("bytes")
            }

        except Exception as e:
            logger.error(f"[MediaGeneratorAgent] Cloudinary upload error: {str(e)}")
            return {
                "uploaded": False,
                "error": str(e)
            }

    async def upload_video_to_cloudinary(
        self,
        video_base64: str,
        folder: str = "shopivell/generated/videos"
    ) -> Dict[str, Any]:
        """Upload a base64 video to Cloudinary."""
        if not CLOUDINARY_CONFIGURED:
            return {"uploaded": False, "error": "Cloudinary not configured"}

        try:
            data_uri = f"data:video/mp4;base64,{video_base64}"

            result = cloudinary.uploader.upload(
                data_uri,
                folder=folder,
                resource_type="video",
                public_id=f"video_{uuid.uuid4().hex[:12]}",
                overwrite=True
            )

            logger.info(f"[MediaGeneratorAgent] Video uploaded to Cloudinary: {result.get('secure_url')}")

            return {
                "uploaded": True,
                "public_id": result.get("public_id"),
                "url": result.get("url"),
                "secure_url": result.get("secure_url"),
                "cloudinary_url": result.get("secure_url"),
                "duration": result.get("duration"),
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
                "bytes": result.get("bytes")
            }

        except Exception as e:
            logger.error(f"[MediaGeneratorAgent] Cloudinary video upload error: {str(e)}")
            return {"uploaded": False, "error": str(e)}

    # ==================== IMAGE GENERATION ====================

    async def generate_image(
        self,
        prompt: str,
        style: str = "professional",
        aspect_ratio: str = "1:1",
        provider: Optional[ImageProvider] = None,
        upload_to_cloud: bool = True,
        cloudinary_folder: str = "shopivell/generated/ads"
    ) -> Dict[str, Any]:
        """
        Generate an image using available providers with automatic fallback.

        Args:
            prompt: The image generation prompt
            style: Visual style (professional, vibrant, minimal, etc.)
            aspect_ratio: Image aspect ratio (1:1, 16:9, 9:16, 4:5)
            provider: Specific provider to use, or None for auto-selection
            upload_to_cloud: Whether to upload to Cloudinary (default: True)
            cloudinary_folder: Folder path in Cloudinary

        Returns:
            Dict with image_base64, cloudinary_url, provider_used, and metadata
        """
        # Enhance prompt with style
        enhanced_prompt = self._enhance_image_prompt(prompt, style)

        # Try providers in order
        providers_to_try = [provider] if provider else self.available_image_providers

        for prov in providers_to_try:
            try:
                logger.info(f"[MediaGeneratorAgent] Trying image generation with {prov.value}")

                if prov == ImageProvider.GEMINI_BANANA:
                    result = await self._generate_gemini_banana_image(enhanced_prompt, aspect_ratio)
                elif prov == ImageProvider.IMAGEN:
                    result = await self._generate_imagen_image(enhanced_prompt, aspect_ratio)
                elif prov == ImageProvider.DALLE:
                    result = await self._generate_dalle(enhanced_prompt, aspect_ratio)
                elif prov == ImageProvider.STABILITY:
                    result = await self._generate_stability(enhanced_prompt, aspect_ratio)
                elif prov == ImageProvider.REPLICATE:
                    result = await self._generate_replicate_image(enhanced_prompt, aspect_ratio)
                else:
                    continue

                if result and result.get("image_base64"):
                    result["provider_used"] = prov.value
                    logger.info(f"[MediaGeneratorAgent] Successfully generated image with {prov.value}")

                    # Run vision compliance check on AI-generated images
                    try:
                        logger.info("[MediaGeneratorAgent] Running vision compliance check...")
                        compliance_result = await vision_compliance_service.analyze_image(
                            image_base64=result["image_base64"],
                            industry=None  # Can be enhanced to pass industry context
                        )

                        # Add compliance info to result
                        result["compliance_check"] = {
                            "is_compliant": compliance_result.is_compliant,
                            "risk_level": compliance_result.risk_level,
                            "confidence": compliance_result.confidence,
                            "analysis_time_ms": compliance_result.analysis_time_ms
                        }

                        # Handle compliance results
                        if not compliance_result.is_compliant:
                            if compliance_result.risk_level == "critical":
                                # Block critical violations - don't return the image
                                logger.warning(f"[MediaGeneratorAgent] Image blocked due to critical compliance violation: {[i.description for i in compliance_result.issues]}")
                                return {
                                    "image_base64": None,
                                    "blocked": True,
                                    "block_reason": "Critical compliance violation detected",
                                    "compliance_issues": [
                                        {
                                            "category": issue.category,
                                            "severity": issue.severity,
                                            "description": issue.description,
                                            "location": issue.location
                                        }
                                        for issue in compliance_result.issues
                                    ],
                                    "suggestions": compliance_result.suggestions,
                                    "provider_used": prov.value
                                }
                            else:
                                # Flag for review but allow (medium/high risk)
                                result["requires_review"] = True
                                result["compliance_warnings"] = [
                                    {
                                        "category": issue.category,
                                        "severity": issue.severity,
                                        "description": issue.description,
                                        "location": issue.location
                                    }
                                    for issue in compliance_result.issues
                                ]
                                result["compliance_suggestions"] = compliance_result.suggestions
                                logger.warning(f"[MediaGeneratorAgent] Image flagged for review: {[i.category for i in compliance_result.issues]}")
                        else:
                            logger.info(f"[MediaGeneratorAgent] Image passed compliance check (risk: {compliance_result.risk_level})")

                    except Exception as compliance_error:
                        # Log compliance check failure but don't block image
                        logger.warning(f"[MediaGeneratorAgent] Compliance check failed: {str(compliance_error)}")
                        result["compliance_check"] = {
                            "error": str(compliance_error),
                            "status": "check_failed",
                            "requires_manual_review": True
                        }

                    # Upload to Cloudinary if enabled
                    if upload_to_cloud and result.get("image_base64"):
                        logger.info("[MediaGeneratorAgent] Uploading image to Cloudinary...")
                        cloudinary_result = self.upload_to_cloudinary(
                            image_base64=result["image_base64"],
                            folder=cloudinary_folder
                        )
                        if cloudinary_result.get("uploaded"):
                            result["cloudinary"] = cloudinary_result
                            result["cloudinary_url"] = cloudinary_result.get("secure_url")
                            result["thumbnail_url"] = cloudinary_result.get("thumbnail_url")
                            logger.info(f"[MediaGeneratorAgent] Image uploaded: {result['cloudinary_url']}")
                        else:
                            result["cloudinary"] = cloudinary_result
                            logger.warning(f"[MediaGeneratorAgent] Cloudinary upload failed: {cloudinary_result.get('error')}")

                    return result

            except Exception as e:
                logger.warning(f"[MediaGeneratorAgent] {prov.value} failed: {str(e)}")
                continue

        # All providers failed - return placeholder
        logger.warning("[MediaGeneratorAgent] All image providers failed, using placeholder")
        return self._generate_placeholder_image(prompt, aspect_ratio)

    def _enhance_image_prompt(self, prompt: str, style: str) -> str:
        """Enhance the prompt with style modifiers"""
        style_modifiers = {
            "professional": "professional commercial photography, high quality, clean composition, studio lighting",
            "vibrant": "vibrant colors, eye-catching, dynamic composition, energetic",
            "minimal": "minimalist design, clean white background, simple elegant composition",
            "luxury": "luxury aesthetic, premium feel, sophisticated lighting, elegant composition",
            "lifestyle": "authentic lifestyle photography, natural lighting, relatable setting",
            "bold": "bold graphic design, high contrast, striking visual impact",
            "cinematic": "cinematic quality, dramatic lighting, movie-like composition"
        }

        modifier = style_modifiers.get(style, style_modifiers["professional"])
        return f"{prompt}. Style: {modifier}. No text or watermarks."

    async def _generate_dalle(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate image using OpenAI DALL-E 3"""
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not configured")

        # Map aspect ratio to DALL-E size
        size_map = {
            "1:1": "1024x1024",
            "16:9": "1792x1024",
            "9:16": "1024x1792",
            "4:5": "1024x1024"  # DALL-E doesn't support 4:5, use square
        }
        size = size_map.get(aspect_ratio, "1024x1024")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                    "quality": "hd",
                    "response_format": "b64_json"
                }
            )
            response.raise_for_status()
            data = response.json()

            return {
                "image_base64": data["data"][0]["b64_json"],
                "revised_prompt": data["data"][0].get("revised_prompt", prompt),
                "model": "dall-e-3"
            }

    async def _generate_stability(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate image using Stability AI"""
        if not self.stability_api_key:
            raise ValueError("Stability API key not configured")

        # Map aspect ratio
        ar_map = {
            "1:1": "1:1",
            "16:9": "16:9",
            "9:16": "9:16",
            "4:5": "4:5"
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.stability.ai/v2beta/stable-image/generate/sd3",
                headers={
                    "Authorization": f"Bearer {self.stability_api_key}",
                    "Accept": "application/json"
                },
                files={
                    "prompt": (None, prompt),
                    "aspect_ratio": (None, ar_map.get(aspect_ratio, "1:1")),
                    "output_format": (None, "png"),
                    "model": (None, "sd3-large")
                }
            )
            response.raise_for_status()
            data = response.json()

            return {
                "image_base64": data.get("image"),
                "model": "stable-diffusion-3"
            }

    async def _generate_replicate_image(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate image using Replicate (Flux model)"""
        api_key = self.replicate_api_key or self.fal_api_key
        if not api_key:
            raise ValueError("Replicate/FAL API key not configured")

        async with httpx.AsyncClient(timeout=180.0) as client:
            # Start the prediction
            response = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "version": "black-forest-labs/flux-1.1-pro",
                    "input": {
                        "prompt": prompt,
                        "aspect_ratio": aspect_ratio,
                        "output_format": "png",
                        "output_quality": 90
                    }
                }
            )
            response.raise_for_status()
            prediction = response.json()

            # Poll for completion
            prediction_id = prediction["id"]
            for _ in range(60):  # Max 60 attempts (2 minutes)
                await asyncio.sleep(2)

                status_response = await client.get(
                    f"https://api.replicate.com/v1/predictions/{prediction_id}",
                    headers={"Authorization": f"Token {api_key}"}
                )
                status_data = status_response.json()

                if status_data["status"] == "succeeded":
                    output_url = status_data["output"]
                    if isinstance(output_url, list):
                        output_url = output_url[0]

                    # Download the image
                    img_response = await client.get(output_url)
                    image_base64 = base64.b64encode(img_response.content).decode("utf-8")

                    return {
                        "image_base64": image_base64,
                        "model": "flux-1.1-pro"
                    }
                elif status_data["status"] == "failed":
                    raise Exception(f"Replicate prediction failed: {status_data.get('error')}")

            raise Exception("Replicate prediction timed out")

    async def _generate_gemini_banana_image(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate image using Gemini Banana Pro via OpenRouter.

        This is the PRIMARY image provider:
        - Best quality for ad images with text
        - Native text rendering in images
        - Model: google/gemini-3-pro-image-preview (via OpenRouter)
        """
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise ValueError("OpenRouter API key not configured")

        try:
            import json

            # Enhanced prompt for better ad image generation
            enhanced_prompt = f"""Create a high-quality advertisement image:

{prompt}

Requirements:
- Professional commercial photography quality
- Clean composition with clear focal point
- Aspect ratio: {aspect_ratio}
- No watermarks or stock photo indicators
- Premium, sophisticated aesthetic
- Photorealistic, 8K quality"""

            logger.info("[MediaGeneratorAgent] Generating with Gemini Banana Pro via OpenRouter (google/gemini-3-pro-image-preview)...")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "google/gemini-3-pro-image-preview",
                        "messages": [
                            {
                                "role": "user",
                                "content": enhanced_prompt
                            }
                        ],
                        "modalities": ["image", "text"]
                    }
                )

                result = response.json()

                if result.get("choices"):
                    message = result["choices"][0]["message"]
                    if message.get("images"):
                        for image in message["images"]:
                            image_url = image["image_url"]["url"]
                            # Extract base64 from data URL (format: data:image/png;base64,...)
                            if image_url.startswith("data:"):
                                # Remove the data URL prefix
                                image_base64 = image_url.split(",", 1)[1] if "," in image_url else image_url
                            else:
                                image_base64 = image_url

                            logger.info("[MediaGeneratorAgent] Gemini Banana Pro generation successful via OpenRouter")
                            return {
                                "image_base64": image_base64,
                                "model": "gemini-banana-pro",
                                "supports_text": True
                            }

                # Check for error
                if result.get("error"):
                    raise Exception(f"OpenRouter error: {result['error']}")

            raise Exception("No image generated by Gemini Banana Pro")

        except Exception as e:
            raise Exception(f"Gemini Banana Pro image generation failed: {str(e)}")

    async def _generate_imagen_image(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate image using Google Imagen 3 (fallback provider)"""
        if not self.gemini_api_key:
            raise ValueError("Gemini API key not configured")

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)

            # Map aspect ratio format
            ar_map = {
                "1:1": "1:1",
                "16:9": "16:9",
                "9:16": "9:16",
                "4:5": "4:5",
                "4:3": "4:3",
                "3:4": "3:4"
            }
            mapped_ar = ar_map.get(aspect_ratio, "1:1")

            logger.info(f"[MediaGeneratorAgent] Generating with Imagen 3, aspect ratio: {mapped_ar}")

            # Use Imagen 3 for high-quality image generation
            response = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=mapped_ar,
                    safety_filter_level="BLOCK_MEDIUM_AND_ABOVE"
                )
            )

            if response.generated_images:
                image = response.generated_images[0]
                image_base64 = base64.b64encode(image.image.image_bytes).decode("utf-8")
                logger.info("[MediaGeneratorAgent] Imagen 3 generation successful")
                return {
                    "image_base64": image_base64,
                    "model": "imagen-3.0-generate-002"
                }

            raise Exception("No image generated by Imagen 3")

        except Exception as e:
            raise Exception(f"Imagen 3 image generation failed: {str(e)}")

    def _generate_placeholder_image(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate a placeholder image when all providers fail"""
        try:
            from PIL import Image, ImageDraw, ImageFont

            # Determine dimensions
            dimensions = {
                "1:1": (1080, 1080),
                "16:9": (1920, 1080),
                "9:16": (1080, 1920),
                "4:5": (1080, 1350)
            }
            width, height = dimensions.get(aspect_ratio, (1080, 1080))

            # Create gradient background
            img = Image.new('RGB', (width, height), color='#667eea')
            draw = ImageDraw.Draw(img)

            # Add gradient effect
            for i in range(height):
                ratio = i / height
                r = int(102 + (118 - 102) * ratio)
                g = int(126 + (75 - 126) * ratio)
                b = int(234 + (109 - 234) * ratio)
                draw.line([(0, i), (width, i)], fill=(r, g, b))

            # Add text
            try:
                font = ImageFont.truetype("arial.ttf", 48)
                small_font = ImageFont.truetype("arial.ttf", 24)
            except:
                font = ImageFont.load_default()
                small_font = font

            # Extract product name from prompt
            product_name = prompt.split('.')[0][:50] if '.' in prompt else prompt[:50]

            draw.text((width//2, height//2 - 30), product_name, fill='white', anchor='mm', font=font)
            draw.text((width//2, height//2 + 40), "Learn More", fill='#FFD700', anchor='mm', font=small_font)
            draw.text((width//2, height - 60), "[Placeholder - Configure API Key]", fill='#ffffff80', anchor='mm', font=small_font)

            # Convert to base64
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return {
                "image_base64": image_base64,
                "model": "placeholder",
                "is_placeholder": True
            }

        except Exception as e:
            logger.error(f"Failed to generate placeholder: {e}")
            return {"image_base64": None, "error": str(e)}

    # ==================== VIDEO GENERATION ====================

    async def generate_video(
        self,
        prompt: str,
        image_base64: Optional[str] = None,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        provider: Optional[VideoProvider] = None
    ) -> Dict[str, Any]:
        """
        Generate a video using available providers.

        Args:
            prompt: The video generation prompt
            image_base64: Optional starting image for image-to-video
            duration: Video duration in seconds (3-10)
            aspect_ratio: Video aspect ratio
            provider: Specific provider or None for auto-selection

        Returns:
            Dict with video_base64 or video_url, provider_used, and metadata
        """
        providers_to_try = [provider] if provider else self.available_video_providers

        for prov in providers_to_try:
            try:
                logger.info(f"[MediaGeneratorAgent] Trying video generation with {prov.value}")

                if prov == VideoProvider.VEO:
                    result = await self._generate_veo_video(prompt, image_base64, duration, aspect_ratio)
                elif prov == VideoProvider.REPLICATE:
                    result = await self._generate_replicate_video(prompt, image_base64, duration, aspect_ratio)
                elif prov == VideoProvider.RUNWAY:
                    result = await self._generate_runway_video(prompt, image_base64, duration)
                elif prov == VideoProvider.LUMA:
                    result = await self._generate_luma_video(prompt, image_base64, duration, aspect_ratio)
                else:
                    continue

                if result and (result.get("video_base64") or result.get("video_url")):
                    result["provider_used"] = prov.value
                    logger.info(f"[MediaGeneratorAgent] Successfully generated video with {prov.value}")
                    return result

            except Exception as e:
                logger.warning(f"[MediaGeneratorAgent] {prov.value} video generation failed: {str(e)}")
                continue

        # All providers failed
        logger.warning("[MediaGeneratorAgent] All video providers failed")
        return {
            "video_base64": None,
            "video_url": None,
            "error": "All video providers failed or not configured",
            "available_providers": [p.value for p in self.available_video_providers]
        }

    async def _generate_veo_video(
        self,
        prompt: str,
        image_base64: Optional[str],
        duration: int,
        aspect_ratio: str
    ) -> Dict[str, Any]:
        """Generate video using Google Veo 2.

        This is the PRIMARY video provider:
        - Best quality for ad videos
        - Native audio support
        - Duration: Up to 8 seconds per clip
        - Model: veo-2.0-generate-001
        """
        if not self.gemini_api_key:
            raise ValueError("Gemini API key not configured for Veo")

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)

            # Build video generation request for Veo 2
            video_prompt = f"""Create a professional advertising video:

{prompt}

Requirements:
- Duration: {min(duration, 8)} seconds
- Aspect ratio: {aspect_ratio}
- Style: High-quality commercial, smooth camera movements, professional lighting
- No text overlays or watermarks
- Cinematic quality with dynamic visuals"""

            logger.info(f"[MediaGeneratorAgent] Generating video with Veo 2, duration: {min(duration, 8)}s")

            # Try Veo 2 for video generation
            try:
                # Generate video with Veo 2 model
                operation = client.models.generate_videos(
                    model="veo-2.0-generate-001",
                    prompt=video_prompt,
                    config=types.GenerateVideosConfig(
                        aspect_ratio=aspect_ratio,
                        number_of_videos=1,
                        duration_seconds=min(duration, 8),
                        person_generation="dont_allow"  # Safe for ads
                    )
                )

                # Wait for the operation to complete
                logger.info("[MediaGeneratorAgent] Waiting for Veo 2 video generation...")

                # Poll for completion (video generation can take 1-3 minutes)
                for attempt in range(60):  # Max 5 minutes
                    await asyncio.sleep(5)

                    # Check if operation is complete
                    result = operation.result(timeout=5)
                    if result and result.generated_videos:
                        video = result.generated_videos[0]

                        # Get video data
                        if hasattr(video, 'video') and video.video:
                            video_bytes = video.video.video_bytes
                            video_base64 = base64.b64encode(video_bytes).decode("utf-8")

                            logger.info("[MediaGeneratorAgent] Veo 2 video generation successful")
                            return {
                                "video_base64": video_base64,
                                "video_url": None,
                                "model": "veo-2.0-generate-001",
                                "duration": min(duration, 8),
                                "has_audio": True
                            }

                raise Exception("Veo 2 video generation timed out")

            except Exception as veo_error:
                logger.warning(f"[MediaGeneratorAgent] Veo 2 failed: {veo_error}")

                # Fallback: Try using Gemini with video prompt for creative direction
                # This won't generate actual video but provides video concept
                raise Exception(f"Veo 2 video generation failed: {str(veo_error)}")

        except Exception as e:
            raise Exception(f"Veo video generation failed: {str(e)}")

    async def _generate_replicate_video(
        self,
        prompt: str,
        image_base64: Optional[str],
        duration: int,
        aspect_ratio: str
    ) -> Dict[str, Any]:
        """Generate video using Replicate (Stable Video Diffusion or Kling) - Fallback"""
        api_key = self.replicate_api_key or self.fal_api_key
        if not api_key:
            raise ValueError("Replicate API key not configured")

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Use different model based on whether we have an image
            if image_base64:
                # Image-to-video with Stable Video Diffusion
                model = "stability-ai/stable-video-diffusion:3f0457e4619daac51203dedb472816fd4af51f3149fa7a9e0b5ffcf1b8172438"
                input_data = {
                    "input_image": f"data:image/png;base64,{image_base64}",
                    "motion_bucket_id": 127,
                    "fps": 24,
                    "cond_aug": 0.02
                }
            else:
                # Text-to-video with AnimateDiff or similar
                model = "lucataco/animate-diff:beecf59c4aee8d81bf04f0381033dfa10dc16e845b4ae00d281e2fa377e48571"
                input_data = {
                    "prompt": prompt,
                    "negative_prompt": "bad quality, worst quality, jpeg artifacts, blurry",
                    "num_frames": min(duration * 8, 32),
                    "num_inference_steps": 25,
                    "guidance_scale": 7.5
                }

            # Start prediction
            response = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "version": model.split(":")[-1] if ":" in model else model,
                    "input": input_data
                }
            )
            response.raise_for_status()
            prediction = response.json()

            # Poll for completion
            prediction_id = prediction["id"]
            for _ in range(120):  # Max 4 minutes
                await asyncio.sleep(2)

                status_response = await client.get(
                    f"https://api.replicate.com/v1/predictions/{prediction_id}",
                    headers={"Authorization": f"Token {api_key}"}
                )
                status_data = status_response.json()

                if status_data["status"] == "succeeded":
                    output = status_data["output"]
                    video_url = output if isinstance(output, str) else output[0]

                    # Download and encode video
                    video_response = await client.get(video_url)
                    video_base64 = base64.b64encode(video_response.content).decode("utf-8")

                    return {
                        "video_base64": video_base64,
                        "video_url": video_url,
                        "model": "stable-video-diffusion" if image_base64 else "animate-diff",
                        "duration": duration
                    }
                elif status_data["status"] == "failed":
                    raise Exception(f"Replicate video failed: {status_data.get('error')}")

            raise Exception("Replicate video generation timed out")

    async def _generate_runway_video(
        self,
        prompt: str,
        image_base64: Optional[str],
        duration: int
    ) -> Dict[str, Any]:
        """Generate video using Runway ML Gen-3"""
        if not self.runway_api_key:
            raise ValueError("Runway API key not configured")

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Runway Gen-3 Alpha API
            payload = {
                "promptText": prompt,
                "duration": min(duration, 10),
                "ratio": "16:9"
            }

            if image_base64:
                payload["promptImage"] = f"data:image/png;base64,{image_base64}"

            response = await client.post(
                "https://api.runwayml.com/v1/tasks",
                headers={
                    "Authorization": f"Bearer {self.runway_api_key}",
                    "Content-Type": "application/json",
                    "X-Runway-Version": "2024-11-06"
                },
                json={
                    "taskType": "gen3a_turbo",
                    "options": payload
                }
            )
            response.raise_for_status()
            task = response.json()

            # Poll for completion
            task_id = task["id"]
            for _ in range(120):
                await asyncio.sleep(3)

                status_response = await client.get(
                    f"https://api.runwayml.com/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self.runway_api_key}"}
                )
                status_data = status_response.json()

                if status_data["status"] == "SUCCEEDED":
                    video_url = status_data["output"][0]

                    # Download video
                    video_response = await client.get(video_url)
                    video_base64 = base64.b64encode(video_response.content).decode("utf-8")

                    return {
                        "video_base64": video_base64,
                        "video_url": video_url,
                        "model": "runway-gen3-turbo",
                        "duration": duration
                    }
                elif status_data["status"] == "FAILED":
                    raise Exception(f"Runway failed: {status_data.get('error')}")

            raise Exception("Runway video generation timed out")

    async def _generate_luma_video(
        self,
        prompt: str,
        image_base64: Optional[str],
        duration: int,
        aspect_ratio: str
    ) -> Dict[str, Any]:
        """Generate video using Luma AI Dream Machine"""
        if not self.luma_api_key:
            raise ValueError("Luma API key not configured")

        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "loop": False
            }

            if image_base64:
                payload["keyframes"] = {
                    "frame0": {
                        "type": "image",
                        "url": f"data:image/png;base64,{image_base64}"
                    }
                }

            response = await client.post(
                "https://api.lumalabs.ai/dream-machine/v1/generations",
                headers={
                    "Authorization": f"Bearer {self.luma_api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            generation = response.json()

            # Poll for completion
            generation_id = generation["id"]
            for _ in range(120):
                await asyncio.sleep(3)

                status_response = await client.get(
                    f"https://api.lumalabs.ai/dream-machine/v1/generations/{generation_id}",
                    headers={"Authorization": f"Bearer {self.luma_api_key}"}
                )
                status_data = status_response.json()

                if status_data["state"] == "completed":
                    video_url = status_data["assets"]["video"]

                    video_response = await client.get(video_url)
                    video_base64 = base64.b64encode(video_response.content).decode("utf-8")

                    return {
                        "video_base64": video_base64,
                        "video_url": video_url,
                        "model": "luma-dream-machine",
                        "duration": duration
                    }
                elif status_data["state"] == "failed":
                    raise Exception(f"Luma failed: {status_data.get('failure_reason')}")

            raise Exception("Luma video generation timed out")

    # ==================== BATCH GENERATION ====================

    async def generate_ad_media(
        self,
        product_info: Dict[str, Any],
        ad_angle: Dict[str, Any],
        generate_video: bool = False
    ) -> Dict[str, Any]:
        """
        Generate complete ad media (image and optionally video) for an ad.

        Args:
            product_info: Product details (name, description, benefits, etc.)
            ad_angle: Creative angle information
            generate_video: Whether to also generate a video

        Returns:
            Dict with image and optional video data
        """
        # Build image prompt
        image_prompt = self._build_ad_image_prompt(product_info, ad_angle)

        # Generate image
        image_result = await self.generate_image(
            prompt=image_prompt,
            style=ad_angle.get("visual_style", "professional"),
            aspect_ratio=ad_angle.get("aspect_ratio", "1:1")
        )

        result = {
            "image": image_result,
            "prompt_used": image_prompt
        }

        # Generate video if requested
        if generate_video and image_result.get("image_base64"):
            video_prompt = self._build_ad_video_prompt(product_info, ad_angle)
            video_result = await self.generate_video(
                prompt=video_prompt,
                image_base64=image_result["image_base64"],
                duration=5,
                aspect_ratio="16:9"
            )
            result["video"] = video_result

        return result

    def _build_ad_image_prompt(self, product_info: Dict, ad_angle: Dict) -> str:
        """Build an optimized prompt for ad image generation"""
        prompt_parts = [
            f"Professional advertisement for {product_info.get('product_name', 'product')}.",
            f"Product: {product_info.get('product_description', '')[:200]}.",
        ]

        if ad_angle.get("visual_direction"):
            prompt_parts.append(f"Visual direction: {ad_angle['visual_direction']}.")

        if ad_angle.get("emotion_target"):
            prompt_parts.append(f"Evoke feeling of: {ad_angle['emotion_target']}.")

        prompt_parts.append("High quality commercial photography, clean composition, no text.")

        return " ".join(prompt_parts)

    def _build_ad_video_prompt(self, product_info: Dict, ad_angle: Dict) -> str:
        """Build an optimized prompt for ad video generation"""
        return f"""
        Cinematic advertisement video for {product_info.get('product_name', 'product')}.
        Show the product in action with smooth camera movements.
        {ad_angle.get('visual_direction', 'Professional and engaging visuals')}.
        High production quality, commercial style, no text overlays.
        """

    # ==================== LUXURY ASSET GENERATION ====================

    def generate_luxury_asset_prompts(
        self,
        product_name: str,
        product_description: str,
        num_assets: int = 5,
        brand_colors: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate varied luxury ad asset specifications with unique combinations.

        Each asset has different:
        - backgroundTone
        - surfaceType
        - accentProp
        - lighting
        - cameraAngle
        - overlayText

        Returns structured JSON for each asset.
        """
        import random

        # Shuffle all options to ensure variety
        backgrounds = random.sample(self.BACKGROUND_TONES, min(num_assets, len(self.BACKGROUND_TONES)))
        surfaces = random.sample(self.SURFACE_TYPES, min(num_assets, len(self.SURFACE_TYPES)))
        accents = random.sample(self.ACCENT_PROPS, min(num_assets, len(self.ACCENT_PROPS)))
        lightings = random.sample(self.LIGHTING_STYLES, min(num_assets, len(self.LIGHTING_STYLES)))
        angles = random.sample(self.CAMERA_ANGLES, min(num_assets, len(self.CAMERA_ANGLES)))

        assets = []
        used_combinations = set()

        for i in range(num_assets):
            # Select unique combination
            bg = backgrounds[i % len(backgrounds)]
            surface = surfaces[i % len(surfaces)]
            accent = accents[i % len(accents)]
            lighting = lightings[i % len(lightings)]
            angle = angles[i % len(angles)]

            # Generate overlay text
            text_style = random.choice(self.OVERLAY_TEXT_STYLES)
            overlay_text = random.choice(text_style["examples"])

            # Build the image prompt
            image_prompt = self._build_luxury_prompt(
                product_name=product_name,
                product_description=product_description,
                background_tone=bg,
                surface_type=surface,
                accent_prop=accent,
                lighting=lighting,
                camera_angle=angle,
                brand_colors=brand_colors
            )

            asset = {
                "asset_number": i + 1,
                "creative_direction": {
                    "backgroundTone": bg,
                    "surfaceType": surface,
                    "accentProp": accent,
                    "lighting": lighting,
                    "cameraAngle": angle,
                    "overlayText": {
                        "type": text_style["type"],
                        "text": overlay_text
                    }
                },
                "image_prompt": image_prompt,
                "mood": self._determine_mood(bg, lighting),
                "recommended_format": self._recommend_format(angle)
            }

            assets.append(asset)

        return assets

    def _build_luxury_prompt(
        self,
        product_name: str,
        product_description: str,
        background_tone: str,
        surface_type: str,
        accent_prop: str,
        lighting: str,
        camera_angle: str,
        brand_colors: Optional[List[str]] = None
    ) -> str:
        """Build a detailed luxury product photography prompt"""

        color_instruction = ""
        if brand_colors:
            color_instruction = f"Incorporate brand colors: {', '.join(brand_colors)}. "

        prompt = f"""Ultra-premium luxury product photography of {product_name}.

SCENE SETUP:
- Background: {background_tone}
- Surface: {surface_type}
- Accent prop: {accent_prop} placed elegantly nearby
- Lighting: {lighting}
- Camera: {camera_angle}

PRODUCT CONTEXT:
{product_description}

STYLE REQUIREMENTS:
- High-end editorial quality, magazine-worthy composition
- {color_instruction}Tasteful, intentional styling with premium feel
- Clean, uncluttered composition with breathing room
- Product as hero, accent props complement but don't distract
- Luxurious texture emphasis on materials
- No text, watermarks, or logos in the image
- Photorealistic, 8K quality, professional product photography"""

        return prompt

    def _determine_mood(self, background: str, lighting: str) -> str:
        """Determine the mood based on background and lighting"""
        if "warm" in background.lower() or "golden" in lighting.lower():
            return "warm and inviting"
        elif "dark" in background.lower() or "dramatic" in lighting.lower() or "moody" in lighting.lower():
            return "dramatic and sophisticated"
        elif "pink" in background.lower() or "blush" in background.lower():
            return "soft and romantic"
        elif "navy" in background.lower() or "charcoal" in background.lower():
            return "bold and elegant"
        else:
            return "refined and luxurious"

    def _recommend_format(self, camera_angle: str) -> Dict[str, str]:
        """Recommend format based on camera angle"""
        if "flat lay" in camera_angle.lower() or "overhead" in camera_angle.lower():
            return {"ratio": "1:1", "placement": "Instagram Feed, Facebook Feed"}
        elif "wide" in camera_angle.lower():
            return {"ratio": "16:9", "placement": "Website Banner, YouTube Thumbnail"}
        elif "close-up" in camera_angle.lower():
            return {"ratio": "4:5", "placement": "Instagram Feed Portrait"}
        else:
            return {"ratio": "9:16", "placement": "Instagram Stories, Reels, TikTok"}

    async def generate_luxury_ad_assets(
        self,
        product_name: str,
        product_description: str,
        num_assets: int = 5,
        brand_colors: Optional[List[str]] = None,
        generate_images: bool = True
    ) -> Dict[str, Any]:
        """
        Generate complete luxury ad assets with varied creative directions.

        Returns JSON with asset specifications and optionally generated images.
        """
        # Generate asset specifications
        asset_specs = self.generate_luxury_asset_prompts(
            product_name=product_name,
            product_description=product_description,
            num_assets=num_assets,
            brand_colors=brand_colors
        )

        result = {
            "product": {
                "name": product_name,
                "description": product_description
            },
            "brand_colors": brand_colors,
            "total_assets": num_assets,
            "assets": asset_specs
        }

        # Optionally generate actual images
        if generate_images:
            for asset in result["assets"]:
                try:
                    image_result = await self.generate_image(
                        prompt=asset["image_prompt"],
                        style="luxury",
                        aspect_ratio=asset["recommended_format"]["ratio"]
                    )
                    asset["generated_image"] = {
                        "success": bool(image_result.get("image_base64")),
                        "provider": image_result.get("provider_used"),
                        "model": image_result.get("model"),
                        "image_base64": image_result.get("image_base64")
                    }
                except Exception as e:
                    asset["generated_image"] = {
                        "success": False,
                        "error": str(e)
                    }

        return result

    # ==================== INDUSTRY TEMPLATE METHODS ====================

    def get_industry_template(self, industry: str) -> Dict[str, Any]:
        """Get the Meta-safe template for a specific industry.

        Args:
            industry: Industry key (security, food_restaurant, retail_ecommerce, etc.)

        Returns:
            Industry template dict with backgrounds, subjects, props, colors, mood, avoid
        """
        return self.INDUSTRY_TEMPLATES.get(industry.lower(), self.INDUSTRY_TEMPLATES.get("retail_ecommerce"))

    def generate_industry_prompt(
        self,
        industry: str,
        product_name: str,
        product_description: str,
        include_text: Optional[str] = None
    ) -> str:
        """Generate a Meta-compliant image prompt for a specific industry.

        Args:
            industry: Industry key
            product_name: Name of the product/service
            product_description: Description of the product/service
            include_text: Optional text to render in the image (uses Nano Banana Pro)

        Returns:
            Complete image generation prompt
        """
        import random

        template = self.get_industry_template(industry)

        # Randomly select elements for variety
        background = random.choice(template.get("backgrounds", ["clean professional background"]))
        subject = random.choice(template.get("subjects", ["product shot"]))
        prop = random.choice(template.get("props", []))
        color_scheme = random.choice(template.get("color_schemes", ["professional colors"]))
        mood = template.get("mood", "professional")
        avoid_items = template.get("avoid", [])

        # Build prompt
        prompt_parts = [
            f"Professional advertisement for {product_name}.",
            f"Background: {background}.",
            f"Main subject: {subject}.",
        ]

        if prop:
            prompt_parts.append(f"Accent prop: {prop}.")

        prompt_parts.extend([
            f"Color scheme: {color_scheme}.",
            f"Mood: {mood}.",
            f"Product context: {product_description[:200]}.",
            "High-quality commercial photography, clean composition, 8K quality."
        ])

        # Add text rendering instruction if specified
        if include_text:
            prompt_parts.append(f"Include text overlay: \"{include_text}\" - render clearly and legibly.")

        # Add explicit avoidance instructions
        if avoid_items:
            prompt_parts.append(f"IMPORTANT: Do NOT include: {', '.join(avoid_items)}.")

        prompt_parts.append("No AI-generated faces, no weapons, no controversial content.")

        return " ".join(prompt_parts)

    async def generate_industry_ad_image(
        self,
        industry: str,
        product_name: str,
        product_description: str,
        headline_text: Optional[str] = None,
        aspect_ratio: str = "1:1"
    ) -> Dict[str, Any]:
        """Generate a Meta-compliant ad image for a specific industry.

        Uses Nano Banana Pro for native text rendering when headline_text is provided.

        Args:
            industry: Industry key
            product_name: Name of the product/service
            product_description: Description of the product/service
            headline_text: Optional headline to render in the image
            aspect_ratio: Image aspect ratio

        Returns:
            Generated image result
        """
        prompt = self.generate_industry_prompt(
            industry=industry,
            product_name=product_name,
            product_description=product_description,
            include_text=headline_text
        )

        return await self.generate_image(
            prompt=prompt,
            style="professional",
            aspect_ratio=aspect_ratio
        )

    def list_industries(self) -> List[str]:
        """List all available industry templates."""
        return list(self.INDUSTRY_TEMPLATES.keys())


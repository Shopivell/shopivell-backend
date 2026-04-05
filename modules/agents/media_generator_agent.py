# media_generator_agent.py - AI Agent for Image and Video Generation
"""
Multi-provider media generation agent supporting:
- Images: Gemini (multiple models with fallback), Imagen 4, DALL-E 3, Stability AI, Replicate (Flux)
- Videos: Google Veo 2, Replicate (Stable Video Diffusion), Runway ML, Luma AI

Primary Providers:
- IMAGE: Gemini (gemini-2.0-flash-exp-image-generation → gemini-2.5-flash-image → gemini-3-pro-image-preview)
- IMAGE FALLBACK: Imagen 4 (imagen-4.0-generate-001)
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
    GEMINI_PRO = "gemini_pro"        # Gemini 3 Pro - Primary (direct API, native image gen + text)
    IMAGEN = "imagen"                # Imagen 3 - Fallback
    DALLE = "dalle"                  # OpenAI DALL-E 3
    STABILITY = "stability"          # Stability AI SD3
    REPLICATE = "replicate"          # Replicate Flux


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

    LENS_CHOICES = [
        "shot on Canon 5D Mark IV with 85mm f/1.4 lens, creamy bokeh, soft focus background",
        "shot on Sony A7R IV with 50mm f/1.8 lens, natural perspective, smooth background separation",
        "shot on Nikon Z9 with 105mm f/2.8 macro lens, razor-sharp detail, buttery background blur",
        "shot on Hasselblad X2D with 90mm f/3.2 lens, medium format richness, silky depth of field",
        "shot on Canon R5 with 70-200mm f/2.8 at 135mm, compressed perspective, painterly bokeh",
        "shot on Fujifilm GFX 100S with 80mm f/1.7 lens, medium format depth, velvety soft focus background",
        "shot on Leica SL2 with 75mm f/1.25 Noctilux, ultra-shallow depth of field, dreamy soft focus background",
        "shot on Phase One IQ4 with 120mm f/4 macro lens, tack-sharp focus, gentle background falloff"
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
            "avoid": ["weapons", "guns", "armed guards", "military", "violence", "threatening imagery"],
            # Scene generation is DYNAMIC based on ad set target audience - not hardcoded
            # The target_audience from ad set is used directly in prompt generation
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

        # Initialize Gemini image generator for campaign ad generation
        from modules.agents.gemini_image_generator import GeminiImageGenerator
        self.gemini_generator = GeminiImageGenerator(api_key=self.gemini_api_key)

        logger.info(f"[MediaGeneratorAgent] Initialized with image providers: {self.available_image_providers}")
        logger.info(f"[MediaGeneratorAgent] Initialized with video providers: {self.available_video_providers}")

    def _get_available_image_providers(self) -> List[ImageProvider]:
        """Get list of available image providers based on API keys.

        Priority order:
        1. GEMINI_PRO (Gemini 3 Pro via direct API) - Best quality with native text rendering
        2. IMAGEN (Imagen 3) - High-quality fallback
        3. DALLE (DALL-E 3) - OpenAI alternative
        4. REPLICATE (Flux) - Good quality
        5. STABILITY (SD3) - Stable Diffusion
        """
        providers = []
        # Priority 1: Gemini 3 Pro via direct API - Best for ads with text
        if self.gemini_api_key:
            providers.append(ImageProvider.GEMINI_PRO)
            # Priority 2: Imagen 3 also uses Gemini API key
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

    # ==================== BRAND ASSETS ====================

    def _get_brand_assets(self, store_id: str) -> Dict[str, Any]:
        """
        Retrieve brand assets for a store to inform image generation.

        Checks for uploaded assets like logos, uniforms, vehicles, workplace photos,
        and brand colors to incorporate into generated ad images.

        Args:
            store_id: UUID of the store

        Returns:
            Dict with brand_assets info (URLs, descriptions, brand colors)
        """
        from database import SessionLocal
        db = SessionLocal()
        try:
            from modules.assets.models import Asset
            from modules.stores.models import Store

            # Get store info for brand colors/name
            store = db.query(Store).filter(Store.id == store_id).first()
            brand_info = {
                "store_name": store.name if store else "Unknown",
                "store_description": store.description if store else "",
                "brand_colors": getattr(store, 'brand_colors', None),
                "logo_url": getattr(store, 'logo_url', None),
            }

            # Get relevant brand assets
            assets = db.query(Asset).filter(
                Asset.store_id == store_id,
                Asset.is_active == True,
                Asset.source == "upload"  # Only user-uploaded assets
            ).order_by(Asset.created_at.desc()).limit(20).all()

            categorized = {
                "logos": [],
                "products": [],
                "brand_photos": [],  # Uniforms, vehicles, workplace
                "all_urls": []
            }

            brand_keywords = ["logo", "brand", "uniform", "vehicle", "car", "truck", "van",
                              "office", "workplace", "shop", "store", "team", "staff"]

            for asset in assets:
                asset_url = asset.cloudinary_secure_url or asset.cloudinary_url
                if not asset_url:
                    continue

                asset_info = {
                    "name": asset.name,
                    "url": asset_url,
                    "tags": asset.tags or [],
                    "description": asset.description or ""
                }

                name_lower = (asset.name or "").lower()
                desc_lower = (asset.description or "").lower()
                tags_lower = " ".join([str(t).lower() for t in (asset.tags or [])])
                combined = f"{name_lower} {desc_lower} {tags_lower}"

                if "logo" in combined:
                    categorized["logos"].append(asset_info)
                elif any(kw in combined for kw in brand_keywords):
                    categorized["brand_photos"].append(asset_info)
                else:
                    categorized["products"].append(asset_info)

                categorized["all_urls"].append(asset_url)

            brand_info["assets"] = categorized
            brand_info["has_assets"] = len(categorized["all_urls"]) > 0
            brand_info["asset_count"] = len(categorized["all_urls"])

            logger.info(
                f"[MediaGeneratorAgent] Brand assets for store {store_id}: "
                f"{len(categorized['logos'])} logos, {len(categorized['brand_photos'])} brand photos, "
                f"{len(categorized['products'])} product images"
            )

            return brand_info

        except Exception as e:
            logger.error(f"[MediaGeneratorAgent] Error getting brand assets: {e}")
            return {"store_name": "Unknown", "has_assets": False, "assets": {}}
        finally:
            db.close()

    def _build_brand_context_prompt(self, brand_assets: Dict[str, Any]) -> str:
        """
        Build a brand context string to prepend to image generation prompts.

        Incorporates brand colors, existing assets references, and brand identity.
        """
        parts = []

        store_name = brand_assets.get("store_name", "")
        if store_name:
            parts.append(f"Brand: {store_name}")

        # Brand colors
        brand_colors = brand_assets.get("brand_colors")
        if brand_colors:
            if isinstance(brand_colors, list):
                parts.append(f"Brand colors: {', '.join(brand_colors)}")
            elif isinstance(brand_colors, dict):
                colors = [f"{k}: {v}" for k, v in brand_colors.items()]
                parts.append(f"Brand colors: {', '.join(colors)}")
            elif isinstance(brand_colors, str):
                parts.append(f"Brand colors: {brand_colors}")

        # Asset context
        assets = brand_assets.get("assets", {})
        if assets.get("logos"):
            parts.append("Brand has a logo — maintain visual consistency")
        if assets.get("brand_photos"):
            photo_types = [p.get("name", "") for p in assets["brand_photos"][:3]]
            parts.append(f"Brand photos available: {', '.join(photo_types)}")
        if assets.get("products"):
            parts.append(f"Has {len(assets['products'])} product images — reference brand aesthetic")

        store_desc = brand_assets.get("store_description", "")
        if store_desc:
            parts.append(f"Business: {store_desc[:100]}")

        if parts:
            return "BRAND CONTEXT: " + " | ".join(parts) + ". "
        return ""

    # ==================== IMAGE UPLOAD (MinIO primary, Cloudinary fallback) ====================

    def upload_to_cloudinary(
        self,
        image_base64: str,
        folder: str = "shopivell/generated",
        resource_type: str = "image"
    ) -> Dict[str, Any]:
        """
        Upload a base64 image to MinIO (primary) or Cloudinary (fallback).

        Args:
            image_base64: Base64 encoded image data
            folder: Storage folder path
            resource_type: 'image' or 'video'

        Returns:
            Dict with url, public_id, and metadata
        """
        import base64
        import io

        # Decode base64 to bytes
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception as e:
            logger.error(f"[MediaGeneratorAgent] Base64 decode error: {e}")
            return {"uploaded": False, "error": f"Base64 decode error: {e}"}

        # Try MinIO first
        from modules.assets.service import minio_client, MINIO_BUCKET, _get_minio_url
        if minio_client:
            try:
                filename = f"generated_{uuid.uuid4().hex[:12]}.png"
                object_name = f"{folder}/{filename}"

                minio_client.put_object(
                    MINIO_BUCKET,
                    object_name,
                    io.BytesIO(image_bytes),
                    length=len(image_bytes),
                    content_type="image/png"
                )

                url = _get_minio_url(object_name)
                logger.info(f"[MediaGeneratorAgent] Uploaded to MinIO: {url}")

                return {
                    "uploaded": True,
                    "public_id": object_name,
                    "url": url,
                    "secure_url": url,
                    "cloudinary_url": url,
                    "thumbnail_url": url,
                    "width": None,
                    "height": None,
                    "format": "png",
                    "bytes": len(image_bytes)
                }
            except Exception as e:
                logger.warning(f"[MediaGeneratorAgent] MinIO upload failed, trying Cloudinary: {e}")

        # Fallback to Cloudinary
        if not CLOUDINARY_CONFIGURED:
            logger.warning("[MediaGeneratorAgent] No storage configured, skipping upload")
            return {"uploaded": False, "error": "No storage configured (MinIO and Cloudinary both unavailable)"}

        try:
            data_uri = f"data:image/png;base64,{image_base64}"

            result = cloudinary.uploader.upload(
                data_uri,
                folder=folder,
                resource_type=resource_type,
                public_id=f"generated_{uuid.uuid4().hex[:12]}",
                overwrite=True,
                eager=[
                    {"width": 300, "height": 300, "crop": "fill", "format": "jpg"}
                ],
                eager_async=False
            )

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
            return {"uploaded": False, "error": str(e)}

    async def upload_video_to_cloudinary(
        self,
        video_base64: str,
        folder: str = "shopivell/generated/videos"
    ) -> Dict[str, Any]:
        """Upload a base64 video to MinIO (primary) or Cloudinary (fallback)."""
        import base64
        import io

        try:
            video_bytes = base64.b64decode(video_base64)
        except Exception as e:
            return {"uploaded": False, "error": f"Base64 decode error: {e}"}

        # Try MinIO first
        from modules.assets.service import minio_client, MINIO_BUCKET, _get_minio_url
        if minio_client:
            try:
                filename = f"video_{uuid.uuid4().hex[:12]}.mp4"
                object_name = f"{folder}/{filename}"
                minio_client.put_object(
                    MINIO_BUCKET, object_name,
                    io.BytesIO(video_bytes), length=len(video_bytes),
                    content_type="video/mp4"
                )
                url = _get_minio_url(object_name)
                logger.info(f"[MediaGeneratorAgent] Video uploaded to MinIO: {url}")
                return {
                    "uploaded": True, "public_id": object_name,
                    "url": url, "secure_url": url, "cloudinary_url": url,
                    "duration": None, "width": None, "height": None,
                    "format": "mp4", "bytes": len(video_bytes)
                }
            except Exception as e:
                logger.warning(f"[MediaGeneratorAgent] MinIO video upload failed: {e}")

        # Fallback to Cloudinary
        if not CLOUDINARY_CONFIGURED:
            return {"uploaded": False, "error": "No storage configured"}

        try:
            data_uri = f"data:video/mp4;base64,{video_base64}"
            result = cloudinary.uploader.upload(
                data_uri, folder=folder, resource_type="video",
                public_id=f"video_{uuid.uuid4().hex[:12]}", overwrite=True
            )
            logger.info(f"[MediaGeneratorAgent] Video uploaded to Cloudinary: {result.get('secure_url')}")
            return {
                "uploaded": True, "public_id": result.get("public_id"),
                "url": result.get("url"), "secure_url": result.get("secure_url"),
                "cloudinary_url": result.get("secure_url"),
                "duration": result.get("duration"), "width": result.get("width"),
                "height": result.get("height"), "format": result.get("format"),
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
        cloudinary_folder: str = "shopivell/generated/ads",
        store_id: Optional[str] = None
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
            store_id: Optional store UUID to fetch brand assets for context

        Returns:
            Dict with image_base64, cloudinary_url, provider_used, and metadata
        """
        # Prepend brand context if store_id is provided
        if store_id:
            try:
                brand_assets = self._get_brand_assets(store_id)
                if brand_assets.get("has_assets"):
                    brand_context = self._build_brand_context_prompt(brand_assets)
                    prompt = brand_context + prompt
                    logger.info(f"[MediaGeneratorAgent] Brand context added for store {store_id}")
            except Exception as e:
                logger.warning(f"[MediaGeneratorAgent] Could not load brand assets: {e}")

        # Enhance prompt with style
        enhanced_prompt = self._enhance_image_prompt(prompt, style)

        # Try providers in order
        providers_to_try = [provider] if provider else self.available_image_providers
        provider_errors = []  # Track errors for debugging

        for prov in providers_to_try:
            try:
                logger.info(f"[MediaGeneratorAgent] Trying image generation with {prov.value}")

                if prov == ImageProvider.GEMINI_PRO:
                    result = await self._generate_gemini_pro_image(enhanced_prompt, aspect_ratio)
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
                    result["provider_errors"] = provider_errors  # Include previous failures
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
                error_msg = f"{prov.value}: {str(e)}"
                logger.warning(f"[MediaGeneratorAgent] {error_msg}")
                provider_errors.append(error_msg)
                continue

        # All providers failed - return placeholder
        logger.warning("[MediaGeneratorAgent] All image providers failed, using placeholder")
        placeholder = self._generate_placeholder_image(prompt, aspect_ratio)
        placeholder["provider_errors"] = provider_errors
        return placeholder

    def _enhance_image_prompt(self, prompt: str, style: str) -> str:
        """Enhance the prompt with style modifiers, lens spec, and soft focus background"""
        import random

        lens = random.choice(self.LENS_CHOICES)

        style_modifiers = {
            "professional": f"Photorealistic commercial photography, {lens}, soft diffused key light from upper-left with gentle fill, clean composition, soft focus background",
            "vibrant": f"Photorealistic vibrant commercial photography, {lens}, bright saturated key light with colorful rim accents, dynamic composition, soft focus background with color bokeh",
            "minimal": f"Photorealistic minimalist product photography, {lens}, clean even studio softbox lighting from above, white background, smooth soft focus falloff",
            "luxury": f"Photorealistic luxury editorial photography, {lens}, dramatic spotlight with deep shadows and golden rim light, elegant composition, velvety soft focus background",
            "lifestyle": f"Photorealistic authentic lifestyle photography, {lens}, natural window light with warm ambient fill, relatable setting, soft focus background with environmental bokeh",
            "bold": f"Photorealistic bold commercial photography, {lens}, high-contrast directional key light with hard shadows, striking visual impact, soft focus background",
            "cinematic": f"Cinematic photorealistic photography, {lens}, dramatic rim lighting with moody fill, anamorphic-style composition, cinematic soft focus background with oval bokeh"
        }

        modifier = style_modifiers.get(style, style_modifiers["professional"])
        return f"{prompt}. Style: {modifier}. 8K resolution. No text or watermarks."

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

    # Gemini image-generation models in priority order (verified available)
    GEMINI_IMAGE_MODELS = [
        "gemini-3-pro-image-preview",              # Pro image preview - Primary
        "gemini-2.0-flash-exp-image-generation",   # Flash image gen fallback
        "gemini-2.5-flash-image",                  # Flash image variant fallback
    ]

    async def _generate_gemini_pro_image(self, prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """Generate image using Gemini via direct Gemini API with model fallback.

        This is the PRIMARY image provider:
        - Best quality for ad images with text
        - Native text rendering in images
        - Tries multiple Gemini image models in priority order
        """
        if not self.gemini_api_key:
            raise ValueError("Gemini API key not configured")

        try:
            from google import genai
            from google.genai import types

            # Initialize Gemini client
            client = genai.Client(api_key=self.gemini_api_key)

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

            # Try each Gemini image model in priority order
            last_error = None
            for model_name in self.GEMINI_IMAGE_MODELS:
                try:
                    logger.info(f"[MediaGeneratorAgent] Generating with Gemini model: {model_name}...")

                    response = client.models.generate_content(
                        model=model_name,
                        contents=enhanced_prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE", "TEXT"],
                            temperature=0.7
                        )
                    )

                    # Process response to extract image
                    if response and response.candidates:
                        for candidate in response.candidates:
                            if candidate.content and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if hasattr(part, 'inline_data') and part.inline_data:
                                        image_data = part.inline_data
                                        if hasattr(image_data, 'data') and image_data.data:
                                            if isinstance(image_data.data, bytes):
                                                image_base64 = base64.b64encode(image_data.data).decode("utf-8")
                                            else:
                                                image_base64 = image_data.data
                                            logger.info(f"[MediaGeneratorAgent] Gemini generation successful with {model_name}")
                                            return {
                                                "image_base64": image_base64,
                                                "model": model_name,
                                                "supports_text": True
                                            }

                    logger.warning(f"[MediaGeneratorAgent] No image in response from {model_name}, trying next...")
                    last_error = f"No image generated by {model_name}"

                except Exception as model_err:
                    last_error = str(model_err)
                    logger.warning(f"[MediaGeneratorAgent] {model_name} failed: {last_error[:150]}, trying next...")
                    continue

            raise Exception(f"All Gemini image models failed. Last error: {last_error}")

        except Exception as e:
            raise Exception(f"Gemini image generation failed: {str(e)}")

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

            # Imagen models in priority order (verified available)
            imagen_models = [
                "imagen-4.0-generate-001",
                "imagen-4.0-fast-generate-001",
                "imagen-4.0-ultra-generate-001",
            ]

            last_error = None
            for imagen_model in imagen_models:
                try:
                    logger.info(f"[MediaGeneratorAgent] Generating with {imagen_model}, aspect ratio: {mapped_ar}")

                    response = client.models.generate_images(
                        model=imagen_model,
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
                        logger.info(f"[MediaGeneratorAgent] {imagen_model} generation successful")
                        return {
                            "image_base64": image_base64,
                            "model": imagen_model
                        }

                    last_error = f"No image generated by {imagen_model}"
                except Exception as model_err:
                    last_error = str(model_err)
                    logger.warning(f"[MediaGeneratorAgent] {imagen_model} failed: {last_error[:150]}")
                    continue

            raise Exception(f"All Imagen models failed. Last error: {last_error}")

        except Exception as e:
            raise Exception(f"Imagen image generation failed: {str(e)}")

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
        """Build an optimized prompt for ad image generation with full visual specification"""
        import random

        lighting = random.choice(self.LIGHTING_STYLES)
        lens = random.choice(self.LENS_CHOICES)
        camera = random.choice(self.CAMERA_ANGLES)

        prompt_parts = [
            "Photorealistic commercial advertisement photography.",
            f"SUBJECT: {product_info.get('product_name', 'product')} as the hero of the image.",
            f"DETAILS: {product_info.get('product_description', '')[:200]}.",
        ]

        if ad_angle.get("visual_direction"):
            prompt_parts.append(f"ACTION & DIRECTION: {ad_angle['visual_direction']}.")

        if ad_angle.get("emotion_target"):
            prompt_parts.append(f"MOOD: {ad_angle['emotion_target']} — the viewer should feel drawn to the product.")

        prompt_parts.append(f"LIGHTING: {lighting}.")
        prompt_parts.append(f"LENS & CAMERA: {lens}. {camera}. Soft focus background with creamy bokeh.")
        prompt_parts.append("Photorealistic commercial photography, clean composition, 8K resolution, 4:5 portrait format. No text.")

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
        lenses = random.sample(self.LENS_CHOICES, min(num_assets, len(self.LENS_CHOICES)))

        assets = []
        used_combinations = set()

        for i in range(num_assets):
            # Select unique combination
            bg = backgrounds[i % len(backgrounds)]
            surface = surfaces[i % len(surfaces)]
            accent = accents[i % len(accents)]
            lighting = lightings[i % len(lightings)]
            angle = angles[i % len(angles)]
            lens = lenses[i % len(lenses)]

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
                lens_spec=lens,
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
                    "lensSpec": lens,
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
        lens_spec: str = "shot on Hasselblad X2D with 90mm f/3.2 lens, medium format richness, silky depth of field",
        brand_colors: Optional[List[str]] = None
    ) -> str:
        """Build a detailed luxury product photography prompt with full visual specification"""

        color_instruction = ""
        if brand_colors:
            color_instruction = f"Incorporate brand colors: {', '.join(brand_colors)}. "

        mood = self._determine_mood(background_tone, lighting)

        prompt = f"""Photorealistic ultra-premium luxury product photography of {product_name}.

ART STYLE: High-end editorial product photography, magazine-worthy advertising still life.

SUBJECT: {product_name} as the hero, positioned as the clear focal point of the composition.
ACTION: The product rests elegantly on the surface, with the accent prop placed to create visual flow and guide the eye toward the product.

SCENE SETUP:
- Background: {background_tone}
- Surface: {surface_type}
- Accent prop: {accent_prop} placed elegantly nearby
- Lighting: {lighting}
- Camera: {camera_angle}

LENS & CAMERA: {lens_spec}. Soft focus background with creamy bokeh separating the product from the environment.

PRODUCT CONTEXT:
{product_description}

MOOD: {mood} — the viewer should feel desire and aspiration when looking at this image.

STYLE REQUIREMENTS:
- {color_instruction}Tasteful, intentional styling with premium feel
- Clean, uncluttered composition with breathing room
- Product as hero, accent props complement but don't distract
- Luxurious texture emphasis on materials — show tactile quality
- No text, watermarks, or logos in the image
- Photorealistic, 8K resolution, 1:1 square format for social media"""

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
        include_text: Optional[str] = None,
        target_audience: Optional[str] = None,
        brand_colors: Optional[str] = None,
        include_logo: bool = False
    ) -> str:
        """Generate a Meta-compliant image prompt for a specific industry.

        Dynamically generates scene based on target_audience from ad set.

        Args:
            industry: Industry key
            product_name: Name of the product/service
            product_description: Description of the product/service
            include_text: Optional text to render in the image
            target_audience: Target audience from ad set (e.g., "Homeowners", "Parking Facility Managers")
            brand_colors: Optional brand color theme
            include_logo: Whether to include brand logo in the design

        Returns:
            Complete image generation prompt
        """
        template = self.get_industry_template(industry)

        # Get template metadata
        mood = template.get("mood", "professional")
        avoid_items = template.get("avoid", [])

        # Build INDUSTRY-SPECIFIC scene instructions
        # Each industry has different subjects/scenes - DO NOT use generic security language for non-security industries
        industry_scene_instructions = {
            "security": {
                "scene": "security equipment in action - a hand interacting with access control, a monitoring screen, or equipment actively working (gate opening, light indicating access granted)",
                "subject": "security system BEING USED"
            },
            "retail_ecommerce": {
                "scene": "products beautifully displayed - clothing on racks, items arranged on shelves, or a product hero shot with clean background",
                "subject": "retail products in an aspirational shopping environment"
            },
            "food_restaurant": {
                "scene": "delicious food presentation - beautifully plated dishes, fresh ingredients, or a warm restaurant atmosphere",
                "subject": "appetizing food in an inviting dining setting"
            },
            "tech_saas": {
                "scene": "modern technology workspace - clean desk setup with devices, abstract data visualization, or sleek software interface",
                "subject": "technology solutions in a professional modern setting"
            },
            "beauty_cosmetics": {
                "scene": "elegant beauty products - luxurious packaging, texture swatches, or spa-like setting with soft lighting",
                "subject": "premium beauty products in an elegant arrangement"
            },
            "health_fitness": {
                "scene": "fitness and wellness - gym equipment, healthy meals, or active lifestyle setting",
                "subject": "fitness products/environment promoting healthy living"
            },
            "real_estate": {
                "scene": "beautiful property - bright interior spaces, architectural details, or welcoming home exterior",
                "subject": "aspirational living space"
            },
            "professional_services": {
                "scene": "professional business environment - modern office, handshake (hands only), or clean workspace",
                "subject": "professional services in a trustworthy corporate setting"
            },
            "education": {
                "scene": "learning environment - books and study materials, laptop with course interface, or inspiring study space",
                "subject": "educational resources in an inspiring setting"
            },
            "automotive": {
                "scene": "automotive showcase - car detail shots, clean showroom, or scenic road setting",
                "subject": "vehicle or automotive service in premium environment"
            }
        }

        # Get industry-specific instructions, default to retail if not found
        industry_info = industry_scene_instructions.get(industry, industry_scene_instructions["retail_ecommerce"])

        import random

        # Pick varied lighting, lens, and camera for each generation
        lighting = random.choice(self.LIGHTING_STYLES)
        lens = random.choice(self.LENS_CHOICES)
        camera_position = random.choice([
            "shot from eye-level, medium shot framing the main subject from waist up",
            "shot from slightly above at a 30-degree angle, showing the full scene with context",
            "shot from a low angle looking slightly up for an empowering perspective",
            "shot from a three-quarter view, medium-close framing the subject with environmental depth"
        ])

        # Build dynamic scene instruction based on target_audience and INDUSTRY
        if target_audience:
            audience_context = f"Target audience: {target_audience}. Create a DEMONSTRATIVE scene showing {industry_info['scene']} that would appeal to this audience."
        else:
            audience_context = f"Create a DEMONSTRATIVE scene showing {industry_info['scene']}."

        # Build the prompt - dynamically generates scene based on INDUSTRY and ad set audience
        prompt_parts = [
            # Art style declaration
            "Photorealistic commercial advertisement photography.",
            f"Professional marketing image for a {industry.replace('_', ' ')} company: {product_name}.",
            # Subject and action
            f"SUBJECT: {industry_info['subject']} as the focal point of the composition.",
            f"ACTION: The scene is demonstrative — {industry_info['scene']}.",
            audience_context,
            # Lighting
            f"LIGHTING: {lighting}.",
            # Lens and camera
            f"LENS & CAMERA: {lens}. {camera_position}. Soft focus background with smooth bokeh separating the subject from the environment.",
            # Color and mood
            f"IMPORTANT COLOR THEME: Use {brand_colors if brand_colors else 'brand-appropriate colors'} as accent color throughout the image.",
            f"MOOD: {mood} — the viewer should feel confident choosing this company.",
            "All products and props must be plain with NO competitor logos, NO random text visible on them.",
        ]

        # Add logo instruction if requested - logo as overlay only
        if include_logo:
            prompt_parts.append(f"Add a small '{product_name}' company logo ONLY in the bottom right corner as a subtle overlay watermark.")

        # Add headline text if specified
        if include_text:
            prompt_parts.append(f"Add headline text: \"{include_text}\" - positioned prominently and legibly.")

        # Add quality and style requirements
        prompt_parts.append("Photorealistic commercial photography, clean composition, 8K resolution, 4:5 portrait format.")

        # Add explicit avoidance instructions for Meta compliance
        if avoid_items:
            prompt_parts.append(f"CRITICAL: Do NOT include any of the following: {', '.join(avoid_items)}.")

        prompt_parts.append("No AI-generated human faces, no weapons, no controversial or violent content.")

        return " ".join(prompt_parts)

    async def generate_industry_ad_image(
        self,
        industry: str,
        product_name: str,
        product_description: str,
        headline_text: Optional[str] = None,
        aspect_ratio: str = "1:1",
        brand_colors: Optional[str] = None,
        logo_url: Optional[str] = None,
        target_audience: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a Meta-compliant ad image for a specific industry.

        Uses Nano Banana Pro for native text rendering when headline_text is provided.

        Args:
            industry: Industry key
            product_name: Name of the product/service
            product_description: Description of the product/service
            headline_text: Optional headline to render in the image
            aspect_ratio: Image aspect ratio
            brand_colors: Optional brand color theme (e.g., "#1E3A5F navy blue")
            logo_url: Optional URL to brand logo (for reference in prompt)
            target_audience: Optional audience segment for audience-specific imagery

        Returns:
            Generated image result
        """
        prompt = self.generate_industry_prompt(
            industry=industry,
            product_name=product_name,
            product_description=product_description,
            include_text=headline_text,
            target_audience=target_audience,
            brand_colors=brand_colors,
            include_logo=logo_url is not None
        )

        return await self.generate_image(
            prompt=prompt,
            style="professional",
            aspect_ratio=aspect_ratio
        )

    # ==================== STORE AD GENERATION ====================

    def _strip_text_overlay_from_prompt(self, prompt: str) -> str:
        """
        Remove text-overlay directives AND in-scene text references from
        an AdCreativeAgent-generated prompt.

        Strips:
        - TEXT OVERLAY / bullet-point / CTA button overlay directives
        - Quoted in-scene text (e.g. "SYSTEM ARMED", "WARNING ... FENCE")
        - Background people/personnel references (causes distorted faces)
        """
        import re

        # Remove "TEXT OVERLAY: ..." sentences (headline banner instructions)
        cleaned = re.sub(r"TEXT OVERLAY:\s*[^.]*\.?\s*", "", prompt)

        # Remove bullet-point overlay instructions
        cleaned = re.sub(
            r"On the left side of the image,?\s*display\s+\d*\s*bullet\s+points?[^.]*\.\s*",
            "", cleaned, flags=re.IGNORECASE
        )

        # Remove CTA button instructions
        cleaned = re.sub(
            r"Include\s+a\s+[\w\s#]+colored\s+button[^.]*\.\s*",
            "", cleaned, flags=re.IGNORECASE
        )

        # Remove LOGO placement instructions
        cleaned = re.sub(
            r"LOGO:\s*[^.]*\.\s*", "", cleaned, flags=re.IGNORECASE
        )

        # Remove "Ensure all text overlays are crisp..." trailing sentences
        cleaned = re.sub(
            r"Ensure\s+all\s+text\s+(overlays?\s+)?[^.]*\.\s*",
            "", cleaned, flags=re.IGNORECASE
        )

        # Remove "Subject positioned center-right"
        cleaned = re.sub(
            r"Subject\s+positioned\s+center-right\.?\s*",
            "", cleaned, flags=re.IGNORECASE
        )

        # ---- NEW: Strip in-scene text references ----

        # Remove ALL quoted strings (text on signs, screens, vehicles, etc.)
        # e.g. "SYSTEM ARMED - ALL SECURE", 'WARNING SAFEGUARD ELECTRIC FENCE'
        # Also remove the verb phrases leading up to them
        cleaned = re.sub(
            r"""(?:reading|showing|displaying|saying|with text|with the text|that reads|that says|stating)\s*[:.]?\s*["'][^"']*["']""",
            "", cleaned, flags=re.IGNORECASE
        )
        # Remaining standalone quoted strings (3+ chars)
        cleaned = re.sub(r"""["'][A-Z][^"']{2,}["']""", "", cleaned)
        cleaned = re.sub(r"""'[A-Z][^']{2,}'""", "", cleaned)

        # Remove "with 'SAFEGUARD' clearly visible on the side" type phrases
        cleaned = re.sub(
            r"with\s+[\"'][^\"']+[\"']\s+(?:clearly\s+)?visible[^.]*",
            "", cleaned, flags=re.IGNORECASE
        )

        # Remove background people/personnel (they get distorted faces)
        # e.g. "with uniformed security personnel visible in the background"
        # Also catches "with uniformed security personnel visible" (no "in the background")
        cleaned = re.sub(
            r",?\s*(?:with\s+)?(?:uniformed\s+)?(?:security\s+)?(?:personnel|officers?|guards?|staff)\s+(?:visible\s+)?(?:in\s+the\s+background)?[.,]?\s*",
            ". ", cleaned, flags=re.IGNORECASE
        )
        # "... visible in the background" for any people reference (family member, people, etc.)
        cleaned = re.sub(
            r",?\s*(?:with\s+)?(?:\w+\s+){0,3}(?:people|persons?|figures?|workers?|family\s+members?|members?)\s+(?:is\s+|are\s+)?(?:visible\s+)?(?:in\s+the\s+background)?[.,]?\s*",
            ". ", cleaned, flags=re.IGNORECASE
        )
        # Catch "A [person] is visible in the background" pattern
        cleaned = re.sub(
            r"[A-Z][^.]*(?:visible|seen|standing)\s+in\s+the\s+background[^.]*\.\s*",
            "", cleaned, flags=re.IGNORECASE
        )

        # Remove "to allow space for bullet points" leftover
        cleaned = re.sub(
            r"to\s+allow\s+space\s+for\s+(?:bullet\s+points?|text\s+overlay)\.?\s*",
            "", cleaned, flags=re.IGNORECASE
        )

        # ---- END NEW ----

        # Collapse multiple spaces / dots / leading whitespace
        cleaned = re.sub(r"\.\s*\.", ".", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        # Append instruction telling Gemini to produce a clean scene only
        cleaned += (
            " Do NOT include any text, words, letters, numbers, signs with text, "
            "labels, headlines, buttons, or text overlays of any kind. "
            "Do NOT place any small people or faces in the background. "
            "Generate ONLY the photorealistic scene."
        )

        return cleaned

    def _build_scene_prompt(
        self,
        business_type: str,
        products_or_services: List[str] = None,
        store_description: str = None,
        has_screenshot: bool = False
    ) -> str:
        """
        Build a photorealistic scene prompt for background generation.
        Maps business_type to INDUSTRY_TEMPLATES where possible.
        When a screenshot reference is provided, instructs Gemini to extract
        and incorporate brand assets (logos, icons, color identity) from it.
        Now includes full visual specification: art style, lighting, lens,
        camera position, action, mood, and aspect ratio.
        """
        import random

        # Try to match business_type to an industry template
        template = None
        business_lower = (business_type or "").lower().replace(" ", "_")

        # Direct match
        if business_lower in self.INDUSTRY_TEMPLATES:
            template = self.INDUSTRY_TEMPLATES[business_lower]
        else:
            # Fuzzy match by checking if business_type contains a template key
            for key, tmpl in self.INDUSTRY_TEMPLATES.items():
                if key in business_lower or business_lower in key:
                    template = tmpl
                    break

        # Pick varied lighting and lens for each generation
        lighting = random.choice(self.LIGHTING_STYLES)
        lens = random.choice(self.LENS_CHOICES)
        camera_angle = random.choice([
            "shot from eye-level, straight-on perspective",
            "shot from slightly above at a 30-degree angle",
            "shot from a low angle looking slightly up",
            "shot from a three-quarter perspective"
        ])

        prompt_parts = []

        # Art style declaration upfront
        prompt_parts.append("Photorealistic commercial photography.")

        if template:
            # Use template backgrounds and subjects
            bg = template["backgrounds"][0] if template["backgrounds"] else "professional business setting"
            subject = template["subjects"][0] if template["subjects"] else "business scene"
            mood = template.get("mood", "professional")
            color_scheme = template["color_schemes"][0] if template.get("color_schemes") else "professional colors"

            # Pick a random prop as an action element
            prop = random.choice(template.get("props", ["professional equipment"])) if template.get("props") else "professional equipment"

            prompt_parts.append(
                f"SUBJECT: A {bg} featuring {subject} as the focal point."
            )
            prompt_parts.append(
                f"ACTION: The scene is alive — {prop} is prominently placed suggesting active use, "
                f"with environmental details implying ongoing business activity."
            )
            prompt_parts.append(
                f"MOOD: {mood} — the viewer should feel trust and confidence. Color palette: {color_scheme}."
            )

            # Add avoidance items
            if template.get("avoid"):
                prompt_parts.append(
                    f"Do NOT include: {', '.join(template['avoid'])}."
                )
        else:
            # Generic scene based on business_type
            prompt_parts.append(
                f"SUBJECT: A professional {business_type} business environment as the focal point."
            )
            prompt_parts.append(
                "ACTION: The scene conveys active business operations — equipment in use, "
                "workspace showing signs of current activity."
            )
            prompt_parts.append(
                "MOOD: Professional, trustworthy, modern — the viewer should feel this is a reliable business."
            )

        # Lighting specification
        prompt_parts.append(f"LIGHTING: {lighting}.")

        # Lens and camera specification
        prompt_parts.append(f"LENS & CAMERA: {lens}. {camera_angle}. Soft focus background with gentle bokeh separating foreground subjects from the environment.")

        # Incorporate products/services context
        if products_or_services:
            services_str = ", ".join(products_or_services[:5])
            prompt_parts.append(
                f"DETAILS: The scene should visually relate to these services: {services_str}."
            )

        # Incorporate store description for context
        if store_description:
            desc_short = store_description[:200]
            prompt_parts.append(
                f"Business context: {desc_short}."
            )

        # Screenshot-aware instructions
        if has_screenshot:
            prompt_parts.append(
                "A reference screenshot of the business website/store is provided. "
                "Extract and incorporate the brand's logo, icons, and visual identity elements "
                "(color palette, brand marks, emblems) from the screenshot into the scene naturally — "
                "for example, show the logo on a building sign, uniform badge, vehicle decal, or display screen. "
                "Do NOT include any headlines, paragraph text, buttons, or ad-copy text overlays. "
                "The logo and brand marks should appear as part of the physical scene, not as flat overlays."
            )
        else:
            prompt_parts.append(
                "Do NOT include any text, logos, headlines, buttons, or text overlays. "
                "Generate ONLY the photorealistic background scene."
            )

        prompt_parts.append(
            "Photorealistic commercial photography, clean composition, 8K resolution, 4:5 portrait format. "
            "No AI-generated human faces."
        )

        return " ".join(prompt_parts)

    def _generate_default_ad_copy(
        self,
        store_name: str,
        store_description: str = None,
        business_type: str = None,
        products_or_services: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate default headline and bullet points from store data
        when the caller doesn't provide them.
        """
        # Build headline from store name and business type
        if business_type:
            headline = f"{store_name} — Your Trusted {business_type.replace('_', ' ').title()} Partner"
        else:
            headline = f"Discover {store_name}"

        # Build bullet points from products/services or description
        bullets = []
        if products_or_services:
            for svc in products_or_services[:3]:
                bullets.append(svc if len(svc) < 60 else svc[:57] + "...")
        elif store_description:
            # Extract short phrases from description
            sentences = store_description.replace(". ", ".|").split("|")
            for s in sentences[:3]:
                s = s.strip().rstrip(".")
                if s and len(s) > 5:
                    bullets.append(s if len(s) < 60 else s[:57] + "...")

        if not bullets:
            bullets = ["Professional quality service", "Trusted by customers", "Contact us today"]

        return {"headline": headline, "bullet_points": bullets}

    async def generate_store_ad(
        self,
        store_name: str,
        store_description: str,
        business_type: str,
        logo_url: str = None,
        screenshot_url: str = None,
        color_theme: str = None,
        products_or_services: List[str] = None,
        headline: str = None,
        bullet_points: List[str] = None,
        cta_text: str = "Learn More",
        aspect_ratio: str = "1:1",
        upload_to_cloud: bool = True
    ) -> Dict[str, Any]:
        """
        Generate a modern store ad image using a store's data.

        Orchestration:
        1. Call AdCreativeAgent for a rich, AI-crafted image prompt
        2. Strip text-overlay directives (PIL composer handles text rendering)
        3. Build reference images from screenshot_url
        4. Generate base scene with Gemini using the AI-crafted prompt
        5. Resolve headline/bullets (caller-provided > AI-generated > template fallback)
        6. Compose final ad with AdImageComposer.compose_modern_ad_image()
        7. Upload to Cloudinary if requested

        Falls back to _build_scene_prompt() + _generate_default_ad_copy() if
        AdCreativeAgent is unavailable.

        Args:
            store_name: Name of the store/business
            store_description: Description of the business
            business_type: Type of business (maps to INDUSTRY_TEMPLATES)
            logo_url: URL to company logo (passed to PIL composer for overlay)
            screenshot_url: URL to store website screenshot (used as Gemini scene reference for logo/brand extraction)
            color_theme: Hex color for brand theming
            products_or_services: List of products/services offered
            headline: Ad headline (auto-generated if not provided)
            bullet_points: Ad bullet points (auto-generated if not provided)
            cta_text: Call-to-action button text
            aspect_ratio: Image aspect ratio
            upload_to_cloud: Whether to upload final image to Cloudinary

        Returns:
            Dict with image_base64, cloudinary_url, thumbnail_url, and metadata
        """
        from .gemini_image_generator import GeminiImageGenerator
        from .ad_image_composer import AdImageComposer
        from .ad_creative_agent import AdCreativeAgent

        brand_color = color_theme or "#FFD700"
        result_meta = {
            "store_name": store_name,
            "business_type": business_type,
            "aspect_ratio": aspect_ratio,
        }

        # ------------------------------------------------------------------
        # Step 1: Call AdCreativeAgent for AI-crafted prompt & copy
        # ------------------------------------------------------------------
        creative_result = None
        try:
            creative_agent = AdCreativeAgent()
            target_audience = (
                f"{business_type.replace('_', ' ').title()} customers"
                if business_type else "General audience"
            )
            creative_result = await creative_agent.generate_ad_creative(
                product_name=store_name,
                product_description=store_description or f"{store_name} business",
                target_audience=target_audience,
                key_benefits=products_or_services[:3] if products_or_services else None,
                call_to_action=cta_text,
                brand_color=brand_color,
            )
            result_meta["creative_agent_used"] = True
            result_meta["prompt_source"] = "ad_creative_agent"
            if creative_result.get("ai_model"):
                result_meta["creative_model"] = creative_result["ai_model"]
            if creative_result.get("tokens_used"):
                result_meta["creative_tokens"] = creative_result["tokens_used"]
            logger.info("[MediaGeneratorAgent] AdCreativeAgent returned prompt successfully")
        except Exception as e:
            logger.warning(f"[MediaGeneratorAgent] AdCreativeAgent failed, falling back to template: {e}")
            creative_result = None
            result_meta["creative_agent_used"] = False
            result_meta["prompt_source"] = "template"

        # ------------------------------------------------------------------
        # Step 2: Build scene prompt
        # ------------------------------------------------------------------
        if creative_result and creative_result.get("image_prompt"):
            # Strip text-overlay directives — PIL composer handles text rendering
            scene_prompt = self._strip_text_overlay_from_prompt(
                creative_result["image_prompt"]
            )

            # Append screenshot reference instructions
            if screenshot_url:
                scene_prompt += (
                    " A reference screenshot of the business website is attached. "
                    "Use anything useful from the screenshot as reference — "
                    "any images, colors, vehicles, uniforms, equipment, products, or "
                    "any other visual assets you can see. Copy them as closely as "
                    "possible into the generated image. Match the website's color "
                    "scheme and overall aesthetic."
                )
        else:
            # Fallback: use existing template-based prompt builder
            scene_prompt = self._build_scene_prompt(
                business_type=business_type,
                products_or_services=products_or_services,
                store_description=store_description,
                has_screenshot=bool(screenshot_url)
            )
        result_meta["scene_prompt"] = scene_prompt

        # ------------------------------------------------------------------
        # Step 3: Build reference images from screenshot_url
        # ------------------------------------------------------------------
        reference_images = []
        if screenshot_url:
            reference_images.append({"url": screenshot_url, "type": "screenshot"})
            result_meta["screenshot_used"] = True

        # ------------------------------------------------------------------
        # Step 4: Generate base scene image with Gemini
        # ------------------------------------------------------------------
        scene_image_b64 = None

        try:
            gemini = GeminiImageGenerator()
            if gemini.client:
                logger.info(f"[MediaGeneratorAgent] Generating store ad scene with Gemini (refs: {len(reference_images)})")
                gemini_result = await gemini.generate_ad_image(
                    prompt=scene_prompt,
                    logo_url=None,  # Logo extracted from screenshot reference, not passed separately
                    reference_images=reference_images if reference_images else None,
                    aspect_ratio=aspect_ratio
                )
                if gemini_result.get("success") and gemini_result.get("image_base64"):
                    scene_image_b64 = gemini_result["image_base64"]
                    result_meta["scene_provider"] = "gemini"
                    logger.info("[MediaGeneratorAgent] Gemini scene generation succeeded")
        except Exception as e:
            logger.warning(f"[MediaGeneratorAgent] Gemini scene generation failed: {e}")

        # Fallback to multi-provider generate_image()
        if not scene_image_b64:
            logger.info("[MediaGeneratorAgent] Falling back to multi-provider for scene generation")
            fallback_result = await self.generate_image(
                prompt=scene_prompt,
                style="professional",
                aspect_ratio=aspect_ratio,
                upload_to_cloud=False  # Don't upload raw scene, only final composite
            )
            if fallback_result.get("image_base64"):
                scene_image_b64 = fallback_result["image_base64"]
                result_meta["scene_provider"] = fallback_result.get("provider_used", "fallback")

        if not scene_image_b64:
            return {
                "success": False,
                "error": "Failed to generate scene image with all providers",
                "image_base64": None,
                "cloudinary_url": None,
                "metadata": result_meta
            }

        # ------------------------------------------------------------------
        # Step 5: Resolve headline & bullets
        #   Priority: caller-provided > AI-generated > template fallback
        #   Bullets always prefer products_or_services (concrete store data)
        # ------------------------------------------------------------------
        ai_headline = creative_result.get("headline") if creative_result else None
        ai_ad_angle = creative_result.get("ad_angle") if creative_result else None

        if not headline:
            if ai_headline:
                headline = ai_headline
                result_meta["headline_source"] = "ad_creative_agent"
            else:
                default_copy = self._generate_default_ad_copy(
                    store_name=store_name,
                    store_description=store_description,
                    business_type=business_type,
                    products_or_services=products_or_services
                )
                headline = default_copy["headline"]
                result_meta["headline_source"] = "template"
            result_meta["headline_auto_generated"] = True
        else:
            result_meta["headline_source"] = "caller"

        if not bullet_points:
            # Prefer concrete store data for bullets
            if products_or_services:
                bullet_points = [
                    svc if len(svc) < 60 else svc[:57] + "..."
                    for svc in products_or_services[:3]
                ]
                result_meta["bullets_source"] = "products_or_services"
            else:
                default_copy = self._generate_default_ad_copy(
                    store_name=store_name,
                    store_description=store_description,
                    business_type=business_type,
                    products_or_services=products_or_services
                )
                bullet_points = default_copy["bullet_points"]
                result_meta["bullets_source"] = "template"
            result_meta["bullets_auto_generated"] = True
        else:
            result_meta["bullets_source"] = "caller"

        result_meta["headline"] = headline
        result_meta["bullet_points"] = bullet_points
        if ai_ad_angle:
            result_meta["ad_angle"] = ai_ad_angle

        # ------------------------------------------------------------------
        # Step 6: Compose final ad with modern layout
        # ------------------------------------------------------------------
        composer = AdImageComposer()
        scene_bytes = base64.b64decode(scene_image_b64)

        compose_result = composer.compose_modern_ad_image(
            base_image=scene_bytes,
            headline=headline,
            bullet_points=bullet_points,
            cta_text=cta_text,
            brand_name=store_name,
            brand_color=brand_color,
            logo_url=logo_url
        )

        if not compose_result.get("success"):
            return {
                "success": False,
                "error": f"Failed to compose ad image: {compose_result.get('error')}",
                "image_base64": scene_image_b64,  # Return raw scene as fallback
                "cloudinary_url": None,
                "metadata": result_meta
            }

        final_image_b64 = compose_result["image_base64"]

        # ------------------------------------------------------------------
        # Step 7: Upload to Cloudinary if requested
        # ------------------------------------------------------------------
        cloudinary_url = None
        thumbnail_url = None

        if upload_to_cloud and final_image_b64:
            logger.info("[MediaGeneratorAgent] Uploading store ad to Cloudinary...")
            cloud_result = self.upload_to_cloudinary(
                image_base64=final_image_b64,
                folder="shopivell/generated/store-ads"
            )
            if cloud_result.get("uploaded"):
                cloudinary_url = cloud_result.get("secure_url")
                thumbnail_url = cloud_result.get("thumbnail_url")
                logger.info(f"[MediaGeneratorAgent] Store ad uploaded: {cloudinary_url}")
            else:
                logger.warning(f"[MediaGeneratorAgent] Cloudinary upload failed: {cloud_result.get('error')}")

        return {
            "success": True,
            "image_base64": final_image_b64,
            "cloudinary_url": cloudinary_url,
            "thumbnail_url": thumbnail_url,
            "metadata": result_meta,
            "error": None
        }

    # ------------------------------------------------------------------
    # Campaign ad generation with screenshot cropping
    # ------------------------------------------------------------------

    def _download_image_bytes(self, url: str) -> Optional[bytes]:
        """Download image from URL and return raw bytes."""
        try:
            import requests as req
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
            resp = req.get(url, headers=headers, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 500:
                return resp.content
        except Exception as e:
            logger.warning(f"[MediaGenerator] Failed to download image from {url}: {e}")
        return None

    def _crop_screenshot_sections(self, screenshot_bytes: bytes, max_width: int = 1024) -> List[Dict[str, Any]]:
        """Crop full-page screenshot into focused sections and resize for API consumption.

        Each section is resized to max_width (default 1024px) and saved as JPEG
        to keep the base64 payload manageable for OpenRouter/Gemini APIs.
        """
        try:
            from PIL import Image as PILImage
            from io import BytesIO

            img = PILImage.open(BytesIO(screenshot_bytes)).convert("RGB")
            w, h = img.size
            sections = []

            def _save_section(crop, label):
                """Resize section to max_width and save as JPEG for smaller payloads."""
                cw, ch = crop.size
                if cw > max_width:
                    ratio = max_width / cw
                    crop = crop.resize((max_width, int(ch * ratio)), PILImage.Resampling.LANCZOS)
                buf = BytesIO()
                crop.save(buf, format="JPEG", quality=90)
                sections.append({"label": label, "bytes": buf.getvalue()})
                logger.info(f"[MediaGenerator] Section '{label}': {crop.size[0]}x{crop.size[1]} ({len(buf.getvalue()):,} bytes)")

            # Section 1: Header/Logo area (top ~500px) - has logo, nav, brand colors
            header_h = min(500, h)
            _save_section(img.crop((0, 0, w, header_h)), "HEADER (logo, navigation, branding)")

            # Section 2: Hero area (500-1500px) - usually has main hero image, key visuals
            hero_end = min(1500, h)
            if hero_end > header_h + 100:
                _save_section(img.crop((0, header_h, w, hero_end)), "HERO AREA (main visuals, key images)")

            # Section 3: Mid content (1500-3500px) - services, products, uniforms, vehicles
            mid_end = min(3500, h)
            if mid_end > hero_end + 100:
                _save_section(img.crop((0, hero_end, w, mid_end)), "SERVICES/PRODUCTS (uniforms, vehicles, equipment)")

            # Section 4: Lower content (3500-5500px) - more assets, gallery
            lower_end = min(5500, h)
            if lower_end > mid_end + 100:
                _save_section(img.crop((0, mid_end, w, lower_end)), "GALLERY/ASSETS (additional images)")

            logger.info(f"[MediaGenerator] Cropped screenshot ({w}x{h}) into {len(sections)} sections (resized to {max_width}px wide)")
            return sections
        except Exception as e:
            logger.warning(f"[MediaGenerator] Failed to crop screenshot: {e}")
            return []

    def _crop_logo_from_screenshot(self, screenshot_bytes: bytes) -> Optional[bytes]:
        """Crop the logo area from the top-left of the screenshot.

        Uses a tighter crop (200x80) and trims whitespace/background to isolate
        just the logo rather than capturing the entire header bar.
        """
        try:
            from PIL import Image as PILImage, ImageStat
            from io import BytesIO

            img = PILImage.open(BytesIO(screenshot_bytes))
            w, h = img.size
            # Tighter crop - logos are typically in the top-left ~200x80 area
            crop_w = min(250, w)
            crop_h = min(90, h)
            logo_crop = img.crop((0, 0, crop_w, crop_h))

            # Try to auto-trim background edges for a cleaner logo
            try:
                # Convert to RGBA if not already
                logo_rgba = logo_crop.convert("RGBA")
                # Sample background color from the top-left corner pixel
                bg_pixel = logo_rgba.getpixel((0, 0))[:3]

                # Find bounding box of non-background content
                pixels = logo_rgba.load()
                min_x, min_y = crop_w, crop_h
                max_x, max_y = 0, 0
                threshold = 30  # Color distance threshold

                for y in range(crop_h):
                    for x in range(crop_w):
                        r, g, b, a = pixels[x, y]
                        # Check if pixel differs significantly from background
                        dist = abs(r - bg_pixel[0]) + abs(g - bg_pixel[1]) + abs(b - bg_pixel[2])
                        if dist > threshold:
                            min_x = min(min_x, x)
                            min_y = min(min_y, y)
                            max_x = max(max_x, x)
                            max_y = max(max_y, y)

                # Only use trimmed version if we found meaningful content
                content_w = max_x - min_x
                content_h = max_y - min_y
                if content_w > 30 and content_h > 15:
                    # Add small padding
                    pad = 5
                    min_x = max(0, min_x - pad)
                    min_y = max(0, min_y - pad)
                    max_x = min(crop_w, max_x + pad)
                    max_y = min(crop_h, max_y + pad)
                    logo_crop = logo_crop.crop((min_x, min_y, max_x, max_y))
                    logger.info(f"[MediaGenerator] Trimmed logo crop to {logo_crop.size[0]}x{logo_crop.size[1]}")
            except Exception as trim_err:
                logger.debug(f"[MediaGenerator] Logo trim failed, using raw crop: {trim_err}")

            buf = BytesIO()
            logo_crop.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"[MediaGenerator] Failed to crop logo from screenshot: {e}")
            return None

    async def _generate_with_openrouter_image(
        self,
        prompt: str,
        store_name: str = "Company",
        what_they_do: str = "",
        primary_color: str = "#1A233A",
        accent_color: str = "#FFB800",
        has_pil_logo: bool = False,
        screenshot_sections: List[Dict] = None,
        uniforms_description: str = "",
        vehicles_description: str = "",
        equipment_description: str = "",
        imagery_description: str = "",
    ) -> Dict[str, Any]:
        """
        Generate an ad image using Nano Banana Pro (Gemini 3 Pro) via OpenRouter
        chat completions with modalities=["image","text"].

        Passes cropped screenshot sections as multimodal image inputs so the model
        can see the actual website (logos, uniforms, vehicles, colors, products)
        and reproduce them accurately - same approach as the direct Gemini pipeline.
        """
        openrouter_key = self.openrouter_api_key
        if not openrouter_key:
            return {"success": False, "image_base64": None, "error": "No OpenRouter API key"}

        # Build the same enhanced prompt used by generate_ad_image_with_sections()
        if screenshot_sections:
            enhanced_prompt = f"""I am attaching CROPPED SECTIONS of {store_name}'s website homepage so you can see the details clearly.

{store_name} does: {what_they_do}

YOUR TASK: Generate a professional advertising image for {store_name}.

Study each attached image carefully. Use any useful VISUAL assets you find - uniforms, vehicles, equipment, products, colors, branding VISUALS - and copy them EXACTLY as they appear into the generated image. Same colors, same style, same details.

CRITICAL: Only copy VISUAL elements (uniforms, vehicles, equipment, colors, physical objects). Do NOT copy any TEXT you see in the screenshots - no company names, no slogans, no product names, no headings, no labels, no watermarks. Text will be added separately.

EXACT VISUAL DETAILS TO REPRODUCE:
- UNIFORMS: {uniforms_description if uniforms_description else 'Study the screenshots carefully for any staff uniforms and copy them exactly - same colors, same style, same patches, same belts, same boots.'}
- VEHICLES: {vehicles_description if vehicles_description else 'Study the screenshots carefully for any branded vehicles and copy them exactly - same body color, same branding placement, same vehicle type.'}
- EQUIPMENT: {equipment_description if equipment_description else 'Study the screenshots for any equipment and copy it exactly.'}
- IMAGERY: {imagery_description if imagery_description else 'Use all visual elements from the screenshots.'}

"""
            if has_pil_logo:
                enhanced_prompt += "DO NOT add any standalone logo graphic or company name text overlay to the image. However, if vehicles, uniforms, or equipment from the screenshot already have branding on them, keep that branding as it appears. The real logo will be added separately.\n"
            else:
                enhanced_prompt += "Include the company logo as it appears on the screenshot. Copy it exactly.\n"

            enhanced_prompt += f"""
Match the website's color scheme: background {primary_color}, accents {accent_color}.

SCENE TO GENERATE:
{prompt}

RULES:
- ABSOLUTELY NO TEXT of any kind in the generated image. No headlines, no labels, no company names, no product names, no slogans, no buttons, no bullet text, no watermarks, no review cards, no testimonials, no sign text, no screen text, no vehicle text. The image must contain ZERO readable characters.
- If the scene mentions text on signs, screens, tablets, or vehicles - DO NOT render that text. Leave those surfaces blank, blurred, or use abstract colored shapes instead.
- Do NOT reproduce any text you see in the screenshot reference images. Only copy PHYSICAL/VISUAL elements (colors, shapes, uniforms, vehicles, equipment).
- NEVER place small people or faces in the background - they will appear distorted. Only 1-3 main foreground subjects with clear, large faces are allowed.
- No background figures, no crowd scenes, no distant personnel. Keep the background clean with buildings, vehicles, or equipment only.
- ONLY generate the photorealistic scene with NO text whatsoever
"""
        else:
            # Text-only fallback prompt (no reference images available)
            enhanced_prompt = f"""Professional advertising image for {store_name}.
{store_name} does: {what_they_do}

SCENE: {prompt}

STYLE REQUIREMENTS:
- Photorealistic, high-quality commercial photography
- Color scheme: primary {primary_color}, accent {accent_color}
- Professional advertising look, suitable for social media ads
- NEVER place small people or faces in the background. Only 1-3 main foreground subjects with large clear faces. Keep backgrounds clean.
- ABSOLUTELY NO TEXT of any kind. No headlines, no labels, no company names, no slogans, no buttons, no watermarks, no signs with text, no screen text. ZERO readable characters.
- {"NO standalone logos" if has_pil_logo else "Include subtle company branding"}
- Clean composition with space for text overlay at the bottom
- 1:1 square aspect ratio
"""

        # Build multimodal content: text + section images as base64 data URLs
        content_parts = []

        # Add each screenshot section as an image part (already resized to 1024px + JPEG)
        if screenshot_sections:
            for section in screenshot_sections:
                try:
                    section_b64 = base64.b64encode(section["bytes"]).decode()
                    # Detect mime type from bytes header
                    raw = section["bytes"]
                    mime = "image/jpeg" if raw[:2] == b'\xff\xd8' else "image/png"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{section_b64}"
                        }
                    })
                except Exception as e:
                    logger.warning(f"[MediaGenerator] Failed to encode section {section.get('label')}: {e}")

        # Add the text prompt last (after images, so model sees images first)
        content_parts.append({
            "type": "text",
            "text": enhanced_prompt[:4000]
        })

        logger.info(f"[MediaGenerator] OpenRouter request: {len(content_parts)} parts ({len(content_parts)-1} images + text)")

        for model_id in ["google/gemini-3-pro-image-preview", "google/gemini-2.5-flash-image-preview"]:
            try:
                logger.info(f"[MediaGenerator] Calling {model_id} via OpenRouter with {len(screenshot_sections or [])} sections...")
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://shopivell.com",
                            "X-Title": "Shopivell Ad Generator",
                        },
                        json={
                            "model": model_id,
                            "messages": [
                                {"role": "user", "content": content_parts}
                            ],
                            "modalities": ["image", "text"],
                        },
                    )
                    response.raise_for_status()
                    result = response.json()

                # Extract image from response
                if result.get("choices"):
                    message = result["choices"][0].get("message", {})

                    # Check message.images[] (OpenRouter image generation format)
                    images = message.get("images", [])
                    if images:
                        image_url = images[0].get("image_url", {}).get("url", "")
                        if image_url.startswith("data:image/"):
                            image_b64 = image_url.split(",", 1)[1]
                            logger.info(f"[MediaGenerator] {model_id} via OpenRouter generated image ({len(image_b64):,} chars)")
                            return {"success": True, "image_base64": image_b64, "model": model_id, "error": None}

                    # Check content parts (alternative response format)
                    msg_content = message.get("content", "")
                    if isinstance(msg_content, list):
                        for part in msg_content:
                            if isinstance(part, dict) and part.get("type") == "image_url":
                                img_url = part.get("image_url", {}).get("url", "")
                                if img_url.startswith("data:image/"):
                                    image_b64 = img_url.split(",", 1)[1]
                                    logger.info(f"[MediaGenerator] {model_id} via OpenRouter generated image (content parts)")
                                    return {"success": True, "image_base64": image_b64, "model": model_id, "error": None}

                logger.warning(f"[MediaGenerator] {model_id} via OpenRouter returned no image")
            except Exception as e:
                logger.warning(f"[MediaGenerator] {model_id} via OpenRouter failed: {str(e)[:200]}")

        return {"success": False, "image_base64": None, "error": "All OpenRouter image models failed"}

    async def _generate_with_pollinations(
        self,
        prompt: str,
        store_name: str = "Company",
        what_they_do: str = "",
        primary_color: str = "#1A233A",
        accent_color: str = "#FFB800",
        has_pil_logo: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate an ad image using Pollinations.ai (free, no API key required).
        Uses FLUX model under the hood via GET URL API.
        """
        try:
            import urllib.parse

            # Build a concise SINGLE-LINE prompt (no newlines - they break the URL)
            logo_note = "no logos" if has_pil_logo else "subtle branding"
            short_desc = (what_they_do[:120] if what_they_do else store_name).replace("\n", " ")
            scene_text = (prompt[:300] if prompt else f"professional ad for {store_name}").replace("\n", " ")

            poll_prompt = (
                f"Professional advertising photo for {store_name}, "
                f"{short_desc}, SCENE: {scene_text}, "
                f"photorealistic commercial photography, colors {primary_color} and {accent_color}, "
                f"professional ad, NO text overlays, NO watermarks, {logo_note}, "
                f"clean composition with space at bottom"
            )
            # Remove any remaining newlines and limit length
            poll_prompt = poll_prompt.replace("\n", " ").replace("\r", " ")[:800]

            encoded = urllib.parse.quote(poll_prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&model=flux"

            logger.info(f"[MediaGenerator] Calling Pollinations.ai (free FLUX), prompt length: {len(poll_prompt)}")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if content_type.startswith("image") or len(response.content) > 10000:
                    image_b64 = base64.b64encode(response.content).decode()
                    logger.info(f"[MediaGenerator] Pollinations.ai generated image ({len(image_b64):,} chars base64)")
                    return {"success": True, "image_base64": image_b64, "model": "pollinations-flux", "error": None}
                else:
                    logger.warning(f"[MediaGenerator] Pollinations.ai returned non-image: {content_type}, {len(response.content)} bytes")
                    return {"success": False, "image_base64": None, "error": "Non-image response"}

        except Exception as e:
            logger.warning(f"[MediaGenerator] Pollinations.ai failed: {e}")
            return {"success": False, "image_base64": None, "error": str(e)}

    async def generate_campaign_ad(
        self,
        store_name: str,
        store_description: str = "",
        business_type: str = "business",
        logo_url: str = None,
        screenshot_url: str = None,
        screenshot_base64: str = None,
        color_theme: str = None,
        accent_color: str = None,
        products_or_services: List[str] = None,
        key_benefits: List[str] = None,
        scene_prompt: str = "",
        headline: str = None,
        bullet_points: List[str] = None,
        cta_text: str = "Learn More",
        upload_to_cloud: bool = True,
        uniforms_description: str = "",
        vehicles_description: str = "",
        equipment_description: str = "",
        imagery_description: str = "",
    ) -> Dict[str, Any]:
        """
        Generate a campaign ad image using cropped screenshot sections.

        This is the production orchestrator that:
        1. Gets screenshot bytes (from base64 or by downloading URL)
        2. Crops into focused sections for Gemini
        3. Resolves logo (URL or cropped from screenshot)
        4. Generates scene with Gemini using multi-image prompt
        5. Composes final ad with PIL (headline, bullets, CTA, logo)
        6. Uploads to Cloudinary

        Args:
            store_name: Business name
            store_description: What the business does
            business_type: Industry type
            logo_url: URL to company logo (PIL-renderable formats only)
            screenshot_url: Cloudinary URL to full-page screenshot
            screenshot_base64: Base64-encoded screenshot (avoids re-download)
            color_theme: Primary brand color hex
            accent_color: Accent/CTA color hex
            products_or_services: List of services for bullet points
            key_benefits: List of key benefits
            scene_prompt: Pre-stripped scene prompt from AdCreativeAgent
            headline: Headline text for the ad
            bullet_points: Override bullet points (else uses products_or_services)
            cta_text: CTA button text
            upload_to_cloud: Upload result to Cloudinary

        Returns:
            Dict with success, image_base64, cloudinary_url, thumbnail_url, error
        """
        import tempfile

        brand_color = accent_color or color_theme or "#FFB800"
        primary_color = color_theme or "#1A233A"

        # Step 1: Get screenshot bytes
        screenshot_bytes = None
        if screenshot_base64:
            try:
                screenshot_bytes = base64.b64decode(screenshot_base64)
                logger.info(f"[MediaGenerator] Using provided screenshot_base64 ({len(screenshot_bytes):,} bytes)")
            except Exception:
                pass
        if not screenshot_bytes and screenshot_url:
            screenshot_bytes = self._download_image_bytes(screenshot_url)
            if screenshot_bytes:
                logger.info(f"[MediaGenerator] Downloaded screenshot from URL ({len(screenshot_bytes):,} bytes)")

        # Step 2: Crop into sections
        sections = []
        if screenshot_bytes:
            sections = self._crop_screenshot_sections(screenshot_bytes)

        # Step 3: Resolve logo (skip tiny favicons < 64px, use cropped screenshot instead)
        pil_formats = ['.png', '.jpg', '.jpeg', '.webp', '.ico', '.gif']
        has_pil_logo = bool(logo_url and any(logo_url.lower().endswith(ext) for ext in pil_formats))
        logo_crop_bytes = None
        logo_temp_path = None

        # Check if the logo URL is a tiny favicon - if so, prefer cropped screenshot
        if has_pil_logo and logo_url:
            try:
                logo_bytes_check = self._download_image_bytes(logo_url)
                if logo_bytes_check:
                    from PIL import Image as PILCheck
                    check_img = PILCheck.open(BytesIO(logo_bytes_check))
                    if check_img.width < 64 or check_img.height < 64:
                        logger.info(f"[MediaGenerator] Logo too small ({check_img.width}x{check_img.height}), will use cropped screenshot instead")
                        has_pil_logo = False  # Force fallback to cropped screenshot
            except Exception:
                pass

        if not has_pil_logo and screenshot_bytes:
            logo_crop_bytes = self._crop_logo_from_screenshot(screenshot_bytes)
            if logo_crop_bytes:
                has_pil_logo = True
                logo_url = None  # Clear the tiny favicon URL so composer uses the temp file
                logger.info("[MediaGenerator] Using cropped screenshot logo as fallback")

        # Step 3b: Quick visual analysis if no descriptions provided
        if sections and not uniforms_description and not vehicles_description:
            try:
                logger.info("[MediaGenerator] Running quick visual analysis on screenshot sections...")
                # Use first 2 sections (header + hero) for analysis
                analysis_parts = []
                for s in sections[:2]:
                    s_b64 = base64.b64encode(s["bytes"]).decode()
                    raw = s["bytes"]
                    mime = "image/jpeg" if raw[:2] == b'\xff\xd8' else "image/png"
                    analysis_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{s_b64}"}
                    })
                analysis_parts.append({
                    "type": "text",
                    "text": f"""Analyze these website screenshots for {store_name}. Return ONLY valid JSON with these fields:
{{"uniforms": "describe any staff uniforms: exact shirt color, trouser color, hat color, any patches, belts, boots, reflective strips. Say 'none visible' if none.",
"vehicles": "describe any branded vehicles: vehicle type, body color, branding text/logos visible, any stripes or markings. Say 'none visible' if none.",
"equipment": "describe any equipment: cameras, alarms, tools, devices, barriers. Say 'none visible' if none.",
"imagery": "briefly describe the key visual elements on the page"}}"""
                })

                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.openrouter_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "google/gemini-2.5-flash",
                            "messages": [{"role": "user", "content": analysis_parts}],
                        },
                    )
                    resp.raise_for_status()
                    analysis_text = resp.json()["choices"][0]["message"]["content"]
                    # Parse JSON from response
                    import json as _json
                    js = analysis_text.find('{')
                    je = analysis_text.rfind('}') + 1
                    if js >= 0:
                        analysis = _json.loads(analysis_text[js:je])
                        uniforms_description = analysis.get("uniforms", "")
                        vehicles_description = analysis.get("vehicles", "")
                        equipment_description = analysis.get("equipment", "")
                        imagery_description = analysis.get("imagery", "")
                        logger.info(f"[MediaGenerator] Visual analysis: uniforms='{uniforms_description[:80]}', vehicles='{vehicles_description[:80]}'")
            except Exception as e:
                logger.warning(f"[MediaGenerator] Quick visual analysis failed (non-critical): {e}")

        # Step 4: Generate scene with Gemini using cropped sections
        scene_b64 = None

        if sections and self.gemini_generator:
            try:
                result = await self.gemini_generator.generate_ad_image_with_sections(
                    prompt=scene_prompt,
                    screenshot_sections=sections,
                    company_name=store_name,
                    primary_color=primary_color,
                    accent_color=brand_color,
                    what_they_do=store_description,
                    has_pil_logo=has_pil_logo,
                    uniforms_description=uniforms_description,
                    vehicles_description=vehicles_description,
                    equipment_description=equipment_description,
                    imagery_description=imagery_description,
                )
                if result.get("success"):
                    scene_b64 = result["image_base64"]
                    logger.info(f"[MediaGenerator] Scene generated with sections via {result.get('model')}")
            except Exception as e:
                logger.warning(f"[MediaGenerator] Section-based generation failed: {e}")

        # Step 4b: Fallback - try with full screenshot as single reference
        if not scene_b64 and screenshot_url and self.gemini_generator:
            try:
                logger.info("[MediaGenerator] Falling back to full screenshot reference...")
                fallback_result = await self.gemini_generator.generate_ad_image(
                    prompt=scene_prompt,
                    reference_images=[{"url": screenshot_url, "type": "screenshot"}],
                )
                if fallback_result.get("success"):
                    scene_b64 = fallback_result["image_base64"]
                    logger.info("[MediaGenerator] Scene generated with full screenshot fallback")
            except Exception as e:
                logger.warning(f"[MediaGenerator] Full screenshot fallback failed: {e}")

        # Step 4c: OpenRouter Nano Banana Pro with same screenshot sections (bypasses direct Gemini quota)
        if not scene_b64:
            try:
                logger.info("[MediaGenerator] Trying Nano Banana Pro via OpenRouter (with screenshot sections)...")
                or_result = await self._generate_with_openrouter_image(
                    prompt=scene_prompt,
                    store_name=store_name,
                    what_they_do=store_description,
                    primary_color=primary_color,
                    accent_color=brand_color,
                    has_pil_logo=has_pil_logo,
                    screenshot_sections=sections,
                    uniforms_description=uniforms_description,
                    vehicles_description=vehicles_description,
                    equipment_description=equipment_description,
                    imagery_description=imagery_description,
                )
                if or_result.get("success"):
                    scene_b64 = or_result["image_base64"]
                    logger.info(f"[MediaGenerator] Scene generated via OpenRouter {or_result.get('model')}")
            except Exception as e:
                logger.warning(f"[MediaGenerator] OpenRouter image fallback failed: {e}")

        # Step 4d: Free Pollinations.ai fallback (FLUX model, no API key needed)
        if not scene_b64:
            try:
                logger.info("[MediaGenerator] Trying Pollinations.ai free fallback...")
                poll_result = await self._generate_with_pollinations(
                    prompt=scene_prompt,
                    store_name=store_name,
                    what_they_do=store_description,
                    primary_color=primary_color,
                    accent_color=brand_color,
                    has_pil_logo=has_pil_logo,
                )
                if poll_result.get("success"):
                    scene_b64 = poll_result["image_base64"]
                    logger.info("[MediaGenerator] Scene generated with Pollinations.ai free fallback")
            except Exception as e:
                logger.warning(f"[MediaGenerator] Pollinations.ai fallback failed: {e}")

        if not scene_b64:
            return {
                "success": False,
                "image_base64": None,
                "cloudinary_url": None,
                "thumbnail_url": None,
                "error": "Failed to generate scene image (all providers exhausted)"
            }

        # Step 5: Resolve logo for PIL overlay
        logo_for_compose = logo_url if (logo_url and any(logo_url.lower().endswith(ext) for ext in pil_formats)) else None

        if not logo_for_compose and logo_crop_bytes:
            # Save cropped logo to temp file
            try:
                tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                tmp.write(logo_crop_bytes)
                tmp.close()
                logo_temp_path = tmp.name
                logo_for_compose = logo_temp_path
            except Exception as e:
                logger.warning(f"[MediaGenerator] Failed to save temp logo: {e}")

        # Step 6: Compose final ad with PIL
        try:
            from modules.agents.ad_image_composer import AdImageComposer
            composer = AdImageComposer()
            scene_bytes = base64.b64decode(scene_b64)

            # Resolve bullet points
            bullets = bullet_points or (products_or_services[:3] if products_or_services else key_benefits[:3] if key_benefits else [])
            bullets = [b if len(b) < 55 else b[:52] + "..." for b in bullets]

            compose_result = composer.compose_modern_ad_image(
                base_image=scene_bytes,
                headline=headline or f"Discover {store_name}",
                bullet_points=bullets,
                cta_text=cta_text,
                brand_name=store_name,
                brand_color=brand_color,
                logo_url=logo_for_compose,
            )

            if not compose_result.get("success"):
                logger.warning(f"[MediaGenerator] Compose failed: {compose_result.get('error')}")
                # Use raw scene as fallback
                final_b64 = scene_b64
            else:
                final_b64 = compose_result["image_base64"]
                logger.info("[MediaGenerator] Final ad composed with PIL overlays")
        except Exception as e:
            logger.warning(f"[MediaGenerator] Compose error: {e}, using raw scene")
            final_b64 = scene_b64
        finally:
            # Clean up temp logo file
            if logo_temp_path:
                try:
                    os.remove(logo_temp_path)
                except Exception:
                    pass

        # Step 7: Upload to Cloudinary
        cloudinary_url = None
        thumbnail_url = None
        if upload_to_cloud and final_b64:
            try:
                upload_result = self.upload_to_cloudinary(
                    image_base64=final_b64,
                    folder="shopivell/generated/campaign_ads",
                )
                if upload_result.get("uploaded"):
                    cloudinary_url = upload_result.get("secure_url")
                    thumbnail_url = upload_result.get("thumbnail_url")
                    logger.info(f"[MediaGenerator] Uploaded to Cloudinary: {cloudinary_url}")
            except Exception as e:
                logger.warning(f"[MediaGenerator] Cloudinary upload failed: {e}")

        return {
            "success": True,
            "image_base64": final_b64,
            "cloudinary_url": cloudinary_url,
            "thumbnail_url": thumbnail_url,
            "error": None
        }

    def list_industries(self) -> List[str]:
        """List all available industry templates."""
        return list(self.INDUSTRY_TEMPLATES.keys())


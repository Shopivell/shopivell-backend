from fastapi import APIRouter, HTTPException, Depends
from typing import List
import logging

from .schemas import (
    GenerateAdRequest, GenerateAdResponse,
    AdVariationsRequest, AdVariationsResponse,
    AdStyle, AdFormat, AdPlatform
)
from .service import AdGeneratorService

logger = logging.getLogger(__name__)

ad_generator_router = APIRouter(prefix="/api/ad-generator", tags=["Ad Generator"])

# Initialize service
ad_service = AdGeneratorService()


@ad_generator_router.post("/generate", response_model=GenerateAdResponse)
async def generate_ad(request: GenerateAdRequest):
    """
    Generate a single ad image using AI.

    The generated ad includes:
    - Professional product image
    - Optional text overlay with product name and CTA
    - Style matching the selected aesthetic
    - Format optimized for the target platform
    """
    try:
        result = await ad_service.generate_ad(request)
        return result
    except Exception as e:
        logger.error(f"Error generating ad: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@ad_generator_router.post("/generate-variations", response_model=AdVariationsResponse)
async def generate_ad_variations(request: AdVariationsRequest):
    """
    Generate multiple ad variations with different styles.

    Useful for A/B testing and finding the best performing ad design.
    """
    try:
        variations = []
        styles_to_use = request.styles or [AdStyle.MODERN, AdStyle.VIBRANT, AdStyle.PROFESSIONAL]

        for i in range(min(request.num_variations, len(styles_to_use))):
            ad_request = GenerateAdRequest(
                product_name=request.product_name,
                product_description=request.product_description,
                style=styles_to_use[i % len(styles_to_use)],
                format=request.format
            )
            result = await ad_service.generate_ad(ad_request)
            variations.append(result)

        return AdVariationsResponse(
            success=True,
            variations=variations,
            total_generated=len(variations)
        )
    except Exception as e:
        logger.error(f"Error generating variations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@ad_generator_router.get("/styles")
async def get_available_styles():
    """Get all available ad styles"""
    return {
        "styles": [
            {"value": style.value, "label": style.value.capitalize(), "description": _get_style_description(style)}
            for style in AdStyle
        ]
    }


@ad_generator_router.get("/formats")
async def get_available_formats():
    """Get all available ad formats with platform recommendations"""
    return {
        "formats": [
            {
                "value": AdFormat.SQUARE.value,
                "label": "Square (1:1)",
                "description": "Instagram post, Facebook post",
                "dimensions": "1080x1080"
            },
            {
                "value": AdFormat.PORTRAIT.value,
                "label": "Portrait (9:16)",
                "description": "Instagram/Facebook Story, TikTok, Reels",
                "dimensions": "1080x1920"
            },
            {
                "value": AdFormat.LANDSCAPE.value,
                "label": "Landscape (16:9)",
                "description": "YouTube thumbnail, Twitter, Website",
                "dimensions": "1920x1080"
            },
            {
                "value": AdFormat.FACEBOOK_AD.value,
                "label": "Facebook Ad (4:5)",
                "description": "Facebook feed ad (recommended)",
                "dimensions": "1080x1350"
            },
            {
                "value": AdFormat.BANNER.value,
                "label": "Banner (3:1)",
                "description": "Website banner, Email header",
                "dimensions": "1200x400"
            }
        ]
    }


@ad_generator_router.get("/platforms")
async def get_available_platforms():
    """Get all supported platforms"""
    return {
        "platforms": [
            {"value": platform.value, "label": platform.value.capitalize()}
            for platform in AdPlatform
        ]
    }


def _get_style_description(style: AdStyle) -> str:
    """Get description for each style"""
    descriptions = {
        AdStyle.MODERN: "Clean, contemporary design with bold typography",
        AdStyle.MINIMALIST: "Simple, elegant with lots of white space",
        AdStyle.VIBRANT: "Colorful, energetic and eye-catching",
        AdStyle.PROFESSIONAL: "Corporate, trustworthy business aesthetic",
        AdStyle.PLAYFUL: "Fun, cheerful with rounded shapes",
        AdStyle.ELEGANT: "Luxurious, sophisticated premium feel",
        AdStyle.BOLD: "Striking, high contrast visual statements",
        AdStyle.VINTAGE: "Retro, nostalgic classic design"
    }
    return descriptions.get(style, "")

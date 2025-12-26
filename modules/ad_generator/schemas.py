from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class AdStyle(str, Enum):
    """Available ad styles"""
    MODERN = "modern"
    MINIMALIST = "minimalist"
    VIBRANT = "vibrant"
    PROFESSIONAL = "professional"
    PLAYFUL = "playful"
    ELEGANT = "elegant"
    BOLD = "bold"
    VINTAGE = "vintage"


class AdFormat(str, Enum):
    """Ad format/aspect ratio"""
    SQUARE = "1:1"           # Instagram post, Facebook post
    PORTRAIT = "9:16"        # Instagram story, TikTok
    LANDSCAPE = "16:9"       # YouTube thumbnail, Twitter
    FACEBOOK_AD = "4:5"      # Facebook feed ad
    BANNER = "3:1"           # Website banner


class AdPlatform(str, Enum):
    """Target platform for the ad"""
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    WHATSAPP = "whatsapp"
    TIKTOK = "tiktok"
    WEBSITE = "website"
    GENERAL = "general"


class GenerateAdRequest(BaseModel):
    """Request schema for ad generation"""
    product_name: str = Field(..., min_length=1, max_length=100, description="Name of the product/service")
    product_description: str = Field(..., min_length=10, max_length=500, description="Description of the product/service")
    target_audience: Optional[str] = Field(None, max_length=200, description="Target audience for the ad")
    key_benefits: Optional[List[str]] = Field(None, max_items=5, description="Key benefits to highlight")
    call_to_action: Optional[str] = Field("Shop Now", max_length=50, description="Call to action text")
    style: AdStyle = Field(AdStyle.MODERN, description="Visual style of the ad")
    format: AdFormat = Field(AdFormat.SQUARE, description="Ad format/aspect ratio")
    platform: AdPlatform = Field(AdPlatform.GENERAL, description="Target platform")
    brand_colors: Optional[List[str]] = Field(None, max_items=3, description="Brand colors in hex format")
    include_text_overlay: bool = Field(True, description="Include text overlay on the image")
    custom_prompt: Optional[str] = Field(None, max_length=500, description="Additional custom instructions")
    agent_prompt: Optional[str] = Field(None, max_length=1000, description="Pre-generated prompt from Ad Creative Agent (overrides auto-generated prompt)")

    class Config:
        json_schema_extra = {
            "example": {
                "product_name": "Organic Coffee Blend",
                "product_description": "Premium organic coffee beans sourced from Ethiopian highlands",
                "target_audience": "Coffee enthusiasts aged 25-45",
                "key_benefits": ["100% Organic", "Fair Trade", "Rich Flavor"],
                "call_to_action": "Order Now",
                "style": "modern",
                "format": "1:1",
                "platform": "instagram",
                "brand_colors": ["#8B4513", "#F5DEB3"],
                "include_text_overlay": True
            }
        }


class GenerateAdResponse(BaseModel):
    """Response schema for ad generation"""
    success: bool
    image_base64: Optional[str] = Field(None, description="Base64 encoded image data")
    image_url: Optional[str] = Field(None, description="URL to the generated image (if saved)")
    ad_copy: Optional[str] = Field(None, description="Generated ad copy/text")
    prompt_used: Optional[str] = Field(None, description="The prompt used for generation")
    format: str = Field(..., description="Format of the generated ad")
    error: Optional[str] = Field(None, description="Error message if generation failed")


class AdVariationsRequest(BaseModel):
    """Request for generating multiple ad variations"""
    product_name: str = Field(..., min_length=1, max_length=100)
    product_description: str = Field(..., min_length=10, max_length=500)
    num_variations: int = Field(3, ge=1, le=5, description="Number of variations to generate")
    styles: Optional[List[AdStyle]] = Field(None, description="Styles to use for variations")
    format: AdFormat = Field(AdFormat.SQUARE)


class AdVariationsResponse(BaseModel):
    """Response for ad variations"""
    success: bool
    variations: List[GenerateAdResponse]
    total_generated: int

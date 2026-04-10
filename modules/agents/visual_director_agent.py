# visual_director_agent.py - AI Agent for Visual Creative Direction
"""Uses OpenRouter API via ChatOpenRouter adapter for AI generation."""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, CreativeAngle, AdCopy

# Import OpenRouter adapter (with fallback to Claude direct)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = bool(os.getenv("OPENROUTER_API_KEY"))
except ImportError:
    OPENROUTER_AVAILABLE = False

if not OPENROUTER_AVAILABLE:
    try:
        from langchain_anthropic import ChatAnthropic as ChatOpenRouter
    except ImportError:
        from langchain_openai import ChatOpenAI as ChatOpenRouter

load_dotenv()
logger = logging.getLogger(__name__)


# Visual styles for Meta Ads
VISUAL_STYLES = {
    "lifestyle": "Real people using the product in everyday situations",
    "product_hero": "Product as the main focus with clean background",
    "before_after": "Transformation showing results",
    "ugc_style": "User-generated content aesthetic, authentic and raw",
    "motion_graphics": "Animated text and graphics",
    "testimonial": "Customer speaking directly to camera",
    "behind_scenes": "Behind-the-scenes authentic content",
    "minimal": "Clean, minimal design with strong typography",
    "bold_graphic": "Eye-catching graphics and bold colors",
    "cinematic": "High-production value, story-driven"
}

# Aspect ratios for Meta placements
ASPECT_RATIOS = {
    "feed_square": {"ratio": "1:1", "resolution": "1080x1080", "placement": "Feed"},
    "feed_portrait": {"ratio": "4:5", "resolution": "1080x1350", "placement": "Feed"},
    "stories_reels": {"ratio": "9:16", "resolution": "1080x1920", "placement": "Stories/Reels"},
    "feed_landscape": {"ratio": "16:9", "resolution": "1920x1080", "placement": "In-Stream"}
}


class VisualDirectorAgent:
    """
    AI Agent for translating creative hooks into visual prompts.

    This agent:
    1. Analyzes the hook/angle and determines the best visual approach
    2. Generates detailed prompts for image generation (DALL-E, Midjourney, etc.)
    3. Creates video concept scripts with shot-by-shot breakdowns
    4. Specifies visual elements, colors, composition, and mood
    """

    def __init__(self):
        if OPENROUTER_AVAILABLE:
            self.llm = ChatOpenRouter(model="anthropic/claude-sonnet-4", temperature=0.7)
            logger.info("[VisualDirectorAgent] Initialized with OpenRouter (Claude)")
        else:
            self.llm = ChatOpenRouter(model="claude-sonnet-4-20250514", temperature=0.7)
            logger.info("[VisualDirectorAgent] Initialized with Claude direct")

        self.image_prompt_template = ChatPromptTemplate.from_template("""
You are an expert visual director specializing in Meta advertising creatives.

Generate detailed image generation prompts based on this creative hook/angle.

CAMPAIGN DETAILS:
Name: {campaign_name}
Product: {product_description}
Target Audience: {target_audience}

CREATIVE HOOK:
Hook Type: {hook_type}
Hook Text: {hook_text}
Emotion: {emotion}
Visual Direction Hint: {visual_hint}

AD COPY (for context):
Headline: {headline}
Primary Text: {primary_text}

Generate visual prompts for 3 different image concepts. For each:

{{
    "image_concepts": [
        {{
            "concept_name": "Descriptive name",
            "visual_style": "One of: lifestyle, product_hero, before_after, ugc_style, minimal, bold_graphic",
            "ai_image_prompt": "Detailed prompt for AI image generation (DALL-E/Midjourney style). Include: subject, action, setting, lighting, mood, camera angle, style modifiers",
            "composition": {{
                "focal_point": "Where the eye should be drawn",
                "text_safe_zones": "Where to place text overlays",
                "color_palette": ["primary color", "secondary color", "accent color"]
            }},
            "mood_board_keywords": ["list", "of", "mood", "keywords"],
            "format_variants": {{
                "square": "Adjustments for 1:1",
                "portrait": "Adjustments for 4:5",
                "stories": "Adjustments for 9:16"
            }},
            "overlay_text": {{
                "headline_placement": "top/middle/bottom",
                "cta_placement": "bottom-right/bottom-center",
                "text_color": "color that contrasts with background"
            }}
        }}
    ]
}}

Make prompts specific, detailed, and optimized for AI image generation.
Return ONLY valid JSON, no markdown.
""")

        self.video_concept_template = ChatPromptTemplate.from_template("""
You are an expert video creative director for Meta advertising.

Create a detailed video concept based on this creative hook/angle.

CAMPAIGN DETAILS:
Name: {campaign_name}
Product: {product_description}
Target Audience: {target_audience}

CREATIVE HOOK:
Hook Type: {hook_type}
Hook Text: {hook_text}
Emotion: {emotion}

AD COPY:
Headline: {headline}
Primary Text: {primary_text}

Create a {video_length}-second video concept with shot-by-shot breakdown:

{{
    "video_concept": {{
        "concept_name": "Name of this concept",
        "format": "UGC/Animated/Live Action/Mixed",
        "total_duration": {video_length},
        "aspect_ratio": "9:16 for Reels/Stories or 1:1 for Feed",
        "hook_timing": "First 3 seconds must grab attention",
        "shots": [
            {{
                "shot_number": 1,
                "duration_seconds": 3,
                "shot_type": "Close-up/Wide/Medium/POV",
                "description": "Detailed description of what happens",
                "visual_elements": ["list of visual elements"],
                "text_overlay": "Any text to display",
                "audio": "Music style, voiceover text, or sound effect",
                "transition_to_next": "Cut/Fade/Zoom/etc"
            }}
        ],
        "music_style": "Description of music/audio vibe",
        "color_grading": "Description of overall color treatment",
        "pacing": "Fast-paced/Medium/Slow and emotional",
        "cta_placement": {{
            "timing": "When CTA appears",
            "style": "How CTA is displayed"
        }},
        "production_notes": ["Any special requirements or considerations"]
    }}
}}

Create an engaging video that captures attention in the first 3 seconds.
Return ONLY valid JSON, no markdown.
""")

    def _clean_json_response(self, response: str) -> str:
        """Clean the JSON response from markdown formatting"""
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:]
        elif response.startswith('```'):
            response = response[3:]
        if response.endswith('```'):
            response = response[:-3]
        return response.strip()

    async def generate_image_prompts(
        self,
        campaign: Campaign,
        angle: CreativeAngle,
        ad_copy: Optional[AdCopy] = None
    ) -> Dict[str, Any]:
        """
        Generate image prompts for a creative angle.

        Args:
            campaign: Campaign object
            angle: CreativeAngle object containing the hook
            ad_copy: Optional AdCopy object for context

        Returns:
            Dict containing image concepts and prompts
        """
        prompt_data = {
            "campaign_name": campaign.name,
            "product_description": campaign.product_description or "Product not specified",
            "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "General audience",
            "hook_type": angle.angle_name,
            "hook_text": angle.value_proposition or "",
            "emotion": angle.emotion_target or "Engaging",
            "visual_hint": angle.visual_direction or "No specific direction",
            "headline": ad_copy.headline if ad_copy else "No headline yet",
            "primary_text": ad_copy.primary_text if ad_copy else "No primary text yet"
        }

        from modules.openrouter.context import set_ai_context
        chain = self.image_prompt_template | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="visual_director"):
            response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"error": "Failed to parse image prompts", "raw": cleaned}

    async def generate_video_concept(
        self,
        campaign: Campaign,
        angle: CreativeAngle,
        ad_copy: Optional[AdCopy] = None,
        video_length: int = 15
    ) -> Dict[str, Any]:
        """
        Generate a video concept for a creative angle.

        Args:
            campaign: Campaign object
            angle: CreativeAngle object containing the hook
            ad_copy: Optional AdCopy object for context
            video_length: Target video length in seconds (15, 30, or 60)

        Returns:
            Dict containing video concept with shot breakdown
        """
        prompt_data = {
            "campaign_name": campaign.name,
            "product_description": campaign.product_description or "Product not specified",
            "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "General audience",
            "hook_type": angle.angle_name,
            "hook_text": angle.value_proposition or "",
            "emotion": angle.emotion_target or "Engaging",
            "headline": ad_copy.headline if ad_copy else "No headline yet",
            "primary_text": ad_copy.primary_text if ad_copy else "No primary text yet",
            "video_length": video_length
        }

        from modules.openrouter.context import set_ai_context
        chain = self.video_concept_template | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="visual_director"):
            response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"error": "Failed to parse video concept", "raw": cleaned}

    async def generate_full_visual_package(
        self,
        campaign: Campaign,
        angle: CreativeAngle,
        ad_copy: Optional[AdCopy] = None,
        include_video: bool = True,
        video_lengths: List[int] = [15, 30]
    ) -> Dict[str, Any]:
        """
        Generate complete visual package with images and video concepts.

        Args:
            campaign: Campaign object
            angle: CreativeAngle object
            ad_copy: Optional AdCopy object
            include_video: Whether to include video concepts
            video_lengths: List of video lengths to generate

        Returns:
            Complete visual package
        """
        # Generate image prompts
        image_prompts = await self.generate_image_prompts(campaign, angle, ad_copy)

        result = {
            "campaign_id": str(campaign.id),
            "angle_id": str(angle.id),
            "angle_name": angle.angle_name,
            "image_concepts": image_prompts.get("image_concepts", []),
            "aspect_ratios": ASPECT_RATIOS,
            "visual_styles_reference": VISUAL_STYLES
        }

        # Generate video concepts if requested
        if include_video:
            video_concepts = []
            for length in video_lengths:
                concept = await self.generate_video_concept(campaign, angle, ad_copy, length)
                if "video_concept" in concept:
                    video_concepts.append(concept["video_concept"])
            result["video_concepts"] = video_concepts

        return result


async def generate_visuals_for_angle(
    campaign_id: str,
    angle_id: str,
    include_video: bool = True
) -> Dict[str, Any]:
    """
    Generate visual package for a specific angle.

    Args:
        campaign_id: UUID of the campaign
        angle_id: UUID of the creative angle
        include_video: Whether to include video concepts

    Returns:
        Complete visual package
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()
        if not angle:
            raise ValueError(f"Creative angle with ID {angle_id} not found")

        # Get related ad copy if available
        ad_copy = db.query(AdCopy).filter(AdCopy.angle_id == angle_id).first()

        agent = VisualDirectorAgent()
        return await agent.generate_full_visual_package(
            campaign, angle, ad_copy, include_video
        )
    finally:
        db.close()


async def generate_all_visuals(
    campaign_id: str,
    include_video: bool = True
) -> List[Dict[str, Any]]:
    """
    Generate visual packages for all angles of a campaign.

    Args:
        campaign_id: UUID of the campaign
        include_video: Whether to include video concepts

    Returns:
        List of visual packages
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        angles = db.query(CreativeAngle).filter(
            CreativeAngle.campaign_id == campaign_id
        ).all()

        if not angles:
            raise ValueError("No creative angles found. Generate angles first.")

        agent = VisualDirectorAgent()
        visual_packages = []

        for angle in angles:
            ad_copy = db.query(AdCopy).filter(AdCopy.angle_id == angle.id).first()
            package = await agent.generate_full_visual_package(
                campaign, angle, ad_copy, include_video
            )
            visual_packages.append(package)

        return visual_packages
    finally:
        db.close()

# copywriter_agent.py - AI Agent for Meta Ad Copy Generation
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


# Meta Ad Copy Best Practices
META_COPY_SPECS = {
    "primary_text": {
        "max_length": 125,  # Recommended for feed
        "extended_max": 500,  # Maximum allowed
        "best_practice": "Front-load key message, use line breaks, include CTA"
    },
    "headline": {
        "max_length": 40,  # Recommended
        "extended_max": 255,  # Maximum allowed
        "best_practice": "Clear value prop, action-oriented, create urgency"
    },
    "description": {
        "max_length": 30,  # Recommended
        "extended_max": 125,  # Maximum
        "best_practice": "Support headline, add context or offer details"
    }
}

# Available CTAs on Meta
META_CTAS = [
    "Learn More", "Shop Now", "Sign Up", "Download", "Book Now",
    "Get Quote", "Contact Us", "Subscribe", "Apply Now", "Get Offer",
    "Order Now", "Buy Now", "Get Started", "Watch More", "Send Message"
]


class CopywriterAgent:
    """
    AI Agent for writing Meta-specific ad copy (Facebook/Instagram).

    This agent specializes in:
    1. Primary Text - The main body copy
    2. Headlines - Attention-grabbing headlines
    3. Descriptions - Supporting description text
    4. CTAs - Call-to-action selection
    5. A/B test variations

    Uses GPT-4o for high-quality, conversion-focused copy.
    """

    def __init__(self):
        if OPENROUTER_AVAILABLE:
            self.llm = ChatOpenRouter(model="anthropic/claude-sonnet-4.6", temperature=0.9)
            logger.info("[CopywriterAgent] Initialized with OpenRouter (Claude)")
        else:
            self.llm = ChatOpenRouter(model="claude-sonnet-4-6", temperature=0.9)
            logger.info("[CopywriterAgent] Initialized with Claude direct")

        self.main_prompt = ChatPromptTemplate.from_template("""
You are an expert Meta (Facebook/Instagram) ad copywriter with deep knowledge of direct response marketing.

Write high-converting ad copy for this campaign and creative hook.

CAMPAIGN DETAILS:
Name: {campaign_name}
Objective: {objective}
Product/Service: {product_description}
Target Audience: {target_audience}
Unique Selling Points: {usps}

CREATIVE HOOK:
Hook Type: {hook_type}
Hook Text: {hook_text}
Target Emotion: {emotion}
Angle: {angle}

META AD COPY SPECS:
- Primary Text: {primary_text_max} chars recommended (125), {primary_text_extended} max
- Headline: {headline_max} chars recommended (40)
- Description: {description_max} chars recommended (30)

AVAILABLE CTAs: {available_ctas}

Generate 3 complete ad copy variations. Each should have a different approach while staying true to the hook.

{{
    "variations": [
        {{
            "variation_name": "Descriptive name for this version",
            "approach": "Brief description of the copywriting approach",
            "primary_text": {{
                "text": "The main ad copy. Use line breaks for readability. Start with the hook. Include emotional triggers. End with CTA.",
                "character_count": 0,
                "key_elements": ["list of persuasion elements used"]
            }},
            "headline": {{
                "text": "Punchy, benefit-driven headline",
                "character_count": 0
            }},
            "description": {{
                "text": "Supporting description",
                "character_count": 0
            }},
            "cta": "Best matching CTA from the list",
            "hashtags": ["relevant", "hashtags"],
            "emoji_usage": "Where and why emojis are used",
            "tone": "Description of the tone used"
        }}
    ],
    "copywriting_notes": {{
        "strongest_variation": "Which variation is likely to perform best and why",
        "a_b_test_recommendation": "Which elements to test against each other",
        "audience_segment_match": "Which variation works best for which segment"
    }}
}}

Write copy that:
1. Grabs attention in the first line
2. Speaks directly to the target audience's pain points/desires
3. Clearly communicates the value proposition
4. Creates urgency or FOMO when appropriate
5. Has a clear call-to-action
6. Uses power words and emotional triggers
7. Is authentic and not overly salesy

Return ONLY valid JSON, no markdown.
""")

        self.short_form_prompt = ChatPromptTemplate.from_template("""
You are a Meta ad copy specialist. Write ultra-concise copy for Stories/Reels.

PRODUCT: {product_description}
HOOK: {hook_text}
EMOTION: {emotion}

Generate 5 short-form copy variations for Stories/Reels ads (max 72 characters each):

{{
    "short_form_copies": [
        {{
            "text": "Ultra-short, punchy copy",
            "character_count": 0,
            "best_for": "Which placement this works best for"
        }}
    ]
}}

Keep it punchy, NO EMOJIS in headlines - keep them clean and professional.
Return ONLY valid JSON.
""")

    def _clean_json_response(self, response: str) -> str:
        """Clean the JSON response from markdown formatting (shared impl)."""
        from modules.agents.llm_json import clean_json_response
        return clean_json_response(response)

    async def generate_ad_copy(
        self,
        campaign: Campaign,
        angle: CreativeAngle
    ) -> Dict[str, Any]:
        """
        Generate comprehensive ad copy for a creative angle.

        Args:
            campaign: Campaign object
            angle: CreativeAngle object containing the hook

        Returns:
            Dict containing all copy variations
        """
        prompt_data = {
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "product_description": campaign.product_description or "Product not specified",
            "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "General audience",
            "usps": ", ".join(campaign.keywords) if campaign.keywords else "Not specified",
            "hook_type": angle.angle_name,
            "hook_text": angle.value_proposition or "",
            "emotion": angle.emotion_target or "Engaging",
            "angle": angle.reasoning or "",
            "primary_text_max": META_COPY_SPECS["primary_text"]["max_length"],
            "primary_text_extended": META_COPY_SPECS["primary_text"]["extended_max"],
            "headline_max": META_COPY_SPECS["headline"]["max_length"],
            "description_max": META_COPY_SPECS["description"]["max_length"],
            "available_ctas": ", ".join(META_CTAS)
        }

        from modules.openrouter.context import set_ai_context
        chain = self.main_prompt | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="copywriter"):
            response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            copy_data = json.loads(cleaned)
        except json.JSONDecodeError:
            copy_data = {"error": "Failed to parse copy", "raw": cleaned}

        # Store the best variation in database
        db = SessionLocal()
        try:
            variations = copy_data.get("variations", [])
            if variations:
                best = variations[0] if isinstance(variations[0], dict) else {}

                def _field_text(field: str) -> str:
                    # The model may return either {"text": "..."} or a bare string.
                    val = best.get(field, "")
                    if isinstance(val, dict):
                        return val.get("text", "")
                    return val if isinstance(val, str) else ("" if val is None else str(val))

                ad_copy = AdCopy(
                    campaign_id=campaign.id,
                    angle_id=angle.id,
                    headline=_field_text("headline"),
                    primary_text=_field_text("primary_text"),
                    description=_field_text("description"),
                    call_to_action=best.get("cta", "Learn More"),
                    variations=[v for v in variations[1:]]  # Store other variations
                )
                db.add(ad_copy)
                db.commit()
                db.refresh(ad_copy)

                copy_data["saved_ad_copy_id"] = str(ad_copy.id)

            return {
                "campaign_id": str(campaign.id),
                "angle_id": str(angle.id),
                "angle_name": angle.angle_name,
                "copy_data": copy_data
            }
        finally:
            db.close()

    async def generate_short_form_copy(
        self,
        campaign: Campaign,
        angle: CreativeAngle
    ) -> Dict[str, Any]:
        """
        Generate short-form copy for Stories/Reels.

        Args:
            campaign: Campaign object
            angle: CreativeAngle object

        Returns:
            Dict containing short-form copy variations
        """
        prompt_data = {
            "product_description": campaign.product_description or "Product",
            "hook_text": angle.value_proposition or "",
            "emotion": angle.emotion_target or "Engaging"
        }

        from modules.openrouter.context import set_ai_context
        chain = self.short_form_prompt | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="copywriter"):
            response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"error": "Failed to parse short-form copy", "raw": cleaned}

    async def generate_copy_variations_for_url_ad(
        self,
        business_name: str,
        product_description: str,
        target_audience: str,
        base_headline: str,
        base_primary_text: str,
        features: List[str],
        cta: str = "Learn More",
        num_variations: int = 3,
        store_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate copy variations for URL-based campaigns.
        Delegates to AdCopyAgent which has structured output + performance feedback.
        """
        try:
            from .ad_copy_agent import AdCopyAgent
            agent = AdCopyAgent()
            return await agent.generate_copy_variations_for_url_ad(
                business_name=business_name,
                product_description=product_description,
                target_audience=target_audience,
                base_headline=base_headline,
                base_primary_text=base_primary_text,
                features=features,
                cta=cta,
                num_variations=num_variations,
                store_id=store_id
            )
        except Exception as e:
            logger.error(f"[CopywriterAgent] Delegation to AdCopyAgent failed: {e}")
            return [{
                "headline": base_headline,
                "primary_text": base_primary_text,
                "description": "",
                "call_to_action": cta,
                "strategy": "fallback",
            }]

    async def generate_all_copy(
        self,
        campaign: Campaign,
        angles: Optional[List[CreativeAngle]] = None,
        include_short_form: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Generate ad copy for all angles of a campaign.

        Args:
            campaign: Campaign object
            angles: Optional list of angles
            include_short_form: Whether to include short-form copy

        Returns:
            List of copy packages for each angle
        """
        db = SessionLocal()
        try:
            if not angles:
                angles = db.query(CreativeAngle).filter(
                    CreativeAngle.campaign_id == campaign.id
                ).all()

            if not angles:
                raise ValueError("No creative angles found. Generate angles first.")

            all_copy = []
            for angle in angles:
                copy_package = await self.generate_ad_copy(campaign, angle)

                if include_short_form:
                    short_form = await self.generate_short_form_copy(campaign, angle)
                    copy_package["short_form"] = short_form

                all_copy.append(copy_package)

            return all_copy
        finally:
            db.close()


# Convenience functions
async def generate_copy_for_angle(campaign_id: str, angle_id: str) -> Dict[str, Any]:
    """Generate ad copy for a specific angle."""
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()
        if not angle:
            raise ValueError(f"Angle with ID {angle_id} not found")

        agent = CopywriterAgent()
        return await agent.generate_ad_copy(campaign, angle)
    finally:
        db.close()


async def generate_all_campaign_copy(
    campaign_id: str,
    include_short_form: bool = True
) -> List[Dict[str, Any]]:
    """Generate all ad copy for a campaign."""
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        agent = CopywriterAgent()
        return await agent.generate_all_copy(campaign, include_short_form=include_short_form)
    finally:
        db.close()

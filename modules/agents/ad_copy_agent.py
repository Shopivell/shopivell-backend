# ad_copy_agent.py - AI Agent for Ad Copy Generation
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

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class AdCopyAgent:
    """AI Agent for generating ad copy based on creative angles"""

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.9  # Higher temperature for more creative outputs
        )
        logger.info(f"[AdCopyAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

        self.prompt = ChatPromptTemplate.from_template("""
Generate Facebook/Instagram ad copy for the given creative angle.

CAMPAIGN DETAILS:
Name: {campaign_name}
Objective: {objective}
Product: {product_description}
Keywords: {keywords}

CREATIVE ANGLE:
Angle: {angle_name}
Value Proposition: {value_proposition}
Emotion Target: {emotion_target}
Visual Direction: {visual_direction}

Generate ad copy with:

HEADLINE: [Catchy headline, max 40 characters]
PRIMARY TEXT: [Main ad text, 1-2 paragraphs, compelling and action-oriented]
DESCRIPTION: [Optional description text, 1 sentence]
CALL TO ACTION: [Choose from: Learn More, Shop Now, Sign Up, Download, Book Now, Get Quote, Contact Us]

Also provide 3 alternative headline variations.

Format your response as valid JSON:
{{
  "headline": "Your headline here",
  "primary_text": "Your primary text here",
  "description": "Your description here",
  "call_to_action": "Learn More",
  "variations": [
    {{"headline": "Alternative headline 1"}},
    {{"headline": "Alternative headline 2"}},
    {{"headline": "Alternative headline 3"}}
  ]
}}

IMPORTANT: Return ONLY valid JSON, no markdown or other text.
""")

    def _clean_json_response(self, response: str) -> str:
        """Clean the JSON response from markdown formatting"""
        response = response.strip()

        # Remove markdown code blocks
        if response.startswith('```json'):
            response = response[7:]
        elif response.startswith('```'):
            response = response[3:]

        if response.endswith('```'):
            response = response[:-3]

        return response.strip()

    async def generate_ad_copy(
        self,
        campaign: Campaign,
        angle: CreativeAngle
    ) -> Dict[str, Any]:
        """
        Generate ad copy for a specific creative angle.

        Args:
            campaign: Campaign object
            angle: CreativeAngle object

        Returns:
            Dict containing ad copy data
        """
        # Prepare data for prompt
        prompt_data = {
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "product_description": campaign.product_description or "Not specified",
            "keywords": ", ".join(campaign.keywords) if campaign.keywords else "Not specified",
            "angle_name": angle.angle_name,
            "value_proposition": angle.value_proposition or "",
            "emotion_target": angle.emotion_target or "",
            "visual_direction": angle.visual_direction or ""
        }

        # Run the LLM chain
        chain = self.prompt | self.llm | StrOutputParser()
        ad_json = await chain.ainvoke(prompt_data)

        # Clean and parse JSON
        cleaned_json = self._clean_json_response(ad_json)

        try:
            ad_data = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Raw response: {ad_json}")
            print(f"Cleaned response: {cleaned_json}")
            # Return a default structure if parsing fails
            ad_data = {
                "headline": "Security Made Simple",
                "primary_text": cleaned_json[:500] if cleaned_json else "Contact us for more information.",
                "description": "Professional security solutions",
                "call_to_action": "Learn More",
                "variations": []
            }

        # Store in database
        db = SessionLocal()
        try:
            ad_copy = AdCopy(
                campaign_id=campaign.id,
                angle_id=angle.id,
                headline=ad_data.get('headline', ''),
                primary_text=ad_data.get('primary_text', ''),
                description=ad_data.get('description', ''),
                call_to_action=ad_data.get('call_to_action', 'Learn More'),
                variations=ad_data.get('variations', [])
            )
            db.add(ad_copy)
            db.commit()
            db.refresh(ad_copy)

            return {
                "id": str(ad_copy.id),
                "campaign_id": str(campaign.id),
                "angle_id": str(angle.id),
                "angle_name": angle.angle_name,
                "headline": ad_copy.headline,
                "primary_text": ad_copy.primary_text,
                "description": ad_copy.description,
                "call_to_action": ad_copy.call_to_action,
                "variations": ad_copy.variations,
                "created_at": ad_copy.created_at.isoformat() if ad_copy.created_at else None
            }
        finally:
            db.close()

    async def generate_all_ad_copies(
        self,
        campaign: Campaign,
        angles: Optional[List[CreativeAngle]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate ad copies for all creative angles of a campaign.

        Args:
            campaign: Campaign object
            angles: Optional list of angles (will fetch from DB if not provided)

        Returns:
            List of ad copy dictionaries
        """
        db = SessionLocal()
        try:
            # Get angles if not provided
            if not angles:
                angles = db.query(CreativeAngle).filter(
                    CreativeAngle.campaign_id == campaign.id
                ).all()

            if not angles:
                raise ValueError("No creative angles found for this campaign. Generate angles first.")

            ad_copies = []
            for angle in angles:
                ad_copy = await self.generate_ad_copy(campaign, angle)
                ad_copies.append(ad_copy)

            return ad_copies
        finally:
            db.close()


# Convenience function for direct use
async def generate_ad_copy_for_angle(campaign_id: str, angle_id: str) -> Dict[str, Any]:
    """
    Generate ad copy for a specific angle.

    Args:
        campaign_id: UUID of the campaign
        angle_id: UUID of the creative angle

    Returns:
        Dict containing ad copy data
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()
        if not angle:
            raise ValueError(f"Creative angle with ID {angle_id} not found")

        agent = AdCopyAgent()
        return await agent.generate_ad_copy(campaign, angle)
    finally:
        db.close()

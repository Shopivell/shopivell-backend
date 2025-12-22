# creative_angles_agent.py - AI Agent for Creative Angles Generation

import os
import json
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, MarketResearch, CreativeAngle

load_dotenv()


class CreativeAnglesAgent:
    """AI Agent for generating creative angles based on market research"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.8  # Higher temperature for more creative outputs
        )
        self.embeddings = OpenAIEmbeddings()

        self.prompt = ChatPromptTemplate.from_template("""
Based on the market research and campaign brief, generate {num_angles} creative angles:

CAMPAIGN BRIEF:
Name: {campaign_name}
Objective: {objective}
Product: {product_description}
Target: {target_audience}
Keywords: {keywords}

MARKET RESEARCH:
{market_research}

Generate {num_angles} distinct creative angles for advertising this product. For each angle, provide:

ANGLE NAME: [Creative name for this angle]
VALUE PROPOSITION: [What unique value does this angle present?]
EMOTION TARGET: [What emotion does this angle aim to evoke?]
VISUAL DIRECTION: [What should the visual look like?]
REASONING: [Why this angle fits the research?]

Separate each angle with "---" and format exactly as above.
Make each angle unique and tailored to different segments of the target audience.
""")

    def _parse_angles_response(self, response_text: str) -> List[Dict[str, str]]:
        """Parse the AI response into structured angles"""
        angles = []
        current_angle = {}

        def extract_value(line: str, key: str) -> str:
            """Extract value after key, removing markdown formatting"""
            # Remove the key and any leading #, *, or whitespace
            value = line.split(':', 1)[-1].strip()
            # Remove markdown bold markers
            value = value.replace('**', '').replace('*', '')
            return value

        def contains_key(line: str, key: str) -> bool:
            """Check if line contains the key (case insensitive)"""
            line_upper = line.upper()
            return key.upper() in line_upper and ':' in line

        for line in response_text.split('\n'):
            line = line.strip()

            if contains_key(line, 'ANGLE NAME'):
                if current_angle and current_angle.get('angle_name'):
                    angles.append(current_angle)
                current_angle = {'angle_name': extract_value(line, 'ANGLE NAME')}
            elif contains_key(line, 'VALUE PROPOSITION'):
                current_angle['value_proposition'] = extract_value(line, 'VALUE PROPOSITION')
            elif contains_key(line, 'EMOTION TARGET'):
                current_angle['emotion_target'] = extract_value(line, 'EMOTION TARGET')
            elif contains_key(line, 'VISUAL DIRECTION'):
                current_angle['visual_direction'] = extract_value(line, 'VISUAL DIRECTION')
            elif contains_key(line, 'REASONING'):
                current_angle['reasoning'] = extract_value(line, 'REASONING')
            elif line == '---' or line.startswith('---'):
                if current_angle and current_angle.get('angle_name'):
                    angles.append(current_angle)
                current_angle = {}

        # Don't forget the last angle
        if current_angle and current_angle.get('angle_name'):
            angles.append(current_angle)

        return angles

    async def generate_angles(
        self,
        campaign: Campaign,
        research: Optional[MarketResearch] = None,
        num_angles: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Generate creative angles for a campaign based on market research.

        Args:
            campaign: Campaign object
            research: Optional MarketResearch object (will fetch latest if not provided)
            num_angles: Number of angles to generate (default: 5)

        Returns:
            List of creative angle dictionaries
        """
        db = SessionLocal()
        try:
            # Get latest research if not provided
            if not research:
                research = db.query(MarketResearch).filter(
                    MarketResearch.campaign_id == campaign.id
                ).order_by(MarketResearch.created_at.desc()).first()

            # Build market research context
            if research:
                market_research = f"""
Competitor Analysis: {research.competitor_analysis or 'Not available'}

Audience Insights: {research.audience_insights or 'Not available'}

Trends: {research.trend_data or 'Not available'}

Recommendations: {research.recommendations or 'Not available'}
"""
            else:
                market_research = "No market research available. Generate angles based on campaign brief only."

            # Prepare campaign data
            campaign_data = {
                "campaign_name": campaign.name,
                "objective": campaign.objective,
                "product_description": campaign.product_description or "Not specified",
                "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "Not specified",
                "keywords": ", ".join(campaign.keywords) if campaign.keywords else "Not specified",
                "market_research": market_research,
                "num_angles": num_angles
            }

            # Run the LLM chain
            chain = self.prompt | self.llm | StrOutputParser()
            angles_text = await chain.ainvoke(campaign_data)

            # Parse angles
            angles = self._parse_angles_response(angles_text)

            # Store each angle in database
            saved_angles = []
            for angle_data in angles:
                # Generate embedding for the angle
                angle_text = f"{angle_data.get('angle_name', '')} {angle_data.get('value_proposition', '')} {angle_data.get('reasoning', '')}"
                embedding = self.embeddings.embed_query(angle_text)

                creative_angle = CreativeAngle(
                    campaign_id=campaign.id,
                    angle_name=angle_data.get('angle_name', 'Unnamed Angle'),
                    value_proposition=angle_data.get('value_proposition', ''),
                    emotion_target=angle_data.get('emotion_target', ''),
                    visual_direction=angle_data.get('visual_direction', ''),
                    reasoning=angle_data.get('reasoning', ''),
                    embedding=embedding
                )
                db.add(creative_angle)
                db.flush()  # Get the ID

                saved_angles.append({
                    "id": str(creative_angle.id),
                    "campaign_id": str(campaign.id),
                    "angle_name": creative_angle.angle_name,
                    "value_proposition": creative_angle.value_proposition,
                    "emotion_target": creative_angle.emotion_target,
                    "visual_direction": creative_angle.visual_direction,
                    "reasoning": creative_angle.reasoning,
                    "created_at": creative_angle.created_at.isoformat() if creative_angle.created_at else None
                })

            db.commit()
            return saved_angles

        finally:
            db.close()


# Convenience function for direct use
async def generate_creative_angles(campaign_id: str, num_angles: int = 5) -> List[Dict[str, Any]]:
    """
    Generate creative angles for a campaign by ID.

    Args:
        campaign_id: UUID of the campaign
        num_angles: Number of angles to generate

    Returns:
        List of creative angle dictionaries
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        agent = CreativeAnglesAgent()
        return await agent.generate_angles(campaign, num_angles=num_angles)
    finally:
        db.close()

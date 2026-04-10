# creative_angles_agent.py - AI Agent for Creative Angles Generation
"""Uses OpenRouter API via ChatOpenRouter adapter for AI generation."""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, MarketResearch, CreativeAngle

# Import OpenRouter adapter (with fallback to ChatOpenAI)
_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
if _OPENROUTER_KEY:
    try:
        from modules.openrouter.langchain_adapter import ChatOpenRouter
        OPENROUTER_AVAILABLE = True
    except ImportError:
        from langchain_openai import ChatOpenAI as ChatOpenRouter
        OPENROUTER_AVAILABLE = False
else:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


# --- Structured output models ---

class CreativeAngleOutput(BaseModel):
    angle_name: str = Field(..., description="Creative name for this angle")
    value_proposition: str = Field(..., description="What unique value does this angle present?")
    emotion_target: str = Field(..., description="What emotion does this angle aim to evoke?")
    visual_direction: str = Field(..., description="What should the visual look like?")
    reasoning: str = Field(..., description="Why this angle fits the research?")


class CreativeAnglesResponse(BaseModel):
    angles: List[CreativeAngleOutput]


class CreativeAnglesAgent:
    """AI Agent for generating creative angles based on market research"""

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="anthropic/claude-sonnet-4" if OPENROUTER_AVAILABLE else "claude-sonnet-4-20250514",
            temperature=0.8  # Higher temperature for more creative outputs
        )
        self._supports_json_mode = OPENROUTER_AVAILABLE
        self.embeddings = OpenAIEmbeddings()
        logger.info(f"[CreativeAnglesAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'Anthropic direct'}")

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

KEYWORD INTELLIGENCE:
{keyword_intelligence}

Generate {num_angles} distinct creative angles for advertising this product.
Make each angle unique and tailored to different segments of the target audience.

{performance_insights}

If keyword intelligence data is available, use it to:
- Align angles with high-volume search terms people actually use
- Create angles that match different search intents (transactional keywords for conversion angles, informational for awareness angles)
- Reference specific keyword language in value propositions so ads match what people search for

IMPORTANT: Return your response as valid JSON with this exact structure:
{{
  "angles": [
    {{
      "angle_name": "Creative name for this angle",
      "value_proposition": "What unique value does this angle present?",
      "emotion_target": "What emotion does this angle aim to evoke?",
      "visual_direction": "What should the visual look like?",
      "reasoning": "Why this angle fits the research?"
    }}
  ]
}}

Return ONLY valid JSON, no other text.
""")

    def _parse_angles_response(self, response_text: str) -> List[Dict[str, str]]:
        """Parse the AI response into structured angles. JSON-first with prefix fallback."""
        # Try JSON parsing first (Pydantic validation)
        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = CreativeAnglesResponse.model_validate_json(cleaned)
            return [a.model_dump() for a in data.angles]
        except Exception:
            pass

        # Try plain JSON
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "angles" in parsed:
                return parsed["angles"]
        except Exception:
            pass

        logger.warning("[CreativeAnglesAgent] JSON parse failed, falling back to prefix parsing")

        # Fallback: prefix-based parsing
        angles = []
        current_angle = {}

        def extract_value(line: str, key: str) -> str:
            value = line.split(':', 1)[-1].strip()
            value = value.replace('**', '').replace('*', '')
            return value

        def contains_key(line: str, key: str) -> bool:
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

        if current_angle and current_angle.get('angle_name'):
            angles.append(current_angle)

        return angles

    def _get_angle_performance_insights(self) -> str:
        """Query past creative test results to learn which angle types perform best."""
        db = SessionLocal()
        try:
            from .models import CreativeAngle as CAModel
            from .models import CreativeTest, CreativeTestVariant

            # Get angles linked to winning creative test variants
            tests = db.query(CreativeTest).filter(
                CreativeTest.status == "completed",
                CreativeTest.winner_ad_id.isnot(None)
            ).order_by(CreativeTest.completed_at.desc()).limit(10).all()

            if not tests:
                return ""

            # Collect winning patterns
            winning_emotions = []
            winning_directions = []

            for test in tests:
                results = test.results or {}
                winner_data = results.get("winner", {})
                if winner_data.get("is_original"):
                    continue  # Original won, not useful for angle insights

                # Try to find the angle that produced the winner
                # This is approximate — we look at angle names that match
                winner_headline = winner_data.get("headline", "")
                if winner_headline:
                    # Search for angles with similar value propositions
                    angles = db.query(CAModel).filter(
                        CAModel.value_proposition.ilike(f"%{winner_headline[:20]}%")
                    ).limit(3).all()
                    for a in angles:
                        if a.emotion_target:
                            winning_emotions.append(a.emotion_target)
                        if a.visual_direction:
                            winning_directions.append(a.visual_direction[:50])

            if not winning_emotions and not winning_directions:
                return ""

            insights = "PERFORMANCE INSIGHTS FROM PAST A/B TESTS:"
            if winning_emotions:
                insights += f"\n- Winning emotion targets: {', '.join(set(winning_emotions[:5]))}"
            if winning_directions:
                insights += f"\n- Winning visual directions: {', '.join(set(winning_directions[:3]))}"
            insights += "\nPrioritize similar angle types in your generation."
            return insights

        except Exception as e:
            logger.warning(f"[CreativeAnglesAgent] Failed to get performance insights: {e}")
            return ""
        finally:
            db.close()

    async def generate_angles(
        self,
        campaign: Campaign,
        research: Optional[MarketResearch] = None,
        num_angles: int = 5,
        keyword_data: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate creative angles for a campaign based on market research.

        Args:
            campaign: Campaign object
            research: Optional MarketResearch object (will fetch latest if not provided)
            num_angles: Number of angles to generate (default: 5)
            keyword_data: Optional keyword intelligence with search volume, CPC, and intent clusters

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

            # Format keyword intelligence
            keyword_intel_text = "No keyword data available"
            if keyword_data and keyword_data.get("success"):
                kw_lines = []
                top_kws = keyword_data.get("keywords", [])[:10]
                if top_kws:
                    kw_lines.append("Top searched keywords:")
                    for kw in top_kws:
                        vol = kw.get("search_volume")
                        kw_lines.append(f"  - \"{kw.get('keyword', '')}\" (volume: {vol if vol is not None else 'N/A'})")
                clusters = keyword_data.get("clusters", {})
                if clusters:
                    for intent in ["transactional", "commercial", "informational"]:
                        cluster_kws = clusters.get(intent, [])
                        if cluster_kws:
                            names = [k.get("keyword", "") for k in cluster_kws[:4]]
                            kw_lines.append(f"{intent.title()} intent: {', '.join(names)}")
                keyword_intel_text = "\n".join(kw_lines) if kw_lines else keyword_intel_text

            # Get performance insights from past A/B tests (meta-learner feedback)
            perf_insights = self._get_angle_performance_insights()

            # Prepare campaign data
            campaign_data = {
                "campaign_name": campaign.name,
                "objective": campaign.objective,
                "product_description": campaign.product_description or "Not specified",
                "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "Not specified",
                "keywords": ", ".join(campaign.keywords) if campaign.keywords else "Not specified",
                "market_research": market_research,
                "keyword_intelligence": keyword_intel_text,
                "num_angles": num_angles,
                "performance_insights": perf_insights
            }

            # Run the LLM chain with structured JSON output
            from modules.openrouter.context import set_ai_context
            json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
            chain = self.prompt | json_llm | StrOutputParser()
            with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="creative_angles"):
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


    async def generate_angles_for_campaigns(
        self,
        campaign_ids: List[str],
        num_angles: int = 5,
        keyword_data: Dict[str, Any] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate angles for multiple campaigns in parallel.

        Returns:
            Dict mapping campaign_id to list of angle dicts
        """
        db = SessionLocal()
        try:
            campaigns = db.query(Campaign).filter(Campaign.id.in_(campaign_ids)).all()

            async def _gen_for_campaign(campaign):
                try:
                    return str(campaign.id), await self.generate_angles(
                        campaign, num_angles=num_angles, keyword_data=keyword_data
                    )
                except Exception as e:
                    logger.error(f"[CreativeAnglesAgent] Error for campaign {campaign.id}: {e}")
                    return str(campaign.id), []

            tasks = [_gen_for_campaign(c) for c in campaigns]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            output = {}
            for item in results:
                if isinstance(item, Exception):
                    logger.error(f"[CreativeAnglesAgent] Parallel error: {item}")
                    continue
                campaign_id, angles = item
                output[campaign_id] = angles

            return output
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

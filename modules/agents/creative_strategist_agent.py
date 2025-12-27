# creative_strategist_agent.py - AI Agent for Creative Strategy & Hook Generation
"""Uses OpenRouter API via ChatOpenRouter adapter for AI generation."""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, MarketResearch, CreativeAngle

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


# Hook Types for Meta Ads
HOOK_TYPES = [
    {
        "name": "Fear of Missing Out (FOMO)",
        "description": "Creates urgency by highlighting what users might miss",
        "triggers": ["limited time", "exclusive", "last chance", "ending soon"]
    },
    {
        "name": "Problem/Solution",
        "description": "Identifies a pain point and presents the product as the solution",
        "triggers": ["struggling with", "tired of", "finally", "the answer to"]
    },
    {
        "name": "Social Proof",
        "description": "Leverages testimonials, reviews, and user numbers",
        "triggers": ["join thousands", "rated #1", "trusted by", "as seen on"]
    },
    {
        "name": "Curiosity Gap",
        "description": "Creates intrigue that compels users to learn more",
        "triggers": ["secret", "discover", "what they don't tell you", "hidden"]
    },
    {
        "name": "Aspirational",
        "description": "Shows the ideal outcome or lifestyle the product enables",
        "triggers": ["imagine", "become", "transform", "achieve"]
    },
    {
        "name": "Value Proposition",
        "description": "Directly states the unique benefit or offer",
        "triggers": ["save", "get", "free", "only $"]
    },
    {
        "name": "Authority/Expert",
        "description": "Positions the brand as an expert or authority",
        "triggers": ["experts say", "proven", "backed by", "recommended by"]
    },
    {
        "name": "Emotional Story",
        "description": "Connects through relatable narratives",
        "triggers": ["when I", "just like you", "my journey", "before I"]
    },
    {
        "name": "Comparison",
        "description": "Highlights advantages over alternatives",
        "triggers": ["unlike", "vs", "better than", "why choose"]
    },
    {
        "name": "Question Hook",
        "description": "Opens with a thought-provoking question",
        "triggers": ["what if", "ever wondered", "did you know", "are you"]
    }
]


class CreativeStrategistAgent:
    """
    AI Agent for analyzing target audience and generating creative hooks.

    This agent:
    1. Analyzes the target audience demographics, psychographics, and behavior
    2. Generates 5-10 different hooks based on proven psychological triggers
    3. Maps hooks to specific audience segments
    4. Provides strategic recommendations for each hook
    """

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o" if OPENROUTER_AVAILABLE else os.getenv("OPENAI_MODEL", "gpt-4o"),
            temperature=0.8
        )
        self.embeddings = OpenAIEmbeddings()
        logger.info(f"[CreativeStrategistAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

        self.audience_analysis_prompt = ChatPromptTemplate.from_template("""
You are an expert marketing strategist specializing in Meta (Facebook/Instagram) advertising.

Analyze the target audience for this campaign and provide detailed insights:

CAMPAIGN BRIEF:
Name: {campaign_name}
Objective: {objective}
Product/Service: {product_description}
Target Audience: {target_audience}
Industry: {industry}
Keywords: {keywords}

MARKET RESEARCH (if available):
{market_research}

Provide a comprehensive audience analysis in JSON format:
{{
    "demographics": {{
        "age_range": "e.g., 25-45",
        "gender": "e.g., All/Male/Female",
        "location": "e.g., Urban areas, US",
        "income_level": "e.g., Middle to upper-middle class"
    }},
    "psychographics": {{
        "values": ["list of core values"],
        "interests": ["list of interests"],
        "lifestyle": "description of lifestyle",
        "personality_traits": ["list of traits"]
    }},
    "pain_points": ["list of 3-5 main pain points"],
    "desires": ["list of 3-5 main desires/aspirations"],
    "buying_triggers": ["what makes them buy"],
    "objections": ["common objections to address"],
    "content_preferences": {{
        "platforms": ["preferred social platforms"],
        "content_types": ["video/image/carousel/etc"],
        "tone": "formal/casual/playful/etc"
    }},
    "competitor_awareness": "description of their awareness of alternatives"
}}

Return ONLY valid JSON, no markdown or additional text.
""")

        self.hook_generation_prompt = ChatPromptTemplate.from_template("""
You are a world-class creative director for Meta advertising campaigns.

Based on the audience analysis and campaign brief, generate {num_hooks} unique creative hooks.

CAMPAIGN BRIEF:
Name: {campaign_name}
Objective: {objective}
Product/Service: {product_description}

AUDIENCE ANALYSIS:
{audience_analysis}

AVAILABLE HOOK TYPES TO CONSIDER:
{hook_types}

Generate {num_hooks} hooks that will resonate with this audience. For each hook, provide:

{{
    "hooks": [
        {{
            "hook_type": "One of the hook types above",
            "hook_text": "The actual hook text (first 3-5 seconds of the ad)",
            "angle": "The creative angle this hook takes",
            "target_segment": "Which audience segment this targets",
            "emotion_triggered": "Primary emotion this evokes",
            "visual_suggestion": "Brief visual concept to pair with this hook",
            "why_it_works": "Strategic reasoning for this hook",
            "a_b_test_variant": "A slight variation to test against"
        }}
    ]
}}

Create diverse hooks using different hook types. Make them specific to the product and audience.
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

    async def analyze_audience(
        self,
        campaign: Campaign,
        research: Optional[MarketResearch] = None
    ) -> Dict[str, Any]:
        """
        Analyze the target audience for a campaign.

        Args:
            campaign: Campaign object
            research: Optional MarketResearch object

        Returns:
            Dict containing audience analysis
        """
        # Build market research context
        if research:
            market_research = f"""
Competitor Analysis: {research.competitor_analysis or 'Not available'}
Audience Insights: {research.audience_insights or 'Not available'}
Trends: {research.trend_data or 'Not available'}
Recommendations: {research.recommendations or 'Not available'}
"""
        else:
            market_research = "No market research available."

        prompt_data = {
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "product_description": campaign.product_description or "Not specified",
            "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "Not specified",
            "industry": campaign.industry if hasattr(campaign, 'industry') else "General",
            "keywords": ", ".join(campaign.keywords) if campaign.keywords else "Not specified",
            "market_research": market_research
        }

        chain = self.audience_analysis_prompt | self.llm | StrOutputParser()
        response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"error": "Failed to parse audience analysis", "raw": cleaned}

    async def generate_hooks(
        self,
        campaign: Campaign,
        audience_analysis: Optional[Dict] = None,
        num_hooks: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Generate creative hooks based on audience analysis.

        Args:
            campaign: Campaign object
            audience_analysis: Optional pre-computed audience analysis
            num_hooks: Number of hooks to generate (5-10 recommended)

        Returns:
            List of hook dictionaries
        """
        db = SessionLocal()
        try:
            # Get audience analysis if not provided
            if not audience_analysis:
                research = db.query(MarketResearch).filter(
                    MarketResearch.campaign_id == campaign.id
                ).order_by(MarketResearch.created_at.desc()).first()
                audience_analysis = await self.analyze_audience(campaign, research)

            # Format hook types for prompt
            hook_types_text = "\n".join([
                f"- {h['name']}: {h['description']}" for h in HOOK_TYPES
            ])

            prompt_data = {
                "campaign_name": campaign.name,
                "objective": campaign.objective,
                "product_description": campaign.product_description or "Not specified",
                "audience_analysis": json.dumps(audience_analysis, indent=2),
                "hook_types": hook_types_text,
                "num_hooks": num_hooks
            }

            chain = self.hook_generation_prompt | self.llm | StrOutputParser()
            response = await chain.ainvoke(prompt_data)

            cleaned = self._clean_json_response(response)
            try:
                hooks_data = json.loads(cleaned)
                hooks = hooks_data.get('hooks', [])
            except json.JSONDecodeError:
                hooks = []

            # Store hooks as CreativeAngles in database
            saved_hooks = []
            for hook in hooks:
                # Generate embedding for semantic search
                hook_text = f"{hook.get('hook_text', '')} {hook.get('angle', '')} {hook.get('target_segment', '')}"
                embedding = self.embeddings.embed_query(hook_text)

                creative_angle = CreativeAngle(
                    campaign_id=campaign.id,
                    angle_name=hook.get('hook_type', 'Custom Hook'),
                    value_proposition=hook.get('hook_text', ''),
                    emotion_target=hook.get('emotion_triggered', ''),
                    visual_direction=hook.get('visual_suggestion', ''),
                    reasoning=hook.get('why_it_works', ''),
                    metadata={
                        "target_segment": hook.get('target_segment'),
                        "angle": hook.get('angle'),
                        "a_b_variant": hook.get('a_b_test_variant')
                    },
                    embedding=embedding
                )
                db.add(creative_angle)
                db.flush()

                saved_hooks.append({
                    "id": str(creative_angle.id),
                    "campaign_id": str(campaign.id),
                    "hook_type": hook.get('hook_type'),
                    "hook_text": hook.get('hook_text'),
                    "angle": hook.get('angle'),
                    "target_segment": hook.get('target_segment'),
                    "emotion_triggered": hook.get('emotion_triggered'),
                    "visual_suggestion": hook.get('visual_suggestion'),
                    "why_it_works": hook.get('why_it_works'),
                    "a_b_test_variant": hook.get('a_b_test_variant')
                })

            db.commit()
            return saved_hooks

        finally:
            db.close()

    async def full_strategy(
        self,
        campaign: Campaign,
        num_hooks: int = 8
    ) -> Dict[str, Any]:
        """
        Generate complete creative strategy with audience analysis and hooks.

        Args:
            campaign: Campaign object
            num_hooks: Number of hooks to generate

        Returns:
            Dict containing audience analysis and hooks
        """
        db = SessionLocal()
        try:
            research = db.query(MarketResearch).filter(
                MarketResearch.campaign_id == campaign.id
            ).order_by(MarketResearch.created_at.desc()).first()

            audience_analysis = await self.analyze_audience(campaign, research)
            hooks = await self.generate_hooks(campaign, audience_analysis, num_hooks)

            return {
                "campaign_id": str(campaign.id),
                "campaign_name": campaign.name,
                "audience_analysis": audience_analysis,
                "hooks": hooks,
                "total_hooks": len(hooks)
            }
        finally:
            db.close()


# Convenience function for direct use
async def generate_creative_strategy(campaign_id: str, num_hooks: int = 8) -> Dict[str, Any]:
    """
    Generate complete creative strategy for a campaign.

    Args:
        campaign_id: UUID of the campaign
        num_hooks: Number of hooks to generate

    Returns:
        Dict containing strategy data
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        agent = CreativeStrategistAgent()
        return await agent.full_strategy(campaign, num_hooks)
    finally:
        db.close()

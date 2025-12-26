# Agents Module - AI Agents for Ad Campaign Generation
"""
This module contains AI agents for generating Meta advertising campaigns:

1. CreativeStrategistAgent - Analyzes target audience and generates creative hooks
2. CopywriterAgent - Writes Meta-specific ad copy (Primary Text, Headline, CTA)
3. VisualDirectorAgent - Creates image/video prompts from creative hooks
4. MarketResearchAgent - Conducts market and competitor research
5. AdCreativeAgent - Orchestrates the full creative generation pipeline
"""

from .router import agents_router
from .ad_creative_agent import AdCreativeAgent
from .creative_strategist_agent import CreativeStrategistAgent, generate_creative_strategy
from .copywriter_agent import CopywriterAgent, generate_copy_for_angle, generate_all_campaign_copy
from .visual_director_agent import VisualDirectorAgent, generate_visuals_for_angle, generate_all_visuals
from .market_research_agent import MarketResearchAgent
from .creative_angles_agent import CreativeAnglesAgent
from .ad_copy_agent import AdCopyAgent

__all__ = [
    "agents_router",
    "AdCreativeAgent",
    "CreativeStrategistAgent",
    "CopywriterAgent",
    "VisualDirectorAgent",
    "MarketResearchAgent",
    "CreativeAnglesAgent",
    "AdCopyAgent",
    "generate_creative_strategy",
    "generate_copy_for_angle",
    "generate_all_campaign_copy",
    "generate_visuals_for_angle",
    "generate_all_visuals"
]

"""System-prompt catalog for Meta and advertising agents (excludes chatbots)."""

from modules.openclaw.agent_service import (
    EVALUATOR_AGENT_PROMPT,
    GOAL_AGENT_PROMPT,
    IMAGE_AGENT_PROMPT,
    IMAGE_SET_AGENT_PROMPT,
    PLANNER_AGENT_PROMPT,
)
from modules.market_research.service import _RESEARCH_AGENT_SYSTEM
from modules.openrouter.service import (
    CONTENT_ANALYSIS_SYSTEM_PROMPTS,
    FACEBOOK_AD_TYPES,
    facebook_ad_copy_system_prompt,
)
from modules.optimizer.calibration import CALIBRATION_PROMPT


def marketing_agent_prompts():
    prompts = [
        {"agent": "Strategic Goal Setter", "category": "Campaign strategy", "prompt": GOAL_AGENT_PROMPT,
         "source": "OpenClaw advertising goal agent"},
        {"agent": "Campaign Planner", "category": "Campaign strategy", "prompt": PLANNER_AGENT_PROMPT,
         "source": "OpenClaw advertising planner agent"},
        {"agent": "Campaign Evaluator", "category": "Campaign strategy", "prompt": EVALUATOR_AGENT_PROMPT,
         "source": "OpenClaw advertising evaluator agent"},
        {"agent": "Ad Image Art Director", "category": "Creative", "prompt": IMAGE_AGENT_PROMPT,
         "source": "OpenClaw ads-image agent"},
        {"agent": "Campaign Image Art Director", "category": "Creative", "prompt": IMAGE_SET_AGENT_PROMPT,
         "source": "OpenClaw ads-image agent"},
        {"agent": "Market Research Analyst", "category": "Research", "prompt": _RESEARCH_AGENT_SYSTEM,
         "source": "OpenClaw ads-research agent"},
        {"agent": "Ad Optimizer Calibrator", "category": "Optimization", "prompt": CALIBRATION_PROMPT,
         "source": "OpenClaw calibrator agent"},
    ]

    for ad_type in FACEBOOK_AD_TYPES:
        prompts.append({
            "agent": f"Facebook Ad Copywriter ({ad_type})",
            "category": "Ad copy",
            "prompt": facebook_ad_copy_system_prompt(ad_type, "professional"),
            "source": "Shopivell Meta ad copy service; tone is selected per request",
        })
    for analysis_type, prompt in CONTENT_ANALYSIS_SYSTEM_PROMPTS.items():
        prompts.append({
            "agent": f"Marketing Content Analyst ({analysis_type})",
            "category": "Marketing analysis",
            "prompt": prompt,
            "source": "Shopivell Meta marketing content analysis",
        })
    return prompts

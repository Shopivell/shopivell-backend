# dayparting_service.py - AI-driven ad scheduling / dayparting
"""
Automatically determines optimal ad schedules based on business type and industry.
Used by the agent pipeline when campaigns use lifetime budgets.

Meta API requires:
- Lifetime budget (not daily budget) for ad scheduling
- ad_schedule is set at ad set level
- Schedule uses 1-hour blocks, days 0-6 (Sunday=0, Monday=1, ..., Saturday=6)
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Industry-specific default schedules
# Days: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
INDUSTRY_SCHEDULES: Dict[str, List[Dict[str, Any]]] = {
    # B2B: Weekdays business hours
    "b2b_default": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 8, "end_hour": 18}
    ],
    # B2B Tech/SaaS: Extended weekday hours (decision makers browse evenings)
    "b2b_tech": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 7, "end_hour": 21},
        {"days": [6], "start_minute": 0, "end_minute": 0,
         "start_hour": 9, "end_hour": 14}
    ],
    # E-commerce/Retail: Peak shopping hours including evenings and weekends
    "ecommerce": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 9, "end_hour": 22},
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 10, "end_hour": 21}
    ],
    # Food/Restaurant: Meal decision times
    "food_restaurant": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 10, "end_hour": 14},  # Lunch decisions
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 16, "end_hour": 21},  # Dinner decisions
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 9, "end_hour": 21}   # Weekend all-day
    ],
    # Services (plumbing, repair, etc.): Business hours + early morning
    "local_services": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 7, "end_hour": 19},
        {"days": [6], "start_minute": 0, "end_minute": 0,
         "start_hour": 8, "end_hour": 16},
        {"days": [0], "start_minute": 0, "end_minute": 0,
         "start_hour": 9, "end_hour": 14}
    ],
    # Real estate: Evenings + weekends (when people browse)
    "real_estate": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 12, "end_hour": 21},
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 9, "end_hour": 20}
    ],
    # Education: Afternoon + evening (after school/work)
    "education": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 14, "end_hour": 22},
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 10, "end_hour": 20}
    ],
    # Health/Fitness: Early morning + evening (gym goers)
    "health_fitness": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 5, "end_hour": 9},
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 16, "end_hour": 22},
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 6, "end_hour": 14}
    ],
    # Entertainment/Events: Evenings + weekends
    "entertainment": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 17, "end_hour": 23},
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 10, "end_hour": 23}
    ],
    # Fashion/Apparel: Lunch + evening browsing
    "fashion": [
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 11, "end_hour": 14},
        {"days": [1, 2, 3, 4, 5], "start_minute": 0, "end_minute": 0,
         "start_hour": 18, "end_hour": 23},
        {"days": [0, 6], "start_minute": 0, "end_minute": 0,
         "start_hour": 10, "end_hour": 22}
    ],
    # 24/7 - No schedule restriction (runs all the time)
    "always_on": [],
}

# Map common business types/industries to schedule profiles
INDUSTRY_MAPPING: Dict[str, str] = {
    # B2B
    "technology": "b2b_tech", "saas": "b2b_tech", "software": "b2b_tech",
    "it services": "b2b_tech", "cloud": "b2b_tech", "fintech": "b2b_tech",
    "consulting": "b2b_default", "legal": "b2b_default", "accounting": "b2b_default",
    "finance": "b2b_default", "banking": "b2b_default", "insurance": "b2b_default",
    "manufacturing": "b2b_default", "logistics": "b2b_default", "b2b": "b2b_default",
    "professional services": "b2b_default", "marketing": "b2b_default",
    "security": "b2b_tech", "surveillance": "b2b_tech",

    # E-commerce / Retail
    "ecommerce": "ecommerce", "e-commerce": "ecommerce", "retail": "ecommerce",
    "online store": "ecommerce", "marketplace": "ecommerce", "shop": "ecommerce",
    "grocery": "ecommerce", "electronics": "ecommerce",

    # Food
    "restaurant": "food_restaurant", "food": "food_restaurant", "cafe": "food_restaurant",
    "catering": "food_restaurant", "delivery": "food_restaurant", "bakery": "food_restaurant",

    # Local services
    "plumbing": "local_services", "repair": "local_services", "appliance": "local_services",
    "cleaning": "local_services", "construction": "local_services",
    "hvac": "local_services", "electrical": "local_services", "handyman": "local_services",
    "auto repair": "local_services", "mechanic": "local_services",
    "salon": "local_services", "spa": "local_services", "beauty": "local_services",

    # Real estate
    "real estate": "real_estate", "property": "real_estate", "rental": "real_estate",
    "accommodation": "real_estate", "hotel": "real_estate", "airbnb": "real_estate",

    # Education
    "education": "education", "training": "education", "tutoring": "education",
    "school": "education", "university": "education", "courses": "education",
    "e-learning": "education",

    # Health / Fitness
    "health": "health_fitness", "fitness": "health_fitness", "gym": "health_fitness",
    "wellness": "health_fitness", "medical": "health_fitness", "healthcare": "health_fitness",
    "pharmacy": "health_fitness", "yoga": "health_fitness",

    # Entertainment
    "entertainment": "entertainment", "events": "entertainment", "music": "entertainment",
    "gaming": "entertainment", "nightlife": "entertainment", "cinema": "entertainment",

    # Fashion
    "fashion": "fashion", "clothing": "fashion", "apparel": "fashion",
    "shoes": "fashion", "accessories": "fashion", "jewelry": "fashion",
}


def get_schedule_for_industry(industry: str, business_type: str = None) -> List[Dict[str, Any]]:
    """
    Get the optimal ad schedule for a given industry/business type.

    Args:
        industry: Industry name (e.g., "technology", "restaurant", "ecommerce")
        business_type: Optional business type for more specific matching

    Returns:
        List of ad_schedule entries for Meta API, or empty list for always-on
    """
    # Try business_type first, then industry
    for term in [business_type, industry]:
        if not term:
            continue
        term_lower = term.lower().strip()

        # Direct match
        if term_lower in INDUSTRY_MAPPING:
            profile = INDUSTRY_MAPPING[term_lower]
            schedule = INDUSTRY_SCHEDULES.get(profile, [])
            logger.info(f"[Dayparting] Matched '{term}' → profile '{profile}' ({len(schedule)} blocks)")
            return schedule

        # Partial match
        for keyword, profile in INDUSTRY_MAPPING.items():
            if keyword in term_lower or term_lower in keyword:
                schedule = INDUSTRY_SCHEDULES.get(profile, [])
                logger.info(f"[Dayparting] Partial match '{term}' → '{keyword}' → profile '{profile}'")
                return schedule

    # Default: ecommerce schedule (broad and safe)
    logger.info(f"[Dayparting] No match for industry='{industry}', business_type='{business_type}' → using ecommerce default")
    return INDUSTRY_SCHEDULES["ecommerce"]


def build_adset_schedule_params(
    schedule: List[Dict[str, Any]],
    lifetime_budget_cents: int,
    campaign_duration_days: int = 30,
    timezone: str = "USER_TIMEZONE"
) -> Dict[str, Any]:
    """
    Build the Meta API parameters needed for a scheduled ad set.

    Args:
        schedule: List of schedule blocks from get_schedule_for_industry()
        lifetime_budget_cents: Total budget in cents for the lifetime of the ad set
        campaign_duration_days: How many days the campaign runs
        timezone: "USER_TIMEZONE" or specific timezone

    Returns:
        Dict of additional params to merge into meta_adset_data
    """
    from datetime import datetime, timedelta

    params: Dict[str, Any] = {}

    if not schedule:
        # No schedule = always on, still use lifetime budget
        params["lifetime_budget"] = str(lifetime_budget_cents)
        end_time = datetime.utcnow() + timedelta(days=campaign_duration_days)
        params["end_time"] = end_time.strftime("%Y-%m-%dT%H:%M:%S+0000")
        return params

    # Lifetime budget required for scheduling
    params["lifetime_budget"] = str(lifetime_budget_cents)

    # End time required for lifetime budget
    end_time = datetime.utcnow() + timedelta(days=campaign_duration_days)
    params["end_time"] = end_time.strftime("%Y-%m-%dT%H:%M:%S+0000")

    # Pacing type for scheduled delivery
    params["pacing_type"] = json.dumps(["day_parting"])

    # Ad schedule - Meta expects this format
    params["adset_schedule"] = json.dumps(schedule)

    logger.info(
        f"[Dayparting] Built schedule params: {len(schedule)} blocks, "
        f"budget={lifetime_budget_cents} cents, duration={campaign_duration_days} days"
    )

    return params


def daily_budget_to_lifetime(daily_budget_usd: float, duration_days: int = 30) -> int:
    """Convert daily budget (USD) to lifetime budget in cents."""
    return int(daily_budget_usd * duration_days * 100)


async def generate_schedule_with_ai(
    industry: str,
    business_type: str,
    business_description: str,
    target_countries: List[str] = None,
    llm=None
) -> Dict[str, Any]:
    """
    Use LLM to generate an optimal ad schedule for a business.

    Falls back to rule-based schedule if LLM is unavailable.

    Args:
        industry: Business industry
        business_type: Type of business
        business_description: Brief description of the business
        target_countries: Target countries for timezone context
        llm: LangChain LLM instance

    Returns:
        Dict with schedule, reasoning, and profile_used
    """
    # First try rule-based
    rule_schedule = get_schedule_for_industry(industry, business_type)

    if not llm:
        return {
            "schedule": rule_schedule,
            "reasoning": f"Rule-based schedule for {industry}/{business_type}",
            "profile_used": "rule_based",
            "method": "rule_based"
        }

    # Use LLM to refine
    try:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template("""You are a Meta Ads scheduling expert. Determine the optimal ad delivery schedule (dayparting) for this business.

BUSINESS INFO:
- Industry: {industry}
- Business Type: {business_type}
- Description: {business_description}
- Target Countries: {countries}

RULES:
- Meta uses days 0-6 (0=Sunday, 1=Monday, ..., 6=Saturday)
- Hours are 0-23 in the account's timezone
- Each block has: days (list of ints), start_hour, end_hour, start_minute (always 0), end_minute (always 0)
- Focus on when the TARGET AUDIENCE is most likely to engage/convert
- Consider the business type: B2B = business hours, B2C = evenings/weekends, etc.
- Consider the target countries' typical daily patterns

Output ONLY valid JSON array of schedule blocks. Example:
[
  {{"days": [1, 2, 3, 4, 5], "start_hour": 9, "end_hour": 18, "start_minute": 0, "end_minute": 0}},
  {{"days": [6], "start_hour": 10, "end_hour": 15, "start_minute": 0, "end_minute": 0}}
]

Include a brief reasoning comment as the first element of the response, then the JSON array.
Format: REASONING: <one sentence explanation>
SCHEDULE: <json array>""")

        from modules.openrouter.context import set_ai_context
        chain = prompt | llm | StrOutputParser()
        with set_ai_context(agent_name="dayparting"):
            response = await chain.ainvoke({
                "industry": industry,
                "business_type": business_type,
                "business_description": business_description[:500],
                "countries": ", ".join(target_countries or ["Global"])
            })

        # Parse response
        reasoning = ""
        schedule_json = response

        if "REASONING:" in response:
            parts = response.split("SCHEDULE:", 1)
            reasoning = parts[0].replace("REASONING:", "").strip()
            if len(parts) > 1:
                schedule_json = parts[1].strip()

        # Try to parse JSON
        import re
        json_match = re.search(r'\[[\s\S]*\]', schedule_json)
        if json_match:
            ai_schedule = json.loads(json_match.group())

            # Validate schedule format
            valid = True
            for block in ai_schedule:
                if not all(k in block for k in ["days", "start_hour", "end_hour"]):
                    valid = False
                    break
                # Ensure start_minute and end_minute exist
                block.setdefault("start_minute", 0)
                block.setdefault("end_minute", 0)

            if valid:
                logger.info(f"[Dayparting] AI-generated schedule: {len(ai_schedule)} blocks")
                return {
                    "schedule": ai_schedule,
                    "reasoning": reasoning,
                    "profile_used": "ai_generated",
                    "method": "ai"
                }

        logger.warning("[Dayparting] AI response parsing failed, falling back to rule-based")
    except Exception as e:
        logger.error(f"[Dayparting] AI schedule generation error: {e}")

    return {
        "schedule": rule_schedule,
        "reasoning": f"Rule-based schedule for {industry}/{business_type} (AI fallback)",
        "profile_used": "rule_based_fallback",
        "method": "rule_based"
    }

# creative_strategist_agent.py - AI Agent for Creative Strategy & Hook Generation
"""
Enhanced Creative Strategist Agent with Meta Audience Targeting.

Features:
1. Analyzes target audience demographics, psychographics, and behavior
2. Generates Meta/Facebook audience segments (e.g., "Corporate Finance Departments")
3. Generates Meta interest targeting tags (e.g., "Payment system", "Mobile payment")
4. Creates creative hooks based on psychological triggers
5. Supports direct URL analysis without requiring a campaign
6. Integrates with Market Research Agent for real website data

Uses OpenRouter API via ChatOpenRouter adapter for AI generation.
"""

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

        # NEW: Meta Audience Targeting Prompt
        self.meta_audience_prompt = ChatPromptTemplate.from_template("""
You are an expert Meta (Facebook/Instagram) Ads targeting specialist.

Based on the business information and website data below, generate comprehensive Meta audience targeting recommendations.

BUSINESS INFORMATION:
Company Name: {company_name}
Industry: {industry}
Services/Products: {services}
Value Propositions: {value_props}
Target Audiences from Website: {website_audiences}
Geographic Coverage: {location}

WEBSITE CONTENT SUMMARY:
{website_content}

Generate detailed Meta Ads audience targeting in this exact JSON format:
{{
    "audience_segments": [
        {{
            "name": "Segment name (e.g., Corporate Finance Departments)",
            "description": "Brief description of this audience segment",
            "size_estimate": "Small/Medium/Large",
            "priority": "Primary/Secondary/Tertiary"
        }}
    ],
    "demographics": {{
        "age_range": {{
            "min": 18,
            "max": 65
        }},
        "gender": "All/Male/Female",
        "locations": ["List of target locations/countries"],
        "languages": ["List of languages"]
    }},
    "interest_tags": {{
        "core_interests": ["Primary interests directly related to the business - 8-12 tags"],
        "technology_interests": ["Technology and software related interests - 5-8 tags"],
        "business_interests": ["Business and professional B2B interests - 5-8 tags"],
        "consumer_interests": ["B2C/residential interests - home owners, families, personal users - 5-8 tags"],
        "behavioral_interests": ["Behavioral and mindset interests - 4-6 tags"],
        "complementary_interests": ["Related but broader interests - 4-6 tags"]
    }},
    "job_titles": ["Relevant job titles to target - 5-10 titles"],
    "industries": ["Industries to target - 3-5 industries"],
    "behaviors": {{
        "purchase_behavior": ["Purchase-related behaviors"],
        "device_usage": ["Device and platform behaviors"],
        "business_behaviors": ["B2B behaviors if applicable"]
    }},
    "custom_audience_suggestions": {{
        "website_visitors": "Suggestion for website visitor audience",
        "lookalike_seeds": ["Suggestions for lookalike audience seeds"],
        "email_lists": "Suggestion for email list targeting"
    }},
    "exclusions": {{
        "interests_to_exclude": ["Interests to exclude"],
        "audiences_to_exclude": ["Audience types to exclude"]
    }},
    "ad_set_recommendations": [
        {{
            "name": "Ad Set name",
            "target_segment": "Which segment this targets",
            "interests_combination": ["Specific interests for this ad set"],
            "estimated_reach": "Estimated reach description"
        }}
    ]
}}

IMPORTANT GUIDELINES FOR INTEREST TAGS:
1. Interest tags MUST be actual Facebook/Meta interests that exist in their targeting system
2. Generate 25-40 total interest tags across all categories
3. Be specific to the business industry and offerings
4. Include both B2B and B2C targeting if applicable
5. Suggest realistic job titles that exist on Facebook
6. Consider the geographic market (Zimbabwe/Africa focus if applicable)

GUARDRAILS FOR INTEREST TAG CATEGORIES:
- core_interests: Include interests directly related to the business's products/services
  Examples for fintech: Payment systems, Mobile banking, Digital wallets
  Examples for security: CCTV, Access control, Surveillance systems

- technology_interests: Include relevant software, platforms, and tech interests
  Examples: Cloud computing, SaaS, IoT, AI, specific software names

- business_interests: Include B2B, professional, and industry interests
  Examples: Business networking, LinkedIn, Procurement, Consulting, Enterprise software

- behavioral_interests: Include mindset, career, and behavioral interests
  Examples: Leadership, Entrepreneurship, Innovation, Professional development

- complementary_interests: Include broader related interests that expand reach
  Examples: Industry publications, trade shows, professional associations
  For B2C: Home improvement, Home security, Property investment, Real estate, Family safety

GUARDRAILS FOR AUDIENCE SEGMENTS:
- Generate 5-8 distinct audience segments
- Each segment should represent a real buyer persona
- IMPORTANT: Always consider BOTH B2B and B2C audiences:
  - B2B: Corporate decision-makers, business owners, facility managers, etc.
  - B2C: Individual consumers, home owners, families, property owners, etc.
- For security/home services: MUST include Home Owners, Property Owners, Residential Customers
- For financial services: MUST include Individual Consumers, Personal Banking Users
- Include decision-maker roles (e.g., "Corporate Finance Directors", "IT Security Managers")
- Include end-user/consumer roles (e.g., "Home Owners", "Tech-Savvy Consumers", "Property Owners")
- Consider the buying journey stage for each segment
- Don't over-index on corporate - residential/consumer markets are often larger

GUARDRAILS FOR JOB TITLES:
- Include C-level executives relevant to the industry
- Include department heads and managers
- Include specialist roles
- Include small business owner variations

Return ONLY valid JSON, no markdown or additional text.
""")

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

{performance_insights}

Return ONLY valid JSON, no markdown.
""")

    def _get_hook_performance_insights(self) -> str:
        """Query past creative test results to learn which hook types perform best."""
        db = SessionLocal()
        try:
            from .models import CreativeAngle as CAModel
            from .models import CreativeTest, CreativeTestVariant

            tests = db.query(CreativeTest).filter(
                CreativeTest.status == "completed",
                CreativeTest.winner_ad_id.isnot(None)
            ).order_by(CreativeTest.completed_at.desc()).limit(10).all()

            if not tests:
                return ""

            winning_emotions = []
            for test in tests:
                results = test.results or {}
                winner = results.get("winner", {})
                if winner.get("is_original"):
                    continue
                headline = winner.get("headline", "")
                if headline:
                    angles = db.query(CAModel).filter(
                        CAModel.emotion_target.isnot(None)
                    ).order_by(CAModel.created_at.desc()).limit(20).all()
                    for a in angles:
                        if a.emotion_target:
                            winning_emotions.append(a.emotion_target)

            if not winning_emotions:
                return ""

            from collections import Counter
            top_emotions = Counter(winning_emotions).most_common(3)
            insights = "HOOK PERFORMANCE INSIGHTS (from past A/B tests):\n"
            insights += "Top-performing emotion targets: " + ", ".join([f"{e} ({c}x)" for e, c in top_emotions])
            insights += "\nPrioritize hooks using these emotion types."
            return insights

        except Exception:
            return ""
        finally:
            db.close()

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

    async def generate_meta_audience(
        self,
        website_data: Dict[str, Any],
        company_name: str = None
    ) -> Dict[str, Any]:
        """
        Generate Meta/Facebook audience targeting from website research data.

        Args:
            website_data: Data from market research agent (extracted_data, research_summary)
            company_name: Optional company name override

        Returns:
            Dict containing audience segments and interest tags
        """
        extracted = website_data.get("extracted_data", {})
        summary = website_data.get("research_summary", {})

        # Extract key information
        company = company_name or extracted.get("company_info", {}).get("name") or summary.get("company_name", "Unknown")
        industry = extracted.get("company_info", {}).get("industry") or summary.get("industry", "General")
        location = extracted.get("company_info", {}).get("geographic_coverage") or summary.get("geographic_coverage", "Global")

        # Get services
        services = []
        for svc in extracted.get("services_products", []):
            if isinstance(svc, dict):
                services.append(f"{svc.get('name', '')}: {svc.get('description', '')}")
            else:
                services.append(str(svc))

        # Get value propositions
        value_props = extracted.get("value_propositions", [])

        # Get target audiences from website
        website_audiences = extracted.get("target_audiences", [])

        # Build content summary
        raw_content = website_data.get("raw_content", {})
        content_summary = raw_content.get("main_page", "")[:3000] if isinstance(raw_content, dict) else ""

        prompt_data = {
            "company_name": company,
            "industry": industry,
            "services": "\n".join(services[:15]) if services else "Not specified",
            "value_props": ", ".join(value_props[:10]) if value_props else "Not specified",
            "website_audiences": ", ".join(website_audiences) if website_audiences else "Not specified",
            "location": location,
            "website_content": content_summary
        }

        logger.info(f"[CreativeStrategistAgent] Generating Meta audience for: {company}")

        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"})
        chain = self.meta_audience_prompt | json_llm | StrOutputParser()
        with set_ai_context(agent_name="creative_strategist"):
            response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            audience_data = json.loads(cleaned)

            return {
                "success": True,
                "company_name": company,
                "industry": industry,
                "audience_targeting": audience_data
            }

        except json.JSONDecodeError as e:
            logger.error(f"[CreativeStrategistAgent] Failed to parse audience JSON: {e}")
            return {
                "success": False,
                "error": "Failed to parse audience analysis",
                "raw_response": cleaned[:1000]
            }

    async def generate_meta_audience_validated(
        self,
        website_data: Dict[str, Any],
        access_token: str,
        ad_account_id: str,
        countries: List[str] = None,
        company_name: str = None
    ) -> Dict[str, Any]:
        """
        Generate Meta audience with interest validation and reach estimation.

        Extends generate_meta_audience by:
        1. Generating audience via LLM
        2. Validating all interest_tags against Meta's Interest Search API
        3. Getting reach estimates for the validated targeting spec

        Args:
            website_data: Data from market research agent
            access_token: Meta API access token
            ad_account_id: Meta ad account ID (e.g., "act_123456")
            countries: Target countries (e.g., ["ZW"]). Extracted from audience if not provided.
            company_name: Optional company name override

        Returns:
            Dict with audience_targeting + validation results + reach estimate
        """
        MAX_AUDIENCE_RETRIES = 2  # Retry up to 2 times if <30% interests validate

        for attempt in range(1, MAX_AUDIENCE_RETRIES + 2):  # +2 for initial + retries
            # Step 1: Generate audience via LLM
            if attempt == 1:
                result = await self.generate_meta_audience(website_data, company_name)
            else:
                # Retry with feedback about what failed
                logger.info(
                    f"[CreativeStrategistAgent] Audience retry {attempt - 1}/{MAX_AUDIENCE_RETRIES}: "
                    f"only {prev_valid_count}/{prev_total_count} interests were valid on Meta. "
                    f"Regenerating with broader terms."
                )
                # Augment website_data with retry hint
                retry_data = dict(website_data)
                retry_hint = (
                    f"\n\nIMPORTANT RETRY CONTEXT: A previous attempt generated {prev_total_count} interest tags "
                    f"but only {prev_valid_count} were valid on Meta's ad platform. "
                    f"Invalid tags that failed: {', '.join(prev_invalid_tags[:15])}. "
                    f"Please generate BROADER, more commonly used interest tags that are more likely to exist "
                    f"in Meta's targeting system. Prefer well-known brands, broad categories, and popular topics "
                    f"over niche or overly specific terms."
                )
                raw_content = retry_data.get("raw_content", {})
                if isinstance(raw_content, dict):
                    main_page = raw_content.get("main_page", "")
                    raw_content["main_page"] = main_page + retry_hint
                    retry_data["raw_content"] = raw_content
                else:
                    retry_data["raw_content"] = {"main_page": retry_hint}

                result = await self.generate_meta_audience(retry_data, company_name)

            if not result.get("success"):
                return result

            audience_data = result.get("audience_targeting", {})

            # Step 2: Extract interest tags from LLM response
            interest_tags = []
            interest_categories = audience_data.get("interest_tags", {})
            if isinstance(interest_categories, dict):
                for category, tags in interest_categories.items():
                    if isinstance(tags, list):
                        interest_tags.extend(tags)
            elif isinstance(interest_categories, list):
                interest_tags = interest_categories

            if not interest_tags:
                logger.warning("[CreativeStrategistAgent] No interest tags found in LLM response")
                return result

            # Step 3: Validate interests against Meta API
            try:
                from modules.marketing.meta_targeting_service import MetaTargetingService
                targeting_service = MetaTargetingService(access_token=access_token)

                # Extract countries from audience data if not provided
                if not countries:
                    demographics = audience_data.get("demographics", {})
                    locations = demographics.get("locations", demographics.get("countries", []))
                    if isinstance(locations, list) and locations:
                        countries = locations
                    else:
                        countries = ["US"]  # Fallback

                # Extract age range from demographics
                demographics = audience_data.get("demographics", {})
                age_min = demographics.get("age_min", demographics.get("min_age", 18))
                age_max = demographics.get("age_max", demographics.get("max_age", 65))

                logger.info(f"[CreativeStrategistAgent] Validating {len(interest_tags)} interest tags against Meta API (attempt {attempt})")

                validation_result = targeting_service.validate_and_estimate(
                    ad_account_id=ad_account_id,
                    interest_tags=interest_tags,
                    countries=countries,
                    age_min=age_min,
                    age_max=age_max
                )

                # Update interest_tags with validated ones
                validated_interests = validation_result["validation"]["validated"]
                invalid_tags = validation_result["validation"].get("invalid", [])

                # Check if we need to retry — less than 30% validated
                valid_ratio = len(validated_interests) / len(interest_tags) if interest_tags else 0

                if valid_ratio < 0.3 and attempt <= MAX_AUDIENCE_RETRIES:
                    # Store info for retry
                    prev_valid_count = len(validated_interests)
                    prev_total_count = len(interest_tags)
                    prev_invalid_tags = invalid_tags
                    logger.warning(
                        f"[CreativeStrategistAgent] Low validation rate: {valid_ratio:.0%} "
                        f"({len(validated_interests)}/{len(interest_tags)}). Retrying..."
                    )
                    continue  # Loop back to regenerate

                if validated_interests:
                    # Replace LLM interest tags with validated Meta interests
                    validated_names = [v["name"] for v in validated_interests]
                    audience_data["validated_interest_tags"] = validated_names
                    audience_data["interest_validation"] = {
                        "original_count": len(interest_tags),
                        "validated_count": len(validated_interests),
                        "invalid": invalid_tags,
                        "suggestions": validation_result["validation"]["suggestions"],
                        "corrected": [
                            {"original": v["original_tag"], "corrected_to": v["name"]}
                            for v in validated_interests if v.get("was_corrected")
                        ],
                        "attempts": attempt
                    }

                # Add reach estimate
                reach = validation_result.get("reach_estimate", {})
                audience_data["reach_estimate"] = {
                    "users_lower_bound": reach.get("users_lower_bound", 0),
                    "users_upper_bound": reach.get("users_upper_bound", 0),
                    "estimate_dau": reach.get("estimate_dau", 0),
                    "estimate_mau": reach.get("estimate_mau", 0),
                }

                # Store the targeting spec for direct use in ad set creation
                audience_data["meta_targeting_spec"] = validation_result.get("targeting_spec", {})

                result["audience_targeting"] = audience_data
                result["interest_validation"] = validation_result["validation"]
                result["interest_validation"]["attempts"] = attempt
                result["reach_estimate"] = validation_result["reach_estimate"]

                logger.info(
                    f"[CreativeStrategistAgent] Validation complete (attempt {attempt}): "
                    f"{len(validated_interests)}/{len(interest_tags)} interests valid, "
                    f"reach: {reach.get('users_lower_bound', 0):,}-{reach.get('users_upper_bound', 0):,}"
                )

            except Exception as e:
                logger.error(f"[CreativeStrategistAgent] Interest validation failed: {e}")
                result["interest_validation_error"] = str(e)
                # Still return the LLM-generated audience even if validation fails

            return result

        return result

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

        from modules.openrouter.context import set_ai_context
        chain = self.audience_analysis_prompt | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="creative_strategist"):
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

            # Get performance insights from past A/B tests
            perf_insights = self._get_hook_performance_insights()

            prompt_data = {
                "campaign_name": campaign.name,
                "objective": campaign.objective,
                "product_description": campaign.product_description or "Not specified",
                "audience_analysis": json.dumps(audience_analysis, indent=2),
                "hook_types": hook_types_text,
                "num_hooks": num_hooks,
                "performance_insights": perf_insights
            }

            from modules.openrouter.context import set_ai_context
            json_llm = self.llm.bind(response_format={"type": "json_object"})
            chain = self.hook_generation_prompt | json_llm | StrOutputParser()
            with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="creative_strategist"):
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


    async def refine_audience_from_performance(
        self,
        ad_account_id: str,
        access_token: str,
        current_targeting: Dict[str, Any] = None,
        company_name: str = "Unknown"
    ) -> Dict[str, Any]:
        """
        Refine audience targeting based on actual performance data.

        Uses demographic breakdown from Meta Insights to understand
        which age/gender/placement segments convert best, then asks
        the LLM to refine the targeting strategy.

        Called by scheduler every 7 days (Task 9 tiered scheduling).

        Args:
            ad_account_id: Meta ad account ID
            access_token: Meta API access token
            current_targeting: Current targeting spec (optional)
            company_name: Company name for context

        Returns:
            Dict with refined targeting recommendations
        """
        try:
            from modules.marketing.insights_service import get_demographic_breakdown

            # Get demographic performance data
            demographics = get_demographic_breakdown(ad_account_id, access_token, days=7)

            if not demographics.get("success"):
                return {
                    "success": False,
                    "error": "Could not get demographic breakdown",
                    "details": demographics.get("error")
                }

            # Build prompt for LLM refinement
            refinement_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are an expert Meta Ads targeting strategist. Based on real performance data from the last 7 days, refine the audience targeting.

Analyze which age groups, genders, and segments are converting best and recommend adjustments.

Return JSON with:
{{
    "analysis": "Brief analysis of what's working and what's not",
    "recommended_changes": [
        {{"type": "narrow_age", "reason": "...", "new_age_min": 25, "new_age_max": 45}},
        {{"type": "focus_gender", "reason": "...", "gender": "female"}},
        {{"type": "increase_budget_segment", "reason": "...", "segment": "..."}},
        {{"type": "exclude_segment", "reason": "...", "segment": "..."}}
    ],
    "refined_targeting": {{
        "age_min": 25,
        "age_max": 45,
        "genders": [2],
        "notes": "Focus on female 25-45 based on performance data"
    }},
    "confidence": 0.85
}}

Return ONLY valid JSON."""),
                ("human", """Company: {company_name}

Performance Data (Last 7 Days):
- Age Breakdown: {age_breakdown}
- Gender Breakdown: {gender_breakdown}
- Best Performing Age: {best_age}
- Best Performing Gender: {best_gender}

Current Targeting: {current_targeting}

Based on this real data, how should we refine the targeting?""")
            ])

            from modules.openrouter.context import set_ai_context
            chain = refinement_prompt | self.llm | StrOutputParser()

            with set_ai_context(agent_name="creative_strategist"):
                response = await chain.ainvoke({
                    "company_name": company_name,
                    "age_breakdown": json.dumps(demographics.get("age_breakdown", {})),
                    "gender_breakdown": json.dumps(demographics.get("gender_breakdown", {})),
                    "best_age": demographics.get("best_performing_age", "Unknown"),
                    "best_gender": demographics.get("best_performing_gender", "Unknown"),
                    "current_targeting": json.dumps(current_targeting or {})
                })

            cleaned = self._clean_json_response(response)
            try:
                refinement = json.loads(cleaned)
                return {
                    "success": True,
                    "demographics_data": demographics,
                    "refinement": refinement,
                    "company_name": company_name
                }
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "Failed to parse refinement response",
                    "raw_response": cleaned[:500]
                }

        except Exception as e:
            logger.error(f"[CreativeStrategistAgent] Performance refinement failed: {e}")
            return {"success": False, "error": str(e)}


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


async def generate_audience_from_url(url: str, include_hooks: bool = False, num_hooks: int = 5) -> Dict[str, Any]:
    """
    Generate Meta audience targeting directly from a website URL.

    This function:
    1. Uses Market Research Agent to scrape and analyze the website
    2. Generates detailed audience segments for Meta Ads
    3. Generates Facebook interest targeting tags
    4. Optionally generates creative hooks

    Args:
        url: Website URL to analyze
        include_hooks: Whether to also generate creative hooks
        num_hooks: Number of hooks to generate (if include_hooks=True)

    Returns:
        Dict containing:
        - audience_segments: List of target audience segments
        - demographics: Age, gender, location targeting
        - interest_tags: Categorized Facebook interest tags
        - job_titles: Relevant job titles to target
        - ad_set_recommendations: Ready-to-use ad set configurations
        - hooks: Creative hooks (if include_hooks=True)

    Example Usage:
        result = await generate_audience_from_url("https://zimswitch.co.zw")
        print(result["audience_targeting"]["audience_segments"])
        print(result["audience_targeting"]["interest_tags"])
    """
    from .market_research_agent import research_website_directly

    logger.info(f"[CreativeStrategistAgent] Generating audience from URL: {url}")

    # Step 1: Research the website
    website_data = await research_website_directly(
        url=url,
        deep_scrape=True,
        extract_structure=True
    )

    # Step 2: Generate Meta audience targeting
    agent = CreativeStrategistAgent()
    audience_result = await agent.generate_meta_audience(website_data)

    # Step 3: Optionally generate hooks
    hooks = []
    if include_hooks and audience_result.get("success"):
        # Create a mock campaign-like object for hook generation
        audience_data = audience_result.get("audience_targeting", {})
        extracted = website_data.get("extracted_data", {})

        # Build hook generation context
        hook_prompt_data = {
            "campaign_name": audience_result.get("company_name", "Campaign"),
            "objective": "CONVERSIONS",
            "product_description": "\n".join([
                f"- {svc.get('name', '')}: {svc.get('description', '')}"
                for svc in extracted.get("services_products", [])[:5]
            ]),
            "audience_analysis": json.dumps(audience_data, indent=2),
            "hook_types": "\n".join([
                f"- {h['name']}: {h['description']}" for h in HOOK_TYPES
            ]),
            "num_hooks": num_hooks
        }

        from modules.openrouter.context import set_ai_context
        chain = agent.hook_generation_prompt | agent.llm | StrOutputParser()
        with set_ai_context(agent_name="creative_strategist"):
            hook_response = await chain.ainvoke(hook_prompt_data)

        cleaned = agent._clean_json_response(hook_response)
        try:
            hooks_data = json.loads(cleaned)
            hooks = hooks_data.get('hooks', [])
        except json.JSONDecodeError:
            hooks = []

    # Compile final result
    result = {
        "url": url,
        "company_name": audience_result.get("company_name"),
        "industry": audience_result.get("industry"),
        "website_research": {
            "pages_scraped": website_data.get("research_summary", {}).get("pages_scraped", 0),
            "services_found": len(website_data.get("extracted_data", {}).get("services_products", [])),
            "competitors_found": website_data.get("research_summary", {}).get("competitors_found", 0)
        },
        "audience_targeting": audience_result.get("audience_targeting", {}),
        "success": audience_result.get("success", False)
    }

    if include_hooks:
        result["creative_hooks"] = hooks
        result["total_hooks"] = len(hooks)

    return result


async def generate_audience_comparison(urls: List[str]) -> Dict[str, Any]:
    """
    Generate and compare audience targeting for multiple websites.

    Useful for analyzing competitors or related businesses.

    Args:
        urls: List of website URLs to analyze (max 5)

    Returns:
        Dict containing audience analysis for each URL and comparison insights
    """
    results = {}
    all_interests = []
    all_segments = []

    # Run all URL analyses in parallel
    async def _analyze_url(url: str):
        try:
            result = await generate_audience_from_url(url, include_hooks=False)
            return url, result
        except Exception as e:
            logger.error(f"[CreativeStrategistAgent] Failed to analyze {url}: {e}")
            return url, {"success": False, "error": str(e)}

    tasks = [_analyze_url(url) for url in urls[:5]]
    task_results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in task_results:
        if isinstance(item, Exception):
            logger.error(f"[CreativeStrategistAgent] Parallel analysis error: {item}")
            continue
        url, result = item
        results[url] = result

        if result.get("success"):
            targeting = result.get("audience_targeting", {})
            interests = targeting.get("interest_tags", {})
            for category, tags in interests.items():
                if isinstance(tags, list):
                    all_interests.extend(tags)

            segments = targeting.get("audience_segments", [])
            all_segments.extend([s.get("name", "") for s in segments if isinstance(s, dict)])

    # Find common and unique interests
    from collections import Counter
    interest_counts = Counter(all_interests)
    common_interests = [i for i, c in interest_counts.items() if c > 1]
    unique_interests = {
        url: [i for i in result.get("audience_targeting", {}).get("interest_tags", {}).get("core_interests", [])
              if i not in common_interests]
        for url, result in results.items() if result.get("success")
    }

    return {
        "individual_results": results,
        "comparison": {
            "common_interests": common_interests,
            "unique_interests_by_url": unique_interests,
            "all_segments": list(set(all_segments)),
            "total_urls_analyzed": len([r for r in results.values() if r.get("success")])
        }
    }

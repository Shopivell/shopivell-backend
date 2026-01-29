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


# Industry-specific interest tag categories for Meta targeting
INDUSTRY_INTEREST_CATEGORIES = {
    "fintech": {
        "core": ["Payment system", "Payment service provider", "E-commerce payment system", "Mobile payment",
                 "Financial technology", "Mobile banking", "Digital wallet", "Contactless payment"],
        "business": ["Business-to-business", "Business networking", "Procurement", "Consulting",
                     "Enterprise software", "SaaS", "Cloud computing"],
        "professional": ["LinkedIn", "Web conferencing", "Videotelephony", "Google Apps for Work",
                        "Sales", "LiveChat", "Adobe Acrobat", "Microsoft Office"],
        "mindset": ["Leadership", "Ambition", "Entrepreneurship", "Innovation", "Digital transformation"]
    },
    "security": {
        "core": ["Anti-theft system", "Fire safety", "CCTV", "Access control", "Security system",
                 "Surveillance", "Alarm system", "Smart security"],
        "technology": ["Smart Technologies", "Internet of Things", "Artificial intelligence",
                      "Machine learning", "Computer vision", "Biometrics"],
        "property": ["Commercial property", "Property management", "Real estate", "Facility management",
                    "Building automation", "Smart building"],
        "automotive": ["Contactless payment", "Payment system", "Charging station", "Electric vehicle",
                      "Electric car", "Fleet management", "Parking management"],
        "business": ["Small and medium enterprises", "Small business software", "Business development",
                    "Professional services", "Business model", "Sales management"]
    },
    "ecommerce": {
        "core": ["Online shopping", "E-commerce", "Retail", "Shopping", "Consumer goods"],
        "technology": ["Shopify", "WooCommerce", "Magento", "Payment gateway", "Shopping cart"],
        "marketing": ["Digital marketing", "Social media marketing", "Email marketing", "SEO"],
        "business": ["Dropshipping", "Wholesale", "Inventory management", "Supply chain"]
    },
    "saas": {
        "core": ["Software as a service", "Cloud computing", "Enterprise software", "Business software"],
        "productivity": ["Project management", "CRM", "ERP", "Collaboration tools", "Automation"],
        "technology": ["API", "Integration", "Analytics", "Data visualization", "Business intelligence"]
    }
}


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
        "business_interests": ["Business and professional interests - 5-8 tags"],
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

IMPORTANT GUIDELINES:
1. Interest tags MUST be actual Facebook/Meta interests that exist in their targeting system
2. Generate 25-40 total interest tags across all categories
3. Be specific to the business industry and offerings
4. Include both B2B and B2C targeting if applicable
5. Suggest realistic job titles that exist on Facebook
6. Consider the geographic market (Zimbabwe/Africa focus if applicable)

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

    def _detect_industry(self, services: List[str], content: str) -> str:
        """Detect the industry based on services and content"""
        content_lower = content.lower()
        services_str = " ".join(services).lower() if services else ""

        if any(kw in content_lower or kw in services_str for kw in
               ["payment", "banking", "fintech", "transfer", "wallet", "pos", "atm"]):
            return "fintech"
        elif any(kw in content_lower or kw in services_str for kw in
                 ["security", "cctv", "surveillance", "alarm", "anpr", "access control"]):
            return "security"
        elif any(kw in content_lower or kw in services_str for kw in
                 ["ecommerce", "shop", "store", "retail", "cart"]):
            return "ecommerce"
        elif any(kw in content_lower or kw in services_str for kw in
                 ["saas", "software", "platform", "cloud", "subscription"]):
            return "saas"
        else:
            return "general"

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

        chain = self.meta_audience_prompt | self.llm | StrOutputParser()
        response = await chain.ainvoke(prompt_data)

        cleaned = self._clean_json_response(response)
        try:
            audience_data = json.loads(cleaned)

            # Detect industry and add industry-specific tags
            detected_industry = self._detect_industry(services, content_summary)
            if detected_industry in INDUSTRY_INTEREST_CATEGORIES:
                industry_tags = INDUSTRY_INTEREST_CATEGORIES[detected_industry]
                # Merge with generated tags
                for category, tags in industry_tags.items():
                    existing_key = f"{category}_interests"
                    if existing_key not in audience_data.get("interest_tags", {}):
                        if "interest_tags" not in audience_data:
                            audience_data["interest_tags"] = {}
                        # Add unique tags
                        existing_tags = []
                        for key, val in audience_data["interest_tags"].items():
                            if isinstance(val, list):
                                existing_tags.extend(val)
                        new_tags = [t for t in tags if t not in existing_tags]
                        if new_tags:
                            audience_data["interest_tags"][f"industry_{category}"] = new_tags[:6]

            return {
                "success": True,
                "company_name": company,
                "detected_industry": detected_industry,
                "audience_targeting": audience_data
            }

        except json.JSONDecodeError as e:
            logger.error(f"[CreativeStrategistAgent] Failed to parse audience JSON: {e}")
            return {
                "success": False,
                "error": "Failed to parse audience analysis",
                "raw_response": cleaned[:1000]
            }

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

        chain = agent.hook_generation_prompt | agent.llm | StrOutputParser()
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
        "detected_industry": audience_result.get("detected_industry"),
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

    for url in urls[:5]:  # Limit to 5 URLs
        try:
            result = await generate_audience_from_url(url, include_hooks=False)
            results[url] = result

            # Collect interests for comparison
            if result.get("success"):
                targeting = result.get("audience_targeting", {})
                interests = targeting.get("interest_tags", {})
                for category, tags in interests.items():
                    if isinstance(tags, list):
                        all_interests.extend(tags)

                segments = targeting.get("audience_segments", [])
                all_segments.extend([s.get("name", "") for s in segments if isinstance(s, dict)])

        except Exception as e:
            logger.error(f"[CreativeStrategistAgent] Failed to analyze {url}: {e}")
            results[url] = {"success": False, "error": str(e)}

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

# ad_copy_agent.py - AI Agent for Ad Copy Generation
"""
Enhanced Ad Copy Agent that generates high-converting ad copy.

Features:
1. Market research integration - Uses scraped website data
2. Audience-specific copy - B2B vs B2C tailored messaging
3. Social proof integration - Statistics, years in business, credentials
4. Hook generation - Attention-grabbing opening lines
5. Platform-specific formats - Facebook, Instagram, LinkedIn optimized
6. Multiple full copy variations - Not just headline variations
7. Brand voice matching - Consistent tone across all copy
"""

import os
import json
import logging
import asyncio
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

from pydantic import BaseModel, Field

load_dotenv()
logger = logging.getLogger(__name__)


# --- Structured output models for ad copy ---

class AdCopyHooks(BaseModel):
    pattern_interrupt: str = ""
    question: str = ""
    social_proof: str = ""

class AdCopyHeadline(BaseModel):
    type: str = ""
    text: str = ""

class AdCopyPrimaryText(BaseModel):
    short: str = ""
    medium: str = ""
    long: str = ""

class AdCopyStructuredOutput(BaseModel):
    hooks: dict = Field(default_factory=dict)
    headlines: List[dict] = Field(default_factory=list)
    primary_text: dict = Field(default_factory=dict)
    descriptions: List[str] = Field(default_factory=list)
    call_to_action: str = "Learn More"


class AdCopyAgent:
    """Enhanced AI Agent for generating high-converting ad copy"""

    def __init__(self):
        if OPENROUTER_AVAILABLE:
            self.llm = ChatOpenRouter(model="anthropic/claude-sonnet-4", temperature=0.8)
            self._supports_json_mode = True
            logger.info("[AdCopyAgent] Initialized with OpenRouter (Claude)")
        else:
            self.llm = ChatOpenRouter(model="claude-sonnet-4-20250514", temperature=0.8)
            self._supports_json_mode = False  # ChatAnthropic doesn't support response_format
            logger.info("[AdCopyAgent] Initialized with Claude direct")

        # Enhanced prompt for market research based copy generation
        self.research_based_prompt = ChatPromptTemplate.from_template("""
You are an expert direct-response copywriter specializing in Facebook/Instagram ads.
Generate high-converting ad copy using the market research data provided.

COMPANY INFORMATION:
Company Name: {company_name}
WHAT THEY SELL (USE THESE SPECIFIC TERMS - NOT GENERIC INDUSTRY TERMS): {primary_products}
Tagline: {tagline}
Years in Business: {years_in_business}
Geographic Coverage: {geographic_coverage}

PRODUCTS/SERVICES DETAILS:
{services_products}

VALUE PROPOSITIONS:
{value_propositions}

KEY STATISTICS (USE THESE EXACT NUMBERS AS SOCIAL PROOF):
{statistics}

TARGET AUDIENCE FOR THIS AD:
Audience Segment: {audience_segment}
What they're looking for: {shopping_need}
Their frustration: {pain_point}
Audience Type: {audience_type}

PLATFORM: {platform}

BRAND VOICE: {brand_voice}

{creative_insights}

---

CRITICAL INSTRUCTIONS:
- Use the SPECIFIC product terms provided above (e.g., "fashion", "clothing", "workwear")
- NEVER use generic terms like "retail", "products", "services", or "solutions"
- Reference the ACTUAL statistics and years in business as proof points
- Make hooks specific to what {company_name} sells and who {audience_segment} are
- Address the actual frustration ({pain_point}) the audience faces

Generate ad copy optimized for {platform} with the following:

1. HOOKS (3 attention-grabbing opening lines - first 125 characters are crucial)
   - Pattern interrupt: Something unexpected about {primary_products}
   - Question: A question {audience_segment} ask themselves about {primary_products}
   - Social proof: Use the actual statistics ({statistics}) or years in business

2. HEADLINES (3 variations, max 40 characters each) - MUST mention specific products
   - Benefit-focused (specific benefit of {primary_products})
   - Curiosity-driven (about {company_name}'s {primary_products})
   - Social proof based (use actual numbers)

3. PRIMARY TEXT (3 variations)
   For {platform}:
   - Short version (50-80 words) - mention {primary_products} specifically
   - Medium version (100-150 words) - address {pain_point}
   - Long version (200-250 words) - include statistics as proof

   Each should include:
   - Hook in first line (specific to {primary_products})
   - Problem agitation (about {pain_point})
   - Solution presentation (how {company_name}'s {primary_products} helps)
   - Social proof using actual statistics
   - Clear call to action
   - NO EMOJIS

4. DESCRIPTIONS (2 variations, max 30 words each) - mention specific products

5. CALL TO ACTION: Choose the most appropriate from:
   [Learn More, Shop Now, Sign Up, Get Quote, Contact Us, Book Now, See More]

Return as valid JSON:
{{
  "hooks": {{
    "pattern_interrupt": "Hook about {primary_products}",
    "question": "Question {audience_segment} ask about {primary_products}",
    "social_proof": "Hook using {statistics}"
  }},
  "headlines": [
    {{"type": "benefit", "text": "Headline about {primary_products}"}},
    {{"type": "curiosity", "text": "Headline 2"}},
    {{"type": "social_proof", "text": "Headline with statistics"}}
  ],
  "primary_text": {{
    "short": "Short version mentioning {primary_products}...",
    "medium": "Medium version addressing {pain_point}...",
    "long": "Long version with statistics..."
  }},
  "descriptions": ["Description with {primary_products}", "Description 2"],
  "call_to_action": "Shop Now",
  "audience_segment": "{audience_segment}",
  "platform": "{platform}"
}}

IMPORTANT:
- Use ACTUAL company data and product terms provided above
- Include real statistics as social proof
- Match the brand voice
- NO emojis in any text
- Return ONLY valid JSON
""")

        # Prompt for B2B specific copy
        self.b2b_prompt = ChatPromptTemplate.from_template("""
You are a B2B copywriter specializing in professional services advertising.
Generate LinkedIn/Facebook B2B ad copy that speaks to business decision-makers.

COMPANY: {company_name}
WHAT THEY PROVIDE (USE THESE SPECIFIC TERMS): {primary_products}
CREDENTIALS: {credentials}
YEARS IN BUSINESS: {years_in_business}

PRODUCTS/SERVICES FOR BUSINESSES:
{services_products}

TARGET B2B AUDIENCE:
Segment: {audience_segment}
What they need: {business_need}
Their challenge: {business_challenge}
Job Titles: {job_titles}
Company Types: {company_types}

KEY DIFFERENTIATORS:
{differentiators}

STATISTICS/SOCIAL PROOF (USE THESE SPECIFIC NUMBERS):
{statistics}

IMPORTANT INSTRUCTIONS:
- Use the SPECIFIC product/service terms provided above - NEVER use generic terms like "solutions" or "services"
- Reference actual statistics and years in business as proof points
- Address the specific business challenge of the audience segment
- Make hooks specific to what {company_name} actually provides

Generate professional B2B ad copy:

1. HOOKS (3 - must be specific to {primary_products} for {audience_segment})
   - Industry insight hook: A trend or insight about {primary_products} in the industry
   - Problem-aware hook: A specific challenge {audience_segment} face with {primary_products}
   - ROI/results hook: A measurable outcome from using {company_name}'s {primary_products}

2. HEADLINES (3, max 40 chars) - mention specific products/services, not generic terms
   - Authority-based (use years in business or credentials)
   - Solution-focused (specific to the product)
   - Results-driven (mention outcomes)

3. PRIMARY TEXT (2 versions)
   - LinkedIn style (professional, detailed, 150-200 words)
   - Facebook B2B style (slightly casual, 100-150 words)

   Include specific references to {primary_products} and {statistics}.

4. DESCRIPTIONS (2 versions) - mention specific products/services

5. CALL TO ACTION: [Get Quote, Learn More, Contact Us, Schedule Demo, Download Guide]

Return as valid JSON:
{{
  "hooks": {{
    "industry_insight": "Hook about {primary_products} in the industry",
    "problem_aware": "Hook about challenge with {primary_products}",
    "roi_results": "Hook about results from {primary_products}"
  }},
  "headlines": [
    {{"type": "authority", "text": "Headline with credentials"}},
    {{"type": "solution", "text": "Headline with specific product"}},
    {{"type": "results", "text": "Headline with outcome"}}
  ],
  "primary_text": {{
    "linkedin": "LinkedIn version mentioning {primary_products}...",
    "facebook": "Facebook B2B version..."
  }},
  "descriptions": ["Description 1", "Description 2"],
  "call_to_action": "Get Quote",
  "audience_segment": "{audience_segment}",
  "audience_type": "B2B"
}}

NO emojis. Professional tone only. Return ONLY valid JSON.
""")

        # Prompt for B2C specific copy
        self.b2c_prompt = ChatPromptTemplate.from_template("""
You are a B2C copywriter specializing in consumer advertising on social media.
Generate engaging Facebook/Instagram ad copy that connects with everyday consumers.

COMPANY: {company_name}
WHAT THEY SELL (USE THESE SPECIFIC TERMS, NOT GENERIC INDUSTRY TERMS): {primary_products}
TAGLINE: {tagline}
REPUTATION: {reputation}

PRODUCTS/SERVICES DETAILS:
{services_products}

TARGET CONSUMER AUDIENCE:
Segment: {audience_segment}
What they're shopping for: {shopping_need}
Their pain point: {pain_point}
What they desire: {audience_desire}
Demographics: {demographics}

KEY BENEFITS TO HIGHLIGHT:
{value_propositions}

SOCIAL PROOF (USE SPECIFIC NUMBERS):
{statistics}

IMPORTANT INSTRUCTIONS:
- Use the SPECIFIC product terms provided above (e.g., "fashion", "clothing", "footwear") - NEVER use generic terms like "retail" or "products"
- Reference what the audience is actually looking for based on their segment
- Use the actual statistics/years in business as social proof
- Make the hooks specific to the products and audience, not generic

Generate engaging B2C ad copy:

1. HOOKS (3 - must be specific to {primary_products} and {audience_segment})
   - Desire hook: What {audience_segment} aspire to have/be (related to {primary_products})
   - Pain point hook: A frustration {audience_segment} face when shopping for {primary_products}
   - Curiosity hook: Something intriguing about {company_name}'s {primary_products}

2. HEADLINES (3, max 40 chars) - mention specific products, not generic terms
   - Benefit-focused
   - Emotional appeal
   - Offer/value based

3. PRIMARY TEXT (3 versions for testing)
   - Story-driven (personal connection, 100-150 words)
   - Benefit-list (scannable, 80-120 words)
   - Urgency-based (FOMO, limited time, 60-100 words)

   Each should reference {primary_products} specifically.

4. DESCRIPTIONS (2 versions) - mention specific products

5. CALL TO ACTION: [Shop Now, Learn More, Get Started, See Collection, Explore Now]

Return as valid JSON:
{{
  "hooks": {{
    "desire": "Hook about aspiration for {primary_products}",
    "pain_point": "Hook about frustration shopping for {primary_products}",
    "curiosity": "Hook creating intrigue about {company_name}'s {primary_products}"
  }},
  "headlines": [
    {{"type": "benefit", "text": "Headline with specific product"}},
    {{"type": "emotional", "text": "Headline with emotional appeal"}},
    {{"type": "offer", "text": "Headline with value proposition"}}
  ],
  "primary_text": {{
    "story": "Story version mentioning {primary_products}...",
    "benefits": "Benefits list version...",
    "urgency": "Urgency version..."
  }},
  "descriptions": ["Description 1", "Description 2"],
  "call_to_action": "Shop Now",
  "audience_segment": "{audience_segment}",
  "audience_type": "B2C"
}}

Keep it conversational. NO emojis. Return ONLY valid JSON.
""")

        # Original prompt for backward compatibility
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

    def _parse_and_validate_ad_copy(self, response: str) -> Dict[str, Any]:
        """Parse LLM response and validate with Pydantic. Returns validated dict or raises."""
        cleaned = self._clean_json_response(response)

        # Try Pydantic validation first
        try:
            validated = AdCopyStructuredOutput.model_validate_json(cleaned)
            result = validated.model_dump()
            result['validated'] = True
            return result
        except Exception:
            pass

        # Fallback: plain JSON parse
        result = json.loads(cleaned)
        # Ensure required fields exist
        result.setdefault('hooks', {})
        result.setdefault('headlines', [])
        result.setdefault('primary_text', {})
        result.setdefault('descriptions', [])
        result.setdefault('call_to_action', 'Learn More')
        result['validated'] = False
        return result

    def _extract_statistics_string(self, statistics: List[Dict]) -> str:
        """Convert statistics list to readable string"""
        if not statistics:
            return "Established business with proven track record"

        stats_parts = []
        for stat in statistics[:5]:
            if isinstance(stat, dict):
                value = stat.get('value', '')
                metric = stat.get('metric', '')
                if value and metric:
                    stats_parts.append(f"{value} {metric}")

        return ", ".join(stats_parts) if stats_parts else "Established business"

    def _extract_services_string(self, services: List[Dict]) -> str:
        """Convert services list to readable string"""
        if not services:
            return "Quality products and services"

        service_parts = []
        for svc in services[:6]:
            if isinstance(svc, dict):
                name = svc.get('name', '')
                desc = svc.get('description', '')[:100]
                if name:
                    service_parts.append(f"- {name}: {desc}")
            elif isinstance(svc, str):
                service_parts.append(f"- {svc}")

        return "\n".join(service_parts) if service_parts else "Quality products and services"

    async def _extract_product_keywords_ai(self, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use AI to extract product/service keywords from research data.
        Industry-agnostic — works for any business type without hardcoded mappings.
        """
        extracted = research_data.get('extracted_data', {})
        summary = research_data.get('research_summary', {})

        company_name = summary.get('company_name', '')
        industry = summary.get('industry', '')
        services = extracted.get('services_products', [])
        value_props = extracted.get('value_propositions', [])

        services_text = ', '.join([
            s.get('name', '') if isinstance(s, dict) else str(s)
            for s in services[:10]
        ]) if services else 'Not specified'

        vp_text = ', '.join(value_props[:5]) if value_props else 'Not specified'

        try:
            from modules.openrouter.context import set_ai_context
            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a product analyst. Extract specific product/service keywords from company data.
Return ONLY valid JSON with this exact structure:
{{
  "product_keywords": ["specific product 1", "specific product 2", "specific product 3"],
  "benefit_keywords": ["key benefit 1", "key benefit 2"],
  "primary_products": "2-3 word summary of main offerings",
  "primary_benefit": "single most important benefit"
}}

Rules:
- Use SPECIFIC terms a customer would search for (e.g., "fridge repair" not "home services")
- Maximum 5 product keywords, 3 benefit keywords
- primary_products should be concise (2-4 words)"""),
                ("human", """Company: {company_name}
Industry: {industry}
Services/Products: {services}
Value Propositions: {value_props}""")
            ])

            json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
            chain = prompt | json_llm | StrOutputParser()
            with set_ai_context(agent_name="product_extractor"):
                response = await chain.ainvoke({
                    "company_name": company_name,
                    "industry": industry,
                    "services": services_text,
                    "value_props": vp_text
                })

            cleaned = self._clean_json_response(response)
            result = json.loads(cleaned)

            # Ensure all required keys exist
            return {
                'product_keywords': result.get('product_keywords', [])[:5],
                'benefit_keywords': result.get('benefit_keywords', [])[:3],
                'primary_products': result.get('primary_products', 'products and services'),
                'primary_benefit': result.get('primary_benefit', 'quality')
            }

        except Exception as e:
            logger.warning(f"[AdCopyAgent] AI product extraction failed, using basic extraction: {e}")
            return self._extract_product_keywords_basic(research_data)

    def _extract_product_keywords_basic(self, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """Basic fallback product extraction from service names — no hardcoded industry mappings."""
        extracted = research_data.get('extracted_data', {})
        summary = research_data.get('research_summary', {})

        product_keywords = []
        services = extracted.get('services_products', [])
        for svc in services[:6]:
            if isinstance(svc, dict):
                name = svc.get('name', '')
                if name and len(name) < 50:
                    product_keywords.append(name.strip())
            elif isinstance(svc, str) and len(svc) < 50:
                product_keywords.append(svc.strip())

        primary_products = ', '.join(product_keywords[:3]) if product_keywords else 'products and services'

        return {
            'product_keywords': product_keywords[:5],
            'benefit_keywords': ['quality', 'reliability'],
            'primary_products': primary_products,
            'primary_benefit': 'quality'
        }

    def _extract_product_keywords(self, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sync wrapper for backward compatibility. Use _extract_product_keywords_ai for async.
        Falls back to basic extraction (no hardcoded industry mappings).
        """
        return self._extract_product_keywords_basic(research_data)

    async def _extract_audience_context_ai(self, audience_name: str, research_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Use AI to extract audience context from research data.
        Works for ANY industry — no hardcoded mappings needed.
        """
        extracted = research_data.get('extracted_data', {})
        summary = research_data.get('research_summary', {})
        company_info = extracted.get('company_info', {})

        # Build a concise business context string
        services = extracted.get('services_products', [])
        services_text = ", ".join(
            svc.get('name', svc) if isinstance(svc, dict) else str(svc)
            for svc in services[:8]
        ) if services else "Not specified"

        value_props = extracted.get('value_propositions', [])
        value_text = ", ".join(value_props[:5]) if value_props else "Not specified"

        prompt = ChatPromptTemplate.from_template("""
You are a marketing strategist. Given a company and an audience segment, identify the audience's specific needs, pain points, and desires related to what this company sells.

COMPANY: {company_name}
INDUSTRY: {industry}
PRODUCTS/SERVICES: {services}
VALUE PROPOSITIONS: {value_props}
GEOGRAPHIC COVERAGE: {location}

AUDIENCE SEGMENT: {audience_name}

Return ONLY valid JSON with these 4 fields — be specific to this company and audience, not generic:
{{
    "shopping_need": "What this specific audience segment is looking for from this company (1 sentence)",
    "pain_point": "The specific frustration or problem this audience faces that this company can solve (1 sentence)",
    "desire": "What outcome this audience ultimately wants (1 short phrase)",
    "demographic_hint": "A 2-3 word descriptor for this audience segment"
}}

Be concrete and specific. Reference the actual products/services. Do NOT use generic phrases like "quality products" or "great service".
Return ONLY valid JSON, no markdown.
""")

        try:
            from modules.openrouter.context import set_ai_context
            chain = prompt | self.llm | StrOutputParser()
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke({
                    'company_name': summary.get('company_name') or company_info.get('name') or 'Company',
                    'industry': company_info.get('industry') or summary.get('industry') or 'General',
                    'services': services_text,
                    'value_props': value_text,
                    'location': company_info.get('geographic_coverage') or summary.get('geographic_coverage') or '',
                    'audience_name': audience_name
                })

            cleaned = self._clean_json_response(response)
            context = json.loads(cleaned)

            # Ensure all required keys exist
            return {
                'shopping_need': context.get('shopping_need', 'quality products and services'),
                'pain_point': context.get('pain_point', 'finding the right provider'),
                'desire': context.get('desire', 'reliable service'),
                'demographic_hint': context.get('demographic_hint', '')
            }

        except Exception as e:
            logger.warning(f"[AdCopyAgent] AI audience context extraction failed: {e}, using defaults")
            return {
                'shopping_need': 'quality products and services',
                'pain_point': 'finding the right provider',
                'desire': 'reliable service',
                'demographic_hint': ''
            }

    async def _extract_audience_context(self, audience_name: str, research_data: Dict[str, Any]) -> Dict[str, str]:
        """Extract audience context using AI. Works for any industry."""
        return await self._extract_audience_context_ai(audience_name, research_data)

    async def generate_ad_copy_from_research(
        self,
        research_data: Dict[str, Any],
        audience_segment: Dict[str, Any] = None,
        platform: str = "facebook",
        brand_voice: str = "professional yet approachable"
    ) -> Dict[str, Any]:
        """
        Generate ad copy directly from market research data.

        Args:
            research_data: Output from market_research_agent (extracted_data, research_summary)
            audience_segment: Optional specific audience to target
            platform: Target platform (facebook, instagram, linkedin)
            brand_voice: Desired tone of voice

        Returns:
            Dict containing comprehensive ad copy variations
        """
        logger.info(f"[AdCopyAgent] Generating ad copy from research for {platform}")

        # Extract data from research
        summary = research_data.get('research_summary', {})
        extracted = research_data.get('extracted_data', {})
        company_info = extracted.get('company_info', {})

        # Build prompt data
        company_name = summary.get('company_name') or company_info.get('name') or 'Company'
        tagline = company_info.get('tagline') or summary.get('tagline') or ''

        # Extract specific product keywords
        product_info = await self._extract_product_keywords_ai(research_data)

        # Calculate years in business from statistics or key features
        years_in_business = self._extract_years(extracted.get('statistics', []))

        # Get services/products
        services_products = self._extract_services_string(extracted.get('services_products', []))

        # Get value propositions
        value_props = extracted.get('value_propositions', [])
        value_propositions = "\n".join([f"- {vp}" for vp in value_props[:5]]) if value_props else "Quality and reliability"

        # Get statistics for social proof
        statistics = self._extract_statistics_string(extracted.get('statistics', []))

        # Audience segment defaults
        if not audience_segment:
            target_audiences = extracted.get('target_audiences', [])
            audience_segment = {
                'name': target_audiences[0] if target_audiences else 'General Audience',
                'type': 'B2C',
                'description': 'Customers interested in ' + product_info['primary_products']
            }

        # Get audience context
        audience_context = await self._extract_audience_context(audience_segment.get('name', ''), research_data)

        prompt_data = {
            'company_name': company_name,
            'primary_products': product_info['primary_products'],
            'tagline': tagline,
            'years_in_business': years_in_business,
            'geographic_coverage': company_info.get('geographic_coverage', summary.get('geographic_coverage', '')),
            'services_products': services_products,
            'value_propositions': value_propositions,
            'statistics': statistics,
            'audience_segment': audience_segment.get('name', 'Target Audience'),
            'shopping_need': audience_context['shopping_need'],
            'pain_point': audience_context['pain_point'],
            'audience_type': audience_segment.get('type', 'B2C'),
            'platform': platform,
            'brand_voice': brand_voice,
            'creative_insights': self._get_creative_performance_insights()
        }

        # Run the LLM chain with structured JSON output
        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
        chain = self.research_based_prompt | json_llm | StrOutputParser()

        try:
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke(prompt_data)
            ad_data = self._parse_and_validate_ad_copy(response)

            # Add metadata
            ad_data['company_name'] = company_name
            ad_data['primary_products'] = product_info['primary_products']
            ad_data['generated_from'] = 'market_research'

            logger.info(f"[AdCopyAgent] Generated ad copy for {company_name}")
            return ad_data

        except json.JSONDecodeError as e:
            logger.error(f"[AdCopyAgent] JSON decode error: {e}")
            return self._fallback_ad_copy(company_name, product_info, audience_context, platform)
        except Exception as e:
            logger.error(f"[AdCopyAgent] Error generating ad copy: {e}")
            return self._fallback_ad_copy(company_name, product_info, audience_context, platform)

    async def _extract_b2b_audience_context_ai(self, audience_name: str, research_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Use AI to extract B2B audience context from research data.
        Works for ANY industry.
        """
        extracted = research_data.get('extracted_data', {})
        summary = research_data.get('research_summary', {})
        company_info = extracted.get('company_info', {})

        services = extracted.get('services_products', [])
        services_text = ", ".join(
            svc.get('name', svc) if isinstance(svc, dict) else str(svc)
            for svc in services[:8]
        ) if services else "Not specified"

        prompt = ChatPromptTemplate.from_template("""
You are a B2B marketing strategist. Given a company and a B2B audience segment, identify their specific business needs, challenges, and who they are.

COMPANY: {company_name}
INDUSTRY: {industry}
PRODUCTS/SERVICES: {services}

B2B AUDIENCE SEGMENT: {audience_name}

Return ONLY valid JSON:
{{
    "business_need": "What this B2B audience specifically needs from this company (1 sentence)",
    "business_challenge": "The specific business challenge this audience faces that this company solves (1 sentence)",
    "job_titles": "Comma-separated list of job titles who make buying decisions for this",
    "company_types": "Comma-separated list of company/organization types in this segment"
}}

Be concrete and specific to this company's actual products/services. Return ONLY valid JSON, no markdown.
""")

        try:
            from modules.openrouter.context import set_ai_context
            chain = prompt | self.llm | StrOutputParser()
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke({
                    'company_name': summary.get('company_name') or company_info.get('name') or 'Company',
                    'industry': company_info.get('industry') or summary.get('industry') or 'General',
                    'services': services_text,
                    'audience_name': audience_name
                })

            cleaned = self._clean_json_response(response)
            context = json.loads(cleaned)

            return {
                'business_need': context.get('business_need', 'reliable business solutions'),
                'business_challenge': context.get('business_challenge', 'finding quality suppliers'),
                'job_titles': context.get('job_titles', 'Decision makers, managers'),
                'company_types': context.get('company_types', 'SMEs, enterprises')
            }

        except Exception as e:
            logger.warning(f"[AdCopyAgent] AI B2B audience context extraction failed: {e}, using defaults")
            return {
                'business_need': 'reliable business solutions',
                'business_challenge': 'finding quality suppliers',
                'job_titles': 'Decision makers, managers',
                'company_types': 'SMEs, enterprises'
            }

    async def _extract_b2b_audience_context(self, audience_name: str, research_data: Dict[str, Any]) -> Dict[str, str]:
        """Extract B2B audience context using AI. Works for any industry."""
        return await self._extract_b2b_audience_context_ai(audience_name, research_data)

    async def generate_b2b_ad_copy(
        self,
        research_data: Dict[str, Any],
        audience_segment: Dict[str, Any],
        platform: str = "linkedin"
    ) -> Dict[str, Any]:
        """
        Generate B2B-specific ad copy for business audiences.

        Args:
            research_data: Market research data
            audience_segment: B2B audience details (job titles, company types, pain points)
            platform: linkedin or facebook
        """
        logger.info(f"[AdCopyAgent] Generating B2B ad copy for {platform}")

        summary = research_data.get('research_summary', {})
        extracted = research_data.get('extracted_data', {})
        company_info = extracted.get('company_info', {})

        # Extract specific product keywords
        product_info = await self._extract_product_keywords_ai(research_data)
        b2b_context = await self._extract_b2b_audience_context(audience_segment.get('name', ''), research_data)

        prompt_data = {
            'company_name': summary.get('company_name', 'Company'),
            'primary_products': product_info['primary_products'],
            'credentials': ", ".join(extracted.get('certifications_awards', [])[:3]) or 'Industry leader',
            'years_in_business': self._extract_years(extracted.get('statistics', [])),
            'services_products': self._extract_services_string(extracted.get('services_products', [])),
            'audience_segment': audience_segment.get('name', 'Business Professionals'),
            'business_need': b2b_context['business_need'],
            'business_challenge': b2b_context['business_challenge'],
            'job_titles': audience_segment.get('job_titles', b2b_context['job_titles']),
            'company_types': audience_segment.get('company_types', b2b_context['company_types']),
            'differentiators': "\n".join([f"- {vp}" for vp in extracted.get('value_propositions', [])[:4]]),
            'statistics': self._extract_statistics_string(extracted.get('statistics', []))
        }

        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
        chain = self.b2b_prompt | json_llm | StrOutputParser()

        try:
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke(prompt_data)
            ad_data = self._parse_and_validate_ad_copy(response)
            ad_data['generated_from'] = 'b2b_research'
            return ad_data
        except Exception as e:
            logger.error(f"[AdCopyAgent] B2B copy error: {e}")
            return self._fallback_b2b_copy(prompt_data, product_info, b2b_context)

    async def generate_b2c_ad_copy(
        self,
        research_data: Dict[str, Any],
        audience_segment: Dict[str, Any],
        platform: str = "facebook"
    ) -> Dict[str, Any]:
        """
        Generate B2C-specific ad copy for consumer audiences.

        Args:
            research_data: Market research data
            audience_segment: B2C audience details (demographics, interests, desires)
            platform: facebook or instagram
        """
        logger.info(f"[AdCopyAgent] Generating B2C ad copy for {platform}")

        summary = research_data.get('research_summary', {})
        extracted = research_data.get('extracted_data', {})
        company_info = extracted.get('company_info', {})

        # Extract specific product keywords instead of generic industry terms
        product_info = await self._extract_product_keywords_ai(research_data)
        audience_context = await self._extract_audience_context(audience_segment.get('name', ''), research_data)

        prompt_data = {
            'company_name': summary.get('company_name', 'Company'),
            'primary_products': product_info['primary_products'],
            'tagline': company_info.get('tagline', ''),
            'reputation': f"{self._extract_years(extracted.get('statistics', []))} of trusted service",
            'services_products': self._extract_services_string(extracted.get('services_products', [])),
            'audience_segment': audience_segment.get('name', 'Consumers'),
            'shopping_need': audience_context['shopping_need'],
            'pain_point': audience_context['pain_point'],
            'audience_desire': audience_context['desire'],
            'demographics': audience_segment.get('demographics', audience_context.get('demographic_hint', 'Adults 25-54')),
            'value_propositions': "\n".join([f"- {vp}" for vp in extracted.get('value_propositions', [])[:4]]),
            'statistics': self._extract_statistics_string(extracted.get('statistics', []))
        }

        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
        chain = self.b2c_prompt | json_llm | StrOutputParser()

        try:
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke(prompt_data)
            ad_data = self._parse_and_validate_ad_copy(response)
            ad_data['generated_from'] = 'b2c_research'
            return ad_data
        except Exception as e:
            logger.error(f"[AdCopyAgent] B2C copy error: {e}")
            return self._fallback_b2c_copy(prompt_data, product_info, audience_context)

    async def generate_multi_audience_ad_copy(
        self,
        research_data: Dict[str, Any],
        audiences: List[Dict[str, Any]] = None,
        platforms: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate ad copy for multiple audiences and platforms.

        Args:
            research_data: Market research data
            audiences: List of audience segments (auto-detected if not provided)
            platforms: List of platforms (defaults to facebook, instagram)

        Returns:
            Dict with ad copy organized by audience and platform
        """
        if not platforms:
            platforms = ['facebook', 'instagram']

        # Auto-detect audiences from research if not provided
        if not audiences:
            extracted = research_data.get('extracted_data', {})
            target_audiences = extracted.get('target_audiences', [])

            audiences = []
            for i, ta in enumerate(target_audiences[:4]):
                # Determine if B2B or B2C based on keywords
                is_b2b = any(kw in ta.lower() for kw in ['corporate', 'business', 'company', 'professional', 'enterprise', 'b2b'])
                audiences.append({
                    'name': ta,
                    'type': 'B2B' if is_b2b else 'B2C',
                    'description': ta
                })

            # Add default audience if none found
            if not audiences:
                audiences = [{'name': 'General Audience', 'type': 'B2C', 'description': 'General consumers'}]

        results = {
            'company_name': research_data.get('research_summary', {}).get('company_name', 'Company'),
            'audiences': {}
        }

        # Build all (audience, platform) tasks for parallel execution
        async def _generate_single(audience: Dict, platform: str) -> tuple:
            audience_name = audience.get('name', 'Unknown')
            audience_type = audience.get('type', 'B2C')
            try:
                if audience_type == 'B2B':
                    ad_copy = await self.generate_b2b_ad_copy(research_data, audience, platform)
                else:
                    ad_copy = await self.generate_b2c_ad_copy(research_data, audience, platform)
                return (audience_name, audience_type, platform, ad_copy)
            except Exception as e:
                logger.error(f"[AdCopyAgent] Error for {audience_name}/{platform}: {e}")
                return (audience_name, audience_type, platform, {'error': str(e)})

        # Run all audience/platform combinations in parallel
        tasks = [
            _generate_single(audience, platform)
            for audience in audiences
            for platform in platforms
        ]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Organize results
        for item in task_results:
            if isinstance(item, Exception):
                logger.error(f"[AdCopyAgent] Parallel generation error: {item}")
                continue
            audience_name, audience_type, platform, ad_copy = item
            if audience_name not in results['audiences']:
                results['audiences'][audience_name] = {'type': audience_type, 'platforms': {}}
            results['audiences'][audience_name]['platforms'][platform] = ad_copy

        return results

    # Meta ad specs (shared with CopywriterAgent)
    META_CTAS = [
        "Learn More", "Shop Now", "Sign Up", "Download", "Book Now",
        "Get Quote", "Contact Us", "Subscribe", "Apply Now", "Get Offer",
        "Order Now", "Buy Now", "Get Started", "Watch More", "Send Message"
    ]

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
        Generate copy variations for URL-based campaigns (cross-mixing).
        Works directly with URL campaign data (no Campaign/CreativeAngle models needed).

        Returns:
            List of dicts, each with headline, primary_text, description, call_to_action
        """
        features_str = ", ".join(features) if features else "Not specified"

        variation_prompt = ChatPromptTemplate.from_template("""
You are an expert Meta ad copywriter. Generate {num_variations} distinct ad copy variations
for A/B testing. Each variation MUST use a different hook strategy and tone.

BUSINESS: {business_name}
PRODUCT/SERVICE: {product_description}
TARGET AUDIENCE: {target_audience}
KEY FEATURES: {features}
REFERENCE HEADLINE: {base_headline}
REFERENCE COPY: {base_primary_text}

META AD SPECS:
- Primary Text: 125 chars recommended, 500 max
- Headline: 40 chars recommended
- Description: 30 chars recommended

AVAILABLE CTAs: {available_ctas}

VARIATION STRATEGIES (use a different one for each):
1. Pain-point focused: Lead with the problem, present the solution
2. Social proof / trust: Lead with credibility, reviews, numbers
3. Urgency / scarcity: Create FOMO, limited-time framing
4. Benefit-first: Lead with the top benefit, emotional outcome
5. Question hook: Start with a relatable question

Return ONLY valid JSON:
{{
    "variations": [
        {{
            "strategy": "which strategy was used",
            "headline": "punchy headline text",
            "primary_text": "main ad copy with line breaks",
            "description": "supporting description",
            "call_to_action": "best CTA from available list"
        }}
    ]
}}
""")

        prompt_data = {
            "num_variations": num_variations,
            "business_name": business_name,
            "product_description": product_description,
            "target_audience": target_audience,
            "features": features_str,
            "base_headline": base_headline,
            "base_primary_text": base_primary_text,
            "available_ctas": ", ".join(self.META_CTAS),
        }

        try:
            from modules.openrouter.context import set_ai_context
            json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
            chain = variation_prompt | json_llm | StrOutputParser()
            with set_ai_context(store_id=store_id, agent_name="ad_copy_variations"):
                response = await chain.ainvoke(prompt_data)

            cleaned = self._clean_json_response(response)
            data = json.loads(cleaned)
            variations = data.get("variations", [])

            result = []
            for v in variations[:num_variations]:
                result.append({
                    "headline": v.get("headline", base_headline),
                    "primary_text": v.get("primary_text", base_primary_text),
                    "description": v.get("description", ""),
                    "call_to_action": v.get("call_to_action", cta),
                    "strategy": v.get("strategy", ""),
                })

            logger.info(f"[AdCopyAgent] Generated {len(result)} copy variations for '{business_name}'")
            return result

        except Exception as e:
            logger.error(f"[AdCopyAgent] Error generating URL ad variations: {e}")
            return [{
                "headline": base_headline,
                "primary_text": base_primary_text,
                "description": "",
                "call_to_action": cta,
                "strategy": "fallback",
            }]

    async def generate_short_form_copy(
        self,
        product_description: str,
        hook_text: str = "",
        emotion: str = "Engaging",
        store_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate short-form copy for Stories/Reels placements.
        Max 125 characters for primary text, ultra-concise headlines.

        Returns:
            Dict with short-form copy variations
        """
        short_prompt = ChatPromptTemplate.from_template("""
Generate 3 ultra-short ad copy variations for Instagram Stories/Reels.

Product: {product_description}
Hook: {hook_text}
Emotion: {emotion}

CONSTRAINTS:
- Primary text: MAX 125 characters
- Headline: MAX 25 characters
- Must be punchy and attention-grabbing
- No emojis unless brand-appropriate

Return ONLY valid JSON:
{{
    "variations": [
        {{
            "primary_text": "short punchy copy (max 125 chars)",
            "headline": "ultra-short (max 25 chars)",
            "call_to_action": "Swipe Up or Learn More"
        }}
    ]
}}
""")

        try:
            from modules.openrouter.context import set_ai_context
            json_llm = self.llm.bind(response_format={"type": "json_object"}) if self._supports_json_mode else self.llm
            chain = short_prompt | json_llm | StrOutputParser()
            with set_ai_context(store_id=store_id, agent_name="ad_copy_short"):
                response = await chain.ainvoke({
                    "product_description": product_description,
                    "hook_text": hook_text or "Discover something amazing",
                    "emotion": emotion
                })

            cleaned = self._clean_json_response(response)
            return json.loads(cleaned)

        except Exception as e:
            logger.error(f"[AdCopyAgent] Short-form copy error: {e}")
            return {
                "variations": [{
                    "primary_text": f"Discover {product_description[:80]}",
                    "headline": "See More",
                    "call_to_action": "Learn More"
                }]
            }

    def _get_creative_performance_insights(self, ad_account_id: Optional[str] = None) -> str:
        """
        Query past creative test results to learn what copy patterns perform best.
        Feeds winning patterns back into generation prompts.

        Returns a text summary like:
        "Based on past A/B tests: authority-based headlines perform 20% better than curiosity-based.
         Short primary text (<100 chars) gets higher CTR than long versions."
        """
        db = SessionLocal()
        try:
            from .models import CreativeTest, CreativeTestVariant

            # Get completed tests
            query = db.query(CreativeTest).filter(CreativeTest.status == "completed")
            if ad_account_id:
                query = query.filter(CreativeTest.ad_account_id == ad_account_id)
            tests = query.order_by(CreativeTest.completed_at.desc()).limit(10).all()

            if not tests:
                return ""

            insights = []
            winner_headlines = []
            loser_headlines = []

            for test in tests:
                variants = db.query(CreativeTestVariant).filter(
                    CreativeTestVariant.test_id == test.id
                ).all()

                for v in variants:
                    if v.status == "winner" and v.headline:
                        winner_headlines.append(v.headline)
                        if v.final_ctr:
                            insights.append(f"Winner: \"{v.headline}\" (CTR={v.final_ctr:.2f}%)")
                    elif v.status == "paused" and v.headline and not v.is_original:
                        loser_headlines.append(v.headline)

            if not insights:
                return ""

            summary = "CREATIVE PERFORMANCE INSIGHTS (from past A/B tests):\n"
            summary += "\n".join(f"- {i}" for i in insights[:5])

            if winner_headlines:
                summary += f"\n\nWinning headline patterns: {', '.join(winner_headlines[:3])}"
            if loser_headlines:
                summary += f"\nUnderperforming patterns: {', '.join(loser_headlines[:3])}"

            summary += "\n\nUse these insights to guide your copy generation — prioritize patterns similar to winners."
            return summary

        except Exception as e:
            logger.warning(f"[AdCopyAgent] Failed to get creative insights: {e}")
            return ""
        finally:
            db.close()

    def _extract_years(self, statistics: List[Dict]) -> str:
        """Extract years in business from statistics"""
        for stat in statistics:
            if isinstance(stat, dict):
                metric = str(stat.get('metric', '')).lower()
                if 'founded' in metric or 'year' in metric or 'established' in metric:
                    return f"Since {stat.get('value', '')}"
                if 'years' in metric:
                    return f"{stat.get('value', '')} years"
        return "Years"

    def _fallback_ad_copy(self, company_name: str, product_info: Dict, audience_context: Dict, platform: str) -> Dict[str, Any]:
        """Fallback ad copy when AI generation fails - uses actual product and audience data"""
        # Extract actual product terms
        if isinstance(product_info, dict):
            products = product_info.get('primary_products', 'quality products')
            benefits = product_info.get('benefit_keywords', [])
        else:
            products = 'quality products'
            benefits = []

        # Extract audience context
        if isinstance(audience_context, dict):
            shopping_need = audience_context.get('shopping_need', 'great products')
            pain_point = audience_context.get('pain_point', 'finding what you need')
            desire = audience_context.get('desire', 'quality')
        else:
            shopping_need = 'great products'
            pain_point = 'finding what you need'
            desire = 'quality'

        # Build benefit string
        benefit_text = benefits[0] if benefits else 'quality and value'

        return {
            "hooks": {
                "pattern_interrupt": f"Still searching for the perfect {products}?",
                "question": f"Want {products} that actually deliver on {benefit_text}?",
                "social_proof": f"See why customers trust {company_name} for their {products}"
            },
            "headlines": [
                {"type": "benefit", "text": f"{products.split(',')[0].title()} You'll Love"},
                {"type": "curiosity", "text": f"Discover {company_name}"},
                {"type": "social_proof", "text": f"Trusted {products.split(',')[0].title()}"}
            ],
            "primary_text": {
                "short": f"{company_name} offers {products} with {benefit_text}. Find exactly what you're looking for today.",
                "medium": f"Tired of {pain_point}? {company_name} makes it easy to find {products} that match your needs. Quality, selection, and {benefit_text} - all in one place. Visit us today.",
                "long": f"Finding {shopping_need} shouldn't be frustrating. At {company_name}, we understand what you're looking for: {products} that deliver on {benefit_text}. That's why customers keep coming back to us. Stop settling and start experiencing the difference. Visit {company_name} today."
            },
            "descriptions": [
                f"Quality {products} at {company_name}",
                f"Your destination for {products}"
            ],
            "call_to_action": "Shop Now",
            "platform": platform,
            "primary_products": products,
            "generated_from": "fallback"
        }

    def _fallback_b2b_copy(self, data: Dict, product_info: Dict = None, b2b_context: Dict = None) -> Dict[str, Any]:
        """Fallback B2B copy using actual product and audience data"""
        company_name = data.get('company_name', 'our company')
        years = data.get('years_in_business', 'Years')

        # Use extracted product info or defaults
        if product_info:
            products = product_info.get('primary_products', 'business solutions')
        else:
            products = 'business solutions'

        # Use B2B context or defaults
        if b2b_context:
            need = b2b_context.get('business_need', 'reliable partners')
            challenge = b2b_context.get('business_challenge', 'quality and consistency')
        else:
            need = 'reliable partners'
            challenge = 'quality and consistency'

        audience = data.get('audience_segment', 'businesses')

        return {
            "hooks": {
                "industry_insight": f"{years} of expertise in {products} for {audience}",
                "problem_aware": f"Struggling with {challenge}?",
                "roi_results": f"See why leading {audience} trust {company_name}"
            },
            "headlines": [
                {"type": "authority", "text": f"{years} of Excellence"},
                {"type": "solution", "text": f"Quality {products.split(',')[0].title()}"},
                {"type": "results", "text": f"Trusted by {audience.title()}"}
            ],
            "primary_text": {
                "linkedin": f"{company_name} has been providing {products} for {audience} with {years} of proven expertise. When you need {need}, partner with a name you can trust. Contact us to discuss your requirements.",
                "facebook": f"Need {need}? {company_name} delivers {products} you can count on. {years} of experience. Get in touch today."
            },
            "descriptions": [
                f"Professional {products} from {company_name}",
                f"Trusted {products} partner"
            ],
            "call_to_action": "Get Quote",
            "audience_type": "B2B",
            "generated_from": "fallback"
        }

    def _fallback_b2c_copy(self, data: Dict, product_info: Dict = None, audience_context: Dict = None) -> Dict[str, Any]:
        """Fallback B2C copy using actual product and audience data"""
        company_name = data.get('company_name', 'our store')

        # Use extracted product info or defaults
        if product_info:
            products = product_info.get('primary_products', 'quality products')
            benefits = product_info.get('benefit_keywords', ['quality', 'value'])
        else:
            products = 'quality products'
            benefits = ['quality', 'value']

        # Use audience context or defaults
        if audience_context:
            desire = audience_context.get('desire', 'quality and value')
            pain = audience_context.get('pain_point', 'finding what you need')
            shopping = audience_context.get('shopping_need', 'great products')
        else:
            desire = 'quality and value'
            pain = 'finding what you need'
            shopping = 'great products'

        # Build contextual hooks based on actual data
        audience = data.get('audience_segment', 'shoppers')

        return {
            "hooks": {
                "desire": f"Get the {products} you've been looking for",
                "pain_point": f"Tired of {pain}?",
                "curiosity": f"See why {audience} choose {company_name}"
            },
            "headlines": [
                {"type": "benefit", "text": f"Quality {products.split(',')[0].title()}"},
                {"type": "emotional", "text": f"Style Your Way"},
                {"type": "offer", "text": f"Great {products.split(',')[0].title()} Deals"}
            ],
            "primary_text": {
                "story": f"At {company_name}, we understand {audience} need {shopping}. That's why we've spent years perfecting our {products}. Come see the difference quality makes.",
                "benefits": f"Looking for {products}? {company_name} offers: Quality you can trust. Prices that make sense. Selection for everyone. Visit us today.",
                "urgency": f"Don't wait to upgrade your {products.split(',')[0]}. {company_name} has what you're looking for. Shop now."
            },
            "descriptions": [
                f"Quality {products} at {company_name}",
                f"Find your perfect {products.split(',')[0]} today"
            ],
            "call_to_action": "Shop Now",
            "audience_type": "B2C",
            "generated_from": "fallback"
        }

    # ========== Original methods for backward compatibility ==========

    async def generate_ad_copy(
        self,
        campaign: Campaign,
        angle: CreativeAngle,
        keyword_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Generate ad copy for a specific creative angle.
        (Original method - kept for backward compatibility)
        """
        # Enrich keywords with search volume data if available
        keywords_str = ", ".join(campaign.keywords) if campaign.keywords else "Not specified"
        if keyword_data and keyword_data.get("success"):
            top_kws = keyword_data.get("keywords", [])[:8]
            if top_kws:
                kw_parts = []
                for kw in top_kws:
                    vol = kw.get("search_volume")
                    if vol is not None:
                        kw_parts.append(f"{kw['keyword']} (vol: {vol})")
                    else:
                        kw_parts.append(kw["keyword"])
                keywords_str = ", ".join(kw_parts)

                # Add intent hint
                clusters = keyword_data.get("clusters", {})
                transactional = clusters.get("transactional", [])
                if transactional:
                    tx_names = [k.get("keyword", "") for k in transactional[:3]]
                    keywords_str += f"\nHigh-intent (transactional) keywords to prioritize: {', '.join(tx_names)}"

        prompt_data = {
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "product_description": campaign.product_description or "Not specified",
            "keywords": keywords_str,
            "angle_name": angle.angle_name,
            "value_proposition": angle.value_proposition or "",
            "emotion_target": angle.emotion_target or "",
            "visual_direction": angle.visual_direction or ""
        }

        from modules.openrouter.context import set_ai_context
        chain = self.prompt | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="ad_copy"):
            ad_json = await chain.ainvoke(prompt_data)
        cleaned_json = self._clean_json_response(ad_json)

        try:
            ad_data = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            logger.error(f"[AdCopyAgent] JSON decode error: {e}")
            ad_data = {
                "headline": "Discover Our Solutions",
                "primary_text": cleaned_json[:500] if cleaned_json else "Contact us for more information.",
                "description": "Professional solutions for your needs",
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
        angles: Optional[List[CreativeAngle]] = None,
        keyword_data: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate ad copies for all creative angles of a campaign.

        Args:
            campaign: Campaign object
            angles: Optional list of CreativeAngle objects
            keyword_data: Optional keyword intelligence with search volume, CPC, and intent clusters
        """
        db = SessionLocal()
        try:
            if not angles:
                angles = db.query(CreativeAngle).filter(
                    CreativeAngle.campaign_id == campaign.id
                ).all()

            if not angles:
                raise ValueError("No creative angles found for this campaign. Generate angles first.")

            ad_copies = []
            for angle in angles:
                ad_copy = await self.generate_ad_copy(campaign, angle, keyword_data=keyword_data)
                ad_copies.append(ad_copy)

            return ad_copies
        finally:
            db.close()


# ========== Convenience functions for direct use ==========

async def generate_ad_copy_from_website(
    research_data: Dict[str, Any],
    platforms: List[str] = None,
    include_b2b: bool = True,
    include_b2c: bool = True
) -> Dict[str, Any]:
    """
    Generate comprehensive ad copy from market research data.

    Args:
        research_data: Output from market_research_agent
        platforms: Target platforms (defaults to facebook, instagram)
        include_b2b: Generate B2B-specific copy
        include_b2c: Generate B2C-specific copy

    Returns:
        Dict containing all ad copy variations organized by audience and platform
    """
    agent = AdCopyAgent()

    if not platforms:
        platforms = ['facebook', 'instagram']

    results = {
        'company_name': research_data.get('research_summary', {}).get('company_name', 'Company'),
        'industry': research_data.get('research_summary', {}).get('industry', 'Business'),
        'ad_copy_sets': []
    }

    # Get target audiences
    extracted = research_data.get('extracted_data', {})
    target_audiences = extracted.get('target_audiences', ['General Audience'])

    for audience in target_audiences[:4]:
        # Determine audience type
        is_b2b = any(kw in audience.lower() for kw in ['corporate', 'business', 'company', 'professional', 'enterprise', 'b2b', 'client'])

        if is_b2b and not include_b2b:
            continue
        if not is_b2b and not include_b2c:
            continue

        audience_data = {
            'name': audience,
            'type': 'B2B' if is_b2b else 'B2C',
            'description': audience
        }

        for platform in platforms:
            try:
                if is_b2b:
                    ad_copy = await agent.generate_b2b_ad_copy(research_data, audience_data, platform)
                else:
                    ad_copy = await agent.generate_b2c_ad_copy(research_data, audience_data, platform)

                results['ad_copy_sets'].append({
                    'audience': audience,
                    'audience_type': 'B2B' if is_b2b else 'B2C',
                    'platform': platform,
                    'ad_copy': ad_copy
                })
            except Exception as e:
                logger.error(f"[AdCopyAgent] Error generating copy for {audience}/{platform}: {e}")

    return results


async def generate_ad_copy_for_angle(campaign_id: str, angle_id: str) -> Dict[str, Any]:
    """
    Generate ad copy for a specific angle.
    (Original function - kept for backward compatibility)
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

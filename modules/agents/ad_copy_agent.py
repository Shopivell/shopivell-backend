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
    """Enhanced AI Agent for generating high-converting ad copy"""

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="anthropic/claude-3.5-sonnet" if OPENROUTER_AVAILABLE else "gpt-4o",
            temperature=0.8
        )
        logger.info(f"[AdCopyAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

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

    def _extract_product_keywords(self, research_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract specific product/service keywords from research data.
        Returns actual product terms instead of generic industry categories.
        """
        extracted = research_data.get('extracted_data', {})
        summary = research_data.get('research_summary', {})

        # Common product keyword mappings
        product_keywords = []
        benefit_keywords = []

        # Extract from services/products
        services = extracted.get('services_products', [])
        for svc in services:
            if isinstance(svc, dict):
                desc = svc.get('description', '').lower()
                name = svc.get('name', '').lower()

                # Fashion/Clothing keywords
                if any(kw in desc or kw in name for kw in ['fashion', 'clothing', 'clothes', 'apparel', 'wear', 'dress']):
                    product_keywords.extend(['fashion', 'clothing', 'style'])
                if any(kw in desc or kw in name for kw in ['footwear', 'shoes', 'boots']):
                    product_keywords.append('footwear')
                if any(kw in desc or kw in name for kw in ['accessories', 'jewelry', 'bags']):
                    product_keywords.append('accessories')
                if any(kw in desc or kw in name for kw in ['beauty', 'cosmetics', 'skincare']):
                    product_keywords.append('beauty products')

                # Fintech/Payment keywords
                if any(kw in desc or kw in name for kw in ['payment', 'pay', 'transfer', 'transaction']):
                    product_keywords.extend(['payments', 'money transfers'])
                if any(kw in desc or kw in name for kw in ['atm', 'cash', 'withdrawal']):
                    product_keywords.append('ATM services')
                if any(kw in desc or kw in name for kw in ['pos', 'merchant', 'card']):
                    product_keywords.append('card payments')
                if any(kw in desc or kw in name for kw in ['mobile', 'p2p', 'instant']):
                    product_keywords.append('instant transfers')
                if any(kw in desc or kw in name for kw in ['online', 'e-commerce', 'ecommerce', 'gateway']):
                    product_keywords.append('online payments')
                if any(kw in desc or kw in name for kw in ['bulk', 'salary', 'disbursement', 'payroll']):
                    product_keywords.append('bulk payments')

                # Security/Surveillance keywords
                if any(kw in desc or kw in name for kw in ['security', 'surveillance', 'cctv', 'camera', 'monitor']):
                    product_keywords.extend(['security systems', 'surveillance'])
                if any(kw in desc or kw in name for kw in ['alarm', 'access control', 'intrusion']):
                    product_keywords.append('alarm systems')
                if any(kw in desc or kw in name for kw in ['guard', 'patrol', 'protection']):
                    product_keywords.append('security services')

                # Technology/Software keywords
                if any(kw in desc or kw in name for kw in ['software', 'app', 'platform', 'system']):
                    product_keywords.append('software solutions')
                if any(kw in desc or kw in name for kw in ['cloud', 'saas', 'hosting']):
                    product_keywords.append('cloud services')
                if any(kw in desc or kw in name for kw in ['invoice', 'invoicing', 'billing']):
                    product_keywords.append('invoicing tools')
                if any(kw in desc or kw in name for kw in ['crm', 'customer relationship', 'client management']):
                    product_keywords.append('CRM')
                if any(kw in desc or kw in name for kw in ['project management', 'task', 'collaboration']):
                    product_keywords.append('project management')
                if any(kw in desc or kw in name for kw in ['analytics', 'reporting', 'dashboard']):
                    product_keywords.append('business analytics')

                # Telecom keywords
                if any(kw in desc or kw in name for kw in ['voice', 'call', 'sms', 'messaging']):
                    product_keywords.append('voice and SMS')
                if any(kw in desc or kw in name for kw in ['data', 'internet', 'connectivity', 'broadband']):
                    product_keywords.append('data and internet')
                if any(kw in desc or kw in name for kw in ['5g', '4g', 'lte', 'network']):
                    product_keywords.append('mobile network')
                if any(kw in desc or kw in name for kw in ['roaming', 'international']):
                    product_keywords.append('international roaming')
                if any(kw in desc or kw in name for kw in ['gaming', 'game', 'entertainment']):
                    product_keywords.append('digital entertainment')
                if any(kw in desc or kw in name for kw in ['esim', 'sim']):
                    product_keywords.append('eSIM services')

                # Healthcare/Pharma keywords
                if any(kw in desc or kw in name for kw in ['medicine', 'pharmaceutical', 'drug', 'medication']):
                    product_keywords.append('medicines')
                if any(kw in desc or kw in name for kw in ['health', 'medical', 'healthcare']):
                    product_keywords.append('healthcare services')
                if any(kw in desc or kw in name for kw in ['distribution', 'delivery', 'supply chain']):
                    product_keywords.append('distribution services')
                if any(kw in desc or kw in name for kw in ['warehouse', 'storage', 'inventory']):
                    product_keywords.append('warehousing')

                # Service keywords
                if any(kw in desc or kw in name for kw in ['finance', 'loan', 'credit', 'microfinance']):
                    product_keywords.append('financing options')
                if any(kw in desc or kw in name for kw in ['loyalty', 'rewards', 'club', 'membership']):
                    benefit_keywords.append('loyalty rewards')

                # Benefit keywords
                if any(kw in desc for kw in ['secure', 'security', 'fraud', 'protect']):
                    benefit_keywords.append('security')
                if any(kw in desc for kw in ['instant', 'real-time', 'fast', 'quick']):
                    benefit_keywords.append('instant processing')
                if any(kw in desc for kw in ['interbank', 'any bank', 'interoperable']):
                    benefit_keywords.append('interbank access')

                # Quality/Value keywords
                if 'quality' in desc:
                    benefit_keywords.append('quality')
                if 'competitive' in desc or 'value' in desc or 'affordable' in desc:
                    benefit_keywords.append('great value')
                if 'family' in desc or 'families' in desc:
                    benefit_keywords.append('family-friendly')

        # Extract from value propositions
        value_props = extracted.get('value_propositions', [])
        for vp in value_props:
            vp_lower = vp.lower()
            if 'one-stop' in vp_lower or 'all-in-one' in vp_lower:
                benefit_keywords.append('one-stop shop')
            if 'family' in vp_lower:
                benefit_keywords.append('whole family')

        # Deduplicate
        product_keywords = list(dict.fromkeys(product_keywords))
        benefit_keywords = list(dict.fromkeys(benefit_keywords))

        # Build primary product description
        if product_keywords:
            primary_products = ', '.join(product_keywords[:3])
        else:
            # Fallback to industry but make it specific
            industry = summary.get('industry', '').lower()
            if 'fashion' in industry or 'clothing' in industry or 'retail' in industry:
                primary_products = 'fashion and clothing'
            elif 'fintech' in industry or 'payment' in industry or 'financial' in industry:
                primary_products = 'payment solutions'
            elif 'security' in industry or 'surveillance' in industry:
                primary_products = 'security solutions'
            elif 'tech' in industry or 'software' in industry:
                primary_products = 'technology solutions'
            elif 'food' in industry or 'restaurant' in industry:
                primary_products = 'food and dining'
            elif 'health' in industry or 'medical' in industry:
                primary_products = 'healthcare services'
            elif 'education' in industry or 'training' in industry:
                primary_products = 'education and training'
            elif 'consulting' in industry or 'advisory' in industry:
                primary_products = 'consulting services'
            else:
                primary_products = 'products and services'

        return {
            'product_keywords': product_keywords,
            'benefit_keywords': benefit_keywords,
            'primary_products': primary_products,
            'primary_benefit': benefit_keywords[0] if benefit_keywords else 'quality'
        }

    def _extract_audience_context(self, audience_name: str, research_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract context about an audience from its name and research data.
        Returns specific descriptors for the audience.
        """
        audience_lower = audience_name.lower()
        extracted = research_data.get('extracted_data', {})

        context = {
            'shopping_need': 'great products',
            'pain_point': 'finding what you need',
            'desire': 'quality and value',
            'demographic_hint': ''
        }

        # Income-based context
        if 'upper-income' in audience_lower or 'upper income' in audience_lower:
            context['shopping_need'] = 'premium quality'
            context['pain_point'] = 'finding exclusive, quality items'
            context['desire'] = 'style and exclusivity'
            context['demographic_hint'] = 'discerning shoppers'
        elif 'middle-income' in audience_lower or 'middle income' in audience_lower:
            context['shopping_need'] = 'quality at fair prices'
            context['pain_point'] = 'balancing quality with budget'
            context['desire'] = 'value without compromise'
            context['demographic_hint'] = 'smart shoppers'
        elif 'lower-income' in audience_lower or 'lower income' in audience_lower or 'budget' in audience_lower:
            context['shopping_need'] = 'affordable options'
            context['pain_point'] = 'stretching their budget'
            context['desire'] = 'great deals and savings'
            context['demographic_hint'] = 'value-conscious shoppers'

        # Family context
        if 'family' in audience_lower or 'families' in audience_lower:
            context['shopping_need'] = 'outfits for the whole family'
            context['pain_point'] = 'shopping at multiple stores for everyone'
            context['desire'] = 'one place for everyone'

        # Fashion context
        if 'fashion' in audience_lower or 'style' in audience_lower:
            context['shopping_need'] = 'trendy, stylish pieces'
            context['pain_point'] = 'staying fashionable on budget'
            context['desire'] = 'looking great'

        # Corporate context
        if 'corporate' in audience_lower or 'business' in audience_lower or 'workwear' in audience_lower:
            context['shopping_need'] = 'professional attire'
            context['pain_point'] = 'finding quality workwear'
            context['desire'] = 'looking professional'

        # Fintech/Payment audiences
        if 'consumer' in audience_lower and ('transfer' in audience_lower or 'payment' in audience_lower or 'money' in audience_lower):
            context['shopping_need'] = 'fast, secure money transfers'
            context['pain_point'] = 'slow bank transfers and high fees'
            context['desire'] = 'instant, affordable payments'

        if 'sme' in audience_lower or 'small' in audience_lower and 'enterprise' in audience_lower:
            context['shopping_need'] = 'efficient payment processing'
            context['pain_point'] = 'managing multiple payment channels'
            context['desire'] = 'streamlined operations'

        if 'merchant' in audience_lower or 'retailer' in audience_lower:
            context['shopping_need'] = 'reliable POS and card acceptance'
            context['pain_point'] = 'payment failures and slow settlements'
            context['desire'] = 'seamless customer payments'

        if 'bank' in audience_lower or 'fintech' in audience_lower or 'financial institution' in audience_lower:
            context['shopping_need'] = 'robust clearing infrastructure'
            context['pain_point'] = 'interoperability challenges'
            context['desire'] = 'seamless integration'

        if 'e-commerce' in audience_lower or 'online' in audience_lower:
            context['shopping_need'] = 'secure online payment gateway'
            context['pain_point'] = 'cart abandonment due to payment issues'
            context['desire'] = 'smooth checkout experience'

        # Security industry audiences
        if 'homeowner' in audience_lower or 'residential' in audience_lower or 'home' in audience_lower:
            context['shopping_need'] = 'home security systems'
            context['pain_point'] = 'worry about break-ins and safety'
            context['desire'] = 'peace of mind'

        if 'property' in audience_lower or 'estate' in audience_lower:
            context['shopping_need'] = 'property surveillance'
            context['pain_point'] = 'monitoring large areas'
            context['desire'] = 'comprehensive coverage'

        return context

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
        product_info = self._extract_product_keywords(research_data)

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
        audience_context = self._extract_audience_context(audience_segment.get('name', ''), research_data)

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
            'brand_voice': brand_voice
        }

        # Run the LLM chain
        from modules.openrouter.context import set_ai_context
        chain = self.research_based_prompt | self.llm | StrOutputParser()

        try:
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke(prompt_data)
            cleaned_json = self._clean_json_response(response)
            ad_data = json.loads(cleaned_json)

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

    def _extract_b2b_audience_context(self, audience_name: str, research_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract B2B context about an audience from its name and research data.
        """
        audience_lower = audience_name.lower()

        context = {
            'business_need': 'reliable business solutions',
            'business_challenge': 'finding quality suppliers',
            'job_titles': 'Decision makers, managers',
            'company_types': 'SMEs, enterprises'
        }

        # Corporate/Workwear context
        if 'corporate' in audience_lower or 'workwear' in audience_lower:
            context['business_need'] = 'professional workwear and uniforms'
            context['business_challenge'] = 'outfitting their workforce consistently'
            context['job_titles'] = 'HR managers, procurement officers, office managers'
            context['company_types'] = 'Corporations, government offices, schools'

        # Manufacturing/Supply context
        if 'manufacturer' in audience_lower or 'retailer' in audience_lower or 'supplier' in audience_lower:
            context['business_need'] = 'reliable manufacturing partners'
            context['business_challenge'] = 'maintaining quality supply chains'
            context['job_titles'] = 'Procurement managers, supply chain directors'
            context['company_types'] = 'Retailers, distributors, wholesalers'

        # Financial services context
        if 'finance' in audience_lower or 'credit' in audience_lower:
            context['business_need'] = 'financial services and credit solutions'
            context['business_challenge'] = 'managing cash flow and customer financing'
            context['job_titles'] = 'Finance directors, CFOs'
            context['company_types'] = 'Financial institutions, lenders'

        return context

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
        product_info = self._extract_product_keywords(research_data)
        b2b_context = self._extract_b2b_audience_context(audience_segment.get('name', ''), research_data)

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
        chain = self.b2b_prompt | self.llm | StrOutputParser()

        try:
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke(prompt_data)
            cleaned_json = self._clean_json_response(response)
            ad_data = json.loads(cleaned_json)
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
        product_info = self._extract_product_keywords(research_data)
        audience_context = self._extract_audience_context(audience_segment.get('name', ''), research_data)

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
        chain = self.b2c_prompt | self.llm | StrOutputParser()

        try:
            with set_ai_context(agent_name="ad_copy"):
                response = await chain.ainvoke(prompt_data)
            cleaned_json = self._clean_json_response(response)
            ad_data = json.loads(cleaned_json)
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

        for audience in audiences:
            audience_name = audience.get('name', 'Unknown')
            audience_type = audience.get('type', 'B2C')

            results['audiences'][audience_name] = {
                'type': audience_type,
                'platforms': {}
            }

            for platform in platforms:
                try:
                    if audience_type == 'B2B':
                        ad_copy = await self.generate_b2b_ad_copy(research_data, audience, platform)
                    else:
                        ad_copy = await self.generate_b2c_ad_copy(research_data, audience, platform)

                    results['audiences'][audience_name]['platforms'][platform] = ad_copy
                except Exception as e:
                    logger.error(f"[AdCopyAgent] Error for {audience_name}/{platform}: {e}")
                    results['audiences'][audience_name]['platforms'][platform] = {'error': str(e)}

        return results

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
        angle: CreativeAngle
    ) -> Dict[str, Any]:
        """
        Generate ad copy for a specific creative angle.
        (Original method - kept for backward compatibility)
        """
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
        angles: Optional[List[CreativeAngle]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate ad copies for all creative angles of a campaign.
        (Original method - kept for backward compatibility)
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
                ad_copy = await self.generate_ad_copy(campaign, angle)
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

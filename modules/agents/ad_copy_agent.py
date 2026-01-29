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
Industry: {industry}
Tagline: {tagline}
Years in Business: {years_in_business}
Geographic Coverage: {geographic_coverage}

PRODUCTS/SERVICES:
{services_products}

VALUE PROPOSITIONS:
{value_propositions}

KEY STATISTICS (Use as social proof):
{statistics}

TARGET AUDIENCE FOR THIS AD:
Audience Segment: {audience_segment}
Audience Type: {audience_type}
Audience Description: {audience_description}

PLATFORM: {platform}

BRAND VOICE: {brand_voice}

---

Generate ad copy optimized for {platform} with the following:

1. HOOKS (3 attention-grabbing opening lines - first 125 characters are crucial)
   - Pattern interrupt hook
   - Question hook
   - Statistics/social proof hook

2. HEADLINES (3 variations, max 40 characters each)
   - Benefit-focused
   - Curiosity-driven
   - Social proof based

3. PRIMARY TEXT (3 variations)
   For {platform}:
   - Short version (50-80 words) - for quick scrollers
   - Medium version (100-150 words) - balanced
   - Long version (200-250 words) - for high-intent audiences

   Each should include:
   - Hook in first line
   - Problem agitation
   - Solution presentation
   - Social proof/credibility
   - Clear call to action
   - NO EMOJIS unless specifically requested

4. DESCRIPTIONS (2 variations, max 30 words each)

5. CALL TO ACTION: Choose the most appropriate from:
   [Learn More, Shop Now, Sign Up, Get Quote, Contact Us, Book Now, See More]

Return as valid JSON:
{{
  "hooks": {{
    "pattern_interrupt": "Hook text here",
    "question": "Hook text here",
    "social_proof": "Hook text here"
  }},
  "headlines": [
    {{"type": "benefit", "text": "Headline 1"}},
    {{"type": "curiosity", "text": "Headline 2"}},
    {{"type": "social_proof", "text": "Headline 3"}}
  ],
  "primary_text": {{
    "short": "Short version...",
    "medium": "Medium version...",
    "long": "Long version..."
  }},
  "descriptions": ["Description 1", "Description 2"],
  "call_to_action": "Learn More",
  "audience_segment": "{audience_segment}",
  "platform": "{platform}"
}}

IMPORTANT:
- Use ACTUAL company data provided above
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
INDUSTRY: {industry}
CREDENTIALS: {credentials}
YEARS IN BUSINESS: {years_in_business}

PRODUCTS/SERVICES FOR BUSINESSES:
{services_products}

TARGET B2B AUDIENCE:
Segment: {audience_segment}
Job Titles: {job_titles}
Company Types: {company_types}
Pain Points: {pain_points}

KEY DIFFERENTIATORS:
{differentiators}

STATISTICS/SOCIAL PROOF:
{statistics}

Generate professional B2B ad copy:

1. HOOKS (3 - professional tone, no hype)
   - Industry insight hook
   - Problem-aware hook
   - ROI/results hook

2. HEADLINES (3, max 40 chars)
   - Authority-based
   - Solution-focused
   - Results-driven

3. PRIMARY TEXT (2 versions)
   - LinkedIn style (professional, detailed, 150-200 words)
   - Facebook B2B style (slightly casual, 100-150 words)

   Include:
   - Industry credibility
   - Specific solutions
   - Business outcomes
   - Professional CTA

4. DESCRIPTIONS (2 versions)

5. CALL TO ACTION: [Get Quote, Learn More, Contact Us, Schedule Demo, Download Guide]

Return as valid JSON:
{{
  "hooks": {{
    "industry_insight": "Hook text",
    "problem_aware": "Hook text",
    "roi_results": "Hook text"
  }},
  "headlines": [
    {{"type": "authority", "text": "Headline"}},
    {{"type": "solution", "text": "Headline"}},
    {{"type": "results", "text": "Headline"}}
  ],
  "primary_text": {{
    "linkedin": "LinkedIn version...",
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
INDUSTRY: {industry}
TAGLINE: {tagline}
REPUTATION: {reputation}

PRODUCTS/SERVICES FOR CONSUMERS:
{services_products}

TARGET CONSUMER AUDIENCE:
Segment: {audience_segment}
Demographics: {demographics}
Interests: {interests}
Desires: {desires}

VALUE PROPOSITIONS:
{value_propositions}

SOCIAL PROOF:
{statistics}

Generate engaging B2C ad copy:

1. HOOKS (3 - conversational, relatable)
   - Desire/aspiration hook
   - Pain point hook
   - Curiosity hook

2. HEADLINES (3, max 40 chars)
   - Benefit-focused
   - Emotional appeal
   - Offer/value based

3. PRIMARY TEXT (3 versions for testing)
   - Story-driven (personal connection, 100-150 words)
   - Benefit-list (scannable, 80-120 words)
   - Urgency-based (FOMO, limited time, 60-100 words)

   Each should feel conversational and relatable.

4. DESCRIPTIONS (2 versions)

5. CALL TO ACTION: [Shop Now, Learn More, Get Started, See Collection, Explore Now]

Return as valid JSON:
{{
  "hooks": {{
    "desire": "Hook text",
    "pain_point": "Hook text",
    "curiosity": "Hook text"
  }},
  "headlines": [
    {{"type": "benefit", "text": "Headline"}},
    {{"type": "emotional", "text": "Headline"}},
    {{"type": "offer", "text": "Headline"}}
  ],
  "primary_text": {{
    "story": "Story version...",
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
        industry = summary.get('industry') or company_info.get('industry') or 'Business'
        tagline = company_info.get('tagline') or summary.get('tagline') or ''

        # Calculate years in business from statistics or key features
        years_in_business = "Established"
        for stat in extracted.get('statistics', []):
            if 'founded' in str(stat.get('metric', '')).lower() or 'year' in str(stat.get('metric', '')).lower():
                years_in_business = f"Since {stat.get('value', '')}"
                break

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
                'description': 'Customers interested in ' + industry.lower()
            }

        prompt_data = {
            'company_name': company_name,
            'industry': industry,
            'tagline': tagline,
            'years_in_business': years_in_business,
            'geographic_coverage': company_info.get('geographic_coverage', summary.get('geographic_coverage', '')),
            'services_products': services_products,
            'value_propositions': value_propositions,
            'statistics': statistics,
            'audience_segment': audience_segment.get('name', 'Target Audience'),
            'audience_type': audience_segment.get('type', 'B2C'),
            'audience_description': audience_segment.get('description', ''),
            'platform': platform,
            'brand_voice': brand_voice
        }

        # Run the LLM chain
        chain = self.research_based_prompt | self.llm | StrOutputParser()

        try:
            response = await chain.ainvoke(prompt_data)
            cleaned_json = self._clean_json_response(response)
            ad_data = json.loads(cleaned_json)

            # Add metadata
            ad_data['company_name'] = company_name
            ad_data['industry'] = industry
            ad_data['generated_from'] = 'market_research'

            logger.info(f"[AdCopyAgent] Generated ad copy for {company_name}")
            return ad_data

        except json.JSONDecodeError as e:
            logger.error(f"[AdCopyAgent] JSON decode error: {e}")
            return self._fallback_ad_copy(company_name, industry, services_products, platform)
        except Exception as e:
            logger.error(f"[AdCopyAgent] Error generating ad copy: {e}")
            return self._fallback_ad_copy(company_name, industry, services_products, platform)

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

        prompt_data = {
            'company_name': summary.get('company_name', 'Company'),
            'industry': summary.get('industry', 'Business'),
            'credentials': ", ".join(extracted.get('certifications_awards', [])[:3]) or 'Industry leader',
            'years_in_business': self._extract_years(extracted.get('statistics', [])),
            'services_products': self._extract_services_string(extracted.get('services_products', [])),
            'audience_segment': audience_segment.get('name', 'Business Professionals'),
            'job_titles': audience_segment.get('job_titles', 'Decision makers, managers'),
            'company_types': audience_segment.get('company_types', 'SMEs, enterprises'),
            'pain_points': audience_segment.get('pain_points', 'Efficiency, cost, quality'),
            'differentiators': "\n".join([f"- {vp}" for vp in extracted.get('value_propositions', [])[:4]]),
            'statistics': self._extract_statistics_string(extracted.get('statistics', []))
        }

        chain = self.b2b_prompt | self.llm | StrOutputParser()

        try:
            response = await chain.ainvoke(prompt_data)
            cleaned_json = self._clean_json_response(response)
            ad_data = json.loads(cleaned_json)
            ad_data['generated_from'] = 'b2b_research'
            return ad_data
        except Exception as e:
            logger.error(f"[AdCopyAgent] B2B copy error: {e}")
            return self._fallback_b2b_copy(prompt_data)

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

        prompt_data = {
            'company_name': summary.get('company_name', 'Company'),
            'industry': summary.get('industry', 'Business'),
            'tagline': company_info.get('tagline', ''),
            'reputation': f"{self._extract_years(extracted.get('statistics', []))} of trusted service",
            'services_products': self._extract_services_string(extracted.get('services_products', [])),
            'audience_segment': audience_segment.get('name', 'Consumers'),
            'demographics': audience_segment.get('demographics', 'Adults 25-54'),
            'interests': audience_segment.get('interests', 'Quality, value, convenience'),
            'desires': audience_segment.get('desires', 'Better lifestyle, savings, quality'),
            'value_propositions': "\n".join([f"- {vp}" for vp in extracted.get('value_propositions', [])[:4]]),
            'statistics': self._extract_statistics_string(extracted.get('statistics', []))
        }

        chain = self.b2c_prompt | self.llm | StrOutputParser()

        try:
            response = await chain.ainvoke(prompt_data)
            cleaned_json = self._clean_json_response(response)
            ad_data = json.loads(cleaned_json)
            ad_data['generated_from'] = 'b2c_research'
            return ad_data
        except Exception as e:
            logger.error(f"[AdCopyAgent] B2C copy error: {e}")
            return self._fallback_b2c_copy(prompt_data)

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

    def _fallback_ad_copy(self, company_name: str, industry: str, services: str, platform: str) -> Dict[str, Any]:
        """Fallback ad copy when AI generation fails"""
        return {
            "hooks": {
                "pattern_interrupt": f"Looking for quality {industry.lower()}?",
                "question": f"Need a trusted {industry.lower()} partner?",
                "social_proof": f"{company_name} - Your trusted choice"
            },
            "headlines": [
                {"type": "benefit", "text": f"Quality {industry} Solutions"},
                {"type": "curiosity", "text": f"Discover {company_name}"},
                {"type": "social_proof", "text": f"Trusted {industry} Leader"}
            ],
            "primary_text": {
                "short": f"{company_name} offers quality {industry.lower()} solutions. Contact us today.",
                "medium": f"{company_name} is your trusted partner for {industry.lower()}. We deliver quality and value. Contact us today to learn more.",
                "long": f"{company_name} provides comprehensive {industry.lower()} solutions designed to meet your needs. With our commitment to quality and customer satisfaction, we're your trusted partner. Contact us today."
            },
            "descriptions": [
                f"Quality {industry.lower()} from {company_name}",
                f"Trusted {industry.lower()} solutions"
            ],
            "call_to_action": "Learn More",
            "platform": platform,
            "generated_from": "fallback"
        }

    def _fallback_b2b_copy(self, data: Dict) -> Dict[str, Any]:
        """Fallback B2B copy"""
        return {
            "hooks": {
                "industry_insight": f"Transform your {data.get('industry', 'business')} operations",
                "problem_aware": "Struggling with efficiency?",
                "roi_results": "See measurable results"
            },
            "headlines": [
                {"type": "authority", "text": "Industry-Leading Solutions"},
                {"type": "solution", "text": "Streamline Your Operations"},
                {"type": "results", "text": "Drive Business Growth"}
            ],
            "primary_text": {
                "linkedin": f"{data.get('company_name', 'We')} provides professional {data.get('industry', 'business')} solutions for organizations seeking quality and efficiency.",
                "facebook": f"Looking for a trusted {data.get('industry', 'business')} partner? {data.get('company_name', 'We')} delivers results."
            },
            "descriptions": ["Professional solutions", "Trusted partner"],
            "call_to_action": "Get Quote",
            "audience_type": "B2B",
            "generated_from": "fallback"
        }

    def _fallback_b2c_copy(self, data: Dict) -> Dict[str, Any]:
        """Fallback B2C copy"""
        return {
            "hooks": {
                "desire": f"Get the {data.get('industry', 'quality')} you deserve",
                "pain_point": "Tired of settling for less?",
                "curiosity": "Discover something better"
            },
            "headlines": [
                {"type": "benefit", "text": "Quality You Can Trust"},
                {"type": "emotional", "text": "You Deserve the Best"},
                {"type": "offer", "text": "Great Value Awaits"}
            ],
            "primary_text": {
                "story": f"At {data.get('company_name', 'our store')}, we believe everyone deserves quality.",
                "benefits": f"Quality products. Great prices. Trusted service. That's {data.get('company_name', 'us')}.",
                "urgency": f"Don't miss out on {data.get('company_name', 'our')} amazing offerings."
            },
            "descriptions": ["Quality and value", "Shop with confidence"],
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

        chain = self.prompt | self.llm | StrOutputParser()
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

# modules/campaigns/service.py
"""
Campaign service for URL scraping, ad generation, and campaign management.
"""
import os
import json
import re
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from tavily import TavilyClient
from openai import OpenAI
from dotenv import load_dotenv
import uuid

from .models import UrlCampaign, CampaignStatus, CampaignGoal, UrlAdSet, UrlAdContent
from modules.ad_generator.service import AdGeneratorService
from modules.ad_generator.schemas import GenerateAdRequest, AdStyle, AdFormat, AdPlatform
from modules.agents.ad_creative_agent import AdCreativeAgent

# Aliases for readability
Campaign = UrlCampaign
AdSet = UrlAdSet
AdContent = UrlAdContent

load_dotenv()

# Initialize clients
tavily_api_key = os.getenv("TAVILY_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")


class CampaignService:
    def __init__(self, db: Session):
        self.db = db
        self.tavily = TavilyClient(api_key=tavily_api_key) if tavily_api_key else None
        self.openai = OpenAI(api_key=openai_api_key) if openai_api_key else None
        self.ad_generator = AdGeneratorService()
        self.ad_creative_agent = AdCreativeAgent()

    def scrape_url_for_campaign(self, url: str, store_id: uuid.UUID, campaign_name: Optional[str] = None) -> Tuple[Campaign, Optional[str]]:
        """
        Scrape a URL and create a campaign with the extracted data.
        Returns (campaign, error_message)
        """
        try:
            # Create campaign in ANALYZING status
            campaign = Campaign(
                store_id=store_id,
                name=campaign_name or self._extract_domain_name(url),
                source_url=url,
                source_type="url",
                status=CampaignStatus.ANALYZING
            )
            self.db.add(campaign)
            self.db.commit()
            self.db.refresh(campaign)

            # Scrape the URL
            scraped_data = self._scrape_website(url)

            if not scraped_data:
                campaign.status = CampaignStatus.FAILED
                campaign.error_message = "Failed to scrape website content"
                self.db.commit()
                return campaign, "Failed to scrape website"

            # Update campaign with scraped data
            campaign.scraped_data = scraped_data
            campaign.scraped_at = datetime.utcnow()

            # Generate ad content
            ad_content = self._generate_ad_content(scraped_data, url)
            if ad_content:
                campaign.generated_headlines = ad_content.get("headlines", [])
                campaign.generated_descriptions = ad_content.get("descriptions", [])

                # Create ad sets
                self._create_ad_sets(campaign, ad_content)

            campaign.status = CampaignStatus.READY
            self.db.commit()
            self.db.refresh(campaign)

            return campaign, None

        except Exception as e:
            self.db.rollback()
            if 'campaign' in locals():
                campaign.status = CampaignStatus.FAILED
                campaign.error_message = str(e)
                self.db.commit()
            return None, str(e)

    def _scrape_website(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape website content using Tavily."""
        if not self.tavily:
            return self._mock_scrape_data(url)

        try:
            base_url = url.rstrip('/')
            if not base_url.startswith('http'):
                base_url = 'https://' + base_url

            domain = base_url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

            # Extract main page and common pages
            urls_to_extract = [base_url]
            for page in ['/about', '/services', '/products', '/features']:
                urls_to_extract.append(base_url + page)

            all_content = []

            # Try direct extraction
            try:
                extract_result = self.tavily.extract(urls=urls_to_extract)
                if extract_result and extract_result.get("results"):
                    for result in extract_result["results"]:
                        content = result.get("raw_content", "")
                        if content:
                            all_content.append(content)
            except Exception as e:
                print(f"[Tavily] Extraction error: {e}")

            # Fallback to search
            if not all_content:
                try:
                    search_result = self.tavily.search(
                        query=f"{domain} products services features",
                        search_depth="advanced",
                        include_raw_content=True,
                        max_results=5,
                        include_domains=[domain]
                    )
                    for result in search_result.get("results", []):
                        content = result.get("raw_content") or result.get("content", "")
                        if content and domain in result.get("url", ""):
                            all_content.append(content)
                except Exception as e:
                    print(f"[Tavily] Search error: {e}")

            combined_content = "\n\n".join(all_content)

            if not combined_content:
                return self._mock_scrape_data(url)

            return {
                "url": url,
                "domain": domain,
                "content": combined_content[:20000],  # Limit content
                "extracted_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            print(f"[Scraping] Error: {e}")
            return self._mock_scrape_data(url)

    def _generate_ad_content(self, scraped_data: Dict[str, Any], url: str) -> Optional[Dict[str, Any]]:
        """Generate ad content using OpenAI."""
        if not self.openai:
            return self._mock_ad_content(url)

        content = scraped_data.get("content", "")
        domain = scraped_data.get("domain", "")

        prompt = f"""You are an expert digital marketing specialist. Analyze this website content and generate ad campaign materials.

Website URL: {url}
Domain: {domain}

CONTENT:
{content[:10000]}

Generate the following:

1. HEADLINES (5 different attention-grabbing headlines for ads, max 40 chars each)
2. DESCRIPTIONS (5 different ad descriptions, max 125 chars each)
3. AD_SETS (5 different audience segments with):
   - name: Segment name (e.g., "Security Professionals")
   - title: Ad set title
   - audience_tags: List of 10-15 interest/behavior targeting tags
   - primary_text: The main ad copy (50-100 words)
   - features: List of 3-4 key selling points

Return as JSON:
{{
    "business_name": "...",
    "business_type": "...",
    "headlines": ["...", "...", "...", "...", "..."],
    "descriptions": ["...", "...", "...", "...", "..."],
    "ad_sets": [
        {{
            "name": "...",
            "title": "...",
            "audience_tags": ["...", "..."],
            "primary_text": "...",
            "features": ["...", "...", "..."]
        }}
    ]
}}

Return ONLY valid JSON, no markdown.
"""

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a digital marketing expert. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=3000
            )

            result_text = response.choices[0].message.content.strip()

            # Clean markdown
            if result_text.startswith("```"):
                result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
                result_text = re.sub(r'\n?```$', '', result_text)

            return json.loads(result_text)

        except Exception as e:
            print(f"[AI] Generation error: {e}")
            return self._mock_ad_content(url)

    def _create_ad_sets(self, campaign: Campaign, ad_content: Dict[str, Any]):
        """Create ad sets from generated content with AI-generated images using Ad Creative Agent."""
        ad_sets_data = ad_content.get("ad_sets", [])
        business_name = ad_content.get("business_name", "Business")

        # Different styles for variety
        styles = [AdStyle.MODERN, AdStyle.VIBRANT, AdStyle.PROFESSIONAL, AdStyle.ELEGANT, AdStyle.BOLD]

        for i, ad_set_data in enumerate(ad_sets_data[:5]):
            ad_set = AdSet(
                campaign_id=campaign.id,
                name=ad_set_data.get("name", f"Ad Set {i+1}"),
                title=ad_set_data.get("title", ""),
                audience_tags=ad_set_data.get("audience_tags", []),
                daily_budget=campaign.daily_budget / max(len(ad_sets_data), 1),
                is_selected=True
            )
            self.db.add(ad_set)
            self.db.flush()

            # Get base content
            headline = ad_content.get("headlines", [""])[i] if i < len(ad_content.get("headlines", [])) else business_name
            description = ad_content.get("descriptions", [""])[i] if i < len(ad_content.get("descriptions", [])) else ""
            primary_text = ad_set_data.get("primary_text", "")
            features = ad_set_data.get("features", [])
            visual_direction = ad_set_data.get("visual_direction", "")

            generated_image_base64 = None
            agent_ad_angle = None
            agent_headline = None

            try:
                # Step 1: Use Ad Creative Agent to generate image prompt and ad angle
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Generate creative with agent
                    print(f"[AdCreativeAgent] Generating creative for ad set: {ad_set.name}")
                    creative = loop.run_until_complete(
                        self.ad_creative_agent.generate_ad_creative(
                            product_name=business_name,
                            product_description=primary_text or description or f"{business_name} - {headline}",
                            target_audience=ad_set_data.get("name", "General audience"),
                            key_benefits=features[:3] if features else None,
                            call_to_action=campaign.conversion_button or "Learn More",
                            angle_name=ad_set_data.get("name", f"Ad Set {i+1}"),
                            angle_value_proposition=ad_set_data.get("value_proposition", ""),
                            angle_emotion=ad_set_data.get("emotion", "Interest"),
                            visual_direction=visual_direction
                        )
                    )

                    # Get the agent's outputs
                    agent_image_prompt = creative.get("image_prompt", "")
                    agent_ad_angle = creative.get("ad_angle", "")
                    agent_headline = creative.get("headline", "")

                    print(f"[AdCreativeAgent] Generated prompt: {agent_image_prompt[:100]}...")
                    print(f"[AdCreativeAgent] Generated ad angle: {agent_ad_angle[:100]}...")

                    # Step 2: Generate image using the agent's prompt
                    ad_request = GenerateAdRequest(
                        product_name=business_name,
                        product_description=primary_text or description or f"{business_name} - {headline}",
                        target_audience=ad_set_data.get("name", "General"),
                        key_benefits=features[:3] if features else None,
                        call_to_action=campaign.conversion_button or "Learn More",
                        style=styles[i % len(styles)],
                        format=AdFormat.SQUARE,
                        platform=AdPlatform.FACEBOOK,
                        include_text_overlay=True,
                        agent_prompt=agent_image_prompt  # Use the agent's prompt
                    )

                    result = loop.run_until_complete(self.ad_generator.generate_ad(ad_request))
                    if result.success and result.image_base64:
                        generated_image_base64 = result.image_base64
                        print(f"[AdGenerator] Generated image for ad set: {ad_set.name}")

                finally:
                    loop.close()

            except Exception as e:
                print(f"[AdCreativeAgent/AdGenerator] Error for ad set {i+1}: {e}")

            # Create ad content with generated image and agent's ad angle
            ad_content_obj = AdContent(
                ad_set_id=ad_set.id,
                headline=agent_headline or headline,  # Use agent's headline if available
                primary_text=agent_ad_angle or primary_text,  # Use agent's ad angle as primary text
                description=description,
                call_to_action=campaign.conversion_button,
                destination_url=campaign.source_url,
                is_primary=True,
                generated_image_base64=generated_image_base64
            )
            self.db.add(ad_content_obj)

    def _extract_domain_name(self, url: str) -> str:
        """Extract readable name from URL."""
        domain = url.lower()
        domain = re.sub(r'^https?://', '', domain)
        domain = re.sub(r'^www\.', '', domain)
        domain = domain.split('/')[0]
        domain = domain.split('.')[0]
        return f"{domain.capitalize()} Campaign"

    def _mock_scrape_data(self, url: str) -> Dict[str, Any]:
        """Generate mock data when scraping is unavailable."""
        domain = self._extract_domain_name(url).replace(" Campaign", "")
        return {
            "url": url,
            "domain": domain.lower(),
            "content": f"Welcome to {domain}. We provide quality products and services.",
            "extracted_at": datetime.utcnow().isoformat(),
            "is_mock": True
        }

    def _mock_ad_content(self, url: str) -> Dict[str, Any]:
        """Generate mock ad content."""
        domain = self._extract_domain_name(url).replace(" Campaign", "")
        return {
            "business_name": domain,
            "business_type": "Business",
            "headlines": [
                f"Discover {domain} Today",
                f"Premium {domain} Solutions",
                f"Transform with {domain}",
                f"Choose {domain} Excellence",
                f"{domain} - Your Best Choice"
            ],
            "descriptions": [
                f"Experience the best of {domain}. Quality products and exceptional service.",
                f"Join thousands who trust {domain}. Start your journey today.",
                f"Premium solutions from {domain}. Results you can count on.",
                f"Discover why {domain} is the industry leader.",
                f"Transform your experience with {domain}'s expert solutions."
            ],
            "ad_sets": [
                {
                    "name": "Professionals",
                    "title": "Industry Professionals",
                    "audience_tags": ["Business", "Professional", "Management", "Technology"],
                    "primary_text": f"Discover how {domain} can transform your business with our premium solutions.",
                    "features": ["Premium Quality", "Expert Support", "Fast Delivery"]
                },
                {
                    "name": "Small Business",
                    "title": "Small Business Owners",
                    "audience_tags": ["Entrepreneur", "Small Business", "Startup", "E-commerce"],
                    "primary_text": f"Scale your business with {domain}'s affordable solutions.",
                    "features": ["Affordable Pricing", "Easy Setup", "24/7 Support"]
                },
                {
                    "name": "Enterprise",
                    "title": "Enterprise Decision Makers",
                    "audience_tags": ["Enterprise", "Corporate", "C-Suite", "IT Director"],
                    "primary_text": f"Enterprise-grade solutions from {domain} for your organization.",
                    "features": ["Enterprise Security", "Scalable", "Custom Solutions"]
                },
                {
                    "name": "Tech Savvy",
                    "title": "Technology Enthusiasts",
                    "audience_tags": ["Technology", "Innovation", "Digital", "Software"],
                    "primary_text": f"Stay ahead with {domain}'s cutting-edge technology solutions.",
                    "features": ["Latest Technology", "Innovation", "Future-Ready"]
                },
                {
                    "name": "Value Seekers",
                    "title": "Budget-Conscious Buyers",
                    "audience_tags": ["Deals", "Savings", "Value", "Smart Shopping"],
                    "primary_text": f"Get the best value with {domain}'s competitive pricing.",
                    "features": ["Best Value", "Money-Back Guarantee", "Free Trial"]
                }
            ]
        }

    def publish_campaign(self, campaign_id: uuid.UUID) -> Tuple[Campaign, Optional[str]]:
        """Publish a campaign (would integrate with ad platforms)."""
        campaign = self.db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return None, "Campaign not found"

        if campaign.status != CampaignStatus.READY:
            return None, f"Campaign cannot be published in {campaign.status} status"

        # Here you would integrate with Facebook/Google Ads APIs
        # For now, just update status
        campaign.status = CampaignStatus.ACTIVE
        campaign.published_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(campaign)

        return campaign, None

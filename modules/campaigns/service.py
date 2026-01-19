# modules/campaigns/service.py
"""
Campaign service for URL scraping, ad generation, and campaign management.
Uses OpenRouter API for AI-powered content generation.
"""
import os
import json
import re
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from tavily import TavilyClient
from dotenv import load_dotenv
import uuid
import logging

from .models import UrlCampaign, CampaignStatus, CampaignGoal, UrlAdSet, UrlAdContent
from modules.ad_generator.service import AdGeneratorService
from modules.ad_generator.schemas import GenerateAdRequest, AdStyle, AdFormat, AdPlatform
from modules.agents.ad_creative_agent import AdCreativeAgent
from modules.agents.media_generator_agent import MediaGeneratorAgent

# Import OpenRouter for AI generation
try:
    from modules.openrouter import OpenRouterClient, OPENROUTER_API_KEY
    OPENROUTER_AVAILABLE = bool(OPENROUTER_API_KEY)
except ImportError:
    OPENROUTER_AVAILABLE = False

# Keep OpenAI as fallback
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

# Aliases for readability
Campaign = UrlCampaign
AdSet = UrlAdSet
AdContent = UrlAdContent

load_dotenv()

# Initialize clients
tavily_api_key = os.getenv("TAVILY_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")

# Use OpenRouter by default
USE_OPENROUTER = os.getenv("USE_OPENROUTER", "true").lower() == "true"


class CampaignService:
    def __init__(self, db: Session):
        self.db = db
        self.tavily = TavilyClient(api_key=tavily_api_key) if tavily_api_key else None
        self.openrouter = None
        self.openai = None
        self._init_ai_clients()
        self.ad_generator = AdGeneratorService()
        self.ad_creative_agent = AdCreativeAgent()
        self.media_generator = MediaGeneratorAgent()  # Primary image generator

    def _init_ai_clients(self):
        """Initialize AI clients (OpenRouter preferred, OpenAI fallback)"""
        # Try OpenRouter first
        if USE_OPENROUTER and OPENROUTER_AVAILABLE:
            try:
                self.openrouter = OpenRouterClient()
                logger.info("[CampaignService] OpenRouter client initialized")
            except Exception as e:
                logger.warning(f"[CampaignService] Failed to initialize OpenRouter: {e}")

        # Initialize OpenAI as fallback
        if OPENAI_AVAILABLE and openai_api_key:
            try:
                self.openai = OpenAI(api_key=openai_api_key)
                logger.info("[CampaignService] OpenAI client initialized as fallback")
            except Exception as e:
                logger.warning(f"[CampaignService] Failed to initialize OpenAI: {e}")

    def scrape_url_for_campaign(self, url: str, store_id: uuid.UUID, campaign_name: Optional[str] = None, asset_ids: Optional[List[uuid.UUID]] = None) -> Tuple[Campaign, Optional[str]]:
        """
        Scrape a URL and create a campaign with the extracted data.
        Returns (campaign, error_message)

        Args:
            url: The URL to scrape
            store_id: The store ID
            campaign_name: Optional custom campaign name
            asset_ids: Optional list of user-provided asset IDs to use in ad generation
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

            # Store user-provided asset IDs in scraped_data for later use
            if asset_ids:
                scraped_data["user_asset_ids"] = [str(aid) for aid in asset_ids]
                campaign.scraped_data = scraped_data

            # Get store information for context-aware ad generation
            store = campaign.store
            store_context = None
            if store:
                store_context = {
                    "store_name": store.store_name,
                    "business_type": store.business_type,
                    "store_description": store.store_description,
                    "services_products": store.services_products if hasattr(store, 'services_products') else None,
                }
                logger.info(f"[CampaignService] Using store context: {store_context.get('business_type')}")

            # Generate ad content with store context
            ad_content = self._generate_ad_content(scraped_data, url, store_context)
            if ad_content:
                campaign.generated_headlines = ad_content.get("headlines", [])
                campaign.generated_descriptions = ad_content.get("descriptions", [])

                # Create ad sets (will use user assets if available)
                self._create_ad_sets(campaign, ad_content, asset_ids)

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
        """Scrape website content using Tavily - extracts from multiple pages for complete picture."""
        if not self.tavily:
            return self._mock_scrape_data(url)

        try:
            base_url = url.rstrip('/')
            if not base_url.startswith('http'):
                base_url = 'https://' + base_url

            domain = base_url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
            print(f"[Tavily] Scraping {domain} - extracting from multiple pages...")

            # Priority pages to extract (Tavily limit is 20 URLs)
            # Ordered by importance for understanding the business
            priority_pages = [
                '',  # Homepage (most important)
                '/about', '/about-us',
                '/products', '/our-products',
                '/services', '/our-services',
                '/brands', '/our-brands',
                '/our-companies',  # For holding companies
                '/subsidiaries',
                '/businesses',
                '/divisions',
                '/menu',  # For restaurants
                '/food', '/restaurant',
                '/shop', '/store',
            ]

            # Build URLs to extract (max 15 to stay under Tavily's 20 limit)
            urls_to_extract = []
            for page in priority_pages[:15]:
                urls_to_extract.append(base_url + page)

            all_content = []
            extracted_pages = []

            # Try direct extraction from multiple pages
            try:
                print(f"[Tavily] Attempting to extract from {len(urls_to_extract)} URLs...")
                extract_result = self.tavily.extract(urls=urls_to_extract)
                if extract_result and extract_result.get("results"):
                    for result in extract_result["results"]:
                        content = result.get("raw_content", "")
                        page_url = result.get("url", "")
                        if content and len(content) > 100:
                            all_content.append(f"=== PAGE: {page_url} ===\n{content}")
                            extracted_pages.append(page_url)
                    print(f"[Tavily] Successfully extracted {len(extracted_pages)} pages")
            except Exception as e:
                print(f"[Tavily] Extraction error: {e}")

            # Always also do a search for products/services to get more context
            try:
                print(f"[Tavily] Searching for {domain} products and services...")
                search_queries = [
                    f"site:{domain} products services what we offer",
                    f"{domain} company about products brands",
                ]

                for query in search_queries:
                    search_result = self.tavily.search(
                        query=query,
                        search_depth="advanced",
                        include_raw_content=True,
                        max_results=5
                    )
                    for result in search_result.get("results", []):
                        content = result.get("raw_content") or result.get("content", "")
                        result_url = result.get("url", "")
                        # Include results from the domain or about the domain
                        if content and len(content) > 100:
                            if domain in result_url or result_url not in extracted_pages:
                                all_content.append(f"=== SEARCH RESULT: {result_url} ===\n{content}")
                print(f"[Tavily] Search complete, total content sources: {len(all_content)}")
            except Exception as e:
                print(f"[Tavily] Search error: {e}")

            combined_content = "\n\n".join(all_content)

            if not combined_content:
                print(f"[Tavily] No content found, using mock data")
                return self._mock_scrape_data(url)

            print(f"[Tavily] Scraping complete - {len(combined_content)} chars from {len(all_content)} sources")

            return {
                "url": url,
                "domain": domain,
                "content": combined_content[:25000],  # Increased limit for more context
                "pages_extracted": len(all_content),
                "extracted_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            print(f"[Scraping] Error: {e}")
            return self._mock_scrape_data(url)

    def _generate_ad_content(self, scraped_data: Dict[str, Any], url: str, store_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Generate ad content using OpenRouter (preferred) or OpenAI.

        Args:
            scraped_data: Data scraped from the website
            url: The source URL
            store_context: Optional dict with store_name, business_type, store_description, services_products
        """
        content = scraped_data.get("content", "")
        domain = scraped_data.get("domain", "")
        pages_extracted = scraped_data.get("pages_extracted", 1)

        # Build store context section if available
        store_info_section = ""
        if store_context:
            store_name = store_context.get("store_name", "")
            business_type = store_context.get("business_type", "")
            store_description = store_context.get("store_description", "")
            services_products = store_context.get("services_products", "")

            store_info_section = f"""
KNOWN STORE INFORMATION (USE THIS AS PRIMARY CONTEXT):
- Store Name: {store_name}
- Business Type: {business_type}
- Store Description: {store_description}
- Services/Products: {services_products}

IMPORTANT: This is a {business_type.upper() if business_type else 'BUSINESS'}.
Generate ALL ad content specifically for this industry.
Audience tags, headlines, and ad copy MUST be relevant to {business_type or 'the business'}.
"""

        prompt = f"""You are an expert digital marketing specialist. Your task is to analyze this business and create compelling Facebook/Instagram ad campaigns.
{store_info_section}
CRITICAL INSTRUCTIONS:
1. FIRST, identify what this business ACTUALLY SELLS or OFFERS (products, services, brands)
2. Use the store information above as the PRIMARY source of truth about what this business does
3. Generate ads that are SPECIFIC to the industry/business type - NOT generic marketing content
4. All audience tags must be relevant to potential customers for THIS SPECIFIC business type
5. Headlines and descriptions must mention the actual products/services offered

Website URL: {url}
Domain: {domain}
Pages Scraped: {pages_extracted}

WEBSITE CONTENT (from multiple pages):
{content[:15000]}

STEP 1 - BUSINESS ANALYSIS:
First, identify:
- What does this business actually sell? (products, services, food, software, etc.)
- What brands or product lines do they have?
- Who are their customers?
- What problems do they solve?

STEP 2 - GENERATE AD CONTENT:
Based on your analysis, generate:

1. HEADLINES (5 different attention-grabbing headlines for ads, max 40 chars each)
   - Focus on products/services, not corporate values
   - Use action words and benefits
   - DO NOT add emojis to headlines - keep them clean and professional

2. DESCRIPTIONS (5 different ad descriptions, max 125 chars each)
   - Highlight what customers can buy or experience
   - Include a call to action
   - DO NOT add random emojis - keep copy professional

3. AD_SETS (5 different audience segments with):
   - name: Segment name based on who would buy these products/services
   - title: Ad set title featuring actual products/services
   - audience_tags: List of 10-15 Facebook interest/behavior targeting tags relevant to buyers
   - primary_text: Compelling ad copy (50-100 words) promoting actual offerings
   - features: List of 3-4 key benefits customers get
   - hashtags: List of 5-8 relevant hashtags for social media (without # symbol)

IMPORTANT: You MUST generate exactly 5 different ad sets targeting different audience segments.

Return as JSON:
{{
    "business_name": "...",
    "business_type": "...",
    "products_services": ["product1", "product2", "product3"],
    "brands": ["brand1", "brand2"],
    "headlines": ["headline1", "headline2", "headline3", "headline4", "headline5"],
    "descriptions": ["desc1", "desc2", "desc3", "desc4", "desc5"],
    "ad_sets": [
        {{
            "name": "Audience Segment 1",
            "title": "Ad Title for Segment 1",
            "audience_tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
            "primary_text": "Compelling ad copy for segment 1...",
            "features": ["benefit1", "benefit2", "benefit3"],
            "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
        }},
        {{
            "name": "Audience Segment 2",
            "title": "Ad Title for Segment 2",
            "audience_tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
            "primary_text": "Compelling ad copy for segment 2...",
            "features": ["benefit1", "benefit2", "benefit3"],
            "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
        }},
        {{
            "name": "Audience Segment 3",
            "title": "Ad Title for Segment 3",
            "audience_tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
            "primary_text": "Compelling ad copy for segment 3...",
            "features": ["benefit1", "benefit2", "benefit3"],
            "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
        }},
        {{
            "name": "Audience Segment 4",
            "title": "Ad Title for Segment 4",
            "audience_tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
            "primary_text": "Compelling ad copy for segment 4...",
            "features": ["benefit1", "benefit2", "benefit3"],
            "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
        }},
        {{
            "name": "Audience Segment 5",
            "title": "Ad Title for Segment 5",
            "audience_tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
            "primary_text": "Compelling ad copy for segment 5...",
            "features": ["benefit1", "benefit2", "benefit3"],
            "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
        }}
    ]
}}

Return ONLY valid JSON, no markdown.
"""

        # Try OpenRouter first
        if self.openrouter:
            result = self._generate_with_openrouter(prompt)
            if result:
                return result
            logger.warning("[CampaignService] OpenRouter failed, trying OpenAI fallback")

        # Fall back to OpenAI
        if self.openai:
            result = self._generate_with_openai(prompt)
            if result:
                return result

        # Final fallback to mock data
        logger.warning("[CampaignService] No AI client available, using mock data")
        return self._mock_ad_content(url, store_context)

    def _generate_with_openrouter(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Generate content using OpenRouter API."""
        try:
            logger.info("[CampaignService] Generating ad content with OpenRouter...")

            # Use synchronous version for compatibility
            result = self.openrouter.chat_completion_sync(
                messages=[
                    {"role": "system", "content": "You are a digital marketing expert. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000,  # Increased for complex companies with many brands
                response_format={"type": "json_object"}
            )

            result_text = result['choices'][0]['message']['content'].strip()

            # Clean markdown if present
            if result_text.startswith("```"):
                result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
                result_text = re.sub(r'\n?```$', '', result_text)

            parsed = json.loads(result_text)
            logger.info("[CampaignService] OpenRouter generated ad content successfully")
            return parsed

        except Exception as e:
            logger.error(f"[CampaignService] OpenRouter generation error: {e}")
            return None

    def _generate_with_openai(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Generate content using OpenAI API (fallback)."""
        try:
            logger.info("[CampaignService] Generating ad content with OpenAI...")

            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a digital marketing expert. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000  # Increased for complex companies with many brands
            )

            result_text = response.choices[0].message.content.strip()

            # Clean markdown
            if result_text.startswith("```"):
                result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
                result_text = re.sub(r'\n?```$', '', result_text)

            parsed = json.loads(result_text)
            logger.info("[CampaignService] OpenAI generated ad content successfully")
            return parsed

        except Exception as e:
            logger.error(f"[CampaignService] OpenAI generation error: {e}")
            return None

    def _create_ad_sets(self, campaign: Campaign, ad_content: Dict[str, Any], asset_ids: Optional[List[uuid.UUID]] = None):
        """Create ad sets from generated content with AI-generated images using Ad Creative Agent.

        If user provides assets via asset_ids, those will be used instead of generating AI images.
        Images are generated with store branding (logo, color theme) when available.
        """
        ad_sets_data = ad_content.get("ad_sets", [])
        business_name = ad_content.get("business_name", "Business")

        # Get store branding information
        store = campaign.store
        store_logo_url = store.logo_url if store else None
        store_color_theme = store.color_theme if store else None
        store_name = store.store_name if store else business_name
        store_description = store.store_description if store else None
        store_business_type = store.business_type if store else None

        # Map business type to industry template
        industry_mapping = {
            "security": "security",
            "security services": "security",
            "security company": "security",
            "food": "food_restaurant",
            "restaurant": "food_restaurant",
            "cafe": "food_restaurant",
            "retail": "retail_ecommerce",
            "ecommerce": "retail_ecommerce",
            "e-commerce": "retail_ecommerce",
            "shop": "retail_ecommerce",
            "tech": "tech_saas",
            "saas": "tech_saas",
            "software": "tech_saas",
            "technology": "tech_saas",
            "beauty": "beauty_cosmetics",
            "cosmetics": "beauty_cosmetics",
            "skincare": "beauty_cosmetics",
            "fitness": "health_fitness",
            "health": "health_fitness",
            "gym": "health_fitness",
            "real estate": "real_estate",
            "property": "real_estate",
            "consulting": "professional_services",
            "legal": "professional_services",
            "finance": "professional_services",
            "education": "education",
            "courses": "education",
            "automotive": "automotive",
            "car": "automotive",
        }

        # Detect industry from business type
        detected_industry = None
        if store_business_type:
            business_type_lower = store_business_type.lower()
            for keyword, industry in industry_mapping.items():
                if keyword in business_type_lower:
                    detected_industry = industry
                    break

        if store:
            logger.info(f"[CampaignService] Store branding - Logo: {store_logo_url}, Theme: {store_color_theme}, BusinessType: {store_business_type}, Industry: {detected_industry}")

        # Different styles for variety
        styles = [AdStyle.MODERN, AdStyle.VIBRANT, AdStyle.PROFESSIONAL, AdStyle.ELEGANT, AdStyle.BOLD]

        # Fetch user-provided assets if available
        user_assets = []
        if asset_ids:
            from modules.assets.models import Asset as AssetModel
            user_assets = self.db.query(AssetModel).filter(AssetModel.id.in_(asset_ids)).all()
            if user_assets:
                logger.info(f"[CampaignService] Using {len(user_assets)} user-provided assets for ad sets")

        for i, ad_set_data in enumerate(ad_sets_data[:5]):
            ad_set = AdSet(
                campaign_id=campaign.id,
                name=ad_set_data.get("name", f"Ad Set {i+1}"),
                title=ad_set_data.get("title", ""),
                audience_tags=ad_set_data.get("audience_tags", []),
                hashtags=ad_set_data.get("hashtags", []),
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
            generated_cloudinary_url = None  # Cloudinary URL for AI-generated image
            agent_ad_angle = None
            agent_headline = None
            user_asset_url = None
            user_asset_id = None

            # Check if we have a user-provided asset for this ad set
            if user_assets and i < len(user_assets):
                user_asset = user_assets[i]
                user_asset_url = user_asset.cloudinary_secure_url or user_asset.cloudinary_url
                user_asset_id = user_asset.id
                logger.info(f"[CampaignService] Using user asset {user_asset.id} for ad set {i+1}")

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

                    # Step 2: Generate image using MediaGeneratorAgent (only if no user asset)
                    if not user_asset_url:
                        # Build comprehensive image prompt with store branding
                        brand_name = store_name or business_name

                        # Map ad style to media generator style
                        style_map = {
                            AdStyle.MODERN: "professional",
                            AdStyle.VIBRANT: "vibrant",
                            AdStyle.PROFESSIONAL: "professional",
                            AdStyle.ELEGANT: "luxury",
                            AdStyle.BOLD: "bold"
                        }
                        image_style = style_map.get(styles[i % len(styles)], "professional")

                        print(f"[MediaGenerator] Generating image for ad set: {ad_set.name}")
                        print(f"[MediaGenerator] Brand: {brand_name}, Colors: {store_color_theme}, Industry: {detected_industry}")

                        # Use industry-specific generation if industry is detected
                        if detected_industry:
                            # Generate industry-compliant ad image (Meta-safe templates)
                            print(f"[MediaGenerator] Using industry template: {detected_industry}")
                            print(f"[MediaGenerator] Brand colors: {store_color_theme}, Has logo: {bool(store_logo_url)}")
                            result = loop.run_until_complete(
                                self.media_generator.generate_industry_ad_image(
                                    industry=detected_industry,
                                    product_name=brand_name,
                                    product_description=primary_text or description or store_description or f"{brand_name} services",
                                    headline_text=agent_headline or headline,
                                    aspect_ratio="1:1",
                                    brand_colors=store_color_theme,
                                    logo_url=store_logo_url,
                                    target_audience=ad_set_data.get("name", "")
                                )
                            )
                        else:
                            # Build custom prompt with branding
                            branding_instructions = [f"Brand: {brand_name}"]

                            if store_color_theme:
                                branding_instructions.append(f"Brand colors: Use {store_color_theme} as the primary color scheme")

                            if store_logo_url:
                                branding_instructions.append(f"Include the brand logo prominently in the design")

                            branding_context = ". ".join(branding_instructions)

                            if agent_image_prompt:
                                image_prompt = f"{agent_image_prompt}. {branding_context}"
                            else:
                                image_prompt = f"""Professional advertisement for {brand_name}.
{primary_text or description or store_description or ''}
{branding_context}
Style: Clean composition, commercial photography, high-quality marketing visual.
The image should reflect the brand identity and be suitable for social media advertising."""

                            result = loop.run_until_complete(
                                self.media_generator.generate_image(
                                    prompt=image_prompt,
                                    style=image_style,
                                    aspect_ratio="1:1",
                                    upload_to_cloud=True,
                                    cloudinary_folder="shopivell/generated/ads"
                                )
                            )

                        if result.get("image_base64"):
                            generated_image_base64 = result["image_base64"]
                            generated_cloudinary_url = result.get("cloudinary_url")
                            print(f"[MediaGenerator] Generated image for ad set: {ad_set.name}, provider: {result.get('provider_used')}")
                            if generated_cloudinary_url:
                                print(f"[MediaGenerator] Cloudinary URL: {generated_cloudinary_url}")
                        else:
                            print(f"[MediaGenerator] Warning: No image generated for ad set: {ad_set.name}")
                    else:
                        print(f"[MediaGenerator] Skipping image generation - using user asset for ad set: {ad_set.name}")

                finally:
                    loop.close()

            except Exception as e:
                print(f"[AdCreativeAgent/AdGenerator] Error for ad set {i+1}: {e}")

            # Create ad content with generated image and agent's ad angle
            # Use user asset URL if available, otherwise use Cloudinary URL from AI generation
            final_media_url = user_asset_url or generated_cloudinary_url

            ad_content_obj = AdContent(
                ad_set_id=ad_set.id,
                headline=agent_headline or headline,  # Use agent's headline if available
                primary_text=agent_ad_angle or primary_text,  # Use agent's ad angle as primary text
                description=description,
                call_to_action=campaign.conversion_button,
                destination_url=campaign.source_url,
                media_url=final_media_url,  # Use user asset URL or AI-generated Cloudinary URL
                asset_id=user_asset_id,  # Link to user asset (if provided)
                is_primary=True,
                generated_image_base64=generated_image_base64 if not user_asset_url else None  # Keep base64 as backup
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

    def _mock_ad_content(self, url: str, store_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate mock ad content based on store context/industry."""
        domain = self._extract_domain_name(url).replace(" Campaign", "")

        # Get business type from store context
        business_type = store_context.get("business_type", "").lower() if store_context else ""
        store_name = store_context.get("store_name", domain) if store_context else domain

        # Industry-specific templates
        industry_templates = {
            "security": {
                "headlines": [
                    f"Protect Your Home with {store_name}",
                    f"24/7 Security Monitoring",
                    f"Professional CCTV Installation",
                    f"Smart Home Security Solutions",
                    f"Peace of Mind Guaranteed"
                ],
                "descriptions": [
                    f"Professional security solutions from {store_name}. Keep your home and business safe.",
                    f"24/7 monitoring and rapid response. Trust {store_name} for complete protection.",
                    f"Expert CCTV installation and maintenance. Your safety is our priority.",
                    f"Smart security systems for modern homes. Get a free consultation today.",
                    f"Comprehensive security services. Protect what matters most."
                ],
                "ad_sets": [
                    {
                        "name": "Homeowners",
                        "title": "Home Security Solutions",
                        "audience_tags": ["Homeowners", "Home Security", "Smart Home", "Property Protection", "Family Safety", "Home Insurance", "Residential Security", "CCTV", "Alarm Systems", "Home Automation"],
                        "primary_text": f"Protect your home and family with {store_name}'s professional security systems. From CCTV installation to 24/7 monitoring, we provide complete peace of mind.",
                        "features": ["Professional CCTV Installation", "24/7 Monitoring", "Quick Response Time"],
                        "hashtags": ["homesecurity", "cctv", "safehome", "securitysystems", "protection"]
                    },
                    {
                        "name": "Business Owners",
                        "title": "Commercial Security",
                        "audience_tags": ["Business Owners", "Commercial Security", "Office Security", "Retail Security", "Business Protection", "Commercial CCTV", "Access Control", "Security Management", "Business Insurance", "Loss Prevention"],
                        "primary_text": f"Secure your business with {store_name}'s commercial security solutions. Protect your assets, employees, and customers with our professional systems.",
                        "features": ["Commercial CCTV Systems", "Access Control", "Employee Safety"],
                        "hashtags": ["businesssecurity", "commercialcctv", "accesscontrol", "securitysolutions", "businessprotection"]
                    },
                    {
                        "name": "Property Managers",
                        "title": "Property Security Systems",
                        "audience_tags": ["Property Management", "Real Estate", "Building Security", "Apartment Security", "Estate Management", "Multi-unit Security", "Building Automation", "Property Investment", "Landlords", "Tenant Safety"],
                        "primary_text": f"Comprehensive security for your properties. {store_name} provides scalable solutions for apartments, estates, and commercial buildings.",
                        "features": ["Scalable Solutions", "Multi-property Management", "Remote Monitoring"],
                        "hashtags": ["propertysecurity", "buildingsecurity", "estatemanagement", "securitymonitoring", "propertyprotection"]
                    },
                    {
                        "name": "Tech-Savvy Customers",
                        "title": "Smart Security Technology",
                        "audience_tags": ["Smart Home Enthusiasts", "Technology Adopters", "IoT Security", "Home Automation", "Smart Devices", "Tech Gadgets", "Connected Home", "Mobile Security", "App-Controlled Security", "Modern Living"],
                        "primary_text": f"Experience next-generation security with {store_name}'s smart systems. Control your security from anywhere with our mobile app.",
                        "features": ["Mobile App Control", "Smart Integration", "Real-time Alerts"],
                        "hashtags": ["smarthome", "smartsecurity", "iotsecurity", "homeautomation", "connectedhome"]
                    },
                    {
                        "name": "Safety-Conscious Families",
                        "title": "Family Protection",
                        "audience_tags": ["Parents", "Family Safety", "Child Safety", "Home Protection", "Peace of Mind", "Family Security", "Safe Neighborhood", "Community Safety", "Emergency Response", "Family Wellness"],
                        "primary_text": f"Keep your family safe with {store_name}. Our security solutions give you peace of mind knowing your loved ones are protected 24/7.",
                        "features": ["Family-Friendly Systems", "Emergency Response", "Peace of Mind"],
                        "hashtags": ["familysafety", "childsafety", "homeprotection", "peaceofmind", "securityforfamilies"]
                    }
                ]
            }
        }

        # Check if we have a matching industry template
        for keyword, template in industry_templates.items():
            if keyword in business_type:
                return {
                    "business_name": store_name,
                    "business_type": business_type or "Security Services",
                    **template
                }

        # Default generic template if no industry match
        return {
            "business_name": store_name,
            "business_type": business_type or "Business",
            "headlines": [
                f"Discover {store_name} Today",
                f"Premium {store_name} Solutions",
                f"Transform with {store_name}",
                f"Choose {store_name} Excellence",
                f"{store_name} - Your Best Choice"
            ],
            "descriptions": [
                f"Experience the best of {store_name}. Quality products and exceptional service.",
                f"Join thousands who trust {store_name}. Start your journey today.",
                f"Premium solutions from {store_name}. Results you can count on.",
                f"Discover why {store_name} is the industry leader.",
                f"Transform your experience with {store_name}'s expert solutions."
            ],
            "ad_sets": [
                {
                    "name": "Professionals",
                    "title": "Industry Professionals",
                    "audience_tags": ["Business", "Professional", "Management", "Technology"],
                    "primary_text": f"Discover how {store_name} can transform your business with our premium solutions.",
                    "features": ["Premium Quality", "Expert Support", "Fast Delivery"],
                    "hashtags": ["business", "professional", "quality", "service", "solutions"]
                },
                {
                    "name": "Small Business",
                    "title": "Small Business Owners",
                    "audience_tags": ["Entrepreneur", "Small Business", "Startup", "E-commerce"],
                    "primary_text": f"Scale your business with {store_name}'s affordable solutions.",
                    "features": ["Affordable Pricing", "Easy Setup", "24/7 Support"],
                    "hashtags": ["smallbusiness", "entrepreneur", "startup", "growth", "success"]
                },
                {
                    "name": "Enterprise",
                    "title": "Enterprise Decision Makers",
                    "audience_tags": ["Enterprise", "Corporate", "C-Suite", "IT Director"],
                    "primary_text": f"Enterprise-grade solutions from {store_name} for your organization.",
                    "features": ["Enterprise Security", "Scalable", "Custom Solutions"],
                    "hashtags": ["enterprise", "corporate", "business", "solutions", "professional"]
                },
                {
                    "name": "Tech Savvy",
                    "title": "Technology Enthusiasts",
                    "audience_tags": ["Technology", "Innovation", "Digital", "Software"],
                    "primary_text": f"Stay ahead with {store_name}'s cutting-edge technology solutions.",
                    "features": ["Latest Technology", "Innovation", "Future-Ready"],
                    "hashtags": ["technology", "innovation", "digital", "future", "tech"]
                },
                {
                    "name": "Value Seekers",
                    "title": "Budget-Conscious Buyers",
                    "audience_tags": ["Deals", "Savings", "Value", "Smart Shopping"],
                    "primary_text": f"Get the best value with {store_name}'s competitive pricing.",
                    "features": ["Best Value", "Money-Back Guarantee", "Free Trial"],
                    "hashtags": ["value", "deals", "savings", "affordable", "quality"]
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

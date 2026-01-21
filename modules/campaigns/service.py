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

            # IMPORTANT: When scraping a NEW URL, use ONLY the scraped data
            # DO NOT use ANY store data (store_name, business_type, etc.) as they may be stale
            # from a previous different website scrape (e.g., security site vs clothing site)
            # The AI should determine business name, type, and details from SCRAPED CONTENT ONLY
            store_context = None  # Pass nothing - AI will derive everything from scraped content
            logger.info(f"[CampaignService] Using NO store context - all data will be derived from scraped URL content")

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

            # Extract logo URL from the website
            logo_url = self._extract_logo_url(base_url, combined_content)
            if logo_url:
                print(f"[Tavily] Extracted logo URL: {logo_url}")

            # Extract brand color from the website CSS
            brand_color = self._extract_brand_color(base_url)
            if brand_color:
                print(f"[Tavily] Extracted brand color: {brand_color}")

            return {
                "url": url,
                "domain": domain,
                "content": combined_content[:25000],  # Increased limit for more context
                "pages_extracted": len(all_content),
                "extracted_at": datetime.utcnow().isoformat(),
                "logo_url": logo_url,  # Store extracted logo URL
                "brand_color": brand_color  # Store extracted brand color
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

        # NOTE: We intentionally do NOT pass any store context to the AI
        # The AI should determine business name, type, and everything else from SCRAPED CONTENT ONLY
        # This prevents stale store data (e.g., "SecureSights") from appearing in campaigns
        # for completely different businesses (e.g., Edgars clothing store)
        store_info_section = ""  # Empty - AI derives everything from scraped content

        prompt = f"""You are an expert B2B/B2C digital marketing specialist creating high-converting Facebook/Instagram ad campaigns.

Website URL: {url}
Domain: {domain}
Pages Scraped: {pages_extracted}

WEBSITE CONTENT:
{content[:15000]}

STEP 1 - DEEP BUSINESS ANALYSIS:
Analyze the scraped content to identify:
1. WHAT does this business sell? (products, services, technology, etc.)
2. WHO are the BUYERS? Think about:
   - What INDUSTRIES use this product? (property management, healthcare, retail, government, etc.)
   - What JOB TITLES make purchasing decisions? (managers, directors, executives, owners)
   - What COMPANY TYPES need this? (SMEs, enterprises, government agencies, residential)
   - What PROBLEMS does each buyer type have that this product solves?
3. Extract any METRICS or STATISTICS mentioned (accuracy %, speed improvements, cost savings)

STEP 2 - GENERATE EXACTLY 5 BUYER PERSONAS (THIS IS REQUIRED):

You MUST generate exactly 5 different ad sets. Each must target a completely different buyer.

FOR B2B BUSINESSES (technology, services, enterprise solutions):
Generate 5 ad sets targeting different:
- INDUSTRY #1: One specific industry vertical
- INDUSTRY #2: Another different industry vertical
- JOB ROLE #3: A specific decision-maker role
- COMPANY TYPE #4: SME or enterprise or government
- USE CASE #5: A specific application of the product

FOR B2C BUSINESSES (retail, fashion, consumer products):
Generate 5 ad sets targeting different shopping occasions and customer types:
- SEASONAL OCCASION #1: A specific holiday or season (e.g., back-to-school season, Valentine's Day, Christmas, summer vacation, winter fashion)
- LIFE EVENT #2: A life milestone that triggers purchases (e.g., first job interview, graduation, wedding preparation, new baby)
- DEMOGRAPHIC #3: A specific customer type (e.g., young professionals, parents with kids, fashion-forward teens)
- PRODUCT CATEGORY #4: A specific product line if the business sells multiple types
- USE CASE #5: A specific occasion or need (e.g., office wear, weekend casual, party outfits, travel essentials)

CRITICAL: You MUST output exactly 5 ad sets in the ad_sets array. Not 1, not 2, not 3 - exactly 5.

STEP 3 - GENERATE AD CONTENT:

1. HEADLINES (5 different, max 40 chars each, include 2-3 relevant emojis)
   - Include specific metrics from scraped content
   - Example format: "99% Accurate ANPR System 🚗🔒" or "Smart Parking Solutions 🅿️✨"

2. DESCRIPTIONS (5 different, max 150 chars each, include emojis)
   - Address specific buyer pain points
   - Include metrics and benefits
   - End with CTA

3. AD_SETS (5 different buyer personas):

For each ad set, provide:
- name: The BUYER PERSONA (industry or role-based, 2-4 words)
  Examples of good names: "Property Management Companies", "Corporate Security Directors", "Smart City Planners", "Retail Store Owners", "Healthcare Facility Managers"

- title: Headline with emojis addressing this buyer's specific pain point (max 50 chars)
  Example: "Smart ANPR for Multi-Site Properties 🚗🔐📊"

- audience_description: 2-3 sentences describing WHO this buyer is:
  * Their job titles (list 2-3 specific titles)
  * Their responsibilities
  * What problem they're trying to solve
  Example: "Commercial and residential property managers responsible for multiple locations who need efficient access control and parking management solutions."

- audience_tags: 15 Facebook targeting interests specific to THIS buyer persona

- primary_text: DETAILED ad copy (100-180 words) that:
  * Opens by addressing the buyer by their job titles
  * Lists specific metrics/benefits with numbers (e.g., "99% accuracy", "85% faster", "40% cost reduction")
  * Describes 4-5 key features relevant to THIS buyer
  * Explains the impact on their business
  * Ends with clear CTA (e.g., "Request a quote today")
  * Include relevant emojis throughout

- features: 5 specific features with metrics where available
  Example: ["99% recognition accuracy", "85% faster processing", "40% cost reduction in year one", "Real-time alerts", "Seamless integration"]

- hashtags: 8 industry-specific hashtags

- value_proposition: One sentence with specific metric
  Example: "Achieve 99% vehicle recognition accuracy with 85% faster gate operations"

- emotion: Primary emotion (Efficiency, Security, Control, Growth, Trust)

- visual_direction: Specific scene showing THIS buyer persona using the product

Return as JSON:
{{
    "business_name": "...",
    "business_type": "...",
    "products_services": ["...", "...", "..."],
    "key_metrics": ["99% accuracy", "85% faster", "etc from scraped content"],
    "headlines": ["Headline with emojis 🚗🔒", "...", "...", "...", "..."],
    "descriptions": ["Description with metrics and emojis ✨", "...", "...", "...", "..."],
    "ad_sets": [
        {{
            "name": "Industry or Role-Based Buyer Persona",
            "title": "Headline with Emojis for This Buyer 🎯",
            "audience_description": "Detailed 2-3 sentence description of WHO this buyer is, their job titles, and what they need...",
            "audience_tags": ["15", "specific", "targeting", "tags"],
            "primary_text": "100-180 word detailed ad copy addressing this specific buyer by job title, with metrics, features, benefits, and CTA with emojis...",
            "features": ["feature with metric", "feature with metric", "feature", "feature", "feature"],
            "hashtags": ["8", "industry", "hashtags"],
            "value_proposition": "Specific benefit with metric",
            "emotion": "Primary emotion",
            "visual_direction": "Scene description"
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

        # IMPORTANT: Use SCRAPED data from the current URL, NOT store data
        # Store data may be stale or from a different website
        # Always use business_name from AI-generated content (derived from scraped URL)
        store_name = business_name  # From ad_content - determined by AI from scraped content

        # Get branding from SCRAPED data only (extracted from the URL being scraped)
        scraped_data = campaign.scraped_data or {}
        logo_url_to_use = scraped_data.get("logo_url")
        color_theme_to_use = scraped_data.get("color_theme") or scraped_data.get("brand_color")

        if logo_url_to_use:
            logger.info(f"[CampaignService] Using SCRAPED logo URL: {logo_url_to_use[:80]}...")
        if color_theme_to_use:
            logger.info(f"[CampaignService] Using SCRAPED color theme: {color_theme_to_use}")

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
            "fintech": "tech_saas",
            "payments": "tech_saas",
            "banking": "tech_saas",
            "financial technology": "tech_saas",
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

        # Detect industry from scraped URL and content, NOT from store.business_type
        # This prevents stale industry (e.g., "security") from affecting new URL scrapes
        detected_industry = None
        source_url = campaign.source_url.lower() if campaign.source_url else ""
        scraped_content = (campaign.scraped_data.get("content", "") if campaign.scraped_data else "").lower()

        # Check URL and scraped content for industry keywords
        detection_text = f"{source_url} {scraped_content[:2000]}"  # Limit content to first 2000 chars
        for keyword, industry in industry_mapping.items():
            if keyword in detection_text:
                detected_industry = industry
                break

        logger.info(f"[CampaignService] Using SCRAPED branding - Logo: {logo_url_to_use}, Theme: {color_theme_to_use}, DetectedIndustry: {detected_industry} (all from current URL scrape)")

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
            base_visual_direction = ad_set_data.get("visual_direction", "")

            # Build enhanced visual direction with brand colors and business type
            # This helps the AdCreativeAgent generate better structured prompts
            visual_direction_parts = []
            if detected_industry:
                visual_direction_parts.append(f"Business type: {detected_industry.replace('_', ' ')}")
            if color_theme_to_use:
                visual_direction_parts.append(f"Brand color: {color_theme_to_use} - use as accent throughout")
            if base_visual_direction:
                visual_direction_parts.append(base_visual_direction)
            visual_direction = ". ".join(visual_direction_parts) if visual_direction_parts else ""

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
                            visual_direction=visual_direction,
                            logo_url=logo_url_to_use or "",
                            brand_color=color_theme_to_use or ""
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
                        print(f"[MediaGenerator] Brand: {brand_name}, Colors: {color_theme_to_use}, Industry: {detected_industry}")

                        # Use industry-specific generation if industry is detected
                        if detected_industry:
                            # Generate industry-compliant ad image (Meta-safe templates)
                            print(f"[MediaGenerator] Using industry template: {detected_industry}")
                            print(f"[MediaGenerator] Brand colors: {color_theme_to_use}, Has logo: {bool(logo_url_to_use)}")
                            # Use scraped description from current URL, not stale store data
                            scraped_description = scraped_data.get("store_description", "") or scraped_data.get("description", "")
                            result = loop.run_until_complete(
                                self.media_generator.generate_industry_ad_image(
                                    industry=detected_industry,
                                    product_name=brand_name,
                                    product_description=primary_text or description or scraped_description or f"{brand_name} services",
                                    headline_text=agent_headline or headline,
                                    aspect_ratio="1:1",
                                    brand_colors=color_theme_to_use,
                                    logo_url=logo_url_to_use,
                                    target_audience=ad_set_data.get("name", "")
                                )
                            )
                        else:
                            # Build custom prompt with branding
                            branding_instructions = [f"Brand: {brand_name}"]

                            if color_theme_to_use:
                                branding_instructions.append(f"Brand colors: Use {color_theme_to_use} as the primary color scheme")

                            if logo_url_to_use:
                                branding_instructions.append(f"Include the brand logo prominently in the design")

                            branding_context = ". ".join(branding_instructions)

                            if agent_image_prompt:
                                image_prompt = f"{agent_image_prompt}. {branding_context}"
                            else:
                                # Use scraped description, not stale store data
                                scraped_desc = scraped_data.get("store_description", "") or scraped_data.get("description", "")
                                image_prompt = f"""Professional advertisement for {brand_name}.
{primary_text or description or scraped_desc or ''}
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

    def _extract_logo_url(self, base_url: str, content: str = "") -> Optional[str]:
        """Extract logo URL from website by fetching and parsing HTML."""
        import httpx

        try:
            # Fetch the homepage HTML
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(base_url)
                html = response.text

            # Common logo patterns to search for (in order of priority)
            logo_patterns = [
                # Open Graph image (often the logo)
                r'<meta\s+property=["\']og:image["\']\s+content=["\'](https?://[^"\']+)["\']',
                r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+property=["\']og:image["\']',
                # Twitter card image
                r'<meta\s+name=["\']twitter:image["\']\s+content=["\'](https?://[^"\']+)["\']',
                # Favicon/icon (often company logo)
                r'<link\s+rel=["\']icon["\']\s+[^>]*href=["\'](https?://[^"\']+)["\']',
                r'<link\s+rel=["\']shortcut icon["\']\s+[^>]*href=["\'](https?://[^"\']+)["\']',
                r'<link\s+rel=["\']apple-touch-icon["\']\s+[^>]*href=["\'](https?://[^"\']+)["\']',
                # Images with logo in class/id/alt
                r'<img\s+[^>]*class=["\'][^"\']*logo[^"\']*["\']\s+[^>]*src=["\'](https?://[^"\']+)["\']',
                r'<img\s+[^>]*src=["\'](https?://[^"\']+)["\'][^>]*class=["\'][^"\']*logo[^"\']*["\']',
                r'<img\s+[^>]*alt=["\'][^"\']*logo[^"\']*["\']\s+[^>]*src=["\'](https?://[^"\']+)["\']',
                r'<img\s+[^>]*src=["\'](https?://[^"\']+)["\'][^>]*alt=["\'][^"\']*logo[^"\']*["\']',
                r'<img\s+[^>]*id=["\'][^"\']*logo[^"\']*["\']\s+[^>]*src=["\'](https?://[^"\']+)["\']',
                # Logo in URL path
                r'<img\s+[^>]*src=["\'](https?://[^"\']*logo[^"\']*)["\']',
            ]

            # Also check for relative URLs and convert to absolute
            relative_patterns = [
                r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                r'<link\s+rel=["\']icon["\']\s+[^>]*href=["\']([^"\']+)["\']',
                r'<img\s+[^>]*class=["\'][^"\']*logo[^"\']*["\']\s+[^>]*src=["\']([^"\']+)["\']',
            ]

            # Try absolute URL patterns first
            for pattern in logo_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    logo_url = match.group(1)
                    # Validate it's an image URL
                    if any(ext in logo_url.lower() for ext in ['.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif']):
                        print(f"[LogoExtract] Found logo via pattern: {logo_url[:100]}")
                        return logo_url

            # Try relative URL patterns and convert to absolute
            for pattern in relative_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    logo_path = match.group(1)
                    if logo_path.startswith('//'):
                        logo_url = 'https:' + logo_path
                    elif logo_path.startswith('/'):
                        logo_url = base_url.rstrip('/') + logo_path
                    elif not logo_path.startswith('http'):
                        logo_url = base_url.rstrip('/') + '/' + logo_path
                    else:
                        logo_url = logo_path

                    if any(ext in logo_url.lower() for ext in ['.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif']):
                        print(f"[LogoExtract] Found logo (converted relative): {logo_url[:100]}")
                        return logo_url

            print(f"[LogoExtract] No logo found for {base_url}")
            return None

        except Exception as e:
            print(f"[LogoExtract] Error extracting logo: {e}")
            return None

    def _extract_domain_name(self, url: str) -> str:
        """Extract readable name from URL."""
        domain = url.lower()
        domain = re.sub(r'^https?://', '', domain)
        domain = re.sub(r'^www\.', '', domain)
        domain = domain.split('/')[0]
        domain = domain.split('.')[0]
        return f"{domain.capitalize()} Campaign"

    def _extract_brand_color(self, base_url: str) -> Optional[str]:
        """Extract brand color from website CSS."""
        import httpx

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(base_url)
                html = response.text

            # Generic colors to exclude (common framework/default colors)
            generic_colors = {
                '#000', '#000000', '#fff', '#ffffff', '#333', '#333333',
                '#666', '#666666', '#999', '#999999', '#ccc', '#cccccc',
                '#f5f5f5', '#f7f7f7', '#e5e5e5', '#d4d4d4', '#fafafa', '#f0f0f0',
                '#f9f9f9', '#eee', '#eeeeee', '#ddd', '#dddddd',
                '#007bff', '#0069d9', '#0062cc', '#0056b3',  # Bootstrap blue
                '#6c757d', '#5a6268', '#545b62',  # Bootstrap gray
                '#28a745', '#218838', '#1e7e34',  # Bootstrap green
                '#dc3545', '#c82333', '#bd2130',  # Bootstrap red
                '#ffc107', '#e0a800', '#d39e00',  # Bootstrap yellow
                '#17a2b8', '#138496', '#117a8b',  # Bootstrap cyan
                '#343a40', '#23272b', '#1d2124',  # Bootstrap dark
                '#f8f9fa', '#e2e6ea', '#dae0e5', '#212529',  # Bootstrap light/dark
                '#32373c', '#abb8c3',  # WordPress defaults
                '#2b2b2b', '#1a1a1a',  # Common dark colors
            }

            # Priority color names (brand-like)
            priority_names = {'gold', 'primary', 'brand', 'main', 'accent', 'highlight', 'secondary'}
            # Generic color names to skip
            skip_names = {'black', 'white', 'gray', 'grey', 'light-gray', 'medium-gray', 'dark-gray'}

            found_colors = []

            # 1. Check meta theme-color
            theme_match = re.search(r'<meta[^>]*name=["\']theme-color["\'][^>]*content=["\']([^\'"]+)["\']', html, re.I)
            if theme_match:
                color = theme_match.group(1).lower().strip()
                if color not in generic_colors:
                    print(f"[ColorExtract] Found theme-color: {color}")
                    found_colors.append(color)

            # 2. Check WordPress preset colors (highest priority)
            wp_pattern = r'--wp--preset--color--([a-z-]+):\s*(#[0-9a-fA-F]{3,6})'
            wp_matches = re.findall(wp_pattern, html, re.I)
            for name, color in wp_matches:
                name_lower = name.lower()
                color_lower = color.lower()
                if name_lower in skip_names or color_lower in generic_colors:
                    continue
                if name_lower in priority_names:
                    print(f"[ColorExtract] Found priority CSS variable '{name}': {color}")
                    found_colors.insert(0, color)  # Priority colors go first
                else:
                    found_colors.append(color)

            # 3. Check standard CSS variables
            css_var_patterns = [
                r'--primary[^:]*:\s*(#[0-9a-fA-F]{3,6})',
                r'--brand[^:]*:\s*(#[0-9a-fA-F]{3,6})',
                r'--main[^:]*:\s*(#[0-9a-fA-F]{3,6})',
                r'--accent[^:]*:\s*(#[0-9a-fA-F]{3,6})',
            ]
            for pattern in css_var_patterns:
                matches = re.findall(pattern, html, re.I)
                for color in matches:
                    color_lower = color.lower()
                    if color_lower in generic_colors:
                        continue
                    if color_lower not in [c.lower() for c in found_colors]:
                        print(f"[ColorExtract] Found CSS variable color: {color}")
                        found_colors.append(color)

            # 4. If no CSS variables found, look for most frequently used non-generic color
            # This catches inline styles like "color: #e60028" or "background: #e60028"
            if not found_colors:
                print("[ColorExtract] No CSS variables found, analyzing inline styles...")
                all_hex_colors = re.findall(r'#[0-9a-fA-F]{6}', html)
                color_counts = {}
                for c in all_hex_colors:
                    c_lower = c.lower()
                    if c_lower not in generic_colors:
                        color_counts[c_lower] = color_counts.get(c_lower, 0) + 1

                if color_counts:
                    # Get the most frequently used non-generic color
                    sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
                    # Only use if it appears at least 3 times (likely intentional brand color)
                    if sorted_colors and sorted_colors[0][1] >= 3:
                        top_color = sorted_colors[0][0]
                        print(f"[ColorExtract] Found frequent color {top_color} ({sorted_colors[0][1]} times)")
                        found_colors.append(top_color)

            if found_colors:
                result = found_colors[0].upper()
                print(f"[ColorExtract] Selected brand color: {result}")
                return result

            print("[ColorExtract] No brand color found")
            return None

        except Exception as e:
            print(f"[ColorExtract] Error: {e}")
            return None

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
        """Generate mock ad content based on URL domain (not store context to avoid stale data)."""
        domain = self._extract_domain_name(url).replace(" Campaign", "")

        # Use domain name as store name, don't rely on store_context to avoid stale data
        store_name = domain

        # Try to detect business type from URL/domain, not from store context
        # This prevents "security" from persisting across different URL scrapes
        url_lower = url.lower()
        business_type = ""

        # Detect business type from URL patterns
        if any(kw in url_lower for kw in ['security', 'secure', 'cctv', 'alarm', 'guard']):
            business_type = "security"
        elif any(kw in url_lower for kw in ['restaurant', 'food', 'cafe', 'kitchen', 'dining']):
            business_type = "restaurant"
        elif any(kw in url_lower for kw in ['shop', 'store', 'buy', 'ecommerce', 'retail']):
            business_type = "retail"
        # Otherwise leave empty for generic template

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

# modules/campaigns/service.py
"""
Campaign service for URL scraping, ad generation, and campaign management.
Uses OpenRouter API for AI-powered content generation.
"""
import os
import json
import re
import asyncio
import nest_asyncio

# Allow nested event loops (needed when FastAPI's async loop is already running)
nest_asyncio.apply()
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from tavily import TavilyClient
from dotenv import load_dotenv
import uuid
import logging

from .models import UrlCampaign, CampaignStatus, CampaignGoal, UrlAdSet, UrlAdContent

# Ad-generation modules were removed in the OpenClaw migration (ad creation now
# lives in OpenClaw). Guard the imports so this service still loads and the
# URL-campaign scraping/analysis features keep working. When unavailable, the
# AI ad-set creative/image generation path is skipped gracefully.
try:
    from modules.ad_generator.service import AdGeneratorService
    from modules.ad_generator.schemas import GenerateAdRequest, AdStyle, AdFormat, AdPlatform
    from modules.agents.ad_creative_agent import AdCreativeAgent
    from modules.agents.media_generator_agent import MediaGeneratorAgent
    from modules.agents.copywriter_agent import CopywriterAgent
    from modules.agents.gemini_image_generator import GeminiImageGenerator
    from modules.agents.ad_image_composer import AdImageComposer
    AD_MODULES_AVAILABLE = True
except ImportError:
    AdGeneratorService = AdCreativeAgent = MediaGeneratorAgent = None
    CopywriterAgent = GeminiImageGenerator = AdImageComposer = None
    GenerateAdRequest = AdStyle = AdFormat = AdPlatform = None
    AD_MODULES_AVAILABLE = False

# Import Vision AI analysis for extracting uniforms, vehicles, brand colors from images
try:
    from modules.stores.scraping_service import _extract_images_from_website, _analyze_images_with_vision
    VISION_AI_AVAILABLE = True
except ImportError:
    VISION_AI_AVAILABLE = False

# Import screenshot capture for campaign creation
try:
    from modules.stores.scraping_service import capture_homepage_screenshot_sync, CLOUDINARY_CONFIGURED
    SCREENSHOT_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False
    CLOUDINARY_CONFIGURED = False

# Import Brand Intelligence for complete brand DNA extraction
try:
    from modules.brand_intelligence import BrandDNAExtractor
    BRAND_DNA_AVAILABLE = True
except ImportError:
    BRAND_DNA_AVAILABLE = False

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

# How ad copy should read. Left alone, the model writes corporate filler ("As a
# professional, you deserve only the best", "experience the difference"); merchants
# need copy that sounds like someone who understands the customer's situation.
# Hook tactics that dominate high-spend Meta accounts (Motion's 2026 creative
# benchmarks). Each ad set gets a different one, so a campaign tests different ways of
# stopping the scroll rather than three versions of the same opener.
HOOK_TACTICS = [
    ("Confession",
     "admit a mistake, failure or wrong belief the customer has held, then resolve it; honest and "
     "vulnerable, like talking to a friend, never salesy",
     ['"I tried everything — [failed attempts] — then I found [product]."',
      '"I have never tried [product] before, believe it or not..."']),
    ("Bold claim",
     "open with a big, hard-to-ignore promise that makes the reader think 'prove it', then prove it "
     "immediately with a fact from the website — never a promise the site does not support",
     ['"[Specific surprising fact from the website]. Here is how."', '"Most [customers] never [thing]. Ours do."']),
    ("Relatability",
     "describe one specific moment from the customer's life in their own words so they think "
     "'that is literally me'; specific beats general",
     ['"My [problem] was [bad situation]. [Product] literally saved me."']),
    ("Contrast",
     "set two things against each other: the old way vs the new way, before vs after, or how everyone "
     "else does it vs how this business does it",
     ['"[Old way] vs [new way] — the difference is [proof]."']),
    ("Curiosity",
     "open a loop: give the known (who and what this is about, so the right person self-selects) and "
     "hold back the unknown, then resolve it later in the copy",
     ['"My [person] has only been using it for [timeframe]..."']),
]


# Site images that are never useful as a photo of the business (logos, badges, certificates).
_NON_PHOTO = re.compile(r"logo|icon|favicon|sprite|flag|badge|award|iso[-_]?\d|superbrand|certif|payment|brands?[-_]|"
                        r"placeholder|avatar|arrow|banner-bg|pattern|\.svg", re.I)


def collect_site_photos(base_url: str, limit: int = 40) -> List[str]:
    """Real photos of the business (staff in uniform, vehicles, premises, products) from its site.

    Reads <img>/og:image tags from the HTML and, because many sites are JavaScript apps whose
    HTML has no <img> tags at all (securico.co.zw), the image asset paths referenced from the
    site's own JS bundles. Used as image-model references so ads show the business's real
    uniforms and livery instead of invented ones."""
    import requests as _requests
    from urllib.parse import urljoin, urlparse
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
    try:
        page = _requests.get(base_url, timeout=20, headers=headers)
        html, origin = page.text, page.url
    except Exception as e:
        logger.warning(f"[SitePhotos] fetch failed for {base_url}: {e}")
        return []
    found: List[str] = []
    for m in re.finditer(r'(?:<img[^>]+(?:src|data-src)|<meta[^>]+property="og:image"[^>]+content)="([^"]+)"', html, re.I):
        found.append(urljoin(origin, m.group(1)))
    host = urlparse(origin).netloc
    for js in re.findall(r'<script[^>]+src="([^"]+\.js)"', html, re.I)[:6]:
        js_url = urljoin(origin, js)
        if urlparse(js_url).netloc != host:
            continue
        try:
            bundle = _requests.get(js_url, timeout=20, headers=headers).text
        except Exception:
            continue
        for m in re.finditer(r"""["'(]((?:/|\./)?[\w./-]*?\.(?:jpe?g|png|webp|avif))["')]""", bundle, re.I):
            found.append(urljoin(origin, m.group(1)))
    photos, seen = [], set()
    for u in found:
        name = u.rsplit("/", 1)[-1].lower()
        if u in seen or not re.search(r"\.(jpe?g|png|webp|avif)(\?|$)", u, re.I) or _NON_PHOTO.search(name):
            continue
        seen.add(u)
        photos.append(u)
    logger.info(f"[SitePhotos] {len(photos)} photos from {base_url}")
    return photos[:limit]


def _thumb_data_uri(content: bytes, size: int = 512) -> Optional[str]:
    """A small JPEG data URI of an image, for cheap vision selection."""
    try:
        import base64, io
        from PIL import Image
        img = Image.open(io.BytesIO(content)).convert("RGB")
        img.thumbnail((size, size))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=75)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()
    except Exception:
        return None


def fetch_photo_candidates(photos: List[str], limit: int = 16) -> List[Tuple[str, str]]:
    """(url, thumbnail data URI) for the business's website photos.

    Just the download-and-shrink step: which of these photos a creative must copy is
    the ads-image agent's judgement (it receives these thumbnails), not a rule here."""
    import requests as _requests
    candidates: List[Tuple[str, str]] = []
    for u in (photos or [])[:limit]:
        try:
            r = _requests.get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            uri = _thumb_data_uri(r.content) if r.status_code == 200 else None
            if uri:
                candidates.append((u, uri))
        except Exception:
            continue
    logger.info(f"[SitePhotos] {len(candidates)} usable thumbnails from {len(photos or [])} photos")
    return candidates

AD_COPYWRITING_RULES = """COPYWRITING RULES (these override everything else in this prompt):
- GOAL: make the right person curious enough to stop scrolling and tap. Short and intriguing beats complete and informative - the ad starts the conversation, the website finishes it.
- primary_text is SHORT: 3-4 short lines, 30-60 words in total - HARD LIMIT 60 words, count them before answering - a line break between lines. Never a paragraph, never a feature list.
  Line 1 (the hook, under 125 characters so it shows before "See more"): a specific, surprising or uncomfortable moment the customer recognises, or a question they can't answer - it must open a loop that only reading on (or clicking) closes. It must NOT repeat the headline; the headline and line 1 are two different hooks for the same idea.
  Line 2: twist or tension - the thing they didn't know, the cost of getting it wrong, or a hint at the answer without giving it all away.
  Line 3: the proof - ONE concrete fact from the website that makes it believable.
  Line 4: one short next step that matches the call_to_action.
- title (headline): under 40 characters, specific to THIS business and THIS situation. Use a question, a surprising number from the website, a "why/how" loop, or a contrast. SWAP TEST: if a competitor could run the same headline unchanged, it is too generic - rewrite it. CURIOSITY TEST: the reader must be left with a question ("wait, why?", "is that me?", "what happened?"); a plain statement of what the business does fails.
  The headline is about the READER's situation, never about the business: do NOT put the business name in the headline, and never "How [brand] beats...", "Why [brand]...", "[Brand] vs ...".
  CLARITY FIRST: a busy person must understand it in one glance, with zero effort. Clever-but-confusing loses to plain-and-intriguing.
  Generic (never): "Smart Security Solutions", "Quality Laptops Here", "Your Trusted Partner", "Protect What Matters", "Reliable Service You Can Trust".
  Hooked (like this): "Is your night guard actually awake?", "Cash van late again?", "Bought a 'new' laptop that wasn't?", "Power cut mid-deadline again?".
- descriptions: under 60 characters each, a teaser that adds to the headline (never repeats it) - e.g. "Most buyers only find out after the warranty ends."
- Start from the customer, never the business: no "At [Business] we...", no "We are a leading...", no listing services.
- Use only facts from the website; tease them, don't dump them. No invented numbers, prices, offers or guarantees.
- Plain spoken words, like a local friend talking to one person. No hype, no fear-mongering.
- Never use em dashes or en dashes. Use a full stop or a comma instead.
- Every line must make sense on its own to someone skimming - no riddles, no abstract statements ("that is when a uniform stops being security", "monitoring changes the moment"). Concrete people, places, times and objects.
- No semicolons, no dashes joining clauses, no "I used to think" openers. Mention the business name at most once, in the proof line.
- Never use: "you deserve the best", "say goodbye to", "experience the difference", "look no further", "one-stop shop", "take it to the next level", "elevate", "unlock", "seamless", "cutting-edge", "solutions", "trusted partner", "peace of mind is just", "Enjoy ... today".
- name is a specific persona in a situation (e.g. "Students buying a first laptop"), not a generic group ("Individuals", "Professionals").
- emotion is the feeling the buyer wants (relief, confidence, pride, peace of mind), not a corporate value."""

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
        # Ad-generation agents live in OpenClaw now; instantiate only if the
        # legacy modules are still present, otherwise leave them as None and
        # skip the AI ad-set creative path in _create_ad_sets.
        if AD_MODULES_AVAILABLE:
            self.ad_generator = AdGeneratorService()
            self.ad_creative_agent = AdCreativeAgent()
            self.copywriter_agent = CopywriterAgent()
            self.media_generator = MediaGeneratorAgent()  # Fallback image generator
            self.gemini_generator = GeminiImageGenerator()  # Primary image generator with reference images
            self.ad_image_composer = AdImageComposer()  # Adds text overlays to generated images
        else:
            self.ad_generator = None
            self.ad_creative_agent = None
            self.copywriter_agent = None
            self.media_generator = None
            self.gemini_generator = None
            self.ad_image_composer = None
        self.brand_dna_extractor = BrandDNAExtractor() if BRAND_DNA_AVAILABLE else None

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

    def scrape_url_for_campaign(self, url: str, store_id: uuid.UUID, campaign_name: Optional[str] = None, asset_ids: Optional[List[uuid.UUID]] = None, num_copies: int = 1, num_images: int = 1,
                                market_research: Optional[Dict[str, Any]] = None, ad_angles: Optional[List[Dict[str, Any]]] = None) -> Tuple[Campaign, Optional[str]]:
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
            # Real starting values instead of the model's placeholder defaults ($100, no region):
            # the store's country and a small test daily budget.
            from modules.stores.models import Store as _Store
            _store = self.db.query(_Store).filter(_Store.id == store_id).first()
            from utils.text_clean import clean_ad_name
            campaign = Campaign(
                store_id=store_id,
                name=clean_ad_name(campaign_name or self._extract_domain_name(url)),
                total_budget=float(os.getenv("AD_DEFAULT_TOTAL_BUDGET", "20")),
                source_url=url,
                source_type="url",
                status=CampaignStatus.ANALYZING,
                daily_budget=float(os.getenv("AD_DEFAULT_DAILY_BUDGET", "2")),
                countries=[str(_store.country_code).upper()] if _store and _store.country_code else [],
            )
            self.db.add(campaign)
            self.db.commit()
            self.db.refresh(campaign)

            # Scrape the URL
            scraped_data = self._scrape_website(url)
            if scraped_data and not scraped_data.get("error"):
                scraped_data = self._apply_store_profile(scraped_data, store_id)

            if not scraped_data:
                campaign.status = CampaignStatus.FAILED
                campaign.error_message = "Failed to scrape website content"
                self.db.commit()
                return campaign, "Failed to scrape website"

            # Update campaign with scraped data
            # Research and angles from the scrape-stream are kept on the campaign, and the
            # angles drive the ad sets generated below (one ad set per angle).
            if market_research:
                scraped_data["market_research"] = market_research
            if ad_angles:
                scraped_data["ad_angles"] = ad_angles
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
            ad_content = self._generate_ad_content(scraped_data, url, store_context, ad_angles=ad_angles)
            if ad_content:
                campaign.generated_headlines = ad_content.get("headlines", [])
                campaign.generated_descriptions = ad_content.get("descriptions", [])

                # Update campaign name with AI-generated business name if available
                ai_business_name = ad_content.get("business_name")
                if ai_business_name and not campaign_name:
                    campaign.name = ai_business_name
                    logger.info(f"[CampaignService] Updated campaign name to AI-generated: {ai_business_name}")

                # Create ad sets with cross-mixing variations
                self._create_ad_sets(campaign, ad_content, asset_ids, num_copies=num_copies, num_images=num_images)

            # Strip large screenshot_base64 from scraped_data before DB commit
            if campaign.scraped_data and isinstance(campaign.scraped_data, dict):
                campaign.scraped_data.pop("screenshot_base64", None)

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

    def create_campaign_from_store(self, store, campaign_name: Optional[str] = None, asset_ids: Optional[List[uuid.UUID]] = None) -> Tuple[Campaign, Optional[str]]:
        """
        Create a campaign directly from existing store data WITHOUT scraping.

        This method uses the store's saved information:
        - store_name, business_type, store_voice
        - products_or_services
        - logo_url, color_theme
        - store_link (for destination URL)

        Args:
            store: The Store object with complete data
            campaign_name: Optional custom campaign name (defaults to store name)
            asset_ids: Optional list of user-provided asset IDs

        Returns:
            (Campaign, error_message) tuple
        """
        try:
            logger.info(f"[CampaignService] Creating campaign from store data: {store.store_name}")

            # Build store data as if it was scraped
            store_data = {
                "url": store.store_link or "",
                "domain": store.store_name.lower().replace(" ", ""),
                "content": self._build_content_from_store(store),
                "extracted_at": datetime.utcnow().isoformat(),
                "source": "store_data",
                "logo_url": store.logo_url,
                "brand_color": store.color_theme,
                "brand_colors": [store.color_theme] if store.color_theme else [],
                "screenshot_url": store.screenshot_url,
            }

            # Create campaign
            campaign = Campaign(
                store_id=store.id,
                name=campaign_name or f"{store.store_name} Campaign",
                source_url=store.store_link or "",
                source_type="store",  # Mark as created from store, not URL scrape
                status=CampaignStatus.ANALYZING
            )
            self.db.add(campaign)
            self.db.commit()
            self.db.refresh(campaign)

            # Store the store data
            campaign.scraped_data = store_data
            campaign.scraped_at = datetime.utcnow()

            # Store user-provided asset IDs
            if asset_ids:
                store_data["user_asset_ids"] = [str(aid) for aid in asset_ids]
                campaign.scraped_data = store_data

            # Build store context for AI generation
            store_context = {
                "store_name": store.store_name,
                "business_type": store.business_type,
                "store_description": store.store_voice,
                "services_products": store.products_or_services or [],
                "logo_url": store.logo_url,
                "color_theme": store.color_theme,
            }

            # Generate ad content using store context
            ad_content = self._generate_ad_content_from_store(store_context)

            if ad_content:
                campaign.generated_headlines = ad_content.get("headlines", [])
                campaign.generated_descriptions = ad_content.get("descriptions", [])

                # Create ad sets
                self._create_ad_sets(campaign, ad_content, asset_ids)

            # Strip large screenshot_base64 from scraped_data before DB commit
            if campaign.scraped_data and isinstance(campaign.scraped_data, dict):
                campaign.scraped_data.pop("screenshot_base64", None)

            campaign.status = CampaignStatus.READY
            self.db.commit()
            self.db.refresh(campaign)

            logger.info(f"[CampaignService] Campaign created from store: {campaign.id}")
            return campaign, None

        except Exception as e:
            self.db.rollback()
            logger.error(f"[CampaignService] Error creating campaign from store: {e}")
            if 'campaign' in locals():
                campaign.status = CampaignStatus.FAILED
                campaign.error_message = str(e)
                self.db.commit()
            return None, str(e)

    def _build_content_from_store(self, store) -> str:
        """Build content string from store data for AI processing."""
        content_parts = []

        content_parts.append(f"# {store.store_name}")

        if store.business_type:
            content_parts.append(f"Business Type: {store.business_type}")

        if store.store_voice:
            content_parts.append(f"About: {store.store_voice}")

        if store.products_or_services:
            content_parts.append(f"Products/Services: {', '.join(store.products_or_services)}")

        if store.store_email:
            content_parts.append(f"Email: {store.store_email}")

        if store.store_phone:
            content_parts.append(f"Phone: {store.store_phone}")

        if store.store_address:
            content_parts.append(f"Address: {store.store_address}")

        return "\n\n".join(content_parts)

    def _generate_ad_content_from_store(self, store_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate ad content using store data (no scraping needed)."""
        store_name = store_context.get("store_name", "Business")
        business_type = store_context.get("business_type", "")
        description = store_context.get("store_description", "")
        products = store_context.get("services_products", [])

        products_str = ", ".join(products[:10]) if products else "various products and services"

        prompt = f"""You are an expert B2B/B2C digital marketing specialist creating high-converting Facebook/Instagram ad campaigns.

STORE INFORMATION (USE THIS DATA - DO NOT MAKE UP INFORMATION):
Store Name: {store_name}
Business Type: {business_type}
Description: {description}
Products/Services: {products_str}

STEP 1 - ANALYZE THE BUSINESS:
Based on the store information above, identify:
1. WHAT does this business sell?
2. WHO are the target buyers? (industries, job titles, company types)
3. What PROBLEMS does this business solve?

STEP 2 - GENERATE 1 BUYER PERSONA:
Generate exactly 1 ad set targeting the PRIMARY buyer persona.

STEP 3 - GENERATE AD CONTENT:

{AD_COPYWRITING_RULES}

IMPORTANT: Do NOT include any emojis. Keep all text clean and professional.

1. HEADLINES (2, max 40 chars each) - curiosity hooks that pass the SWAP TEST above
2. DESCRIPTIONS (2, max 60 chars each) - short teasers that add to the headline
3. AD_SETS (1 buyer persona):

For the ad set, provide:
- name: The BUYER PERSONA (2-4 words)
- title: curiosity headline for this buyer's situation (max 40 chars, NO emojis)
- audience_description: 2-3 sentences describing WHO this buyer is
- audience_tags: 15-20 Facebook targeting interests
- primary_text: SHORT hook-first ad copy, 3-4 lines, 30-60 words, per the COPYWRITING RULES - NO emojis
- features: 5 specific features from the products/services listed
- hashtags: 8-10 social media hashtags (lowercase, no spaces)
- value_proposition: One sentence value statement
- emotion: Primary emotion (Efficiency, Security, Control, Growth, Trust)
- visual_direction: Specific scene description for ad image

Return as JSON:
{{
    "business_name": "{store_name}",
    "business_type": "{business_type}",
    "products_services": {json.dumps(products[:6])},
    "headlines": ["Headline 1", "Headline 2"],
    "descriptions": ["Description 1", "Description 2"],
    "ad_sets": [
        {{
            "name": "Buyer Persona Name",
            "title": "Clear Headline",
            "audience_description": "Description...",
            "audience_tags": ["tag1", "tag2", "...15-20 tags"],
            "primary_text": "Professional ad copy...",
            "features": ["feature 1", "feature 2", "feature 3", "feature 4", "feature 5"],
            "hashtags": ["hashtag1", "hashtag2", "...8-10 tags"],
            "value_proposition": "Value statement",
            "emotion": "Primary emotion",
            "visual_direction": "Scene description",
            "call_to_action": "One of: Shop Now, Learn More, Contact Us, Send Message, Get Quote, Book Now, Order Now, Sign Up, Call Now"
        }}
    ]
}}

Return ONLY valid JSON, no markdown, NO EMOJIS.
"""

        # Claude (via OpenRouter) first: in a side-by-side on securico.co.zw it wrote clear,
        # human hooks where gpt-5.6-terra wrote stiff, riddle-like lines. OpenAI is the fallback.
        if self.openrouter:
            result = self._generate_with_openrouter(prompt)
            if result:
                return result
            logger.warning("[CampaignService] OpenRouter failed, trying OpenAI fallback")

        if self.openai:
            result = self._generate_with_openai(prompt)
            if result:
                return result

        # Final fallback to mock data using store context
        logger.warning("[CampaignService] No AI client available, using store-based mock data")
        return self._mock_ad_content_from_store(store_context)

    def _mock_ad_content_from_store(self, store_context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate mock ad content from store data when AI is unavailable."""
        store_name = store_context.get("store_name", "Business")
        business_type = store_context.get("business_type", "Services")
        products = store_context.get("services_products", [])

        return {
            "business_name": store_name,
            "business_type": business_type,
            "products_services": products[:6],
            "headlines": [
                f"Discover {store_name}",
                f"Professional {business_type}"
            ],
            "descriptions": [
                f"Experience quality {business_type.lower()} from {store_name}. Contact us today.",
                f"Trusted {business_type.lower()} solutions. Get started now."
            ],
            "ad_sets": [
                {
                    "name": f"{business_type} Buyers",
                    "title": f"Quality {business_type}",
                    "audience_description": f"Professionals and businesses looking for {business_type.lower()} solutions.",
                    "audience_tags": [
                        "Business owners", "Professionals", business_type,
                        "Small business", "Enterprise", "B2B services",
                        "Quality services", "Professional services"
                    ],
                    "primary_text": f"Looking for reliable {business_type.lower()}? {store_name} delivers professional solutions tailored to your needs. With our expertise and commitment to quality, we ensure your satisfaction. Contact us today to learn more.",
                    "features": products[:5] if products else [f"{business_type} Service 1", f"{business_type} Service 2"],
                    "hashtags": [business_type.lower().replace(" ", ""), "business", "professional", "quality", "services"],
                    "value_proposition": f"Professional {business_type.lower()} you can trust.",
                    "emotion": "Trust",
                    "visual_direction": f"Professional {business_type.lower()} scene showing quality service."
                }
            ]
        }

    def _apply_store_profile(self, scraped_data: Dict[str, Any], store_id) -> Dict[str, Any]:
        """Make the store's own profile authoritative over what web search guesses.

        Site scraping alone misidentified a business (or its market: .com meant "United
        States") whenever the site text was thin or a same-named company exists. The
        owner-provided profile (what it sells, country) is prepended as authoritative
        content, and the store's country is recorded so research targets the right market."""
        try:
            from modules.stores.models import Store
            store = self.db.query(Store).filter(Store.id == store_id).first()
            if not store or not isinstance(scraped_data, dict):
                return scraped_data
            about = store.store_description or store.store_voice
            products = store.products_or_services or []
            lines = [f"Business name: {store.store_name}"]
            if store.business_type:
                lines.append(f"Business type: {store.business_type}")
            if about:
                lines.append(f"What the business does and sells: {about[:800]}")
            if products:
                lines.append(f"Products/services: {', '.join(str(p) for p in products[:8])}")
            if store.store_country:
                lines.append(f"Country/market it serves: {store.store_country}")
            header = (
                "=== OWNER-PROVIDED BUSINESS PROFILE (authoritative - if anything below or on the web "
                "conflicts with this, or describes a different company with a similar name, this wins) ==="
            )
            scraped_data["content"] = header + chr(10) + chr(10).join(lines) + chr(10) + chr(10) + (scraped_data.get("content") or "")
            scraped_data["store_profile"] = {
                "name": store.store_name, "business_type": store.business_type,
                "country": store.store_country, "country_code": store.country_code,
            }
        except Exception as e:
            logger.warning(f"[CampaignService] could not apply store profile: {e}")
        return scraped_data

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
                    f"site:{domain} company about products brands",
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
                        # Only this site's own pages. The old check also let in any result not
                        # already extracted, so a same-named company (e.g. Movella Systems the
                        # email host vs Movella/Xsens the sensor maker) leaked in and the
                        # business was identified as the wrong company.
                        result_host = result_url.split("//")[-1].split("/")[0].replace("www.", "")
                        if content and len(content) > 100 and (result_host == domain or result_host.endswith("." + domain)):
                            if result_url not in extracted_pages:
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

            # Extract brand color from the website CSS (fallback)
            brand_color = self._extract_brand_color(base_url)
            if brand_color:
                print(f"[Tavily] Extracted brand color from CSS: {brand_color}")

            # Initialize brand intelligence results
            brand_dna = None
            uniform_images = []
            vehicle_images = []
            equipment_images = []
            product_images = []
            team_images = []
            vision_brand_colors = []
            uniform_description = None
            vehicle_description = None
            style_prompt = ""
            visual_style = {}
            business_identity = {}

            # Use Brand DNA Extractor for complete brand analysis (preferred)
            if BRAND_DNA_AVAILABLE and self.brand_dna_extractor:
                try:
                    print(f"[BrandDNA] Extracting complete brand DNA from {domain}...")

                    # Run async extraction
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        brand_dna = loop.run_until_complete(
                            self.brand_dna_extractor.extract_brand_dna(base_url, combined_content)
                        )
                    finally:
                        loop.close()

                    if brand_dna:
                        # Extract logo
                        if brand_dna.get("logo_url"):
                            logo_url = brand_dna["logo_url"]
                            print(f"[BrandDNA] Logo URL: {logo_url}")

                        # Extract brand colors
                        vision_brand_colors = brand_dna.get("brand_colors", [])
                        if vision_brand_colors:
                            brand_color = vision_brand_colors[0]
                            print(f"[BrandDNA] Primary color: {brand_color}")

                        # Extract categorized images
                        categorized = brand_dna.get("categorized_images", {})
                        team_images = categorized.get("team", [])
                        vehicle_images = categorized.get("vehicle", [])
                        product_images = categorized.get("product", [])
                        equipment_images = categorized.get("equipment", [])

                        # Use team images as uniform images (they show staff in uniforms)
                        uniform_images = team_images

                        print(f"[BrandDNA] Team/Uniform images: {len(team_images)}")
                        print(f"[BrandDNA] Vehicle images: {len(vehicle_images)}")
                        print(f"[BrandDNA] Product images: {len(product_images)}")

                        # Extract style information
                        visual_style = brand_dna.get("visual_style", {})
                        style_prompt = brand_dna.get("style_prompt", "")
                        uniform_description = visual_style.get("uniform_details", {})
                        vehicle_description = visual_style.get("vehicle_details", {})
                        business_identity = brand_dna.get("business_identity", {})

                        print(f"[BrandDNA] Visual style: {visual_style.get('photography_style', 'unknown')}")
                        print(f"[BrandDNA] Business type: {business_identity.get('business_type', 'unknown')}")

                except Exception as brand_err:
                    print(f"[BrandDNA] Error (falling back to Vision AI): {brand_err}")
                    brand_dna = None

            # Fallback to basic Vision AI if Brand DNA extraction failed
            if not brand_dna and VISION_AI_AVAILABLE:
                try:
                    print(f"[VisionAI] Falling back to basic Vision AI analysis...")
                    images_data = _extract_images_from_website(base_url)

                    if not logo_url and images_data.get("logo_url"):
                        logo_url = images_data["logo_url"]

                    vision_analysis = _analyze_images_with_vision(images_data, domain)
                    if vision_analysis:
                        vision_brand_colors = vision_analysis.get("brand_colors", [])
                        if vision_brand_colors:
                            brand_color = vision_brand_colors[0]
                        uniform_images = vision_analysis.get("uniform_images", [])
                        vehicle_images = vision_analysis.get("vehicle_images", [])
                        equipment_images = vision_analysis.get("equipment_images", [])
                        uniform_description = vision_analysis.get("uniform_description")
                        vehicle_description = vision_analysis.get("vehicle_description")

                except Exception as vision_err:
                    print(f"[VisionAI] Error: {vision_err}")

            # Capture homepage screenshot for campaign creative reference
            screenshot_url = None
            screenshot_thumbnail_url = None
            screenshot_base64_data = None

            # Try Playwright first
            if SCREENSHOT_AVAILABLE:
                try:
                    print(f"[Screenshot] Capturing homepage screenshot with Playwright...")
                    screenshot_result = capture_homepage_screenshot_sync(base_url, full_page=True)
                    if screenshot_result.get("success"):
                        screenshot_url = screenshot_result.get("screenshot_url")  # MinIO URL
                        screenshot_thumbnail_url = screenshot_result.get("thumbnail_url")
                        screenshot_base64_data = screenshot_result.get("screenshot_base64")
                        print(f"[Screenshot] Playwright captured: {screenshot_url}")
                    else:
                        print(f"[Screenshot] Playwright failed: {screenshot_result.get('error')}")
                except Exception as screenshot_err:
                    print(f"[Screenshot] Playwright error: {screenshot_err}")

            # Fallback: ScreenshotOne API → download → upload to MinIO
            if not screenshot_url:
                try:
                    from modules.stores.scraping_service import (
                        capture_screenshot_via_api, upload_screenshot_to_storage,
                        SCREENSHOTONE_CONFIGURED, SCREENSHOT_MINIO_AVAILABLE
                    )
                    if SCREENSHOTONE_CONFIGURED:
                        print(f"[Screenshot] Falling back to ScreenshotOne API...")
                        api_result = capture_screenshot_via_api(base_url)
                        if api_result.get("success"):
                            ss_bytes = api_result["screenshot_bytes"]
                            screenshot_base64_data = __import__('base64').b64encode(ss_bytes).decode("utf-8")

                            # Upload to MinIO
                            if SCREENSHOT_MINIO_AVAILABLE:
                                import uuid as _uuid
                                ss_filename = f"{domain.replace('.', '_')}_{_uuid.uuid4().hex[:8]}.png"
                                upload_result = upload_screenshot_to_storage(ss_bytes, ss_filename)
                                if upload_result.get("success"):
                                    screenshot_url = upload_result.get("secure_url")
                                    screenshot_thumbnail_url = upload_result.get("thumbnail_url")
                                    print(f"[Screenshot] ScreenshotOne → MinIO: {screenshot_url}")
                                else:
                                    print(f"[Screenshot] MinIO upload failed: {upload_result.get('error')}")
                            else:
                                print(f"[Screenshot] ScreenshotOne captured (base64 only, no MinIO)")
                        else:
                            print(f"[Screenshot] ScreenshotOne failed: {api_result.get('error')}")
                except Exception as ss_fallback_err:
                    print(f"[Screenshot] ScreenshotOne fallback error: {ss_fallback_err}")

            return {
                "url": url,
                "domain": domain,
                "content": combined_content[:25000],
                "pages_extracted": len(all_content),
                "extracted_at": datetime.utcnow().isoformat(),
                # Basic branding
                "logo_url": logo_url,
                "brand_color": brand_color,
                "brand_colors": vision_brand_colors,
                # Real photos from the site (uniforms, vehicles, products) for ad image references
                "site_photos": collect_site_photos(base_url),
                # Homepage screenshot for ad creative reference
                "screenshot_url": screenshot_url,
                "screenshot_thumbnail_url": screenshot_thumbnail_url,
                "screenshot_base64": screenshot_base64_data,
                # Categorized images
                "uniform_images": uniform_images,
                "vehicle_images": vehicle_images,
                "equipment_images": equipment_images,
                "product_images": product_images,
                "team_images": team_images,
                # Descriptions
                "uniform_description": uniform_description,
                "vehicle_description": vehicle_description,
                # Brand DNA (complete analysis)
                "brand_dna": brand_dna,
                "visual_style": visual_style,
                "style_prompt": style_prompt,
                "business_identity": business_identity,
            }

        except Exception as e:
            print(f"[Scraping] Error: {e}")
            return self._mock_scrape_data(url)

    def _generate_ad_content(self, scraped_data: Dict[str, Any], url: str, store_context: Optional[Dict[str, Any]] = None,
                             ad_angles: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
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

        if ad_angles:
            # One ad set per research-backed angle instead of a single generic persona.
            def hook_brief(index):
                name, how, examples = HOOK_TACTICS[index % len(HOOK_TACTICS)]
                return f"   HOOK TACTIC — {name}: {how}. Patterns: {' '.join(examples)}"

            # Copy variations pre-written by the angles step (loss aversion / aspiration /
            # us-vs-them). When present, the copywriter's job is to polish and verify rather
            # than reinvent, so the three variations really do test different framings.
            def variations_block(a):
                vars_ = [v for v in (a.get("copy_variations") or []) if isinstance(v, dict) and v.get("primary_text")]
                if not vars_:
                    return ""
                lines = "\n".join(
                    f"     - approach {v.get('approach')}: primary_text: {v.get('primary_text')}\n"
                    f"       headline: {v.get('headline')} | description: {v.get('description')} | "
                    f"CTA: {v.get('call_to_action')}"
                    for v in vars_)
                return f"\n   PRE-DRAFTED COPY VARIATIONS (publishable drafts to refine, not to discard):\n{lines}"

            angle_lines = "\n".join(
                f"{i + 1}. {a.get('angle_name')} — audience: {a.get('target_audience')}\n"
                f"{hook_brief(i)}\n"
                f"   customer pain: {a.get('customer_pain')}\n"
                f"   desired outcome: {a.get('desired_outcome')}\n"
                f"   hook: {a.get('hook')} | how we solve it: {a.get('value_proposition')} | proof: {a.get('proof')}\n"
                f"   emotion: {a.get('emotion')} | keywords: {', '.join(a.get('keywords') or [])} | "
                f"visual: {a.get('visual_direction')}"
                + variations_block(a)
                for i, a in enumerate(ad_angles))
            persona_block = (
                f"STEP 2 - ONE AD SET PER AD ANGLE:\n\n"
                f"Market research produced these {len(ad_angles)} customer-first ad angles:\n{angle_lines}\n\n"
                f"Generate exactly {len(ad_angles)} ad sets, one per angle, in the same order. For each: name = the "
                "angle's audience; title and the first line of primary_text use that angle's HOOK TACTIC (each ad "
                "set uses a different tactic — do not repeat one); primary_text then acknowledges the customer's "
                "situation with empathy, shows the desired outcome and how this business delivers it, backed by "
                "the proof, and ends with one clear next step; use the keywords naturally; "
                "emotion and visual_direction follow the angle. Only use facts from the website content — do not "
                "invent offers, prices or statistics.\n\n"
                "COPY VARIATIONS per ad set: when an angle carries PRE-DRAFTED COPY VARIATIONS, produce "
                "copy_variations as a JSON array of 3 objects in the SAME order, each with: approach (copy it "
                "verbatim), primary_text, headline (max 40 chars), description (max 30 chars, teases the "
                "headline instead of repeating it), call_to_action. Fix only what breaks the rules: unsupported "
                "claims, emojis, em dashes, generic phrasing, headlines about the business instead of the reader. "
                "Keep each variation's distinct approach and first line — the three must remain genuinely "
                "different framings, never three paraphrases of one idea. When an angle has no pre-drafted "
                "variations, write 3 in the same JSON shape using three different hook tactics.\n\n"
                f"CRITICAL: You MUST output exactly {len(ad_angles)} ad sets in the ad_sets array, one per angle."
            )
        else:
            persona_block = """STEP 2 - GENERATE 1 BUYER PERSONA:

You MUST generate exactly 1 ad set targeting the PRIMARY buyer persona for this business.

FOR B2B BUSINESSES (technology, services, enterprise solutions):
Generate 1 ad set targeting the MOST LIKELY BUYER - choose the most relevant:
- The primary industry vertical that uses this product
- OR the key decision-maker role
- OR the main company type

FOR B2C BUSINESSES (retail, fashion, consumer products):
Generate 1 ad set targeting the PRIMARY CUSTOMER - choose the most relevant:
- The main demographic (e.g., young professionals, parents, fashion-forward consumers)
- OR a specific shopping occasion
- OR the core product category

CRITICAL: You MUST output exactly 1 ad set in the ad_sets array. Only 1 ad set."""

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

{persona_block}

STEP 3 - GENERATE AD CONTENT:

{AD_COPYWRITING_RULES}

IMPORTANT: Do NOT include any emojis in any of the generated content. Keep all text clean and professional.

1. HEADLINES (one per ad set, max 40 chars each) - curiosity hooks that pass the SWAP TEST above

2. DESCRIPTIONS (one per ad set, max 60 chars each) - a short teaser that adds to the headline, no emojis

3. AD_SETS (1 buyer persona):

For each ad set, provide:
- name: The BUYER PERSONA (industry or role-based, 2-4 words)
  Examples: "Property Management Companies", "Corporate Security Directors", "Smart City Planners"

- title: curiosity headline for this buyer's specific situation (max 40 chars, NO emojis) - follows the headline rules above

- audience_description: 2-3 sentences describing WHO this buyer is

- audience_tags: 15-20 Facebook/Meta targeting interests - these are INTERESTS and BEHAVIORS that Facebook uses for ad targeting, NOT hashtags
  Examples of good audience tags: "Small business owners", "Property management", "Commercial real estate", "Security systems", "Business technology", "Fleet management", "Facility management", "Operations management"
  These should be broad interest categories that exist in Facebook Ads Manager

- primary_text: SHORT hook-first ad copy, 3-4 lines, 30-60 words, exactly as the COPYWRITING RULES describe. NO emojis.

- copy_variations: ONLY when pre-drafted copy variations were supplied for this angle (see STEP 2): a JSON array of 3 objects, each {"approach", "primary_text", "headline", "description", "call_to_action"}, refined per the COPY VARIATIONS rules above. When none were supplied, omit this field entirely.

- features: 5 specific features from the website (kept for reference, NOT written into primary_text)

- hashtags: 8-10 social media hashtags for discoverability (single words, no spaces, lowercase)
  These are different from audience_tags - hashtags are for social media posts
  Examples: "security", "business", "technology", "innovation", "smartcity", "proptech"

- value_proposition: One sentence with specific metric

- emotion: Primary emotion (Efficiency, Security, Control, Growth, Trust)

- visual_direction: Specific scene description

Return as JSON:
{{
    "business_name": "The actual business name from the website",
    "business_type": "Industry/sector",
    "products_services": ["product1", "product2", "product3"],
    "key_metrics": ["99% accuracy", "85% faster"],
    "headlines": ["Clean headline without emojis", "Another headline"],
    "descriptions": ["Professional description without emojis", "Another description"],
    "ad_sets": [
        {{
            "name": "Buyer Persona Name",
            "title": "Clear Headline Without Emojis",
            "audience_description": "Description of the target buyer...",
            "audience_tags": ["Small business owners", "Property management", "Commercial real estate", "Security systems", "15-20 Facebook interests"],
            "primary_text": "Professional ad copy without emojis...",
            "copy_variations": [{{"approach": "loss aversion", "primary_text": "...", "headline": "...", "description": "...", "call_to_action": "Sign Up"}}],
            "features": ["feature 1", "feature 2", "feature 3", "feature 4", "feature 5"],
            "hashtags": ["business", "technology", "innovation", "security", "professional", "enterprise", "solutions", "industry"],
            "value_proposition": "Clear value statement",
            "emotion": "Primary emotion",
            "visual_direction": "Scene description",
            "call_to_action": "One of: Shop Now, Learn More, Contact Us, Send Message, Get Quote, Book Now, Order Now, Sign Up, Call Now"
        }}
    ]
}}

Return ONLY valid JSON, no markdown, NO EMOJIS anywhere.
"""

        # Claude (via OpenRouter) first: in a side-by-side on securico.co.zw it wrote clear,
        # human hooks where gpt-5.6-terra wrote stiff, riddle-like lines. OpenAI is the fallback.
        if self.openrouter:
            result = self._generate_with_openrouter(prompt)
            if result:
                return result
            logger.warning("[CampaignService] OpenRouter failed, trying OpenAI fallback")

        if self.openai:
            result = self._generate_with_openai(prompt)
            if result:
                return result

        # Final fallback to mock data
        logger.warning("[CampaignService] No AI client available, using mock data")
        return self._mock_ad_content(url, store_context)

    # Specific promises ad copy tends to invent ("Same-Day Delivery", "100% genuine",
    # "full manufacturer warranty"); kept only when the website itself says them.
    _CLAIM_PATTERNS = (
        r"same[- ]day", r"next[- ]day", r"\b24/7\b", r"\b24 hours?\b", r"\b\d+\s?%", r"\b(?:over|more than)\s+\d+",
        r"\b\d+\+", r"\bwarrant(?:y|ies)\b", r"\bguarantee[ds]?\b", r"\bfree (?:delivery|shipping)\b",
        r"\bcheapest\b", r"\blowest prices?\b", r"#1\b", r"\bnumber one\b", r"\baward[- ]winning\b", r"\bbest\b",
        # Operational promises (Claude wrote "order before midday", "all in stock").
        r"\bbefore (?:midday|noon|\d{1,2}\s?(?:am|pm))\b", r"\bin stock\b", r"\bwithin \d+ (?:hours?|minutes?|days?)\b",
    )
    # Meta call-to-action buttons the copy may choose from.
    _CTA_CHOICES = ("Shop Now", "Learn More", "Contact Us", "Send Message", "Get Quote", "Book Now",
                    "Order Now", "Sign Up", "Call Now", "Get Offer")

    @staticmethod
    def _norm_claim_text(text: str) -> str:
        """Compare claims on meaning, not punctuation: "Same-day" == "same day",
        "2,000+" == "2000+" (a raw substring check deleted true claims)."""
        t = (text or "").lower().replace("‑", "-").replace("–", "-").replace("—", "-")
        t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
        t = re.sub(r"[-_]", " ", t)
        return re.sub(r"\s+", " ", t)

    def _unsupported_claims(self, text: str, website_text: str) -> List[str]:
        site = self._norm_claim_text(website_text)
        body = self._norm_claim_text(text)
        found = {m.group(0) for pat in self._CLAIM_PATTERNS for m in re.finditer(pat, body, re.I)}
        unsupported = []
        for claim in found:
            if claim in site:
                continue
            # "over 2000 customers" is backed by the site's "2000+ Happy Customers".
            number = re.search(r"\d+", claim)
            if number and re.match(r"(?:over|more than)\s", claim) and re.search(rf"\b{number.group(0)}\s?\+", site):
                continue
            unsupported.append(claim)
        return sorted(unsupported)

    def _ground_ad_copy(self, data: Dict[str, Any], website_text: str) -> Dict[str, Any]:
        """Remove claims the website doesn't support: an LLM rewrite first, then drop any
        sentence that still carries one. Without website text there is nothing to check."""
        if not website_text:
            return data
        fields = ("title", "primary_text", "value_proposition")
        claims = self._unsupported_claims(" ".join(str(data.get(f) or "") for f in fields), website_text)
        if not claims:
            return data
        logger.info(f"[CampaignService] Unsupported claims in '{data.get('name')}': {claims}")
        rewrite_prompt = (
            "Rewrite this Facebook ad so it makes no claim the business's website does not support. "
            f"Remove these unsupported claims: {', '.join(claims)}. Keep the audience, tone and roughly "
            "the same length; no emojis; add no new facts, numbers or promises. "
            'Return ONLY JSON {"title": "", "primary_text": "", "value_proposition": ""}.\n\n'
            + json.dumps({f: data.get(f) for f in fields}))
        fixed = None
        if self.openai:
            # Mechanical constrained edit, not creative writing — gpt-4o-mini is plenty.
            try:
                res = self.openai.chat.completions.create(
                    model=os.getenv("AD_REWRITE_MODEL", "gpt-4o-mini"),
                    messages=[{"role": "user", "content": rewrite_prompt}],
                    temperature=0.3, max_tokens=1200, response_format={"type": "json_object"})
                fixed = json.loads(res.choices[0].message.content)
            except Exception as e:
                logger.warning(f"[CampaignService] Ad copy rewrite (OpenAI) failed: {e}")
        if fixed is None and self.openrouter:
            try:
                res = self.openrouter.chat_completion_sync(
                    model=os.getenv("OPENROUTER_AD_REWRITE_MODEL", "openai/gpt-4o-mini"),
                    messages=[{"role": "user", "content": rewrite_prompt}],
                    temperature=0.3, max_tokens=1200, response_format={"type": "json_object"})
                fixed = json.loads(res["choices"][0]["message"]["content"])
            except Exception as e:
                logger.warning(f"[CampaignService] Ad copy rewrite (OpenRouter) failed: {e}")
        if fixed:
            data = {**data, **{f: fixed[f] for f in fields if isinstance(fixed.get(f), str) and fixed[f]}}
        for f in fields:
            text = str(data.get(f) or "")
            if self._unsupported_claims(text, website_text):
                data[f] = " ".join(s for s in re.split(r"(?<=[.!?])\s+", text)
                                   if not self._unsupported_claims(s, website_text))
        return data

    def _save_generated_ad_sets(self, campaign: Campaign, ad_content: Dict[str, Any]) -> None:
        """Persist every generated ad set (one per ad angle) with its ad copy.

        Budget is split evenly across the sets. Headline falls back to the campaign-level
        headlines and description to the set's value proposition. No image yet — that is
        generated by the image step and stored on the same UrlAdContent row.
        """
        ad_sets_data = [s for s in (ad_content.get("ad_sets") or []) if isinstance(s, dict)]
        if not ad_sets_data:
            logger.warning(f"[CampaignService] No ad sets in generated content for campaign {campaign.id}")
            return
        headlines = ad_content.get("headlines") or []
        descriptions = ad_content.get("descriptions") or []
        budget = (campaign.daily_budget or 0) / len(ad_sets_data) if campaign.daily_budget else None
        website_text = (campaign.scraped_data or {}).get("content", "") if isinstance(campaign.scraped_data, dict) else ""

        for i, data in enumerate(ad_sets_data):
            data = self._ground_ad_copy(data, website_text)
            # No em/en dashes in customer-facing copy, even when the model slips one in.
            for f in ("title", "primary_text", "value_proposition"):
                if isinstance(data.get(f), str):
                    data[f] = re.sub(r"\s*[—–]\s*", ", ", data[f])
            # The copy's own CTA wins over the "Learn More" default; a merchant-chosen button wins over both.
            chosen = next((c for c in self._CTA_CHOICES if c.lower() == str(data.get("call_to_action") or "").strip().lower()), None)
            cta = (campaign.conversion_button if campaign.conversion_button not in (None, "", "Learn More") else chosen) or "Learn More"
            description = (descriptions[i] if i < len(descriptions) else "") or data.get("value_proposition") or ""
            if self._unsupported_claims(description, website_text):
                description = data.get("value_proposition") or ""
            headline = str(data.get("title") or (headlines[i] if i < len(headlines) else "") or campaign.name)

            if self._unsupported_claims(headline, website_text):
                headline = campaign.name or ""
            ad_set = AdSet(
                campaign_id=campaign.id,
                name=str(data.get("name") or f"Ad Set {i + 1}")[:255],
                title=str(data.get("title") or "")[:255] or None,
                audience_tags=data.get("audience_tags") or [],
                hashtags=data.get("hashtags") or [],
                daily_budget=budget,
                is_selected=True,
            )
            self.db.add(ad_set)
            self.db.flush()

            # One row per copy variation (Copy-A/B/C) so an ad set launches with A/B test
            # material the way the example campaigns do: same angle, different framings —
            # AND different delivery: each variation carries its own targeting hint,
            # placement, format, optimization goal and demographics from the angles step.
            # The polished base copy stays the primary row; variations are secondary.
            variations = [v for v in (data.get("copy_variations") or [])
                          if isinstance(v, dict) and (v.get("primary_text") or v.get("headline"))][:3]

            def _variation_delivery(v: Dict[str, Any]) -> Dict[str, Any]:
                """Normalized per-variation delivery fields for the creative metadata."""
                hint = v.get("targeting_hint") if isinstance(v.get("targeting_hint"), dict) else {}
                demo = v.get("demographics") if isinstance(v.get("demographics"), dict) else {}
                return {
                    "targeting_hint": {
                        "interests": [str(t) for t in (hint.get("interests") or [])][:6],
                        "behaviors": [str(t) for t in (hint.get("behaviors") or [])][:3],
                    },
                    "placement": str(v.get("placement") or "automatic"),
                    "format": str(v.get("format") or "single_image"),
                    "optimization": str(v.get("optimization") or "conversions"),
                    "demographics": {
                        "age_min": demo.get("age_min") or 18,
                        "age_max": demo.get("age_max") or 65,
                        "gender": str(demo.get("gender") or "all"),
                    },
                    "image_direction": str(v.get("image_direction") or "")[:400],
                    # Which image family this variation's creative gets (lifestyle moment,
                    # product mockup, split concept) - read by _ad_image_jobs.
                    "image_approach": str(v.get("approach") or "").strip().lower()[:40],
                }

            primary_delivery = _variation_delivery(variations[0] if variations else {})
            self.db.add(AdContent(
                ad_set_id=ad_set.id,
                headline=headline[:255],
                primary_text=data.get("primary_text") or "",
                description=description,
                call_to_action=str(cta)[:100],
                destination_url=(campaign.source_url or "")[:512] or None,
                media_type=primary_delivery["format"],
                placement=primary_delivery["placement"],
                optimization_goal=primary_delivery["optimization"],
                creative_metadata=primary_delivery,
                variation_label="Copy-A",
                copy_variation_index=0,
                is_primary=True,
            ))
            for vi, v in enumerate(variations, start=1):
                v_headline = str(v.get("headline") or headline)
                if self._unsupported_claims(v_headline, website_text):
                    v_headline = headline
                v_text = re.sub(r"\s*[—–]\s*", ", ", str(v.get("primary_text") or ""))
                v_text = " ".join(s for s in re.split(r"(?<=[.!?])\s+", v_text)
                                  if not self._unsupported_claims(s, website_text))
                v_cta = next((c for c in self._CTA_CHOICES
                              if c.lower() == str(v.get("call_to_action") or "").strip().lower()), cta)
                delivery = _variation_delivery(v)
                self.db.add(AdContent(
                    ad_set_id=ad_set.id,
                    headline=v_headline[:255],
                    primary_text=v_text,
                    description=str(v.get("description") or "")[:255],
                    call_to_action=str(v_cta)[:100],
                    destination_url=(campaign.source_url or "")[:512] or None,
                    media_type=delivery["format"],
                    placement=delivery["placement"],
                    optimization_goal=delivery["optimization"],
                    creative_metadata=delivery,
                    variation_label=f"Copy-{chr(ord('A') + vi)}",
                    copy_variation_index=vi,
                    is_primary=False,
                ))
        self.db.flush()
        n_vars = sum(len([v for v in (d.get("copy_variations") or []) if isinstance(v, dict)]) for d in ad_sets_data)
        logger.info(f"[CampaignService] Saved {len(ad_sets_data)} ad sets with copy "
                    f"(+{n_vars} copy variations) for campaign {campaign.id}")

    def _ad_image_jobs(self, campaign: Campaign, include_existing: bool = False) -> List[Tuple[Any, str, List[str]]]:
        """(ad content, image prompt, reference image URLs) for each ad lacking an image.

        Every copy variation (Copy-A/B/C) gets its OWN creative for its angle. The
        prompts, and which of the business's real photos each creative must copy,
        are the ads-image OpenClaw agent's art direction: it is given the campaign,
        all variations and the website photos themselves (as thumbnails), so the
        scene is judged per variation instead of filled into a fixed template here.
        The backend only attaches the photos it chose and renders its prompt."""
        from modules.openclaw.agent_service import art_direct_image_set_sync

        sd = campaign.scraped_data if isinstance(campaign.scraped_data, dict) else {}
        profile = (sd.get("market_research") or {}).get("profile") or {}
        angles = sd.get("ad_angles") or []
        business = profile.get("company_name") or campaign.name or "the business"
        kind = profile.get("business_type") or ""
        place = profile.get("location") or ""
        products = [str(p) for p in (profile.get("products") or [])[:5]]
        # The store's Brand DNA aesthetic steers every image (palette mood, imagery style).
        dna = profile.get("brand_dna") if isinstance(profile.get("brand_dna"), dict) else None
        aesthetic = str((dna.get("voice_and_style") or {}).get("aesthetic_style") or "").strip()[:300] if dna else ""
        screenshot = sd.get("screenshot_url")
        site_photos = sd.get("site_photos") or []
        from utils.brand import logo_brand_color
        store_logo = str(getattr(getattr(campaign, "store", None), "logo_url", "") or "")
        brand_color = logo_brand_color(str(sd.get("logo_url") or store_logo)) or sd.get("brand_color") or ""
        store_id = str(getattr(campaign, "store_id", "") or "")

        variations: List[Dict[str, Any]] = []
        contents: List[Any] = []
        ordered_sets = sorted(campaign.ad_sets or [], key=lambda s: s.created_at or datetime.min)
        for i, ad_set in enumerate(ordered_sets):
            angle = angles[i] if i < len(angles) and isinstance(angles[i], dict) else {}
            angle_scene = angle.get("visual_direction") or f"a customer benefiting from: {business}"
            for content in ad_set.ad_contents:
                if not (content.primary_text or content.headline):
                    continue
                if content.media_url and not include_existing:
                    continue
                meta = content.creative_metadata if isinstance(content.creative_metadata, dict) else {}
                approach = str(meta.get("image_approach") or "").lower()
                if not approach:
                    # Primary row (Copy-A): approach from its position - the base copy of the
                    # angle. Secondary rows carry their approach in creative_metadata.
                    approach = "aspiration" if content.is_primary else "loss aversion"
                scene = str(meta.get("image_direction") or "").strip() or angle_scene
                scene = re.sub(r"\s*[—–]\s*", ", ", scene)
                contents.append(content)
                variations.append({
                    "index": len(variations) + 1,
                    "angle": approach,
                    "headline": content.headline or "",
                    "primary_text": (content.primary_text or "")[:1200],
                    "call_to_action": content.call_to_action or "Learn More",
                    "benefit_chips": [str(c) for c in (meta.get("benefit_chips") or []) if str(c)][:4],
                    "scene": scene,
                    "emotion": str(angle.get("emotion") or ""),
                    "proof": str(angle.get("proof") or ""),
                    "campaign_objective": str(angle.get("campaign_objective") or ""),
                })
        if not variations:
            return []

        candidates = fetch_photo_candidates(site_photos)
        photos = [{"url": url, "kind": f"photo {i} from {business}'s own website"}
                  for i, (url, _uri) in enumerate(candidates, 1)]
        thumbnails = [uri for _url, uri in candidates]

        directions = art_direct_image_set_sync(
            {
                "business": {
                    "name": business,
                    "type": kind,
                    "location": place,
                    "products": products,
                    "brand_colours": brand_color,
                    "aesthetic": aesthetic,
                },
                "campaign": {
                    "name": campaign.name,
                    "objective": variations[0].get("campaign_objective"),
                    "has_website_screenshot": bool(screenshot),
                },
            },
            variations,
            photos,
            thumbnails,
            store_id=store_id,
        )

        jobs: List[Tuple[Any, str, List[str]]] = []
        for content, variation in zip(contents, variations):
            direction = directions[variation["index"]]
            references = list(direction["photo_urls"])
            if screenshot and direction["use_screenshot"]:
                references.append(screenshot)
            jobs.append((content, direction["prompt"], references))
        return jobs

    @staticmethod
    def _fetch_logo(campaign: Campaign) -> Optional[bytes]:
        """The business's real logo: the scraper's logo_url, falling back to the store's own
        uploaded logo (set at onboarding, Store.logo_url) if the scraper didn't find one.

        Deliberately does NOT fall back further to cropping something out of the website
        screenshot — a blind crop risks pasting a garbled chunk of a webpage into the ad as
        if it were a clean logo mark, which would look worse than no logo overlay at all.
        The screenshot is still used (see _ad_image_jobs) as a reference image so the model
        picks up brand colours/theme during generation, just not composited as a literal logo."""
        sd = campaign.scraped_data if isinstance(campaign.scraped_data, dict) else {}
        url = str(sd.get("logo_url") or "")
        if not (url.startswith("http") and not url.lower().endswith(".svg")):
            store_logo = str(getattr(getattr(campaign, "store", None), "logo_url", "") or "")
            url = store_logo if store_logo.startswith("http") and not store_logo.lower().endswith(".svg") else ""
        if not url:
            return None
        # A bare "Mozilla/5.0" User-Agent with no other browser-like headers is exactly what
        # WAFs (Cloudflare etc.) fingerprint and block from datacenter IPs - confirmed live:
        # reliabletech.co.zw 403'd this from the production server while an ordinary browser
        # request succeeds. A fuller header set clears some of these; not all.
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": url.split("/", 3)[0] + "//" + url.split("/", 3)[2] + "/" if url.count("/") >= 2 else url,
        }
        try:
            import requests as _requests
            r = _requests.get(url, timeout=15, headers=headers)
            if r.status_code == 200 and r.content:
                return r.content
            logger.warning(f"[CampaignService] Logo fetch got HTTP {r.status_code} ({url}); "
                            f"trying ScreenshotOne fallback.")
        except Exception as e:
            logger.warning(f"[CampaignService] Logo fetch failed ({url}): {e}; trying ScreenshotOne fallback.")

        # Some sites' WAFs block the server's datacenter IP outright (confirmed live against
        # reliabletech.co.zw: 403 + challenge page, no header spoofing gets past it) while
        # letting ScreenshotOne's own infrastructure through - same fallback already used for
        # bot-blocked homepage screenshots elsewhere in scraping_service.py.
        try:
            from modules.stores.scraping_service import SCREENSHOTONE_CONFIGURED, SCREENSHOTONE_ACCESS_KEY
            if not SCREENSHOTONE_CONFIGURED:
                return None
            import requests as _requests
            from urllib.parse import quote
            api_url = (f"https://api.screenshotone.com/take?access_key={SCREENSHOTONE_ACCESS_KEY}"
                       f"&url={quote(url, safe='')}&full_page=true&format=png&timeout=30")
            r = _requests.get(api_url, timeout=45)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and r.content:
                return r.content
            logger.warning(f"[CampaignService] ScreenshotOne logo fallback also failed for {url} "
                            f"(HTTP {r.status_code}); no logo overlay for this campaign.")
            return None
        except Exception as e:
            logger.warning(f"[CampaignService] ScreenshotOne logo fallback failed ({url}): {e}")
            return None

    @staticmethod
    def _overlay_logo(image_data: bytes, logo_data: Optional[bytes]) -> bytes:
        """Place the real logo bottom-right on a white plate. Image models garble logos
        (a test put an unreadable sticker on the box), so the logo is composited in code."""
        if not logo_data:
            return image_data
        try:
            import io
            from PIL import Image, ImageDraw
            image = Image.open(io.BytesIO(image_data)).convert("RGBA")
            logo = Image.open(io.BytesIO(logo_data)).convert("RGBA")
            w, h = image.size
            scale = min(w * 0.20 / logo.width, h * 0.10 / logo.height)
            logo = logo.resize((max(1, int(logo.width * scale)), max(1, int(logo.height * scale))), Image.LANCZOS)
            pad, margin = int(w * 0.015), int(w * 0.03)
            x1, y1 = w - margin - logo.width - 2 * pad, h - margin - logo.height - 2 * pad
            plate = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(plate).rounded_rectangle(
                (x1, y1, w - margin, h - margin), radius=pad, fill=(255, 255, 255, 235))
            image = Image.alpha_composite(image, plate)
            image.alpha_composite(logo, (x1 + pad, y1 + pad))
            out = io.BytesIO()
            image.convert("RGB").save(out, format="PNG")
            return out.getvalue()
        except Exception as e:
            logger.warning(f"[CampaignService] Logo overlay skipped: {e}")
            return image_data

    def generate_campaign_images(self, campaign: Campaign) -> int:
        """One image per copy variation, art-directed by that variation's approach.

        Each Copy-A/B/C gets its own creative (lifestyle moment, product mockup, split
        concept) so the visual test matches the copy test. Images are generated in
        parallel (HTTP only, off the DB session), then uploaded and linked one at a time.
        AD_IMAGES_PER_CAMPAIGN caps the bill (0 = unlimited); ads past the cap fall back
        to sharing the first generated image so every ad stays publishable."""
        from concurrent.futures import ThreadPoolExecutor
        from modules.assets.service import AssetService, generate_image_bytes

        jobs = all_jobs = self._ad_image_jobs(campaign)
        limit = int(os.getenv("AD_IMAGES_PER_CAMPAIGN", "0"))
        if limit > 0:
            jobs = jobs[:limit]
        if not jobs:
            return 0

        def generate_with_retry(job):
            _content, prompt, references = job
            image_data, error = generate_image_bytes(prompt, references)
            if error or not image_data:
                # The model occasionally returns nothing (1 of 3 on reliabletech.co.zw), and a
                # reference URL it can't fetch fails the call: retry once without references.
                image_data, error = generate_image_bytes(prompt)
            return image_data, error

        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            results = list(pool.map(generate_with_retry, jobs))

        business = campaign.name or "the business"
        logo_data = self._fetch_logo(campaign)
        assets = AssetService(self.db)
        done = 0
        for (content, _prompt, _refs), (image_data, error) in zip(jobs, results):
            if error or not image_data:
                logger.warning(f"[CampaignService] Ad image failed for '{content.headline}': {error}")
                continue
            image_data = self._overlay_logo(image_data, logo_data)
            asset, error = assets.save_generated_image(
                campaign.store_id, image_data, content.headline or business,
                description=content.primary_text, call_to_action=content.call_to_action, campaign_id=campaign.id,
                high_quality=bool(logo_data))
            if error or not asset:
                logger.warning(f"[CampaignService] Saving ad image failed for '{content.headline}': {error}")
                continue
            content.asset_id = asset.id
            content.media_url = (asset.cloudinary_secure_url or asset.cloudinary_url or "")[:512] or None
            done += 1
        # Ads past the cap (or whose generation failed) share the first generated image
        # rather than showing none, so every ad set is complete (and publishable).
        first = next((c for c, _p, _r in jobs if c.media_url), None)
        if first:
            for content, _p, _r in all_jobs:
                if not content.media_url:
                    content.asset_id, content.media_url = first.asset_id, first.media_url
        self.db.commit()
        logger.info(f"[CampaignService] Generated {done}/{len(jobs)} ad images for campaign {campaign.id}")
        return done

    def _generate_with_openrouter(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Generate content using OpenRouter API."""
        try:
            logger.info("[CampaignService] Generating ad content with OpenRouter...")

            # Use synchronous version for compatibility
            result = self.openrouter.chat_completion_sync(
                # Ad copy is what customers read, once per campaign: Claude Sonnet writes far more
                # persuasive, specific copy than gpt-4o-mini (~$0.09 per campaign).
                model=os.getenv("AD_CONTENT_MODEL", "anthropic/claude-sonnet-4.6"),
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
        """Generate content using OpenAI API (now the primary path, not just a fallback).

        Ad copy is what customers read, once per campaign — gpt-5.6-terra ($2/$12 per 1M
        tokens) writes noticeably more persuasive, specific copy than gpt-4o-mini for a
        fraction of gpt-6-astra's cost; that balance is worth it at this call volume."""
        try:
            logger.info("[CampaignService] Generating ad content with OpenAI...")

            # gpt-5.6-terra rejects a non-default temperature ("Only the default (1) value
            # is supported" — confirmed against the live API), so it's omitted here.
            response = self.openai.chat.completions.create(
                model=os.getenv("AD_CONTENT_MODEL_OPENAI", "gpt-5.6-terra"),
                messages=[
                    {"role": "system", "content": "You are a digital marketing expert. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                # The gpt-5 family rejects max_tokens (400 "Use 'max_completion_tokens'"), which
                # sent every campaign's copy to the fallback. Reasoning tokens count toward this
                # cap, so it's sized above the ~4k of JSON copy for three ad sets.
                max_completion_tokens=12000
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

    def _create_ad_sets(self, campaign: Campaign, ad_content: Dict[str, Any], asset_ids: Optional[List[uuid.UUID]] = None, num_copies: int = 1, num_images: int = 1):
        """Create ad sets from generated content with AI-generated images using Ad Creative Agent.

        If user provides assets via asset_ids, those will be used instead of generating AI images.
        Images are generated with store branding (logo, color theme) when available.

        Args:
            num_copies: Number of copy variations per ad set (1-5). Default 1 for backward compat.
            num_images: Number of image variations per ad set (1-3). Default 1 for backward compat.
        """
        # Ad-set creative/image generation depended on the ad-generation modules
        # that were removed in the OpenClaw migration. When those are unavailable,
        # skip generating ad sets — the campaign is still created and retains its
        # scraped data and AI-generated headlines/descriptions. Ad creation is
        # now handled by OpenClaw.
        if not AD_MODULES_AVAILABLE:
            # The creative/copywriter/image agents were removed, which used to mean no ad
            # sets were saved at all (every campaign ended READY with zero ads). Save the
            # generated ad sets and their copy directly; images are generated separately.
            self._save_generated_ad_sets(campaign, ad_content)
            return

        # Clamp to safe ranges
        num_copies = max(1, min(num_copies, 5))
        num_images = max(1, min(num_images, 3))
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

        # Get reference images from Vision AI analysis (uniforms, vehicles, equipment)
        uniform_images = scraped_data.get("uniform_images", [])
        vehicle_images = scraped_data.get("vehicle_images", [])
        equipment_images = scraped_data.get("equipment_images", [])

        # Extract visual descriptions for accurate scene generation
        # These may come from BrandDNA (dict) or VisionAI (string)
        def _desc_to_str(val):
            if isinstance(val, dict):
                return "; ".join(f"{k}: {v}" for k, v in val.items() if v) if val else ""
            return str(val) if val else ""

        uniforms_desc = _desc_to_str(scraped_data.get("uniform_description"))
        vehicles_desc = _desc_to_str(scraped_data.get("vehicle_description"))
        # BrandDNA may also store imagery/equipment in visual_style
        vs = scraped_data.get("visual_style", {})
        equipment_desc = _desc_to_str(vs.get("equipment_details")) if isinstance(vs, dict) else ""
        imagery_desc = _desc_to_str(vs.get("photography_style")) if isinstance(vs, dict) else ""

        if logo_url_to_use:
            logger.info(f"[CampaignService] Using SCRAPED logo URL: {logo_url_to_use[:80]}...")
        if color_theme_to_use:
            logger.info(f"[CampaignService] Using SCRAPED color theme: {color_theme_to_use}")
        if uniform_images:
            logger.info(f"[CampaignService] Found {len(uniform_images)} uniform reference images")
        if vehicle_images:
            logger.info(f"[CampaignService] Found {len(vehicle_images)} vehicle reference images")
        if uniforms_desc:
            logger.info(f"[CampaignService] Uniform description: {uniforms_desc[:80]}...")
        if vehicles_desc:
            logger.info(f"[CampaignService] Vehicle description: {vehicles_desc[:80]}...")

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

        for i, ad_set_data in enumerate(ad_sets_data[:1]):  # Create 1 ad set per campaign
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
            visual_direction_parts = []
            if detected_industry:
                visual_direction_parts.append(f"Business type: {detected_industry.replace('_', ' ')}")
            if color_theme_to_use:
                visual_direction_parts.append(f"Brand color: {color_theme_to_use} - use as accent throughout")
            if base_visual_direction:
                visual_direction_parts.append(base_visual_direction)
            visual_direction = ". ".join(visual_direction_parts) if visual_direction_parts else ""

            agent_ad_angle = None
            agent_headline = None
            agent_image_prompt = ""
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
                    logger.info(f"[AdCreativeAgent] Generating creative for ad set: {ad_set.name}")
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

                    logger.info(f"[AdCreativeAgent] Generated prompt: {agent_image_prompt[:100]}...")
                    logger.info(f"[AdCreativeAgent] Generated ad angle: {agent_ad_angle[:100]}...")

                    # --- Step 2: Generate COPY VARIATIONS ---
                    copy_variations = [{
                        "headline": agent_headline or headline,
                        "primary_text": agent_ad_angle or primary_text,
                        "description": description,
                        "call_to_action": campaign.conversion_button or "Learn More",
                        "strategy": "original",
                    }]

                    if num_copies > 1:
                        try:
                            logger.info(f"[CopywriterAgent] Generating {num_copies} copy variations for: {ad_set.name}")
                            extra_copies = loop.run_until_complete(
                                self.copywriter_agent.generate_copy_variations_for_url_ad(
                                    business_name=business_name,
                                    product_description=primary_text or description or f"{business_name}",
                                    target_audience=ad_set_data.get("name", "General audience"),
                                    base_headline=agent_headline or headline,
                                    base_primary_text=agent_ad_angle or primary_text,
                                    features=features,
                                    cta=campaign.conversion_button or "Learn More",
                                    num_variations=num_copies,
                                    store_id=str(campaign.store_id) if campaign.store_id else None,
                                )
                            )
                            # Replace with all variations (the LLM generates fresh ones including a variation of the original)
                            if extra_copies:
                                copy_variations = extra_copies[:num_copies]
                                logger.info(f"[CopywriterAgent] Got {len(copy_variations)} copy variations")
                        except Exception as copy_err:
                            logger.error(f"[CopywriterAgent] Error generating variations: {copy_err}")
                            # Fallback: use the single original copy

                    # --- Step 3: Generate IMAGE VARIATIONS ---
                    image_variations = []  # List of {"image_base64": ..., "cloudinary_url": ...}

                    if user_asset_url:
                        # User provided assets — use them instead of generating
                        image_variations = [{"image_base64": None, "cloudinary_url": user_asset_url, "asset_id": user_asset_id}]
                        logger.info(f"[MediaGenerator] Using user asset for ad set: {ad_set.name}")
                    elif agent_image_prompt:
                        scene_prompt = self.media_generator._strip_text_overlay_from_prompt(agent_image_prompt)
                        brand_colors = scraped_data.get("brand_colors", [])
                        accent = color_theme_to_use or (brand_colors[0] if brand_colors else "#FFB800")

                        for img_idx in range(num_images):
                            try:
                                # Add variation seed for images beyond the first
                                varied_scene = scene_prompt
                                if img_idx > 0:
                                    variation_seeds = [
                                        "Alternative angle: different camera perspective and lighting mood",
                                        "Variation: different background environment and color emphasis",
                                        "Alternate composition: different layout and visual focus",
                                    ]
                                    varied_scene = f"{scene_prompt}. {variation_seeds[img_idx % len(variation_seeds)]}"

                                logger.info(f"[MediaGenerator] Generating image {img_idx+1}/{num_images} for: {ad_set.name}")
                                ad_result = loop.run_until_complete(
                                    self.media_generator.generate_campaign_ad(
                                        store_name=business_name,
                                        store_description=primary_text or description or "",
                                        business_type=scraped_data.get("business_identity", {}).get("industry", "business") if isinstance(scraped_data.get("business_identity"), dict) else "business",
                                        logo_url=logo_url_to_use,
                                        screenshot_url=scraped_data.get("screenshot_url"),
                                        screenshot_base64=scraped_data.get("screenshot_base64"),
                                        color_theme=color_theme_to_use,
                                        accent_color=accent,
                                        products_or_services=features,
                                        key_benefits=ad_set_data.get("key_benefits", features[:3]) if features else None,
                                        scene_prompt=varied_scene,
                                        headline=agent_headline or headline or business_name,
                                        bullet_points=features[:3] if features else None,
                                        cta_text=campaign.conversion_button or "Learn More",
                                        upload_to_cloud=True,
                                        uniforms_description=uniforms_desc,
                                        vehicles_description=vehicles_desc,
                                        equipment_description=equipment_desc,
                                        imagery_description=imagery_desc,
                                    )
                                )

                                if ad_result.get("success"):
                                    image_variations.append({
                                        "image_base64": ad_result.get("image_base64"),
                                        "cloudinary_url": ad_result.get("cloudinary_url"),
                                        "asset_id": None,
                                    })
                                    logger.info(f"[MediaGenerator] SUCCESS - Image {img_idx+1}: {ad_result.get('cloudinary_url', 'base64 only')}")
                                else:
                                    logger.error(f"[MediaGenerator] Failed image {img_idx+1}: {ad_result.get('error')}")
                            except Exception as gen_err:
                                import traceback
                                logger.error(f"[MediaGenerator] Error generating image {img_idx+1}: {gen_err}")
                                logger.error(f"[MediaGenerator] Traceback: {traceback.format_exc()}")

                    # Ensure at least one image slot (even if generation failed)
                    if not image_variations:
                        image_variations = [{"image_base64": None, "cloudinary_url": None, "asset_id": None}]

                finally:
                    loop.close()

            except Exception as e:
                import traceback
                logger.error(f"[AdCreativeAgent/AdGenerator] Error for ad set {i+1}: {e}")
                logger.error(f"[AdCreativeAgent/AdGenerator] Traceback: {traceback.format_exc()}")
                # Fallback: single copy + no image
                copy_variations = [{
                    "headline": headline,
                    "primary_text": primary_text,
                    "description": description,
                    "call_to_action": campaign.conversion_button or "Learn More",
                    "strategy": "fallback",
                }]
                image_variations = [{"image_base64": None, "cloudinary_url": None, "asset_id": None}]

            # --- Step 4: CROSS-MIX copies × images into UrlAdContent entries ---
            content_count = 0
            for copy_idx, copy_var in enumerate(copy_variations):
                for img_idx, img_var in enumerate(image_variations):
                    is_first = (copy_idx == 0 and img_idx == 0)
                    # Build variation label (None for single variant = backward compat)
                    variation_label = None
                    if num_copies > 1 or num_images > 1:
                        variation_label = f"Copy-{chr(65 + copy_idx)}_Image-{img_idx + 1}"

                    ad_content_obj = AdContent(
                        ad_set_id=ad_set.id,
                        headline=copy_var.get("headline", headline),
                        primary_text=copy_var.get("primary_text", primary_text),
                        description=copy_var.get("description", description),
                        call_to_action=copy_var.get("call_to_action", campaign.conversion_button),
                        destination_url=campaign.source_url,
                        media_url=img_var.get("cloudinary_url"),
                        asset_id=img_var.get("asset_id"),
                        is_primary=is_first,
                        generated_image_base64=img_var.get("image_base64") if not user_asset_url else None,
                        variation_label=variation_label,
                        copy_variation_index=copy_idx,
                        image_variation_index=img_idx,
                    )
                    self.db.add(ad_content_obj)
                    content_count += 1

            logger.info(f"[CampaignService] Created {content_count} ad content entries for ad set '{ad_set.name}' ({len(copy_variations)} copies × {len(image_variations)} images)")

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

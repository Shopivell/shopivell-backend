# brand_dna_extractor.py - Extract complete brand DNA from a website
"""
Main orchestrator for brand intelligence extraction.
Combines all analysis components to build a complete brand DNA profile.

Brand DNA includes:
- Company identity (name, industry, business model)
- Visual style (photography, composition, colors)
- Brand assets (logos, team images, vehicles, products)
- Style guidelines (how to recreate the brand's look)
"""

import os
import logging
import asyncio
import json
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, urljoin
from datetime import datetime
from dotenv import load_dotenv

from .asset_categorizer import AssetCategorizer
from .visual_style_analyzer import VisualStyleAnalyzer

load_dotenv()
logger = logging.getLogger(__name__)

# Pages to fetch for comprehensive content extraction
CONTENT_PAGES = [
    '',  # Main page
    '/services', '/products', '/pricing', '/plans',
    '/packages', '/solutions', '/offerings',
    '/about', '/about-us',
]

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class BrandDNAExtractor:
    """
    Extracts complete brand DNA from a website URL.

    This is the main entry point for brand intelligence.
    It orchestrates image extraction, categorization, and style analysis
    to produce a complete brand profile for autonomous ad generation.
    """

    def __init__(self):
        self.asset_categorizer = AssetCategorizer()
        self.style_analyzer = VisualStyleAnalyzer()
        self.openai = None

        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        if not url.startswith('http'):
            url = 'https://' + url
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')

    def _analyze_business_identity(
        self,
        domain: str,
        scraped_content: str,
        categorized_images: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze business identity using LLM.

        Args:
            domain: Website domain
            scraped_content: Text content from website
            categorized_images: Categorized images data

        Returns:
            Dict with business identity analysis
        """
        if not self.openai:
            return self._default_business_identity(domain)

        # Summarize available assets
        asset_summary = []
        for category, images in categorized_images.items():
            if category != 'all_images' and images:
                count = len(images) if isinstance(images, list) else 0
                if count > 0:
                    asset_summary.append(f"- {category}: {count} images")

        asset_text = "\n".join(asset_summary) if asset_summary else "Limited images available"

        prompt = f"""Analyze this business from their website content and extract their ACTUAL products/services.

DOMAIN: {domain}

WEBSITE CONTENT (excerpt):
{scraped_content[:8000]}

AVAILABLE VISUAL ASSETS:
{asset_text}

IMPORTANT: Extract the ACTUAL products/services they sell, NOT generic descriptions.
- Look for specific product names (e.g., "Web Hosting", "Domain Registration", "Email Hosting")
- Look for pricing information (e.g., "$25/year", "$3.50/month")
- Look for service tiers or packages (e.g., "Bronze Plan", "Premium Package")
- If it's a hosting company, list: Domain Registration, Web Hosting, Email Hosting, SSL Certificates, etc.
- If it's a security company, list: Armed Response, CCTV Installation, Access Control, etc.
- Be SPECIFIC - don't use generic terms like "web services" or "digital solutions"

Analyze and provide:

1. COMPANY_NAME: The official company name
2. INDUSTRY: Specific industry (e.g., web_hosting_provider, security_services, retail_fashion, food_delivery)
3. BUSINESS_MODEL: B2B, B2C, or B2B2C
4. BUSINESS_TYPE: More specific type (e.g., domain_registrar, armed_security, fashion_retail)
5. TARGET_MARKET: Who they sell to (be specific)
6. KEY_SERVICES: List of ACTUAL products/services with prices if found (max 5). Format: "Product Name - $XX/month" or just "Product Name" if no price found
7. VALUE_PROPOSITIONS: What makes them unique (max 3)
8. BRAND_PERSONALITY: Their brand voice/personality
9. VISUAL_REQUIREMENTS: What should be shown in their ads:
   - must_show: Elements that MUST appear
   - should_show: Elements that would be good to include
   - avoid: Things to avoid showing

Respond in this exact JSON format:
{{
  "company_name": "...",
  "industry": "...",
  "business_model": "...",
  "business_type": "...",
  "target_market": "...",
  "key_services": ["Product 1 - $XX/month", "Product 2", "..."],
  "value_propositions": ["...", "..."],
  "brand_personality": "...",
  "visual_requirements": {{
    "must_show": ["..."],
    "should_show": ["..."],
    "avoid": ["..."]
  }}
}}"""

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1500,
                temperature=0.2
            )

            result_text = response.choices[0].message.content

            # Parse JSON
            import json
            json_match = result_text
            if '```json' in result_text:
                json_match = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                json_match = result_text.split('```')[1].split('```')[0]

            identity = json.loads(json_match.strip())

            logger.info(f"[BrandDNA] Business identity extracted:")
            logger.info(f"  Company: {identity.get('company_name')}")
            logger.info(f"  Industry: {identity.get('industry')}")
            logger.info(f"  Type: {identity.get('business_type')}")

            return identity

        except Exception as e:
            logger.error(f"[BrandDNA] Business identity analysis error: {e}")
            return self._default_business_identity(domain)

    def _default_business_identity(self, domain: str) -> Dict[str, Any]:
        """Default business identity when analysis fails."""
        # Try to infer from domain name
        company_name = domain.split('.')[0].title()

        return {
            "company_name": company_name,
            "industry": "general_business",
            "business_model": "B2B",
            "business_type": "general_services",
            "target_market": "businesses",
            "key_services": [],
            "value_propositions": [],
            "brand_personality": "professional",
            "visual_requirements": {
                "must_show": ["company_branding"],
                "should_show": ["professional_staff"],
                "avoid": ["competitors", "negative_imagery"]
            }
        }

    def _select_best_reference_images(
        self,
        categorized_images: Dict[str, Any],
        style_data: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Select the best reference images for ad generation.

        Args:
            categorized_images: All categorized images
            style_data: Visual style analysis

        Returns:
            Dict with selected reference images by type
        """
        selected = {
            'primary_logo': None,
            'team_references': [],
            'vehicle_references': [],
            'product_references': [],
            'style_references': [],  # Hero/lifestyle for overall style
        }

        # Select primary logo
        logos = categorized_images.get('logo', [])
        if logos:
            # Prefer the first logo (usually the main one)
            selected['primary_logo'] = logos[0] if isinstance(logos[0], str) else logos[0]

        # Select team references (up to 3)
        team_images = categorized_images.get('team', [])
        for img in team_images[:3]:
            if isinstance(img, dict):
                selected['team_references'].append({
                    'url': img['url'],
                    'type': 'team',
                    'priority': 'high'
                })

        # Select vehicle references (up to 2)
        vehicle_images = categorized_images.get('vehicle', [])
        for img in vehicle_images[:2]:
            if isinstance(img, dict):
                selected['vehicle_references'].append({
                    'url': img['url'],
                    'type': 'vehicle',
                    'priority': 'high'
                })

        # Select product references (up to 2)
        product_images = categorized_images.get('product', [])
        for img in product_images[:2]:
            if isinstance(img, dict):
                selected['product_references'].append({
                    'url': img['url'],
                    'type': 'product',
                    'priority': 'medium'
                })

        # Select style references from hero/lifestyle (up to 2)
        hero_images = categorized_images.get('hero', [])
        for img in hero_images[:2]:
            if isinstance(img, dict):
                selected['style_references'].append({
                    'url': img['url'],
                    'type': 'style',
                    'priority': 'medium'
                })

        # Count total references
        total = sum([
            1 if selected['primary_logo'] else 0,
            len(selected['team_references']),
            len(selected['vehicle_references']),
            len(selected['product_references']),
            len(selected['style_references']),
        ])

        logger.info(f"[BrandDNA] Selected {total} reference images")

        return selected

    async def extract_brand_dna(
        self,
        url: str,
        scraped_content: str = ""
    ) -> Dict[str, Any]:
        """
        Extract complete brand DNA from a website.

        This is the main entry point. It:
        1. Extracts and categorizes all images
        2. Analyzes visual style
        3. Determines business identity
        4. Selects best reference images
        5. Generates style-matched prompts

        Args:
            url: Website URL
            scraped_content: Optional pre-scraped text content

        Returns:
            Complete brand DNA profile
        """
        domain = self._extract_domain(url)
        logger.info(f"[BrandDNA] Extracting brand DNA for {domain}")

        # If no scraped content provided, fetch it ourselves
        if not scraped_content or len(scraped_content) < 500:
            logger.info(f"[BrandDNA] Fetching website content for {url}...")
            try:
                import requests
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200:
                    # Extract text content from HTML
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    scraped_content = soup.get_text(separator=' ', strip=True)
                    logger.info(f"[BrandDNA] Fetched {len(scraped_content)} chars of content")
            except Exception as e:
                logger.warning(f"[BrandDNA] Failed to fetch content: {e}")

        # Step 1: Extract and categorize all images
        logger.info(f"[BrandDNA] Step 1: Extracting and categorizing images...")
        images_data = self.asset_categorizer.extract_all_images(url)
        categorized_images = self.asset_categorizer.categorize_images(images_data, domain)

        # Step 2: Analyze visual style
        logger.info(f"[BrandDNA] Step 2: Analyzing visual style...")
        visual_style = self.style_analyzer.analyze_visual_style(categorized_images, domain)

        # Step 3: Analyze business identity
        logger.info(f"[BrandDNA] Step 3: Analyzing business identity...")
        business_identity = self._analyze_business_identity(
            domain,
            scraped_content,
            categorized_images
        )

        # Step 4: Select best reference images
        logger.info(f"[BrandDNA] Step 4: Selecting reference images...")
        reference_images = self._select_best_reference_images(categorized_images, visual_style)

        # Step 5: Generate style prompt
        logger.info(f"[BrandDNA] Step 5: Generating style prompt...")
        style_prompt = self.style_analyzer.generate_style_prompt(visual_style)

        # Build complete brand DNA
        brand_dna = {
            "extracted_at": datetime.utcnow().isoformat(),
            "domain": domain,
            "url": url,

            # Business Identity
            "business_identity": business_identity,

            # Visual Style
            "visual_style": visual_style,

            # Brand Colors (convenience accessor)
            "brand_colors": visual_style.get('brand_colors', []),
            "primary_color": visual_style.get('brand_colors', ['#000000'])[0] if visual_style.get('brand_colors') else '#000000',

            # Reference Images
            "reference_images": reference_images,
            "logo_url": reference_images['primary_logo'] if isinstance(reference_images['primary_logo'], str) else (reference_images['primary_logo']['url'] if reference_images['primary_logo'] else None),

            # All categorized images
            "categorized_images": {
                "logo": categorized_images.get('logo', []),
                "team": [img['url'] if isinstance(img, dict) else img for img in categorized_images.get('team', [])],
                "vehicle": [img['url'] if isinstance(img, dict) else img for img in categorized_images.get('vehicle', [])],
                "product": [img['url'] if isinstance(img, dict) else img for img in categorized_images.get('product', [])],
                "hero": [img['url'] if isinstance(img, dict) else img for img in categorized_images.get('hero', [])],
                "office": [img['url'] if isinstance(img, dict) else img for img in categorized_images.get('office', [])],
                "equipment": [img['url'] if isinstance(img, dict) else img for img in categorized_images.get('equipment', [])],
            },

            # Image counts
            "image_counts": {
                "total": len(categorized_images.get('all_images', [])),
                "logo": len(categorized_images.get('logo', [])),
                "team": len(categorized_images.get('team', [])),
                "vehicle": len(categorized_images.get('vehicle', [])),
                "product": len(categorized_images.get('product', [])),
                "hero": len(categorized_images.get('hero', [])),
            },

            # Style prompt for image generation
            "style_prompt": style_prompt,

            # Uniform and vehicle details (convenience accessors)
            "uniform_details": visual_style.get('uniform_details', {}),
            "vehicle_details": visual_style.get('vehicle_details', {}),
        }

        logger.info(f"[BrandDNA] Extraction complete for {domain}")
        logger.info(f"  Company: {business_identity.get('company_name')}")
        logger.info(f"  Industry: {business_identity.get('industry')}")
        logger.info(f"  Primary Color: {brand_dna['primary_color']}")
        logger.info(f"  Total Images: {brand_dna['image_counts']['total']}")
        logger.info(f"  Team Images: {brand_dna['image_counts']['team']}")
        logger.info(f"  Vehicle Images: {brand_dna['image_counts']['vehicle']}")

        return brand_dna

    def get_ad_generation_context(self, brand_dna: Dict[str, Any], ad_set_type: str = "general") -> Dict[str, Any]:
        """
        Get context for generating a specific ad based on brand DNA.

        Args:
            brand_dna: Complete brand DNA from extract_brand_dna()
            ad_set_type: Type of ad set (e.g., "team", "vehicle", "product", "general")

        Returns:
            Dict with everything needed to generate a brand-consistent ad
        """
        context = {
            "company_name": brand_dna.get('business_identity', {}).get('company_name', 'Company'),
            "industry": brand_dna.get('business_identity', {}).get('industry', 'business'),
            "brand_personality": brand_dna.get('business_identity', {}).get('brand_personality', 'professional'),
            "logo_url": brand_dna.get('logo_url'),
            "primary_color": brand_dna.get('primary_color', '#000000'),
            "brand_colors": brand_dna.get('brand_colors', []),
            "style_prompt": brand_dna.get('style_prompt', ''),
            "visual_requirements": brand_dna.get('business_identity', {}).get('visual_requirements', {}),
            "reference_images": [],
        }

        # Select appropriate reference images based on ad type
        ref_images = brand_dna.get('reference_images', {})

        if ad_set_type in ['team', 'staff', 'personnel', 'security']:
            # Prioritize team/uniform images
            context['reference_images'] = ref_images.get('team_references', [])[:2]
            context['uniform_details'] = brand_dna.get('uniform_details', {})

        elif ad_set_type in ['vehicle', 'fleet', 'response', 'patrol']:
            # Prioritize vehicle images
            context['reference_images'] = ref_images.get('vehicle_references', [])[:2]
            context['vehicle_details'] = brand_dna.get('vehicle_details', {})

        elif ad_set_type in ['product', 'service', 'offering']:
            # Prioritize product images
            context['reference_images'] = ref_images.get('product_references', [])[:2]

        else:
            # General - mix of references
            context['reference_images'] = (
                ref_images.get('team_references', [])[:1] +
                ref_images.get('style_references', [])[:1]
            )

        return context


# Convenience function for quick extraction
async def extract_brand_dna(url: str, scraped_content: str = "") -> Dict[str, Any]:
    """
    Quick function to extract brand DNA from a URL.

    Args:
        url: Website URL
        scraped_content: Optional pre-scraped content

    Returns:
        Complete brand DNA profile
    """
    extractor = BrandDNAExtractor()
    return await extractor.extract_brand_dna(url, scraped_content)

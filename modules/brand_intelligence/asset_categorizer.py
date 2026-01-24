# asset_categorizer.py - Categorize all images from a website into types
"""
Extracts ALL images from a website and categorizes them using Vision AI.

Categories:
- logo: Company logos (all variations)
- hero: Main banner/hero images
- team: Staff photos, group shots, uniformed personnel
- vehicle: Company vehicles, fleet
- product: Products or services
- office: Office/facility/location photos
- equipment: Tools, equipment, technology
- lifestyle: Context/lifestyle images
- graphic: Icons, illustrations, graphics
- other: Uncategorized
"""

import os
import re
import logging
import time
import random
import requests
import httpx
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Try to import cloudscraper for anti-bot bypass
try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

# Vision AI for image analysis
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Full browser-like headers to avoid 403 errors
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


class AssetCategorizer:
    """
    Extracts and categorizes all images from a website.
    Uses Vision AI to understand what each image contains.
    """

    def __init__(self):
        self.openai = None
        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Initialize cloudscraper for anti-bot bypass
        self.scraper = None
        if CLOUDSCRAPER_AVAILABLE:
            try:
                self.scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "desktop": True}
                )
                logger.info("[AssetCategorizer] Cloudscraper initialized for anti-bot bypass")
            except Exception as e:
                logger.debug(f"[AssetCategorizer] Failed to create cloudscraper: {e}")

        # Track failed domains
        self._failed_domains = set()

        # Pages to crawl for images
        self.pages_to_crawl = [
            "",  # Homepage
            "/about", "/about-us", "/about-us/",
            "/team", "/our-team", "/staff",
            "/services", "/our-services",
            "/products", "/our-products",
            "/gallery", "/photos", "/media",
            "/fleet", "/vehicles",
            "/contact", "/contact-us",
        ]

        # Image patterns to skip (tracking pixels, icons, etc.)
        self.skip_patterns = [
            'facebook.com/tr', 'google-analytics', 'doubleclick',
            'pixel', 'tracking', 'beacon', '1x1', 'spacer',
            'analytics', 'stat', 'counter', 'noscript',
            'wp-includes', 'wp-admin', 'gravatar',
            'data:image', 'svg+xml', 'base64,',
            '.svg', '.ico', 'favicon',
        ]

        # Minimum image size to consider (width or height)
        self.min_image_size = 100

    def _should_skip_image(self, url: str) -> bool:
        """Check if image URL should be skipped."""
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in self.skip_patterns)

    def _fetch_page(self, url: str, timeout: int = 15, max_retries: int = 3) -> Optional[str]:
        """
        Fetch HTML content from URL with anti-bot bypass.
        Uses multiple strategies: cloudscraper, requests, httpx.
        """
        domain = urlparse(url).netloc
        if domain in self._failed_domains:
            return None

        for attempt in range(max_retries):
            if attempt > 0:
                delay = (2 ** attempt) + random.uniform(0.5, 1.5)
                time.sleep(delay)

            # Strategy 1: Cloudscraper (best for Cloudflare/anti-bot)
            if self.scraper:
                try:
                    response = self.scraper.get(url, timeout=timeout)
                    if response.status_code == 200:
                        logger.debug(f"[AssetCategorizer] Fetched {url} with cloudscraper")
                        return response.text
                except Exception as e:
                    logger.debug(f"[AssetCategorizer] Cloudscraper failed: {e}")

            # Strategy 2: Requests with browser headers
            try:
                response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
                if response.status_code == 200:
                    logger.debug(f"[AssetCategorizer] Fetched {url} with requests")
                    return response.text
            except Exception as e:
                logger.debug(f"[AssetCategorizer] Requests failed: {e}")

            # Strategy 3: httpx with HTTP/2
            try:
                with httpx.Client(headers=BROWSER_HEADERS, timeout=timeout, follow_redirects=True, http2=True) as client:
                    response = client.get(url)
                    if response.status_code == 200:
                        logger.debug(f"[AssetCategorizer] Fetched {url} with httpx")
                        return response.text
            except Exception as e:
                logger.debug(f"[AssetCategorizer] httpx failed: {e}")

        logger.warning(f"[AssetCategorizer] All strategies failed for {url}")
        self._failed_domains.add(domain)
        return None

    def _extract_images_from_html(self, html: str, base_url: str) -> List[Dict[str, Any]]:
        """Extract all image URLs from HTML."""
        images = []
        soup = BeautifulSoup(html, 'html.parser')

        # Find all img tags
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if not src:
                continue

            # Make absolute URL
            img_url = urljoin(base_url, src)

            if self._should_skip_image(img_url):
                continue

            # Get additional attributes
            alt = img.get('alt', '')
            classes = ' '.join(img.get('class', []))
            width = img.get('width', '')
            height = img.get('height', '')

            images.append({
                'url': img_url,
                'alt': alt,
                'classes': classes,
                'width': width,
                'height': height,
                'source': 'img_tag'
            })

        # Find background images in style attributes
        for elem in soup.find_all(style=True):
            style = elem.get('style', '')
            bg_match = re.search(r'background(?:-image)?:\s*url\(["\']?([^"\')\s]+)["\']?\)', style)
            if bg_match:
                bg_url = urljoin(base_url, bg_match.group(1))
                if not self._should_skip_image(bg_url):
                    images.append({
                        'url': bg_url,
                        'alt': '',
                        'classes': ' '.join(elem.get('class', [])),
                        'width': '',
                        'height': '',
                        'source': 'background_style'
                    })

        # Find OG image
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            og_url = urljoin(base_url, og_image['content'])
            if not self._should_skip_image(og_url):
                images.append({
                    'url': og_url,
                    'alt': 'og:image',
                    'classes': 'og-image',
                    'width': '',
                    'height': '',
                    'source': 'og_image'
                })

        return images

    def _extract_logos(self, html: str, base_url: str) -> List[str]:
        """Extract logo URLs specifically."""
        logos = []
        soup = BeautifulSoup(html, 'html.parser')

        # Logo selectors (priority order)
        logo_selectors = [
            '.custom-logo',
            '.site-logo img',
            '.logo img',
            '#logo img',
            'a.logo img',
            '.navbar-brand img',
            '.header-logo img',
            'img[class*="logo"]',
            'img[alt*="logo" i]',
            'img[src*="logo"]',
        ]

        for selector in logo_selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    if elem.name == 'img':
                        src = elem.get('src') or elem.get('data-src')
                    else:
                        src = elem.get('src')

                    if src:
                        logo_url = urljoin(base_url, src)
                        if logo_url not in logos and not self._should_skip_image(logo_url):
                            logos.append(logo_url)
            except Exception:
                continue

        return logos

    def extract_all_images(self, base_url: str) -> Dict[str, Any]:
        """
        Extract all images from a website by crawling multiple pages.

        Returns:
            Dict with 'images' list and 'logos' list
        """
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        base_url = base_url.rstrip('/')

        all_images = {}  # Use dict to dedupe by URL
        all_logos = []
        pages_crawled = []

        logger.info(f"[AssetCategorizer] Extracting images from {base_url}")

        for page_path in self.pages_to_crawl:
            page_url = base_url + page_path
            html = self._fetch_page(page_url)

            if not html:
                continue

            pages_crawled.append(page_url)

            # Extract images
            images = self._extract_images_from_html(html, base_url)
            for img in images:
                if img['url'] not in all_images:
                    img['found_on'] = page_url
                    all_images[img['url']] = img

            # Extract logos (only from homepage)
            if page_path == "":
                logos = self._extract_logos(html, base_url)
                all_logos.extend([l for l in logos if l not in all_logos])

            # Small delay between pages to avoid rate limiting
            time.sleep(random.uniform(0.3, 0.8))

        logger.info(f"[AssetCategorizer] Found {len(all_images)} images from {len(pages_crawled)} pages")

        return {
            'images': list(all_images.values()),
            'logos': all_logos,
            'pages_crawled': pages_crawled,
            'total_images': len(all_images)
        }

    def categorize_images(self, images_data: Dict[str, Any], domain: str) -> Dict[str, Any]:
        """
        Categorize images using Vision AI with ACTUAL image analysis.

        Args:
            images_data: Output from extract_all_images()
            domain: Website domain for context

        Returns:
            Dict with categorized images
        """
        if not self.openai:
            logger.warning("[AssetCategorizer] OpenAI not available, returning uncategorized")
            return self._basic_categorization(images_data)

        images = images_data.get('images', [])
        logos = images_data.get('logos', [])

        # Limit to first 20 images for API efficiency (Vision AI with images is more expensive)
        images_to_analyze = images[:20]

        categories = {
            'logo': logos,
            'hero': [],
            'team': [],
            'vehicle': [],
            'product': [],
            'office': [],
            'equipment': [],
            'lifestyle': [],
            'graphic': [],
            'other': [],
        }

        if not images_to_analyze:
            categories['all_images'] = images
            return categories

        # Analyze images in batches of 5 (Vision AI limit)
        batch_size = 5
        all_results = {}

        for batch_start in range(0, len(images_to_analyze), batch_size):
            batch_end = min(batch_start + batch_size, len(images_to_analyze))
            batch = images_to_analyze[batch_start:batch_end]

            logger.info(f"[AssetCategorizer] Analyzing batch {batch_start//batch_size + 1}: images {batch_start+1}-{batch_end}")

            batch_results = self._analyze_image_batch(batch, batch_start, domain)
            all_results.update(batch_results)

            # Small delay between batches
            if batch_end < len(images_to_analyze):
                time.sleep(0.5)

        # Apply categorization results
        for idx, img_data in enumerate(images_to_analyze):
            category = all_results.get(idx, 'other')
            img_data['category'] = category
            if category in categories:
                categories[category].append(img_data)
            else:
                categories['other'].append(img_data)

        # Add remaining uncategorized images to 'other'
        categorized_urls = set()
        for cat_images in categories.values():
            for img in cat_images:
                if isinstance(img, dict):
                    categorized_urls.add(img.get('url'))
                else:
                    categorized_urls.add(img)

        for img in images:
            if img['url'] not in categorized_urls:
                img['category'] = 'other'
                categories['other'].append(img)

        categories['all_images'] = images
        return categories

    def _analyze_image_batch(self, batch: List[Dict], start_idx: int, domain: str) -> Dict[int, str]:
        """
        Analyze a batch of images using Vision AI with actual image content.

        Args:
            batch: List of image data dicts
            start_idx: Starting index for this batch
            domain: Website domain for context

        Returns:
            Dict mapping image index to category
        """
        results = {}

        # Build content array with actual images
        content = [
            {
                "type": "text",
                "text": f"""Analyze these {len(batch)} images from {domain} and categorize each one based on WHAT YOU SEE in the image.

CATEGORIES (choose ONE per image):
- team: People wearing UNIFORMS (security uniforms, company shirts, branded workwear), staff photos, employees at work
- vehicle: Company VEHICLES (trucks, vans, cars with company branding/logos)
- equipment: Tools, machinery, technology, security cameras, equipment being installed
- product: Products being sold or demonstrated
- office: Buildings, facilities, storefronts, office interiors
- hero: Large promotional banners (usually with text overlays)
- graphic: Icons, illustrations, logos, diagrams
- lifestyle: Generic lifestyle/stock photos
- other: Doesn't fit any category

IMPORTANT - Look at the VISUAL CONTENT:
- If you see a person wearing a UNIFORM (branded shirt, security gear, work clothes with logo) = team
- If you see a VEHICLE with company branding = vehicle
- If you see someone INSTALLING or working with equipment = equipment (even if person visible)
- Executive portraits in suits (no uniform) = other

Respond with ONLY the image number and category:
1: [category]
2: [category]
etc."""
            }
        ]

        # Add each image to the content
        for i, img in enumerate(batch):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": img['url'],
                    "detail": "low"  # Use low detail to save tokens
                }
            })

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": content}],
                max_tokens=200,
                temperature=0.1
            )

            result_text = response.choices[0].message.content
            logger.debug(f"[AssetCategorizer] Batch result: {result_text}")

            # Parse results
            for line in result_text.strip().split('\n'):
                match = re.match(r'(\d+):\s*(\w+)', line.strip())
                if match:
                    local_idx = int(match.group(1)) - 1  # Convert to 0-indexed
                    category = match.group(2).lower()
                    global_idx = start_idx + local_idx

                    if 0 <= local_idx < len(batch):
                        results[global_idx] = category
                        logger.debug(f"[AssetCategorizer] Image {global_idx + 1}: {category}")

        except Exception as e:
            logger.error(f"[AssetCategorizer] Batch analysis error: {e}")
            # Mark all as 'other' on error
            for i in range(len(batch)):
                results[start_idx + i] = 'other'

        return results

    def _basic_categorization(self, images_data: Dict[str, Any]) -> Dict[str, Any]:
        """Basic categorization using URL/alt text patterns (fallback)."""
        images = images_data.get('images', [])
        logos = images_data.get('logos', [])

        categories = {
            'logo': logos,
            'hero': [],
            'team': [],
            'vehicle': [],
            'product': [],
            'office': [],
            'equipment': [],
            'lifestyle': [],
            'graphic': [],
            'other': [],
        }

        patterns = {
            'team': ['team', 'staff', 'employee', 'uniform', 'people', 'group'],
            'vehicle': ['vehicle', 'car', 'truck', 'van', 'fleet', 'transport'],
            'hero': ['hero', 'banner', 'slider', 'featured', 'main'],
            'office': ['office', 'building', 'facility', 'location', 'store'],
            'product': ['product', 'service', 'item', 'shop'],
            'equipment': ['equipment', 'tool', 'device', 'tech'],
        }

        for img in images:
            url_lower = img['url'].lower()
            alt_lower = img.get('alt', '').lower()
            search_text = f"{url_lower} {alt_lower}"

            categorized = False
            for category, keywords in patterns.items():
                if any(kw in search_text for kw in keywords):
                    img['category'] = category
                    categories[category].append(img)
                    categorized = True
                    break

            if not categorized:
                img['category'] = 'other'
                categories['other'].append(img)

        categories['all_images'] = images
        return categories

    async def extract_and_categorize(self, url: str) -> Dict[str, Any]:
        """
        Main entry point: Extract all images and categorize them.

        Args:
            url: Website URL

        Returns:
            Dict with categorized images
        """
        domain = urlparse(url).netloc.replace('www.', '')

        # Extract all images
        images_data = self.extract_all_images(url)

        # Categorize with Vision AI
        categorized = self.categorize_images(images_data, domain)

        logger.info(f"[AssetCategorizer] Categorization complete for {domain}:")
        for cat, items in categorized.items():
            if cat != 'all_images' and items:
                logger.info(f"  - {cat}: {len(items)} images")

        return categorized

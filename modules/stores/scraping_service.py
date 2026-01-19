# modules/stores/scraping_service.py
"""
Website scraping service using Tavily for content extraction,
BeautifulSoup for image extraction, and OpenAI Vision for image analysis.
"""
import os
import json
import re
import base64
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse
from tavily import TavilyClient
from openai import OpenAI
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat

load_dotenv()

# Initialize clients
tavily_api_key = os.getenv("TAVILY_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")


def extract_store_info_from_website(url: str) -> Dict[str, Any]:
    """
    Scrape a website using Tavily and extract store information using an AI agent.
    Also extracts and analyzes images (logos, product images) using OpenAI Vision.
    """

    # Validate API keys
    if not tavily_api_key or tavily_api_key == "your-tavily-api-key-here":
        raise ValueError("TAVILY_API_KEY not configured. Please add your Tavily API key to .env")

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    try:
        # Initialize Tavily client
        tavily = TavilyClient(api_key=tavily_api_key)

        # Extract base URL and domain
        base_url = url.rstrip('/')
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        domain = base_url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

        # Build list of URLs to extract (main page + common pages)
        urls_to_extract = [base_url]
        common_pages = ['/contact', '/contact-us', '/about', '/about-us']
        for page in common_pages:
            urls_to_extract.append(base_url + page)

        all_content = []

        # Store extracted images from Tavily
        tavily_images = []

        # Method 1: Direct page extraction with Tavily (with images)
        print(f"[Tavily] Extracting pages with images: {urls_to_extract}")
        try:
            extract_result = tavily.extract(urls=urls_to_extract, include_images=True)
            if extract_result and extract_result.get("results"):
                for result in extract_result["results"]:
                    content = result.get("raw_content", "")
                    result_url = result.get("url", "")
                    images = result.get("images", [])

                    if content:
                        page_type = "MAIN PAGE" if result_url == base_url else "ADDITIONAL PAGE"
                        all_content.append(f"=== {page_type}: {result_url} ===\n{content}")
                        print(f"[Tavily] Extracted {result_url}: {len(content)} characters, {len(images)} images")

                    # Collect images from Tavily
                    if images:
                        tavily_images.extend(images)
                        print(f"[Tavily] Found images: {images[:3]}...")  # Log first 3
        except Exception as e:
            print(f"[Tavily] Extraction failed: {e}")

        # Method 2: If direct extraction failed, try search (but filter by domain)
        if not all_content:
            print(f"[Tavily] Direct extraction failed, trying search for {domain}")
            try:
                search_result = tavily.search(
                    query=f"{domain} contact about services products",
                    search_depth="advanced",
                    include_raw_content=True,
                    max_results=5,
                    include_domains=[domain]
                )

                for result in search_result.get("results", []):
                    result_url = result.get("url", "")
                    if domain in result_url:
                        content = result.get("raw_content") or result.get("content", "")
                        if content:
                            all_content.append(f"=== PAGE: {result_url} ===\n{content}")
                            print(f"[Tavily] Search found {result_url}: {len(content)} characters")
            except Exception as e:
                print(f"[Tavily] Search failed: {e}")

        # Extract images - use Tavily images if available, otherwise scrape
        if tavily_images:
            print(f"[Images] Using {len(tavily_images)} images from Tavily Extract API")
            images_data = _process_tavily_images(tavily_images, base_url)
        else:
            print(f"[Images] No Tavily images, extracting from {base_url}")
            images_data = _extract_images_from_website(base_url)

        # Analyze images with OpenAI Vision
        image_analysis = None
        if images_data.get("logo_url") or images_data.get("og_image") or images_data.get("images"):
            print(f"[Vision] Analyzing images with OpenAI Vision")
            image_analysis = _analyze_images_with_vision(images_data, domain)

        # Combine all content
        combined_content = "\n\n".join(all_content)
        print(f"[Tavily] Total combined content: {len(combined_content)} characters")

        if not combined_content:
            print("[Tavily] No content extracted, using fallback")
            fallback = _generate_fallback_data(url)
            # Add image data if available
            if images_data.get("logo_url"):
                fallback["logo_url"] = images_data["logo_url"]
            return fallback

        # Use OpenAI to extract structured store information
        store_data = _extract_with_ai_agent(combined_content, url, image_analysis)

        # Add logo URL if found
        if images_data.get("logo_url"):
            store_data["logo_url"] = images_data["logo_url"]

        # Add extracted images
        if images_data.get("images"):
            store_data["extracted_images"] = images_data["images"][:10]  # Limit to 10 images

        # Also fetch raw HTML for better contact extraction (Tavily may miss footer/contact sections)
        try:
            print(f"[Contact] Fetching raw HTML for contact extraction...")
            print(f"[Contact] Current email: {store_data.get('store_email')}, phone: {store_data.get('store_phone')}")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

            # Fetch main page and contact page
            urls_to_fetch = [base_url, base_url + '/contact', base_url + '/contact-us']
            all_html = ""

            for fetch_url in urls_to_fetch:
                try:
                    raw_response = requests.get(fetch_url, headers=headers, timeout=10, allow_redirects=True)
                    if raw_response.status_code == 200:
                        all_html += raw_response.text + "\n"
                        print(f"[Contact] Fetched {fetch_url}: {len(raw_response.text)} chars")
                    else:
                        print(f"[Contact] Failed to fetch {fetch_url}: status {raw_response.status_code}")
                except Exception as fetch_error:
                    print(f"[Contact] Error fetching {fetch_url}: {fetch_error}")

            if all_html:
                # Extract contact info directly from raw HTML
                direct_contact = _extract_contact_info_directly(all_html, domain)
                print(f"[Contact] Direct extraction result: email={direct_contact.get('email')}, phone={direct_contact.get('phone')}")

                if direct_contact.get("email"):
                    store_data["store_email"] = direct_contact["email"]
                    print(f"[Contact] SET email from raw HTML: {direct_contact['email']}")
                if direct_contact.get("phone"):
                    store_data["store_phone"] = direct_contact["phone"]
                    print(f"[Contact] SET phone from raw HTML: {direct_contact['phone']}")
        except Exception as e:
            print(f"[Contact] Error fetching raw HTML: {e}")

        # Extract FAQs from the scraped content
        print(f"[FAQ] Extracting FAQs from scraped content...")
        faqs = _extract_faqs_with_ai(combined_content, url)
        store_data["faqs"] = faqs

        return store_data

    except Exception as e:
        print(f"[Scraping] Error: {str(e)}")
        return _generate_fallback_data(url)


def _process_tavily_images(tavily_images: List[str], base_url: str) -> Dict[str, Any]:
    """
    Process images returned by Tavily Extract API.
    Identify logos and organize image data.
    """
    images_data = {
        "logo_url": None,
        "favicon_url": None,
        "images": [],
        "og_image": None
    }

    for img_url in tavily_images:
        if not img_url:
            continue

        # Make URL absolute if needed
        if not img_url.startswith('http'):
            img_url = urljoin(base_url, img_url)

        # Skip data URIs, tiny images, tracking pixels
        if (img_url.startswith('data:') or
            'pixel' in img_url.lower() or
            'tracking' in img_url.lower() or
            'spacer' in img_url.lower() or
            '1x1' in img_url.lower()):
            continue

        # Check if this is likely a logo
        is_logo = 'logo' in img_url.lower()

        # Set logo_url if we find one
        if is_logo and not images_data["logo_url"]:
            images_data["logo_url"] = img_url
            print(f"[Images] Identified logo from Tavily: {img_url}")

        # Check for OG image patterns
        if ('og-image' in img_url.lower() or 'opengraph' in img_url.lower() or
            'social' in img_url.lower()) and not images_data["og_image"]:
            images_data["og_image"] = img_url

        # Add to general images list
        images_data["images"].append({
            "url": img_url,
            "alt": "",
            "is_logo": is_logo
        })

    # If no logo found, try first image that might be header/hero
    if not images_data["logo_url"] and images_data["images"]:
        for img in images_data["images"]:
            url_lower = img["url"].lower()
            if any(kw in url_lower for kw in ['header', 'hero', 'brand', 'banner']):
                images_data["og_image"] = img["url"]
                break

    print(f"[Images] Processed {len(images_data['images'])} Tavily images, logo: {images_data['logo_url']}")
    return images_data


def _extract_images_from_spa_bundle(url: str, soup: BeautifulSoup) -> List[str]:
    """
    Extract images from SPA JavaScript bundles (React, Vue, Angular, etc.).
    Detects if site is SPA and parses JS bundles for image URLs.
    """
    images = []
    base_url = url.rstrip('/')

    try:
        # Find all script tags with src
        scripts = soup.find_all('script', src=True)

        for script in scripts:
            src = script.get('src', '')
            if not src:
                continue

            # Look for main bundle files (common patterns)
            if any(pattern in src.lower() for pattern in [
                'main', 'index', 'app', 'bundle', 'chunk', 'vendor'
            ]) and src.endswith('.js'):

                # Make URL absolute
                if not src.startswith('http'):
                    script_url = urljoin(base_url, src)
                else:
                    script_url = src

                print(f"[SPA] Fetching JS bundle: {script_url}")

                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    js_response = requests.get(script_url, headers=headers, timeout=15)

                    if js_response.status_code == 200:
                        js_content = js_response.text

                        # Extract image URLs from JS bundle
                        # Pattern 1: Full URLs
                        url_pattern = r'https?://[^\s"\'\\<>]+\.(?:png|jpg|jpeg|webp|svg|gif)'
                        found_urls = re.findall(url_pattern, js_content, re.IGNORECASE)

                        # Pattern 2: Relative paths in quotes
                        relative_pattern = r'["\']([^"\']+\.(?:png|jpg|jpeg|webp|svg|gif))["\']'
                        relative_urls = re.findall(relative_pattern, js_content, re.IGNORECASE)

                        for img_url in found_urls:
                            # Clean up URL (remove trailing quotes, etc.)
                            img_url = img_url.rstrip('"\',);')
                            if img_url and len(img_url) < 500:  # Sanity check
                                images.append(img_url)

                        for rel_url in relative_urls:
                            if rel_url.startswith('/') or rel_url.startswith('./'):
                                full_url = urljoin(base_url, rel_url)
                                images.append(full_url)
                            elif rel_url.startswith('http'):
                                images.append(rel_url)

                        print(f"[SPA] Found {len(images)} images in JS bundle")

                except Exception as e:
                    print(f"[SPA] Error fetching JS bundle: {e}")

        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)

        return unique_images[:50]  # Limit to 50 images

    except Exception as e:
        print(f"[SPA] Error extracting from bundle: {e}")
        return []


def _is_spa_website(soup: BeautifulSoup) -> bool:
    """
    Detect if a website is a Single Page Application (React, Vue, Angular, etc.).
    """
    # Check for common SPA root elements
    root_div = soup.find('div', id='root')  # React
    app_div = soup.find('div', id='app')    # Vue
    ng_app = soup.find(attrs={'ng-app': True})  # Angular

    # Check if body has minimal content (typical of SPAs)
    body = soup.find('body')
    if body:
        # Count actual content elements (not scripts)
        content_elements = body.find_all(['p', 'h1', 'h2', 'h3', 'img', 'article', 'section'])
        img_tags = body.find_all('img')

        # SPA indicators:
        # 1. Has root/app div
        # 2. Very few content elements
        # 3. No img tags in HTML
        if (root_div or app_div or ng_app) and len(content_elements) < 3 and len(img_tags) == 0:
            return True

    return False


def _extract_images_from_website(url: str) -> Dict[str, Any]:
    """
    Extract images from a website, focusing on logos and brand images.
    Handles both traditional websites and SPAs.
    """
    images_data = {
        "logo_url": None,
        "favicon_url": None,
        "images": [],
        "og_image": None
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'lxml')
        base_url = url.rstrip('/')

        # Check if this is a SPA
        is_spa = _is_spa_website(soup)
        if is_spa:
            print(f"[Images] Detected SPA website, parsing JS bundles...")
            spa_images = _extract_images_from_spa_bundle(url, soup)

            if spa_images:
                # Process SPA images
                for img_url in spa_images:
                    # Skip tracking pixels and tiny images
                    if any(skip in img_url.lower() for skip in ['pixel', 'tracking', '1x1', 'spacer', '.gif']):
                        continue

                    is_logo = 'logo' in img_url.lower()

                    # Set logo if found
                    if is_logo and not images_data["logo_url"]:
                        images_data["logo_url"] = img_url
                        print(f"[SPA] Found logo: {img_url}")

                    # First image from same domain could be hero/brand image
                    domain = urlparse(url).netloc.replace('www.', '')
                    if not images_data["og_image"]:
                        # Prioritize images from asset CDNs or same domain
                        if 'assets' in img_url.lower() or domain in img_url:
                            images_data["og_image"] = img_url

                    images_data["images"].append({
                        "url": img_url,
                        "alt": "",
                        "is_logo": is_logo
                    })

                # If no logo found, use first asset image as potential brand image
                if not images_data["logo_url"] and not images_data["og_image"] and images_data["images"]:
                    images_data["og_image"] = images_data["images"][0]["url"]

                print(f"[SPA] Extracted {len(images_data['images'])} images, logo: {images_data['logo_url']}")
                return images_data

        # 1. Find Open Graph image (usually a good brand image)
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            og_url = og_image['content']
            if not og_url.startswith('http'):
                og_url = urljoin(base_url, og_url)
            images_data["og_image"] = og_url
            print(f"[Images] Found OG image: {og_url}")

        # 2. Find favicon
        favicon = soup.find('link', rel=lambda x: x and 'icon' in x.lower() if x else False)
        if favicon and favicon.get('href'):
            fav_url = favicon['href']
            if not fav_url.startswith('http'):
                fav_url = urljoin(base_url, fav_url)
            images_data["favicon_url"] = fav_url

        # 3. Find logo - look for common patterns
        logo_selectors = [
            # By class/id containing 'logo'
            lambda: soup.find('img', class_=lambda x: x and 'logo' in x.lower() if x else False),
            lambda: soup.find('img', id=lambda x: x and 'logo' in x.lower() if x else False),
            # By src containing 'logo'
            lambda: soup.find('img', src=lambda x: x and 'logo' in x.lower() if x else False),
            # By alt containing 'logo'
            lambda: soup.find('img', alt=lambda x: x and 'logo' in x.lower() if x else False),
            # In header
            lambda: soup.find('header', class_=lambda x: True).find('img') if soup.find('header') else None,
            # First image in navbar
            lambda: soup.find('nav').find('img') if soup.find('nav') else None,
            # SVG logo
            lambda: soup.find('svg', class_=lambda x: x and 'logo' in x.lower() if x else False),
        ]

        for selector in logo_selectors:
            try:
                logo = selector()
                if logo:
                    if logo.name == 'svg':
                        # For SVG, we might need to handle differently
                        continue
                    logo_url = logo.get('src') or logo.get('data-src')
                    if logo_url:
                        if not logo_url.startswith('http'):
                            logo_url = urljoin(base_url, logo_url)
                        # Skip tiny images or data URIs
                        if not logo_url.startswith('data:') and 'pixel' not in logo_url.lower():
                            images_data["logo_url"] = logo_url
                            print(f"[Images] Found logo: {logo_url}")
                            break
            except Exception:
                continue

        # 4. Collect other significant images (for product/brand understanding)
        all_images = soup.find_all('img')
        for img in all_images[:20]:  # Limit to first 20 images
            src = img.get('src') or img.get('data-src')
            if src:
                if not src.startswith('http'):
                    src = urljoin(base_url, src)
                # Skip data URIs, tiny images, tracking pixels
                if (not src.startswith('data:') and
                    'pixel' not in src.lower() and
                    'tracking' not in src.lower() and
                    'spacer' not in src.lower() and
                    '.gif' not in src.lower()):
                    alt = img.get('alt', '')
                    images_data["images"].append({
                        "url": src,
                        "alt": alt,
                        "is_logo": 'logo' in (alt + src).lower()
                    })

        print(f"[Images] Extracted {len(images_data['images'])} images, logo: {images_data['logo_url']}")

    except Exception as e:
        print(f"[Images] Error extracting images: {e}")

    return images_data


def _analyze_images_with_vision(images_data: Dict[str, Any], domain: str) -> Dict[str, Any]:
    """
    Analyze images using OpenAI Vision to extract brand information.
    """
    client = OpenAI(api_key=openai_api_key)

    analysis_result = {
        "brand_colors": [],
        "logo_description": None,
        "brand_style": None,
        "detected_text": None
    }

    # Prioritize which image to analyze
    image_url = images_data.get("logo_url") or images_data.get("og_image")

    if not image_url:
        # Try the first non-logo image
        for img in images_data.get("images", []):
            if img.get("url"):
                image_url = img["url"]
                break

    if not image_url:
        print("[Vision] No suitable image found for analysis")
        return analysis_result

    try:
        print(f"[Vision] Analyzing image: {image_url}")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"""Analyze this image from the website {domain}. Extract the following information:

1. **Brand Colors**: List the PRIMARY colors you see (as hex codes). Focus on:
   - Main brand/logo colors
   - Dominant accent colors
   - Return 1-3 hex codes like #FF5733

2. **Logo Description**: If this is a logo, describe it briefly:
   - What does it look like? (icon, text, combination)
   - Any symbols or icons used?
   - The overall style (modern, classic, playful, professional)

3. **Brand Style**: What feeling/style does the branding convey?
   - Examples: "Modern & Minimalist", "Warm & Friendly", "Professional & Corporate", "Bold & Energetic"

4. **Text Detected**: Any text/company name visible in the image?

Return ONLY valid JSON in this format:
{{"brand_colors": ["#hex1", "#hex2"], "logo_description": "...", "brand_style": "...", "detected_text": "..."}}"""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                                "detail": "low"  # Use low detail to save tokens
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up markdown if present
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[Vision] Analysis result: {result_text[:200]}")

        analysis_result = json.loads(result_text)

    except Exception as e:
        print(f"[Vision] Error analyzing image: {e}")

    return analysis_result


def _extract_with_ai_agent(content: str, url: str, image_analysis: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Use OpenAI to extract structured store information from website content.
    Incorporates image analysis results if available.
    """
    client = OpenAI(api_key=openai_api_key)

    # Truncate content if too long
    if len(content) > 20000:
        content = content[:20000] + "..."

    domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

    # Build image analysis context
    image_context = ""
    if image_analysis:
        image_context = f"""
IMAGE ANALYSIS FROM LOGO/BRAND IMAGES:
- Brand Colors Detected: {image_analysis.get('brand_colors', 'Not detected')}
- Logo Description: {image_analysis.get('logo_description', 'Not available')}
- Brand Style: {image_analysis.get('brand_style', 'Not detected')}
- Text in Image: {image_analysis.get('detected_text', 'None')}

Use this visual analysis to inform your color_theme choice and brand understanding.
"""

    prompt = f"""You are an expert business analyst extracting store/business information from website content.

TASK: Analyze this website content and extract ALL available business information.

Website URL: {url}
Domain: {domain}
{image_context}

EXTRACT THESE FIELDS (return null only if truly not found):

1. store_name: The business name (from logo, header, title, footer, or About section)

2. store_email: Customer contact email. Look for:
   - mailto: links
   - "Contact us", "Email us", "Get in touch" sections
   - Footer contact info
   - Patterns like info@, hello@, contact@, support@, help@

3. store_phone: Customer service phone. Look for:
   - "Call us", "Phone", "Tel" labels
   - tel: links
   - Numbers in contact section or footer
   - Only use null if NO phone number appears anywhere

4. store_voice: Write 2-3 sentences describing:
   - What the business does
   - Their mission or value proposition
   - What makes them unique

5. store_tone: Analyze the website's communication style and pick ONE:
   - "friendly" = Friendly & Casual tone
   - "professional" = Professional & Formal tone
   - "luxury" = Luxury & Premium feel
   - "modern" = Modern & Trendy vibe
   - "traditional" = Traditional & Classic approach
   - "playful" = Playful & Fun personality
   - "minimalist" = Minimalist & Clean aesthetic
   - "eco_friendly" = Eco-Friendly & Sustainable focus

6. services_products: List the main products/services offered (comma-separated)
   - Look at navigation menu, product categories, services listed
   - Be specific, not generic

7. color_theme: The PRIMARY brand color as hex code
   - IMPORTANT: If brand colors were detected from image analysis above, use those!
   - Otherwise, pick a color that fits the industry
   - Common examples: Blue=#2563EB, Green=#16A34A, Red=#DC2626

8. business_type: Describe the business in 2-4 words
   - Examples: "Coffee Shop", "Athletic Apparel", "SaaS Platform"

WEBSITE CONTENT:
{content}

CRITICAL RULES:
- ONLY extract information that ACTUALLY APPEARS in the content above
- If you cannot find an email/phone, use null - DO NOT INVENT ONE
- For color_theme: PRIORITIZE colors from image analysis if provided
- Return ONLY valid JSON, no markdown or explanation

JSON FORMAT:
{{"store_name": "...", "store_email": "...", "store_phone": "...", "store_voice": "...", "store_tone": "...", "services_products": "...", "color_theme": "#...", "business_type": "..."}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts business information from website content. Always return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0,
            max_tokens=500
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up the response
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[AI Agent] Response: {result_text[:200]}...")

        store_data = json.loads(result_text)

        # Ensure required fields have defaults
        if not store_data.get("store_name"):
            store_data["store_name"] = _extract_domain_name(url)

        # Use image analysis color if available and no color was extracted
        if not store_data.get("color_theme") or store_data.get("color_theme") == "#3B82F6":
            if image_analysis and image_analysis.get("brand_colors"):
                store_data["color_theme"] = image_analysis["brand_colors"][0]
            else:
                store_data["color_theme"] = "#3B82F6"

        if not store_data.get("business_type"):
            store_data["business_type"] = "other"

        # Default store_tone if not extracted
        valid_tones = ["friendly", "professional", "luxury", "modern", "traditional", "playful", "minimalist", "eco_friendly"]
        if not store_data.get("store_tone") or store_data.get("store_tone") not in valid_tones:
            store_data["store_tone"] = "professional"  # Default to professional

        # Generate store_link from store name
        if store_data.get("store_name"):
            store_link = re.sub(r'[^a-z0-9]+', '-', store_data["store_name"].lower())
            store_data["store_link"] = store_link.strip('-')[:30]

        # Add brand style from image analysis
        if image_analysis and image_analysis.get("brand_style"):
            store_data["brand_style"] = image_analysis["brand_style"]

        # Validate contact info
        store_data = _validate_contact_info(store_data, content)

        return store_data

    except json.JSONDecodeError as e:
        print(f"[AI Agent] JSON parse error: {e}")
        return _generate_fallback_data(url)
    except Exception as e:
        print(f"[AI Agent] Error: {e}")
        return _generate_fallback_data(url)


def _extract_contact_info_directly(content: str, domain: str) -> Dict[str, Any]:
    """
    Extract contact info directly from content using regex patterns.
    This is more reliable than AI extraction for structured data.
    """
    import html
    result = {"email": None, "phone": None}

    # Decode HTML entities in content (e.g., &#64; -> @, &amp; -> &)
    decoded_content = html.unescape(content)

    # Also handle common email obfuscations
    decoded_content = re.sub(r'\s*\[at\]\s*', '@', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'\s*\(at\)\s*', '@', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'\s*\[dot\]\s*', '.', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'\s*\(dot\)\s*', '.', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'<span[^>]*>\s*@\s*</span>', '@', decoded_content, flags=re.IGNORECASE)

    # Extract emails using regex
    # Look for emails that match the domain first
    domain_base = domain.split('.')[0] if '.' in domain else domain
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    # Also try mailto: links which are more reliable
    mailto_pattern = r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    mailto_emails = re.findall(mailto_pattern, decoded_content, re.IGNORECASE)

    # Also look for href="mailto:..." patterns
    href_mailto_pattern = r'href=["\']mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})["\']'
    href_mailto_emails = re.findall(href_mailto_pattern, decoded_content, re.IGNORECASE)

    all_emails = re.findall(email_pattern, decoded_content)

    # Add mailto emails to the front (higher priority)
    all_emails = href_mailto_emails + mailto_emails + all_emails

    # Also specifically search for the domain email pattern
    domain_email_pattern = rf'[a-zA-Z0-9._%+-]+@{re.escape(domain)}'
    domain_specific_emails = re.findall(domain_email_pattern, decoded_content, re.IGNORECASE)
    if domain_specific_emails:
        all_emails = domain_specific_emails + all_emails

    print(f"[Contact] Raw content length: {len(content)}, decoded: {len(decoded_content)}")
    print(f"[Contact] Domain: {domain}, domain_base: {domain_base}")
    print(f"[Contact] Mailto emails found: {mailto_emails}")
    print(f"[Contact] Href mailto emails: {href_mailto_emails}")
    print(f"[Contact] Domain specific emails: {domain_specific_emails}")
    print(f"[Contact] All emails found: {list(set(all_emails))[:10]}")

    # Filter and prioritize emails
    domain_emails = []
    contact_emails = []
    other_emails = []

    # Emails to skip (common generic/fake ones)
    skip_emails = {
        'example@example.com', 'test@test.com', 'user@example.com',
        'contact@gmail.com', 'info@gmail.com', 'noreply@'
    }

    for email in all_emails:
        email_lower = email.lower()
        if any(skip in email_lower for skip in skip_emails):
            continue
        if domain_base.lower() in email_lower:
            domain_emails.append(email)
        elif any(prefix in email_lower for prefix in ['info@', 'contact@', 'hello@', 'support@', 'enquiries@', 'sales@', 'help@']):
            contact_emails.append(email)
        else:
            other_emails.append(email)

    # Prioritize: domain emails > contact emails > other emails
    if domain_emails:
        result["email"] = domain_emails[0]
    elif contact_emails:
        result["email"] = contact_emails[0]
    elif other_emails:
        result["email"] = other_emails[0]

    print(f"[Contact] Found emails: domain={domain_emails}, contact={contact_emails}, other={other_emails[:3]}")

    # Extract phone numbers using phonenumbers library (Google's libphonenumber)
    # This handles international formats automatically
    all_phones = []
    seen_digits = set()

    # Try common regions - prioritize based on domain hints
    regions_to_try = ['ZW', 'ZA', 'US', 'GB', 'AU', None]  # None = no region hint

    # Check if domain suggests a specific country
    if '.zw' in domain.lower():
        regions_to_try = ['ZW'] + [r for r in regions_to_try if r != 'ZW']
    elif '.za' in domain.lower():
        regions_to_try = ['ZA'] + [r for r in regions_to_try if r != 'ZA']
    elif '.co.uk' in domain.lower() or '.uk' in domain.lower():
        regions_to_try = ['GB'] + [r for r in regions_to_try if r != 'GB']

    print(f"[Contact] Using phonenumbers library with regions: {regions_to_try[:3]}")

    for region in regions_to_try:
        try:
            for match in PhoneNumberMatcher(decoded_content, region):
                phone_obj = match.number
                # Format as international
                formatted = phonenumbers.format_number(phone_obj, PhoneNumberFormat.INTERNATIONAL)

                # Get digits for deduplication
                digits = re.sub(r'[^\d]', '', formatted)
                last7 = digits[-7:]

                if last7 not in seen_digits:
                    seen_digits.add(last7)
                    all_phones.append(formatted)
                    print(f"[Contact] phonenumbers found: {formatted} (region: {region})")
        except Exception as e:
            print(f"[Contact] phonenumbers error for region {region}: {e}")

    # Fallback to regex if phonenumbers found nothing
    if not all_phones:
        print("[Contact] phonenumbers found nothing, falling back to regex")
        phone_patterns = [
            r'\+\d{1,3}[\s\-\.]\d{2,4}[\s\-\.]\d{5,7}',
            r'\+\d{1,3}[\s\-\.]?\d{2,4}[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}',
            r'\+\d{1,3}[\s\-\.]?\(\d+\)[\s\-\.]?\d{3,}[\s\-\.]?\d*',
            r'\(\d{2,4}\)[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}',
            r'\b\d{3,4}[\s\-\.]\d{3,4}[\s\-\.]\d{3,4}\b',
            r'\b0\d{8,11}\b',
        ]

        for pattern in phone_patterns:
            matches = re.findall(pattern, content)
            for phone in matches:
                digits = re.sub(r'[^\d]', '', phone)
                if len(digits) >= 7 and len(digits) <= 15:
                    last7 = digits[-7:]
                    if last7 not in seen_digits and len(set(digits)) > 2:
                        seen_digits.add(last7)
                        all_phones.append(phone.strip())

    if all_phones:
        result["phone"] = all_phones[0]

    print(f"[Contact] Found phones: {all_phones[:5]}")

    return result


def _validate_contact_info(store_data: Dict[str, Any], original_content: str) -> Dict[str, Any]:
    """
    Validate and enhance contact info.
    First try direct extraction, then validate AI-extracted data.
    """
    # Extract domain for email matching
    domain = ""
    if store_data.get("store_link"):
        domain = store_data.get("store_link", "")

    # Try direct extraction first
    direct_contact = _extract_contact_info_directly(original_content, domain)

    # Use direct extraction results if available
    if direct_contact["email"] and not store_data.get("store_email"):
        store_data["store_email"] = direct_contact["email"]
        print(f"[Validation] Using directly extracted email: {direct_contact['email']}")

    if direct_contact["phone"] and not store_data.get("store_phone"):
        store_data["store_phone"] = direct_contact["phone"]
        print(f"[Validation] Using directly extracted phone: {direct_contact['phone']}")

    # Validate AI-extracted email
    email = store_data.get("store_email")
    if email:
        fake_email_patterns = [
            "contact@gmail.com", "info@gmail.com", "hello@gmail.com",
            "support@gmail.com", "help@gmail.com", "sales@gmail.com",
            "@example.com", "@test.com", "@email.com", "@mail.com",
            "example@", "test@", "user@", "admin@"
        ]
        if any(pattern in email.lower() for pattern in fake_email_patterns):
            print(f"[Validation] Rejected fake email: {email}")
            store_data["store_email"] = direct_contact["email"]  # Fallback to direct extraction
        elif email.lower() not in original_content.lower():
            print(f"[Validation] AI email not found in content: {email}")
            # Still use it if we have no alternative, as AI might have normalized it
            if direct_contact["email"]:
                store_data["store_email"] = direct_contact["email"]

    # Validate AI-extracted phone
    phone = store_data.get("store_phone")
    if phone:
        fake_phone_patterns = [
            "+1 234 567 8901", "+1-234-567-8901", "234-567-8901",
            "555-", "123-456-7890", "000-000-0000",
            "111-111-1111", "123456789", "0000000000"
        ]
        phone_cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)

        if any(pattern.replace("-", "").replace(" ", "") in phone_cleaned for pattern in fake_phone_patterns):
            print(f"[Validation] Rejected fake phone: {phone}")
            store_data["store_phone"] = direct_contact["phone"]
        elif phone_cleaned in ["12345678901", "1234567890"] or len(set(phone_cleaned.replace("+", ""))) <= 2:
            print(f"[Validation] Rejected suspicious phone pattern: {phone}")
            store_data["store_phone"] = direct_contact["phone"]

    # Sanitize phone: if multiple phones (comma-separated), keep only the first one
    # Also ensure it doesn't exceed database limit (50 chars)
    final_phone = store_data.get("store_phone")
    if final_phone:
        # Split by comma and take only the first phone
        if ',' in final_phone:
            final_phone = final_phone.split(',')[0].strip()
            print(f"[Validation] Multiple phones detected, using first: {final_phone}")
        # Truncate if still too long (max 50 chars for DB)
        if len(final_phone) > 50:
            final_phone = final_phone[:50]
            print(f"[Validation] Phone truncated to 50 chars: {final_phone}")
        store_data["store_phone"] = final_phone

    return store_data


def _extract_domain_name(url: str) -> str:
    """Extract a readable name from the domain."""
    domain = url.lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = re.sub(r'^www\.', '', domain)
    domain = domain.split('/')[0]
    domain = domain.split('.')[0]
    return domain.capitalize()


def _extract_faqs_with_ai(content: str, url: str) -> List[Dict[str, str]]:
    """
    Use OpenAI to extract FAQ information from website content.
    Returns a list of {question, answer, category} dicts.
    Enhanced to extract comprehensive business information.
    """
    client = OpenAI(api_key=openai_api_key)

    # Truncate content if too long
    if len(content) > 15000:
        content = content[:15000] + "..."

    domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

    prompt = f"""You are an expert at extracting FAQ and business information from website content.

TASK: Analyze this website content and create helpful FAQs that customers would want to know.

Website URL: {url}
Domain: {domain}

EXTRACT INFORMATION FOR THESE FAQ CATEGORIES:

1. **COMPANY INFO** (PRIORITY - Always extract if available):
   - "Who founded [Company]?" / "When was [Company] founded?"
   - "What does [Company] do?" / "What services does [Company] offer?"
   - "What is [Company]'s mission?"
   - Look for: founder names, CEO, year established, company history, mission statements

2. **LOCATION & CONTACT**:
   - "Where is [Company] located?"
   - "What are [Company]'s business hours?"
   - "How can I contact [Company]?"
   - Look for: physical addresses, office locations, operating hours, contact numbers, email

3. **PRODUCTS & SERVICES**:
   - "What products/services does [Company] offer?"
   - "How does [Product/Service] work?"
   - "What makes [Company] different?"
   - Look for: product descriptions, service offerings, unique selling points

4. **POLICIES & PROCEDURES**:
   - Shipping and delivery information
   - Returns and refunds
   - Payment methods accepted
   - Warranty information

5. **TECHNICAL/SPECIFIC INFO**:
   - Product specifications
   - Service accuracy/reliability stats
   - Certifications or credentials
   - Any numerical claims or statistics

WEBSITE CONTENT:
{content}

IMPORTANT RULES:
- Extract ONLY information that ACTUALLY appears in the content above
- PRIORITIZE company identity info: name, founder/CEO, founding year, location, hours
- Create 8-15 FAQs covering as many categories as possible
- Make questions natural - how a customer would actually ask
- Answers should be complete but concise (1-3 sentences)
- Use the actual company/brand name in questions when known
- Categories: company, location, hours, contact, products, services, shipping, returns, pricing, payment, general

Return ONLY valid JSON array in this format:
[
  {{"question": "When was [Company] founded?", "answer": "[Company] was founded in [year] by [founder].", "category": "company"}},
  {{"question": "Where is [Company] located?", "answer": "[Company] is located at [address].", "category": "location"}},
  {{"question": "What are [Company]'s business hours?", "answer": "[Company] is open [hours].", "category": "hours"}}
]

If no information can be extracted, return an empty array: []
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts FAQ information from website content. Always return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=2000
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up the response
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[FAQ Agent] Extracted FAQs: {result_text[:200]}...")

        faqs = json.loads(result_text)

        # Validate FAQ structure
        valid_faqs = []
        for faq in faqs:
            if isinstance(faq, dict) and faq.get("question") and faq.get("answer"):
                valid_faqs.append({
                    "question": faq.get("question", ""),
                    "answer": faq.get("answer", ""),
                    "category": faq.get("category", "general")
                })

        print(f"[FAQ Agent] Extracted {len(valid_faqs)} valid FAQs")
        return valid_faqs

    except json.JSONDecodeError as e:
        print(f"[FAQ Agent] JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"[FAQ Agent] Error extracting FAQs: {e}")
        return []


def _generate_fallback_data(url: str) -> Dict[str, Any]:
    """Generate fallback data when scraping fails."""
    domain = _extract_domain_name(url)
    store_link = re.sub(r'[^a-z0-9]+', '-', domain.lower()).strip('-')[:30]

    return {
        "store_name": f"{domain} Store",
        "store_email": None,
        "store_phone": None,
        "store_voice": f"Welcome to {domain}. We provide quality products and services tailored to your needs.",
        "store_tone": "professional",
        "store_link": store_link,
        "services_products": "General Products, Services",
        "color_theme": "#3B82F6",
        "business_type": "other",
        "logo_url": None,
        "faqs": []
    }


# Test function
def test_scraping(url: str = "https://example.com"):
    """Test the scraping service."""
    print(f"\n{'='*50}")
    print(f"Testing scraping for: {url}")
    print('='*50)

    result = extract_store_info_from_website(url)

    print(f"\n{'='*50}")
    print("RESULT:")
    print(json.dumps(result, indent=2))
    print('='*50)

    return result

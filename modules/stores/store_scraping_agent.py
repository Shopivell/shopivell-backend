# store_scraping_agent.py - AI Agent for Store Information Extraction
"""Uses Tavily for web scraping and OpenRouter/OpenAI for AI extraction."""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from datetime import datetime

# Import Tavily
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

import html
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# Import screenshot and brand analysis functions
try:
    from modules.stores.scraping_service import (
        capture_homepage_screenshot_sync,
        analyze_brand_from_screenshot_sync,
        PLAYWRIGHT_AVAILABLE,
        GEMINI_AVAILABLE
    )
    SCREENSHOT_AVAILABLE = PLAYWRIGHT_AVAILABLE
except ImportError:
    SCREENSHOT_AVAILABLE = False
    GEMINI_AVAILABLE = False
    capture_homepage_screenshot_sync = None
    analyze_brand_from_screenshot_sync = None

# Import LangChain components
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import OpenRouter adapter (with fallback to Anthropic direct)
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

load_dotenv()
logger = logging.getLogger(__name__)


class StoreScrapingAgent:
    """
    AI Agent for scraping websites and extracting store information.
    Uses Tavily for web content extraction and LangChain for AI processing.

    Features robust extraction with:
    - Direct regex extraction for emails/phones (more reliable)
    - AI-powered extraction for semantic fields
    - Merged results for consistency
    """

    # Regex patterns for direct extraction
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    )
    PHONE_PATTERNS = [
        # International format: +263 xxx xxx xxx
        re.compile(r'\+263\s*\d{2,3}\s*\d{3}\s*\d{3,4}'),
        # Local format with area code: 0242 xxx xxx
        re.compile(r'0\d{3}\s*\d{3}\s*\d{3,4}'),
        # Format with dashes: 024-2-xxx-xxx
        re.compile(r'0\d{2,3}[-\s]?\d{1,3}[-\s]?\d{3}[-\s]?\d{3,4}'),
        # Tel/Phone labeled numbers
        re.compile(r'(?:tel|phone|call)[\s:]+([+\d\s\-()]{7,20})', re.IGNORECASE),
        # Generic phone with + prefix
        re.compile(r'\+\d{1,3}[\s\-]?\d{2,3}[\s\-]?\d{3}[\s\-]?\d{3,4}'),
        # Numbers in parentheses format
        re.compile(r'\(\d{3,4}\)\s*\d{3}[\s\-]?\d{3,4}'),
    ]

    def __init__(self):
        # Initialize Tavily client
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        print(f"[StoreScrapingAgent] Initializing... TAVILY_AVAILABLE={TAVILY_AVAILABLE}, API_KEY={'SET' if tavily_api_key else 'NOT SET'}")
        if tavily_api_key and TAVILY_AVAILABLE:
            self.tavily = TavilyClient(api_key=tavily_api_key)
            print("[StoreScrapingAgent] Tavily client initialized successfully")
            logger.info("[StoreScrapingAgent] Tavily client initialized")
        else:
            self.tavily = None
            print(f"[StoreScrapingAgent] WARNING: Tavily not available! TAVILY_AVAILABLE={TAVILY_AVAILABLE}, API_KEY={'SET' if tavily_api_key else 'NOT SET'}")
            logger.warning("[StoreScrapingAgent] Tavily not available - scraping will be limited")

        # Initialize LLM via OpenRouter or Anthropic direct
        self.llm = ChatOpenRouter(
            model="anthropic/claude-sonnet-4" if OPENROUTER_AVAILABLE else "claude-sonnet-4-20250514",
            temperature=0.2
        )
        logger.info(f"[StoreScrapingAgent] LLM initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'Anthropic direct'}")

        # Store info extraction prompt
        self.store_info_prompt = ChatPromptTemplate.from_template("""
You are an expert business analyst extracting store/business information from website content.

TASK: Analyze this website content and extract ALL available business information.

Website URL: {url}
Domain: {domain}

EXTRACT THESE FIELDS (return null only if truly not found):

1. store_name: The business name (from logo, header, title, footer, or About section)

2. store_email: Customer contact email. Look for:
   - mailto: links
   - "Contact us", "Email us", "Get in touch" sections
   - Footer contact info
   - Patterns like info@, hello@, contact@, support@, help@, sales@, enquiries@
   - Any email format like name@domain.co.zw, name@domain.com

3. store_phone: Customer service phone. Look for:
   - "Call us", "Phone", "Tel", "Telephone" labels
   - tel: links
   - Numbers in contact section, header, or footer
   - Local formats like 0242 XXX XXX, 08XXX XXX XXX
   - International formats like +263 XXX XXX XXX
   - Only use null if NO phone number appears anywhere in the content

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

6. services_products: List of main products/services as a JSON array of objects
   - Look at navigation menu, product categories, services listed
   - Be specific with names and descriptions
   - Include category if visible

7. color_theme: The PRIMARY brand color as hex code
   - Extract from the website's actual CSS/design if visible
   - Common examples: Blue=#2563EB, Green=#16A34A, Red=#DC2626

8. business_type: Describe the business in 2-4 specific words
   - Examples: "IT Equipment Store", "Security Services", "Appliance Repairs", "Coffee Shop"
   - Do NOT use generic terms like "Business" or "Company"

9. brand_style: Describe the brand's visual style in 1-2 sentences
   - What does the website look and feel like?
   - Examples: "Modern and clean with bold orange accents", "Corporate and professional with blue tones"

WEBSITE CONTENT:
{content}

CRITICAL RULES:
- ONLY extract information that ACTUALLY APPEARS in the content above
- For store_name: Use the FULL company name, not abbreviated (e.g. "Reliable Modern Technologies" not "Reliabletech")
- For services_products: Return as JSON array, not a comma-separated string
- If you cannot find an email/phone, use null - DO NOT INVENT ONE
- Return ONLY valid JSON, no markdown or explanation

JSON FORMAT:
{{"store_name": "Full Business Name", "store_email": "...", "store_phone": "...", "store_voice": "2-3 sentences about what the business does and their value proposition", "store_tone": "professional", "services_products": [{{"name": "Service 1", "description": "Brief description", "category": "Category"}}, {{"name": "Service 2", "description": "Brief description", "category": "Category"}}], "color_theme": "#...", "business_type": "Specific Type", "brand_style": "Visual style description"}}
""")

        # FAQ extraction prompt - Enhanced to extract comprehensive business information
        self.faq_prompt = ChatPromptTemplate.from_template("""
You are an expert at extracting FAQ and business information from website content.

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
""")

    def _scrape_website(self, url: str) -> Dict[str, Any]:
        """
        Scrape website content using Tavily - extracts from multiple pages.
        Similar to campaign service scraping.
        """
        print(f"[StoreScrapingAgent] _scrape_website called for: {url}")
        print(f"[StoreScrapingAgent] Tavily client available: {self.tavily is not None}")

        if not self.tavily:
            print("[StoreScrapingAgent] ERROR: Tavily not available, returning empty content")
            logger.warning("[StoreScrapingAgent] Tavily not available")
            return {"content": "", "pages_extracted": 0}

        try:
            base_url = url.rstrip('/')
            if not base_url.startswith('http'):
                base_url = 'https://' + base_url

            domain = base_url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
            logger.info(f"[StoreScrapingAgent] Scraping {domain} - extracting from multiple pages...")

            # Priority pages to extract (ordered by importance)
            priority_pages = [
                '',  # Homepage
                '/contact', '/contact-us', '/contactus', '/get-in-touch',
                '/about', '/about-us', '/aboutus', '/who-we-are',
                '/products', '/services', '/our-services', '/what-we-do',
                '/faq', '/faqs', '/help', '/support',
                '/pricing', '/prices', '/rates', '/plans', '/packages',  # Pricing pages
                '/solutions', '/offerings', '/features',  # Product pages
                '/locations', '/branches', '/find-us',
            ]

            # Build URLs to extract
            urls_to_extract = [base_url + page for page in priority_pages[:15]]

            all_content = []
            extracted_pages = []
            all_images = []

            # Extract from multiple pages
            try:
                print(f"[StoreScrapingAgent] Calling Tavily extract for {len(urls_to_extract)} URLs...")
                logger.info(f"[StoreScrapingAgent] Attempting to extract from {len(urls_to_extract)} URLs...")
                extract_result = self.tavily.extract(urls=urls_to_extract, include_images=True)
                print(f"[StoreScrapingAgent] Tavily extract returned: {len(extract_result.get('results', [])) if extract_result else 0} results")

                if extract_result and extract_result.get("results"):
                    for result in extract_result["results"]:
                        content = result.get("raw_content", "")
                        page_url = result.get("url", "")
                        images = result.get("images", [])

                        if content and len(content) > 100:
                            all_content.append(f"=== PAGE: {page_url} ===\n{content}")
                            extracted_pages.append(page_url)

                        if images:
                            all_images.extend(images)

                    print(f"[StoreScrapingAgent] Successfully extracted {len(extracted_pages)} pages with content")
                    logger.info(f"[StoreScrapingAgent] Successfully extracted {len(extracted_pages)} pages")
                else:
                    print(f"[StoreScrapingAgent] Tavily extract returned no results!")
            except Exception as e:
                print(f"[StoreScrapingAgent] Extraction error: {e}")
                logger.error(f"[StoreScrapingAgent] Extraction error: {e}")

            # Also do a search for more context, especially contact info
            try:
                print(f"[StoreScrapingAgent] Starting Tavily search for {domain}...")
                logger.info(f"[StoreScrapingAgent] Searching for {domain} information...")
                search_queries = [
                    f"site:{domain} contact email phone address",
                    f"site:{domain} about services products",
                    f"site:{domain} FAQ help",
                    f"{domain} contact phone email",  # Also search without site: restriction
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

                        if content and len(content) > 100 and result_url not in extracted_pages:
                            all_content.append(f"=== SEARCH: {result_url} ===\n{content}")
                            extracted_pages.append(result_url)

                print(f"[StoreScrapingAgent] Search complete, total sources: {len(all_content)}")
                logger.info(f"[StoreScrapingAgent] Search complete, total sources: {len(all_content)}")
            except Exception as e:
                print(f"[StoreScrapingAgent] Search error: {e}")
                logger.error(f"[StoreScrapingAgent] Search error: {e}")

            combined_content = "\n\n".join(all_content)
            print(f"[StoreScrapingAgent] Final content length: {len(combined_content)} chars, {len(all_content)} sources, {len(all_images)} images")

            return {
                "url": url,
                "domain": domain,
                "content": combined_content[:25000],
                "pages_extracted": len(all_content),
                "images": all_images[:20],
                "extracted_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            print(f"[StoreScrapingAgent] FATAL Scraping error: {e}")
            logger.error(f"[StoreScrapingAgent] Scraping error: {e}")
            return {"content": "", "pages_extracted": 0, "images": []}

    def _clean_json_response(self, text: str) -> str:
        """Clean markdown code blocks from JSON response."""
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        return text.strip()

    def _fetch_raw_html(self, base_url: str) -> str:
        """
        Fetch raw HTML directly from the website.
        This helps capture emails/phones that Tavily might miss.
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        urls_to_fetch = [
            base_url,
            base_url + '/contact',
            base_url + '/contact-us',
            base_url + '/about',
            base_url + '/about-us',
        ]

        all_html = ""
        for url in urls_to_fetch:
            try:
                response = requests.get(url, headers=headers, timeout=10, allow_redirects=True, verify=True)
                if response.status_code == 200:
                    all_html += response.text + "\n"
                    print(f"[StoreScrapingAgent] Fetched HTML from {url}: {len(response.text)} chars")
            except Exception as e:
                print(f"[StoreScrapingAgent] Failed to fetch {url}: {e}")

        return all_html

    def _extract_emails_from_content(self, content: str, domain: str) -> List[str]:
        """
        Extract emails directly from content using regex.
        Prioritizes emails from the same domain.
        Handles HTML entities and common obfuscations.
        """
        from urllib.parse import unquote
        # Decode HTML entities (&#64; -> @, &amp; -> &, etc.)
        decoded_content = html.unescape(content)
        # Decode URL encoding (%20 -> space, %40 -> @)
        decoded_content = unquote(decoded_content)

        # Handle common email obfuscations
        decoded_content = re.sub(r'\s*\[at\]\s*', '@', decoded_content, flags=re.IGNORECASE)
        decoded_content = re.sub(r'\s*\(at\)\s*', '@', decoded_content, flags=re.IGNORECASE)
        decoded_content = re.sub(r'\s*\[dot\]\s*', '.', decoded_content, flags=re.IGNORECASE)
        decoded_content = re.sub(r'\s*\(dot\)\s*', '.', decoded_content, flags=re.IGNORECASE)

        # First, try to extract from mailto: links (most reliable)
        mailto_pattern = r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        mailto_emails = re.findall(mailto_pattern, decoded_content, re.IGNORECASE)

        # Also look for href="mailto:..." patterns
        href_mailto_pattern = r'href=["\']mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        href_mailto_emails = re.findall(href_mailto_pattern, decoded_content, re.IGNORECASE)

        # General email pattern
        emails = self.EMAIL_PATTERN.findall(decoded_content)

        # Also specifically search for domain emails
        domain_email_pattern = rf'[a-zA-Z0-9._%+-]+@{re.escape(domain)}'
        domain_specific_emails = re.findall(domain_email_pattern, decoded_content, re.IGNORECASE)

        # Combine all sources (mailto has priority)
        all_emails = href_mailto_emails + mailto_emails + domain_specific_emails + emails

        print(f"[StoreScrapingAgent] Email extraction - mailto: {mailto_emails}, href_mailto: {href_mailto_emails}, domain: {domain_specific_emails}, general: {emails[:5]}")

        if not all_emails:
            return []

        # Filter out common non-business emails
        excluded_patterns = ['example.com', 'test.com', 'email.com', 'domain.com',
                            'yourcompany', 'yourdomain', 'company.com', 'noreply',
                            'no-reply', 'donotreply', 'wix.com', 'wordpress',
                            'sentry.io', 'gravatar.com', 'w3.org']
        filtered_emails = [
            e for e in all_emails
            if not any(ex in e.lower() for ex in excluded_patterns)
        ]

        # Sort: prioritize domain emails, then info@, contact@, hello@, etc.
        priority_prefixes = ['info@', 'contact@', 'hello@', 'sales@', 'support@', 'enquiries@', 'admin@']
        domain_base = domain.split('.')[0].lower()

        def email_priority(email: str) -> int:
            email_lower = email.lower()
            # Highest priority: domain email with info/contact prefix
            if domain_base in email_lower:
                for i, prefix in enumerate(priority_prefixes):
                    if email_lower.startswith(prefix):
                        return i
                return len(priority_prefixes)
            # Lower priority: other emails with good prefixes
            for i, prefix in enumerate(priority_prefixes):
                if email_lower.startswith(prefix):
                    return 100 + i
            return 200

        filtered_emails = list(set(filtered_emails))  # Remove duplicates
        filtered_emails.sort(key=email_priority)
        print(f"[StoreScrapingAgent] Filtered emails (sorted): {filtered_emails[:5]}")
        return filtered_emails[:5]  # Return top 5

    def _extract_phones_from_content(self, content: str) -> List[str]:
        """
        Extract phone numbers directly from content using regex patterns.
        Returns cleaned and deduplicated phone numbers.
        Handles Zimbabwe phone formats specifically.
        """
        # Decode HTML entities first
        decoded_content = html.unescape(content)

        phones = []

        # Zimbabwe-specific patterns (highest priority)
        zim_patterns = [
            # +263-242-746620 or +263 242 746620
            re.compile(r'\+263[\s\-\.]*\d{2,3}[\s\-\.]*\d{3}[\s\-\.]*\d{3,4}'),
            # +263 (4) 758711 format
            re.compile(r'\+263[\s\-\.]*\(\d+\)[\s\-\.]*\d{6,}'),
            # 0242-746620 or 024 2746620
            re.compile(r'0\d{2,3}[\s\-\.]*\d{3}[\s\-\.]*\d{3,4}'),
        ]

        # First try Zimbabwe patterns
        for pattern in zim_patterns:
            matches = pattern.findall(decoded_content)
            for match in matches:
                phone = str(match).strip()
                if phone and len(re.sub(r'[^\d]', '', phone)) >= 9:
                    phones.append(phone)

        # Then try general patterns
        for pattern in self.PHONE_PATTERNS:
            matches = pattern.findall(decoded_content)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match else ''
                phone = str(match).strip()
                # Only accept if it looks like a real phone (has enough digits)
                digits = re.sub(r'[^\d]', '', phone)
                if len(digits) >= 9 and len(digits) <= 15:
                    phones.append(phone)

        # Also extract from tel: links
        tel_pattern = r'tel:([+\d\s\-().]{7,20})'
        tel_matches = re.findall(tel_pattern, decoded_content, re.IGNORECASE)
        for match in tel_matches:
            phone = match.strip()
            if phone:
                phones.append(phone)

        print(f"[StoreScrapingAgent] Raw phones found: {phones[:10]}")

        # Deduplicate while preserving order
        seen = set()
        unique_phones = []
        for phone in phones:
            # Normalize for comparison (remove spaces/dashes)
            normalized = re.sub(r'[\s\-().+]', '', phone)
            # Skip fake patterns
            if normalized in ['1234567890', '12345678901', '0000000000'] or len(set(normalized)) <= 2:
                continue
            # Skip if too short or already seen
            if len(normalized) < 9 or normalized in seen:
                continue
            seen.add(normalized)
            unique_phones.append(phone)

        print(f"[StoreScrapingAgent] Filtered phones: {unique_phones[:5]}")
        return unique_phones[:5]  # Return top 5

    def _extract_logo_url_robust(self, images: List[Any], domain: str, content: str) -> Optional[str]:
        """
        Robustly extract logo URL from images list.
        Handles both string URLs and dict formats.
        """
        if not images:
            return None

        # Normalize images to list of URLs
        image_urls = []
        for img in images:
            if isinstance(img, str):
                image_urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('src') or img.get('image_url')
                if url:
                    image_urls.append(url)

        if not image_urls:
            return None

        # Skip patterns — these contain "logo" but are NOT the actual company logo
        skip_patterns = [
            r'brands[-_]?logo', r'partner[-_]?logo', r'client[-_]?logo',
            r'logos[-_]?banner', r'brand[-_]?logos', r'brands[-_]?logos',
            r'sponsor[-_]?logo', r'payment[-_]?logo', r'trusted[-_]?logo',
        ]

        # Logo detection patterns (ordered by priority — most specific first)
        logo_patterns = [
            r'site[-_]?logo', r'company[-_]?logo', r'main[-_]?logo',
            r'header[-_]?logo', r'/logo\.', r'logo[-_]?img',
            r'favicon', r'icon',
        ]

        # First pass: look for explicit logo patterns in URL (but skip partner/brand logos)
        for img_url in image_urls:
            img_lower = img_url.lower()
            # Skip partner/brand logo banners
            if any(re.search(sp, img_lower) for sp in skip_patterns):
                continue
            for pattern in logo_patterns:
                if re.search(pattern, img_lower):
                    logger.info(f"[StoreScrapingAgent] Found logo via pattern '{pattern}': {img_url[:80]}")
                    return img_url

        # Second pass: look for generic "logo" in URL (still skip partner logos)
        for img_url in image_urls:
            img_lower = img_url.lower()
            if any(re.search(sp, img_lower) for sp in skip_patterns):
                continue
            if 'logo' in img_lower:
                logger.info(f"[StoreScrapingAgent] Found logo via generic 'logo' match: {img_url[:80]}")
                return img_url

        # Second pass: look for domain name in image URL (likely brand asset)
        domain_base = domain.split('.')[0].lower()
        for img_url in image_urls:
            if domain_base in img_url.lower():
                # Prefer smaller images (likely logos vs hero images)
                if any(x in img_url.lower() for x in ['logo', 'icon', 'brand', '-sm', '-small', 'thumb']):
                    logger.info(f"[StoreScrapingAgent] Found logo via domain match: {img_url[:80]}")
                    return img_url

        # Third pass: return first image from same domain
        for img_url in image_urls:
            if domain in img_url:
                logger.info(f"[StoreScrapingAgent] Using first domain image as logo: {img_url[:80]}")
                return img_url

        # Fallback: return first image
        if image_urls:
            logger.info(f"[StoreScrapingAgent] Using first image as fallback logo: {image_urls[0][:80]}")
            return image_urls[0]

        return None

    def _extract_images_from_html(self, url: str) -> List[Dict[str, Any]]:
        """
        Fallback method to extract images directly from HTML when Tavily returns none.
        Focuses on logos and brand images.
        """
        images = []
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')
            base_url = url.rstrip('/')
            domain = urlparse(url).netloc.replace('www.', '')

            # Logo selectors - common patterns
            logo_selectors = [
                'img[class*="logo"]', 'img[id*="logo"]', 'img[alt*="logo"]',
                'img[src*="logo"]', '.logo img', '#logo img', 'header img',
                '.navbar img', '.brand img', 'a.navbar-brand img'
            ]

            found_urls = set()

            # Find logos first
            for selector in logo_selectors:
                for img in soup.select(selector):
                    src = img.get('src') or img.get('data-src')
                    if src and src not in found_urls:
                        if not src.startswith('http'):
                            src = urljoin(base_url, src)
                        # Skip tracking pixels and tiny images
                        if any(skip in src.lower() for skip in ['pixel', 'tracking', '1x1', 'spacer', '.gif', 'data:']):
                            continue
                        found_urls.add(src)
                        images.append({
                            "url": src,
                            "alt": img.get('alt', ''),
                            "is_logo": True
                        })
                        print(f"[StoreScrapingAgent] Found logo via selector: {src[:80]}")

            # Find other images
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src and src not in found_urls:
                    if not src.startswith('http'):
                        src = urljoin(base_url, src)
                    # Skip tracking pixels and tiny images
                    if any(skip in src.lower() for skip in ['pixel', 'tracking', '1x1', 'spacer', '.gif', 'data:', 'facebook', 'twitter', 'analytics']):
                        continue
                    found_urls.add(src)
                    is_logo = 'logo' in src.lower() or 'logo' in (img.get('alt', '') or '').lower()
                    images.append({
                        "url": src,
                        "alt": img.get('alt', ''),
                        "is_logo": is_logo
                    })

            print(f"[StoreScrapingAgent] Extracted {len(images)} images from HTML")
            return images[:20]  # Limit to 20 images

        except Exception as e:
            print(f"[StoreScrapingAgent] Error extracting images from HTML: {e}")
            return []

    async def extract_store_info(self, url: str) -> Dict[str, Any]:
        """
        Main method to extract all store information from a website.
        Uses Tavily for scraping and LangChain for AI extraction.

        Combines:
        - Direct regex extraction for emails/phones (reliable)
        - AI extraction for semantic fields (store name, voice, tone)
        - Merged results for best consistency
        """
        logger.info(f"[StoreScrapingAgent] Starting extraction for: {url}")

        # Step 1: Scrape website content
        scraped_data = self._scrape_website(url)

        domain = scraped_data.get("domain", "")
        content = scraped_data.get("content", "")
        images = scraped_data.get("images", [])

        # Step 1.5: If Tavily returned thin/empty content, try Playwright (JS-rendered SPAs)
        if len(content) < 500:
            print(f"[StoreScrapingAgent] Tavily content too thin ({len(content)} chars), trying Playwright...")
            try:
                if SCREENSHOT_AVAILABLE:
                    from playwright.async_api import async_playwright
                    import platform as platform_mod

                    async with async_playwright() as p:
                        is_linux = platform_mod.system() == "Linux"
                        launch_args = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] if is_linux else []
                        browser = await p.chromium.launch(headless=True, args=launch_args)
                        context = await browser.new_context(
                            viewport={"width": 1920, "height": 1080},
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        )
                        page = await context.new_page()

                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            if url.startswith("https://"):
                                await page.goto(url.replace("https://", "http://"), wait_until="domcontentloaded", timeout=30000)
                            else:
                                raise

                        try:
                            await page.wait_for_selector("body", state="visible", timeout=5000)
                        except Exception:
                            pass
                        await page.wait_for_timeout(3000)

                        # Scroll to trigger lazy loading
                        try:
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                            await page.wait_for_timeout(1000)
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            await page.wait_for_timeout(1000)
                        except Exception:
                            pass

                        # Extract text content
                        pw_content = await page.evaluate("""() => {
                            document.querySelectorAll('script, style, noscript, iframe').forEach(el => el.remove());
                            const parts = [];
                            const title = document.title;
                            if (title) parts.push('# ' + title);
                            const metaDesc = document.querySelector('meta[name="description"]');
                            if (metaDesc) parts.push('Description: ' + metaDesc.content);
                            document.querySelectorAll('h1, h2, h3').forEach(h => {
                                const text = h.textContent.trim();
                                if (text && text.length > 2) parts.push('#'.repeat(h.tagName[1]) + ' ' + text);
                            });
                            document.querySelectorAll('p').forEach(p => {
                                const text = p.textContent.trim();
                                if (text && text.length > 15) parts.push(text);
                            });
                            document.querySelectorAll('li').forEach(li => {
                                const text = li.textContent.trim();
                                if (text && text.length > 10 && text.length < 200) parts.push('- ' + text);
                            });
                            document.querySelectorAll('a').forEach(a => {
                                const href = a.href;
                                const text = a.textContent.trim();
                                if (text && href && text.length > 2 && text.length < 50) parts.push('[' + text + '](' + href + ')');
                            });
                            return parts.join('\\n\\n');
                        }""")

                        # Extract images
                        pw_images = await page.evaluate("""() => {
                            const imgs = [];
                            document.querySelectorAll('img').forEach(img => {
                                const src = img.src || img.dataset.src;
                                if (src && !src.startsWith('data:') && src.length > 10) {
                                    imgs.push({url: src, alt: img.alt || ''});
                                }
                            });
                            return imgs;
                        }""")

                        await browser.close()

                        if pw_content and len(pw_content) > len(content):
                            print(f"[StoreScrapingAgent] Playwright extracted {len(pw_content)} chars (was {len(content)})")
                            content = pw_content
                            scraped_data["content"] = content
                            scraped_data["pages_extracted"] = max(scraped_data.get("pages_extracted", 0), 1)
                        if pw_images and not images:
                            images = pw_images
                            scraped_data["images"] = images
                            print(f"[StoreScrapingAgent] Playwright found {len(pw_images)} images")

            except Exception as e:
                print(f"[StoreScrapingAgent] Playwright fallback failed: {e}")

        if not content:
            logger.warning("[StoreScrapingAgent] No content scraped, returning fallback")
            return self._generate_fallback_data(url)

        # Fallback: Extract images from HTML if Tavily returned none
        if not images:
            print(f"[StoreScrapingAgent] No images from Tavily, extracting from HTML...")
            images = self._extract_images_from_html(url)

        # Step 2: Fetch raw HTML for better contact extraction
        base_url = url.rstrip('/')
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        raw_html = self._fetch_raw_html(base_url)

        # Combine Tavily content with raw HTML for contact extraction
        combined_content = content + "\n" + raw_html
        print(f"[StoreScrapingAgent] Combined content length: {len(combined_content)} (Tavily: {len(content)}, HTML: {len(raw_html)})")

        # Step 3: DIRECT EXTRACTION - Extract emails and phones using regex (reliable)
        logger.info("[StoreScrapingAgent] Extracting contact info directly from combined content...")
        direct_emails = self._extract_emails_from_content(combined_content, domain)
        direct_phones = self._extract_phones_from_content(combined_content)

        logger.info(f"[StoreScrapingAgent] Direct extraction found: {len(direct_emails)} emails, {len(direct_phones)} phones")
        if direct_emails:
            logger.info(f"[StoreScrapingAgent] Best email: {direct_emails[0]}")
        if direct_phones:
            logger.info(f"[StoreScrapingAgent] Best phone: {direct_phones[0]}")

        # Step 3: AI EXTRACTION - Extract store info using AI
        logger.info("[StoreScrapingAgent] Extracting store information with AI...")
        try:
            from modules.openrouter.context import set_ai_context
            store_chain = self.store_info_prompt | self.llm | StrOutputParser()
            with set_ai_context(agent_name="store_scraping"):
                store_response = await store_chain.ainvoke({
                    "url": url,
                    "domain": domain,
                    "content": content[:20000]
                })

            store_response = self._clean_json_response(store_response)
            store_data = json.loads(store_response)
            logger.info(f"[StoreScrapingAgent] AI extracted: {list(store_data.keys())}")

        except Exception as e:
            logger.error(f"[StoreScrapingAgent] Store info extraction error: {e}")
            print(f"[StoreScrapingAgent] AI EXTRACTION FAILED: {e}")
            store_data = {}

        # Step 4: MERGE RESULTS - Direct extraction takes priority for contact info
        # Direct regex extraction is more reliable for emails/phones
        if direct_emails:
            # Clean email: remove URL encoding and leading junk
            from urllib.parse import unquote
            email = unquote(direct_emails[0]).strip()
            email = re.sub(r'^[^a-zA-Z0-9]+', '', email)  # Remove leading non-alphanumeric
            store_data["store_email"] = email
            logger.info(f"[StoreScrapingAgent] Using direct-extracted email: {email}")
        elif not store_data.get("store_email"):
            store_data["store_email"] = None

        if direct_phones:
            # Use only the first phone to avoid DB truncation (max 50 chars)
            phone = direct_phones[0]
            if len(phone) > 50:
                phone = phone[:50]
            store_data["store_phone"] = phone
            logger.info(f"[StoreScrapingAgent] Using direct-extracted phone: {phone}")
        elif not store_data.get("store_phone"):
            store_data["store_phone"] = None

        # Step 5: Extract FAQs using AI
        logger.info("[StoreScrapingAgent] Extracting FAQs with AI...")
        try:
            from modules.openrouter.context import set_ai_context
            faq_chain = self.faq_prompt | self.llm | StrOutputParser()
            with set_ai_context(agent_name="store_scraping"):
                faq_response = await faq_chain.ainvoke({
                    "url": url,
                    "domain": domain,
                    "content": content[:15000]
                })

            faq_response = self._clean_json_response(faq_response)
            faqs = json.loads(faq_response)

            # Validate FAQ structure
            valid_faqs = []
            for faq in faqs:
                if isinstance(faq, dict) and faq.get("question") and faq.get("answer"):
                    valid_faqs.append({
                        "question": faq.get("question", ""),
                        "answer": faq.get("answer", ""),
                        "category": faq.get("category", "general")
                    })

            logger.info(f"[StoreScrapingAgent] Extracted {len(valid_faqs)} FAQs")

        except Exception as e:
            logger.error(f"[StoreScrapingAgent] FAQ extraction error: {e}")
            valid_faqs = []

        # Step 6: Apply defaults and enhancements
        result = self._apply_defaults(store_data, url, domain)

        # Step 7: Extract logo using robust method
        logo_url = self._extract_logo_url_robust(images, domain, content)
        if logo_url:
            result["logo_url"] = logo_url
            logger.info(f"[StoreScrapingAgent] Logo URL set: {logo_url[:80]}...")

        # Add extracted images (normalized)
        if images:
            normalized_images = []
            for img in images[:10]:
                if isinstance(img, str):
                    normalized_images.append({"url": img, "alt": "", "is_logo": img == logo_url})
                elif isinstance(img, dict):
                    img["is_logo"] = img.get("url") == logo_url
                    normalized_images.append(img)
            result["extracted_images"] = normalized_images

        # Add FAQs
        result["faqs"] = valid_faqs

        # Add metadata
        result["pages_scraped"] = scraped_data.get("pages_extracted", 0)
        result["scraped_at"] = scraped_data.get("extracted_at")

        # Step 8: Capture homepage screenshot and analyze brand with Gemini
        if SCREENSHOT_AVAILABLE and capture_homepage_screenshot_sync:
            logger.info(f"[StoreScrapingAgent] Capturing full homepage screenshot...")
            screenshot_data = capture_homepage_screenshot_sync(url, full_page=True)

            if screenshot_data.get("success"):
                result["homepage_screenshot"] = {
                    "path": screenshot_data.get("screenshot_path"),
                    "filename": screenshot_data.get("screenshot_filename"),
                    "base64": screenshot_data.get("screenshot_base64"),
                    "width": screenshot_data.get("width"),
                    "height": screenshot_data.get("height"),
                    "url": screenshot_data.get("url"),
                    "screenshot_url": screenshot_data.get("screenshot_url"),  # Cloudinary URL
                    "thumbnail_url": screenshot_data.get("thumbnail_url"),
                }
                # Also add screenshot_url at top level for easy database access
                if screenshot_data.get("screenshot_url"):
                    result["screenshot_url"] = screenshot_data.get("screenshot_url")
                    result["screenshot_thumbnail_url"] = screenshot_data.get("thumbnail_url")
                logger.info(f"[StoreScrapingAgent] Screenshot captured: {screenshot_data.get('screenshot_filename')}")
                if screenshot_data.get("screenshot_url"):
                    logger.info(f"[StoreScrapingAgent] Cloudinary URL: {screenshot_data.get('screenshot_url')}")

                # Analyze brand from screenshot using Gemini
                if GEMINI_AVAILABLE and analyze_brand_from_screenshot_sync:
                    logger.info(f"[StoreScrapingAgent] Analyzing brand with Gemini...")
                    brand_analysis = analyze_brand_from_screenshot_sync(
                        screenshot_base64=screenshot_data.get("screenshot_base64"),
                        url=url
                    )

                    if brand_analysis.get("success"):
                        brand = brand_analysis.get("brand_analysis", {})
                        result["brand_analysis"] = brand

                        # Use Gemini-extracted colors if available
                        if brand.get("primary_color"):
                            result["brand_color"] = brand["primary_color"]
                            result["brand_color_source"] = "gemini_screenshot_analysis"
                            logger.info(f"[StoreScrapingAgent] Brand color from Gemini: {brand['primary_color']}")

                        if brand.get("color_palette"):
                            result["all_brand_colors"] = [
                                {"color": c, "source": "gemini_screenshot_analysis"}
                                for c in brand["color_palette"]
                            ]

                        if brand.get("industry_guess"):
                            result["detected_industry"] = brand["industry_guess"]

                        logger.info(f"[StoreScrapingAgent] Brand analysis complete")
                    else:
                        logger.warning(f"[StoreScrapingAgent] Brand analysis failed: {brand_analysis.get('error')}")
            else:
                logger.warning(f"[StoreScrapingAgent] Screenshot failed: {screenshot_data.get('error')}")

        logger.info(f"[StoreScrapingAgent] Extraction complete: {result.get('store_name')}")
        logger.info(f"[StoreScrapingAgent] Email: {result.get('store_email')}, Phone: {result.get('store_phone')}")
        logger.info(f"[StoreScrapingAgent] FAQs: {len(valid_faqs)}, Logo: {'Yes' if logo_url else 'No'}")

        return result

    def extract_store_info_sync(self, url: str) -> Dict[str, Any]:
        """Synchronous version of extract_store_info."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.extract_store_info(url))
                return future.result()
        except RuntimeError:
            return asyncio.run(self.extract_store_info(url))

    async def extract_products(self, url: str) -> Dict[str, Any]:
        """
        Extract products/services from a website with prices and pricing tiers.
        Returns structured data with products, services, and pricing tiers.
        """
        logger.info(f"[StoreScrapingAgent] Starting products extraction for: {url}")

        # Step 1: Scrape website content
        scraped_data = self._scrape_website(url)

        if not scraped_data.get("content"):
            logger.warning("[StoreScrapingAgent] No content scraped for products")
            return {"products": [], "services": [], "pricing_tiers": [], "message": "Could not scrape website content"}

        domain = scraped_data.get("domain", "")
        content = scraped_data.get("content", "")

        # Enhanced products extraction prompt with industry-specific guidance
        products_prompt = ChatPromptTemplate.from_template("""
You are an expert at extracting product and service information from websites.

TASK: Extract ALL products, services, and pricing from this website content.

Website URL: {url}
Domain: {domain}

EXTRACT THE FOLLOWING:

1. **PRODUCTS** (physical or digital items for sale):
   - name: Exact product name as shown on website
   - description: What it is (1-2 sentences)
   - price: Actual price with currency (e.g., "$25/year", "$3.50/month", "From $99")
   - price_numeric: Just the number (e.g., 25, 3.50, 99)
   - currency: Currency code (USD, ZAR, ZWL)
   - billing_period: monthly, yearly, once-off, or null
   - category: Product category

2. **SERVICES** (services offered):
   - name: Exact service name
   - description: What the service includes
   - price: Price if shown (e.g., "$100/hour", "From $500")
   - price_numeric: Just the number
   - currency: Currency code
   - billing_period: monthly, yearly, hourly, once-off, or null
   - category: Service category

3. **PRICING TIERS** (for subscription/SaaS/tiered businesses):
   - tier_name: Name of the plan (e.g., "Bronze", "Premium", "Enterprise")
   - price: Price with billing period (e.g., "$10/month", "$99/year")
   - price_numeric: Just the number
   - currency: Currency code
   - billing_period: monthly, yearly
   - features: Key features included (list of strings)

4. **BUSINESS INFO**:
   - industry: Specific industry (e.g., "web_hosting", "security_services", "restaurant", "retail")
   - target_market: Who they sell to

INDUSTRY-SPECIFIC GUIDANCE:
- For HOSTING companies: Look for Domain Registration, Web Hosting plans, Email Hosting, SSL Certificates
- For SECURITY companies: Look for Armed Response, CCTV Installation, Access Control, Monitoring packages
- For RESTAURANTS: Look for menu items, meal deals, catering packages
- For RETAIL: Look for product categories, individual items with prices
- For CONSULTANTS: Look for service packages, hourly rates, project-based pricing

WEBSITE CONTENT:
{content}

IMPORTANT RULES:
- Extract ONLY products/services that ACTUALLY appear in the content
- Include ACTUAL prices if shown - don't make up prices
- Be SPECIFIC - use exact names from the website, not generic terms
- If no price is shown, use "Contact for quote" for price and 0 for price_numeric
- Extract up to 20 products, 10 services, and 10 pricing tiers

Return ONLY valid JSON in this format:
{{
  "products": [
    {{"name": "Product Name", "description": "What it is", "price": "$XX/year", "price_numeric": 25, "currency": "USD", "billing_period": "yearly", "category": "category"}}
  ],
  "services": [
    {{"name": "Service Name", "description": "What it includes", "price": "$XX/month", "price_numeric": 100, "currency": "USD", "billing_period": "monthly", "category": "category"}}
  ],
  "pricing_tiers": [
    {{"tier_name": "Basic", "price": "$10/month", "price_numeric": 10, "currency": "USD", "billing_period": "monthly", "features": ["feature 1", "feature 2"]}}
  ],
  "industry": "specific_industry",
  "target_market": "who they sell to"
}}
""")

        try:
            # Use OpenAI directly for better extraction (bypass OpenRouter for this)
            from openai import OpenAI
            openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

            response = openai_client.chat.completions.create(
                model="gpt-4o",  # Use stronger model for accurate extraction
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at extracting product and pricing information from websites. Always return valid JSON only. Be specific and accurate - extract actual product names and prices."
                    },
                    {
                        "role": "user",
                        "content": products_prompt.format(url=url, domain=domain, content=content[:30000])
                    }
                ],
                temperature=0.1,
                max_tokens=3000
            )

            products_response = response.choices[0].message.content.strip()
            products_response = self._clean_json_response(products_response)
            data = json.loads(products_response)

            # Validate and normalize products
            valid_products = []
            for i, product in enumerate(data.get("products", [])):
                if isinstance(product, dict) and product.get("name"):
                    valid_products.append({
                        "id": i + 1,
                        "name": product.get("name", ""),
                        "description": product.get("description", ""),
                        "price": product.get("price", "Contact for quote"),
                        "price_numeric": float(product.get("price_numeric", 0)) if product.get("price_numeric") else 0,
                        "currency": product.get("currency", "USD"),
                        "billing_period": product.get("billing_period"),
                        "category": product.get("category", "General"),
                        "sku": f"SKU-{i+1:04d}"
                    })

            # Validate services
            valid_services = []
            for i, service in enumerate(data.get("services", [])):
                if isinstance(service, dict) and service.get("name"):
                    valid_services.append({
                        "id": i + 1,
                        "name": service.get("name", ""),
                        "description": service.get("description", ""),
                        "price": service.get("price", "Contact for quote"),
                        "price_numeric": float(service.get("price_numeric", 0)) if service.get("price_numeric") else 0,
                        "currency": service.get("currency", "USD"),
                        "billing_period": service.get("billing_period"),
                        "category": service.get("category", "General")
                    })

            # Validate pricing tiers
            valid_tiers = []
            for i, tier in enumerate(data.get("pricing_tiers", [])):
                if isinstance(tier, dict) and tier.get("tier_name"):
                    valid_tiers.append({
                        "id": i + 1,
                        "tier_name": tier.get("tier_name", ""),
                        "price": tier.get("price", "Contact for quote"),
                        "price_numeric": float(tier.get("price_numeric", 0)) if tier.get("price_numeric") else 0,
                        "currency": tier.get("currency", "USD"),
                        "billing_period": tier.get("billing_period"),
                        "features": tier.get("features", [])
                    })

            logger.info(f"[StoreScrapingAgent] Extracted {len(valid_products)} products, {len(valid_services)} services, {len(valid_tiers)} pricing tiers")

            return {
                "products": valid_products,
                "services": valid_services,
                "pricing_tiers": valid_tiers,
                "industry": data.get("industry", "general"),
                "target_market": data.get("target_market", ""),
                "total_products": len(valid_products),
                "total_services": len(valid_services),
                "total_tiers": len(valid_tiers),
                "source_url": url,
                "message": f"Successfully extracted {len(valid_products)} products, {len(valid_services)} services, {len(valid_tiers)} pricing tiers"
            }

        except Exception as e:
            logger.error(f"[StoreScrapingAgent] Products extraction error: {e}")
            return {
                "products": [],
                "services": [],
                "pricing_tiers": [],
                "industry": "general",
                "target_market": "",
                "total_products": 0,
                "total_services": 0,
                "total_tiers": 0,
                "source_url": url,
                "message": f"Failed to extract products: {str(e)}"
            }

    def _apply_defaults(self, store_data: Dict[str, Any], url: str, domain: str) -> Dict[str, Any]:
        """Apply default values for missing fields."""
        result = store_data.copy()

        # Store name default — use domain name only as last resort
        if not result.get("store_name"):
            domain_name = domain.split('.')[0].replace('-', ' ').replace('_', ' ').title()
            result["store_name"] = domain_name

        # Store tone default and validation
        valid_tones = ["friendly", "professional", "luxury", "modern", "traditional", "playful", "minimalist", "eco_friendly"]
        if not result.get("store_tone") or result.get("store_tone") not in valid_tones:
            result["store_tone"] = "professional"

        # Color theme default
        if not result.get("color_theme"):
            result["color_theme"] = "#3B82F6"

        # Business type — use industry from brand analysis if available, never leave as "Business"
        if not result.get("business_type") or result.get("business_type") == "Business":
            # Try to infer from services
            services = result.get("services_products")
            if isinstance(services, list) and services:
                first_service = services[0]
                cat = first_service.get("category", "") if isinstance(first_service, dict) else ""
                if cat:
                    result["business_type"] = cat
            elif isinstance(services, str) and services:
                result["business_type"] = services.split(",")[0].strip()
            else:
                result["business_type"] = "Business"

        # Brand style default
        if not result.get("brand_style"):
            result["brand_style"] = None

        # Generate store_link from store name
        if result.get("store_name"):
            store_link = re.sub(r'[^a-z0-9]+', '-', result["store_name"].lower())
            result["store_link"] = store_link.strip('-')[:30]

        return result

    def _generate_fallback_data(self, url: str) -> Dict[str, Any]:
        """Generate fallback data when scraping fails."""
        domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
        domain_name = domain.split('.')[0].capitalize()
        store_link = re.sub(r'[^a-z0-9]+', '-', domain_name.lower()).strip('-')[:30]

        return {
            "store_name": f"{domain_name} Store",
            "store_email": None,
            "store_phone": None,
            "store_voice": f"Welcome to {domain_name}. We provide quality products and services tailored to your needs.",
            "store_tone": "professional",
            "store_link": store_link,
            "services_products": "Products, Services",
            "color_theme": "#3B82F6",
            "business_type": "Business",
            "logo_url": None,
            "faqs": []
        }


# Convenience function for direct use
def scrape_store_website(url: str) -> Dict[str, Any]:
    """
    Scrape a website and extract store information.

    Args:
        url: Website URL to scrape

    Returns:
        Dict containing store info, FAQs, and metadata
    """
    agent = StoreScrapingAgent()
    return agent.extract_store_info_sync(url)

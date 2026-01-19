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

# Import LangChain components
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

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

        # Initialize LLM via OpenRouter or OpenAI
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o-mini" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.2
        )
        logger.info(f"[StoreScrapingAgent] LLM initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

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

6. services_products: List the main products/services offered (comma-separated)
   - Look at navigation menu, product categories, services listed
   - Be specific, not generic

7. color_theme: The PRIMARY brand color as hex code
   - Pick a color that fits the brand/industry
   - Common examples: Blue=#2563EB, Green=#16A34A, Red=#DC2626

8. business_type: Describe the business in 2-4 words
   - Examples: "Coffee Shop", "Athletic Apparel", "SaaS Platform", "Security Services"

WEBSITE CONTENT:
{content}

CRITICAL RULES:
- ONLY extract information that ACTUALLY APPEARS in the content above
- If you cannot find an email/phone, use null - DO NOT INVENT ONE
- Return ONLY valid JSON, no markdown or explanation

JSON FORMAT:
{{"store_name": "...", "store_email": "...", "store_phone": "...", "store_voice": "...", "store_tone": "...", "services_products": "...", "color_theme": "#...", "business_type": "..."}}
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
                '/pricing', '/prices', '/rates',
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

    def _extract_emails_from_content(self, content: str, domain: str) -> List[str]:
        """
        Extract emails directly from content using regex.
        Prioritizes emails from the same domain.
        """
        emails = self.EMAIL_PATTERN.findall(content)
        if not emails:
            return []

        # Filter out common non-business emails
        excluded_patterns = ['example.com', 'test.com', 'email.com', 'domain.com',
                            'yourcompany', 'yourdomain', 'company.com', 'noreply',
                            'no-reply', 'donotreply', 'wix.com', 'wordpress']
        filtered_emails = [
            e for e in emails
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
        return filtered_emails[:5]  # Return top 5

    def _extract_phones_from_content(self, content: str) -> List[str]:
        """
        Extract phone numbers directly from content using regex patterns.
        Returns cleaned and deduplicated phone numbers.
        """
        phones = []
        for pattern in self.PHONE_PATTERNS:
            matches = pattern.findall(content)
            for match in matches:
                # Clean the phone number
                if isinstance(match, tuple):
                    match = match[0] if match else ''
                phone = re.sub(r'[^\d+\-\s()]', '', str(match)).strip()
                if len(phone) >= 7:  # Minimum valid phone length
                    phones.append(phone)

        # Deduplicate while preserving order
        seen = set()
        unique_phones = []
        for phone in phones:
            # Normalize for comparison (remove spaces/dashes)
            normalized = re.sub(r'[\s\-()]', '', phone)
            if normalized not in seen and len(normalized) >= 7:
                seen.add(normalized)
                unique_phones.append(phone)

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

        # Logo detection patterns (ordered by priority)
        logo_patterns = [
            r'logo', r'brand', r'icon', r'favicon', r'header[-_]?img',
            r'site[-_]?logo', r'company[-_]?logo', r'main[-_]?logo'
        ]

        # First pass: look for explicit logo patterns in URL
        for img_url in image_urls:
            img_lower = img_url.lower()
            for pattern in logo_patterns:
                if re.search(pattern, img_lower):
                    logger.info(f"[StoreScrapingAgent] Found logo via pattern '{pattern}': {img_url[:80]}")
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

        if not scraped_data.get("content"):
            logger.warning("[StoreScrapingAgent] No content scraped, returning fallback")
            return self._generate_fallback_data(url)

        domain = scraped_data.get("domain", "")
        content = scraped_data.get("content", "")
        images = scraped_data.get("images", [])

        # Step 2: DIRECT EXTRACTION - Extract emails and phones using regex (reliable)
        logger.info("[StoreScrapingAgent] Extracting contact info directly from content...")
        direct_emails = self._extract_emails_from_content(content, domain)
        direct_phones = self._extract_phones_from_content(content)

        logger.info(f"[StoreScrapingAgent] Direct extraction found: {len(direct_emails)} emails, {len(direct_phones)} phones")
        if direct_emails:
            logger.info(f"[StoreScrapingAgent] Best email: {direct_emails[0]}")
        if direct_phones:
            logger.info(f"[StoreScrapingAgent] Best phone: {direct_phones[0]}")

        # Step 3: AI EXTRACTION - Extract store info using AI
        logger.info("[StoreScrapingAgent] Extracting store information with AI...")
        try:
            store_chain = self.store_info_prompt | self.llm | StrOutputParser()
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
            store_data = {}

        # Step 4: MERGE RESULTS - Direct extraction takes priority for contact info
        # Direct regex extraction is more reliable for emails/phones
        if direct_emails:
            store_data["store_email"] = direct_emails[0]
            logger.info(f"[StoreScrapingAgent] Using direct-extracted email: {direct_emails[0]}")
        elif not store_data.get("store_email"):
            store_data["store_email"] = None

        if direct_phones:
            # Join multiple phones if found
            store_data["store_phone"] = ", ".join(direct_phones[:3]) if len(direct_phones) > 1 else direct_phones[0]
            logger.info(f"[StoreScrapingAgent] Using direct-extracted phone: {store_data['store_phone']}")
        elif not store_data.get("store_phone"):
            store_data["store_phone"] = None

        # Step 5: Extract FAQs using AI
        logger.info("[StoreScrapingAgent] Extracting FAQs with AI...")
        try:
            faq_chain = self.faq_prompt | self.llm | StrOutputParser()
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
        Extract products/services from a website.
        Returns a list of products with name, description, price, and category.
        """
        logger.info(f"[StoreScrapingAgent] Starting products extraction for: {url}")

        # Step 1: Scrape website content
        scraped_data = self._scrape_website(url)

        if not scraped_data.get("content"):
            logger.warning("[StoreScrapingAgent] No content scraped for products")
            return {"products": [], "message": "Could not scrape website content"}

        domain = scraped_data.get("domain", "")
        content = scraped_data.get("content", "")

        # Products extraction prompt
        products_prompt = ChatPromptTemplate.from_template("""
You are an expert at extracting products and services from website content.

TASK: Extract ALL products, services, or packages mentioned on this website.

Website URL: {url}
Domain: {domain}

CONTENT:
{content}

EXTRACT products/services with these fields:
- name: Product or service name (required)
- description: Short description (1-2 sentences)
- price: Price as a number (0 if not found, extract from USD, ZAR, ZWL, etc.)
- currency: Currency code (USD, ZAR, ZWL, etc.) - default to USD if unclear
- category: Product category (e.g., "Security Services", "Electronics", "Consulting")
- image_url: Product image URL if found

IMPORTANT:
- Extract ACTUAL products/services from the content, not placeholders
- For service-based businesses, extract service packages/tiers
- Include pricing if mentioned (monthly, yearly, per unit)
- If no specific price, set price to 0
- Maximum 20 products

Return a JSON array of products:
[
    {{"name": "Product Name", "description": "Description", "price": 99.99, "currency": "USD", "category": "Category", "image_url": null}},
    ...
]

Return ONLY the JSON array, no other text.
""")

        try:
            products_chain = products_prompt | self.llm | StrOutputParser()
            products_response = await products_chain.ainvoke({
                "url": url,
                "domain": domain,
                "content": content[:25000]
            })

            products_response = self._clean_json_response(products_response)
            products = json.loads(products_response)

            # Validate and normalize products
            valid_products = []
            for i, product in enumerate(products):
                if isinstance(product, dict) and product.get("name"):
                    valid_products.append({
                        "id": i + 1,
                        "name": product.get("name", "Unnamed Product"),
                        "description": product.get("description", ""),
                        "price": float(product.get("price", 0)) if product.get("price") else 0,
                        "currency": product.get("currency", "USD"),
                        "category": product.get("category", "General"),
                        "image_url": product.get("image_url"),
                        "sku": f"SKU-{i+1:04d}"
                    })

            logger.info(f"[StoreScrapingAgent] Extracted {len(valid_products)} products")

            return {
                "products": valid_products,
                "total": len(valid_products),
                "source_url": url,
                "message": f"Successfully extracted {len(valid_products)} products/services"
            }

        except Exception as e:
            logger.error(f"[StoreScrapingAgent] Products extraction error: {e}")
            return {
                "products": [],
                "total": 0,
                "source_url": url,
                "message": f"Failed to extract products: {str(e)}"
            }

    def _apply_defaults(self, store_data: Dict[str, Any], url: str, domain: str) -> Dict[str, Any]:
        """Apply default values for missing fields."""
        result = store_data.copy()

        # Store name default
        if not result.get("store_name"):
            domain_name = domain.split('.')[0].capitalize()
            result["store_name"] = domain_name

        # Store tone default and validation
        valid_tones = ["friendly", "professional", "luxury", "modern", "traditional", "playful", "minimalist", "eco_friendly"]
        if not result.get("store_tone") or result.get("store_tone") not in valid_tones:
            result["store_tone"] = "professional"

        # Color theme default
        if not result.get("color_theme"):
            result["color_theme"] = "#3B82F6"

        # Business type default
        if not result.get("business_type"):
            result["business_type"] = "Business"

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

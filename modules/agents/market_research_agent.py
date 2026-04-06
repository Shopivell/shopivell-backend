# market_research_agent.py - AI Agent for Market Research
"""
Enhanced Market Research Agent that performs REAL research:
1. Scrapes the actual website using Tavily with DEEP extraction
2. Extracts structured data (navigation, services, contacts, partners)
3. Searches for real competitors
4. Finds actual industry trends
5. Provides data-driven insights
6. Supports multi-page scraping for comprehensive analysis

Improvements over v1:
- Deep website structure extraction (navigation, services, products)
- Contact information extraction (email, phone, address, social media)
- Partner/member list extraction
- Statistics and metrics extraction
- Leadership/team information extraction
- Multi-page scraping capability
- Structured data (JSON-LD, Open Graph) extraction
- Better error handling with retries
"""

import os
import json
import logging
import re
import asyncio
import hashlib
import requests
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from database import SessionLocal
from .models import Campaign, MarketResearch

# Set up logger early so it can be used in import blocks
logger = logging.getLogger(__name__)

# Import BeautifulSoup for fallback scraping
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None

# Import Tavily for web research
try:
    from tavily import TavilyClient
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    TAVILY_AVAILABLE = bool(tavily_api_key)
except ImportError:
    TAVILY_AVAILABLE = False
    tavily_api_key = None

# Import screenshot and scraping functions from stores module (optional enhancement)
try:
    from modules.stores.scraping_service import (
        capture_homepage_screenshot_sync,
        analyze_brand_from_screenshot_sync,
        extract_store_info_from_website,
        PLAYWRIGHT_AVAILABLE,
        GEMINI_AVAILABLE
    )
    SCREENSHOT_AVAILABLE = PLAYWRIGHT_AVAILABLE
    STORE_SCRAPING_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False
    GEMINI_AVAILABLE = False
    STORE_SCRAPING_AVAILABLE = False
    capture_homepage_screenshot_sync = None
    analyze_brand_from_screenshot_sync = None
    extract_store_info_from_website = None

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

# Import Redis cache
from utils.cache import RedisCache, CacheConfig, generate_cache_key

load_dotenv()


# Regex patterns for extracting structured data
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_PATTERN = re.compile(
    r'(?<![v\d.])[\+]?[(]?[0-9]{1,4}[)]?[-\s.]?[(]?[0-9]{2,4}[)]?[-\s.]?[0-9]{3,4}[-\s.]?[0-9]{3,9}(?![.\d])'
)


def _validate_phone(phone: str) -> bool:
    """Validate a phone match has at least 7 digits (filters out version numbers, dates, etc.)"""
    digits = re.sub(r'\D', '', phone)
    return len(digits) >= 7
SOCIAL_PATTERNS = {
    'facebook': re.compile(r'(?:https?://)?(?:www\.)?facebook\.com/[a-zA-Z0-9._-]+', re.IGNORECASE),
    'twitter': re.compile(r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+', re.IGNORECASE),
    'linkedin': re.compile(r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+', re.IGNORECASE),
    'instagram': re.compile(r'(?:https?://)?(?:www\.)?instagram\.com/[a-zA-Z0-9._]+', re.IGNORECASE),
    'youtube': re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/(?:c/|channel/|user/)?[a-zA-Z0-9_-]+', re.IGNORECASE),
}


class MarketResearchAgent:
    """AI Agent for conducting comprehensive market research with REAL data"""

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o-mini" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.3
        )
        self.embeddings = OpenAIEmbeddings()
        self.tavily = TavilyClient(api_key=tavily_api_key) if TAVILY_AVAILABLE else None
        self.cache = RedisCache()
        logger.info(f"[MarketResearchAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}, Tavily: {TAVILY_AVAILABLE}, Cache: {self.cache.is_connected}")

    def _validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validate a URL before attempting to scrape it.
        Checks format and reachability via a lightweight HEAD request.

        Args:
            url: The URL to validate

        Returns:
            (is_valid, final_url) - final_url accounts for redirects
        """
        # Check URL format
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            logger.warning(f"[MarketResearchAgent] Invalid URL format: {url}")
            return False, url

        if parsed.scheme not in ('http', 'https'):
            logger.warning(f"[MarketResearchAgent] Unsupported URL scheme: {parsed.scheme}")
            return False, url

        # Check reachability with HEAD request
        try:
            response = requests.head(
                url,
                timeout=10,
                allow_redirects=True,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            final_url = response.url
            # Accept any 2xx or 3xx status, and some servers return 405 for HEAD
            if response.status_code < 500:
                return True, final_url
            else:
                logger.warning(f"[MarketResearchAgent] URL returned status {response.status_code}: {url}")
                return False, url
        except requests.exceptions.RequestException as e:
            logger.warning(f"[MarketResearchAgent] URL unreachable: {url} - {e}")
            return False, url

    def _extract_contact_info(self, content: str) -> Dict[str, Any]:
        """Extract contact information from website content"""
        contacts = {
            "emails": list(set(EMAIL_PATTERN.findall(content))),
            "phones": [p for p in set(PHONE_PATTERN.findall(content)) if _validate_phone(p)],
            "social_media": {}
        }

        # Extract social media links
        for platform, pattern in SOCIAL_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                contacts["social_media"][platform] = list(set(matches))

        # Filter out common false positives for emails
        contacts["emails"] = [
            email for email in contacts["emails"]
            if not any(x in email.lower() for x in ['example.com', 'test.com', 'domain.com', '.png', '.jpg', '.gif'])
        ]

        return contacts

    def _extract_statistics(self, content: str) -> List[Dict[str, str]]:
        """Extract statistics and metrics from website content"""
        stats = []

        # Common patterns for statistics
        stat_patterns = [
            r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*\+?\s*(members?|users?|customers?|clients?|partners?)',
            r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*\+?\s*(locations?|branches?|offices?|stores?)',
            r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*\+?\s*(ATMs?|terminals?|machines?|devices?)',
            r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*\+?\s*(transactions?|payments?)',
            r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*%\s*(accuracy|uptime|satisfaction|growth)',
            r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*\+?\s*years?\s*(experience|operation|service)',
        ]

        for pattern in stat_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                if len(match) >= 2:
                    stats.append({
                        "value": match[0],
                        "metric": match[1].lower()
                    })

        return stats

    def _scrape_with_beautifulsoup(self, url: str, retries: int = 2) -> Dict[str, Any]:
        """
        Fallback scraper using BeautifulSoup when Tavily fails.
        Extracts text content, links, and metadata from the website.
        Includes retry logic and flexible SSL handling for production servers.
        """
        if not BS4_AVAILABLE:
            logger.warning("[MarketResearchAgent] BeautifulSoup not available - bs4 not installed")
            return {"content": "", "error": "BeautifulSoup not available", "success": False}

        last_error = None

        for attempt in range(retries + 1):
            try:
                logger.info(f"[MarketResearchAgent] BeautifulSoup scraping attempt {attempt + 1}/{retries + 1}: {url}")

                # Request the page with a browser-like user agent
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                }

                # Try with SSL verification first, then without on retry
                verify_ssl = attempt == 0

                response = requests.get(
                    url,
                    headers=headers,
                    timeout=45,  # Longer timeout for slow servers
                    verify=verify_ssl,
                    allow_redirects=True
                )
                response.raise_for_status()

                logger.info(f"[MarketResearchAgent] BeautifulSoup got response: {response.status_code}, {len(response.text)} chars")

                soup = BeautifulSoup(response.text, 'html.parser')

                # Remove script and style elements
                for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
                    element.decompose()

                # Extract metadata
                title = soup.title.string if soup.title else ""
                meta_desc = ""
                meta_keywords = ""

                for meta in soup.find_all('meta'):
                    if meta.get('name', '').lower() == 'description':
                        meta_desc = meta.get('content', '')
                    if meta.get('name', '').lower() == 'keywords':
                        meta_keywords = meta.get('content', '')

                # Extract main content
                content_parts = []

                # Add title and meta
                if title:
                    content_parts.append(f"# {title}")
                if meta_desc:
                    content_parts.append(f"Description: {meta_desc}")

                # Extract headings
                for heading in soup.find_all(['h1', 'h2', 'h3']):
                    text = heading.get_text(strip=True)
                    if text and len(text) > 2:
                        level = heading.name
                        prefix = "#" * int(level[1])
                        content_parts.append(f"{prefix} {text}")

                # Extract paragraphs
                for p in soup.find_all('p'):
                    text = p.get_text(strip=True)
                    if text and len(text) > 20:
                        content_parts.append(text)

                # Extract list items
                for li in soup.find_all('li'):
                    text = li.get_text(strip=True)
                    if text and len(text) > 10:
                        content_parts.append(f"• {text}")

                # Extract links for navigation structure
                nav_links = []
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '')
                    text = a.get_text(strip=True)
                    if text and len(text) > 2 and len(text) < 50:
                        if href.startswith('/') or href.startswith(url):
                            nav_links.append(text)

                if nav_links:
                    content_parts.append(f"\nNavigation: {', '.join(list(set(nav_links))[:20])}")

                # Extract contact information from the page
                page_text = soup.get_text()

                # Find emails
                emails = list(set(EMAIL_PATTERN.findall(page_text)))
                emails = [e for e in emails if not any(x in e.lower() for x in ['example.com', 'test.com', '.png', '.jpg'])]

                # Find phones
                phones = [p for p in set(PHONE_PATTERN.findall(page_text)) if _validate_phone(p)]

                # Find social media links
                social_media = {}
                for platform, pattern in SOCIAL_PATTERNS.items():
                    matches = pattern.findall(response.text)
                    if matches:
                        social_media[platform] = list(set(matches))

                # Combine content
                content = "\n\n".join(content_parts)

                logger.info(f"[MarketResearchAgent] BeautifulSoup extracted {len(content)} chars, {len(emails)} emails, {len(phones)} phones")

                return {
                    "content": content[:15000],
                    "url": url,
                    "success": True,
                    "contact_info": {
                        "emails": emails[:10],
                        "phones": phones[:10],
                        "social_media": social_media
                    },
                    "statistics": self._extract_statistics(content),
                    "source": "beautifulsoup"
                }

            except requests.exceptions.SSLError as e:
                last_error = f"SSL Error: {str(e)}"
                logger.warning(f"[MarketResearchAgent] BeautifulSoup SSL error (attempt {attempt + 1}): {e}")
                continue  # Retry without SSL verification

            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {str(e)}"
                logger.warning(f"[MarketResearchAgent] BeautifulSoup timeout (attempt {attempt + 1}): {e}")
                continue  # Retry

            except requests.exceptions.RequestException as e:
                last_error = f"Request failed: {str(e)}"
                logger.error(f"[MarketResearchAgent] BeautifulSoup request error (attempt {attempt + 1}): {e}")
                continue  # Retry

            except Exception as e:
                last_error = str(e)
                logger.error(f"[MarketResearchAgent] BeautifulSoup scrape error (attempt {attempt + 1}): {e}")
                break  # Don't retry on parsing errors

        # All retries exhausted
        logger.error(f"[MarketResearchAgent] BeautifulSoup failed after {retries + 1} attempts: {last_error}")
        return {"content": "", "error": last_error, "success": False}

    def _scrape_website(self, url: str) -> Dict[str, Any]:
        """Scrape the target website to understand the business"""
        # Validate URL upfront
        is_valid, final_url = self._validate_url(url)
        if not is_valid:
            return {"content": "", "error": f"Invalid or unreachable URL: {url}", "success": False}
        url = final_url  # Use the final URL after redirects

        # Check cache first
        cache_key = generate_cache_key(url, prefix="mra:scrape:")
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"[MarketResearchAgent] Cache HIT for scrape: {url}")
            return cached_result

        content = ""

        # Try Tavily first
        if self.tavily:
            try:
                logger.info(f"[MarketResearchAgent] Scraping website with Tavily: {url}")
                extract_result = self.tavily.extract(urls=[url])

                if extract_result and extract_result.get("results"):
                    content = extract_result["results"][0].get("raw_content", "")
                    logger.info(f"[MarketResearchAgent] Tavily extracted {len(content)} chars")

            except Exception as e:
                logger.error(f"[MarketResearchAgent] Tavily scrape error: {e}")

        # Fallback to store scraping service if Tavily failed or returned empty
        if not content and STORE_SCRAPING_AVAILABLE and extract_store_info_from_website:
            try:
                logger.info(f"[MarketResearchAgent] Falling back to store scraping service: {url}")
                store_data = extract_store_info_from_website(url, capture_screenshot=True, analyze_brand=False)

                if store_data and store_data.get("success"):
                    # Build content from store data
                    content_parts = []
                    if store_data.get("name"):
                        content_parts.append(f"Company: {store_data['name']}")
                    if store_data.get("description"):
                        content_parts.append(f"Description: {store_data['description']}")
                    if store_data.get("services"):
                        content_parts.append(f"Services: {', '.join(store_data['services'])}")
                    if store_data.get("products"):
                        for prod in store_data.get("products", [])[:10]:
                            if isinstance(prod, dict):
                                content_parts.append(f"Product: {prod.get('name', '')} - {prod.get('description', '')}")
                    if store_data.get("faqs"):
                        for faq in store_data.get("faqs", [])[:5]:
                            if isinstance(faq, dict):
                                content_parts.append(f"FAQ: {faq.get('question', '')} - {faq.get('answer', '')}")

                    content = "\n".join(content_parts)
                    logger.info(f"[MarketResearchAgent] Store scraping extracted {len(content)} chars")

                    # Return with store data contact info
                    result = {
                        "content": content[:15000],
                        "url": url,
                        "success": True,
                        "contact_info": {
                            "emails": store_data.get("email", []) if isinstance(store_data.get("email"), list) else [store_data.get("email")] if store_data.get("email") else [],
                            "phones": store_data.get("phone", []) if isinstance(store_data.get("phone"), list) else [store_data.get("phone")] if store_data.get("phone") else [],
                            "social_media": store_data.get("social_media", {})
                        },
                        "statistics": [],
                        "screenshot_url": store_data.get("screenshot_url"),
                        "source": "store_scraping_service"
                    }
                    self.cache.set(cache_key, result, ttl=CacheConfig.TTL_LONG)
                    return result

            except Exception as e:
                logger.error(f"[MarketResearchAgent] Store scraping fallback error: {e}")

        # If we got content from Tavily, process it
        if content:
            contact_info = self._extract_contact_info(content)
            statistics = self._extract_statistics(content)

            result = {
                "content": content[:15000],
                "url": url,
                "success": True,
                "contact_info": contact_info,
                "statistics": statistics,
                "source": "tavily"
            }
            self.cache.set(cache_key, result, ttl=CacheConfig.TTL_LONG)
            return result

        # Fallback to BeautifulSoup if all else fails
        if not content and BS4_AVAILABLE:
            logger.info(f"[MarketResearchAgent] Falling back to BeautifulSoup scraper: {url}")
            bs_result = self._scrape_with_beautifulsoup(url)
            if bs_result.get("success") and bs_result.get("content"):
                self.cache.set(cache_key, bs_result, ttl=CacheConfig.TTL_LONG)
                return bs_result

        # No content from any source
        logger.warning(f"[MarketResearchAgent] No content extracted from any source for: {url}")
        return {"content": "", "error": "No content extracted from any source", "success": False}

    def _discover_internal_links(self, base_url: str) -> List[str]:
        """
        Discover internal links by scraping the homepage HTML.
        Prioritizes pages with relevant keywords (about, service, product, etc.).

        Returns:
            List of discovered internal URLs, prioritized by relevance.
        """
        priority_keywords = [
            "about", "service", "product", "team", "contact",
            "pricing", "solution", "partner", "leadership", "portfolio"
        ]

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
            response = requests.get(base_url, headers=headers, timeout=15, allow_redirects=True)
            response.raise_for_status()

            if not BS4_AVAILABLE:
                return []

            soup = BeautifulSoup(response.text, 'html.parser')
            parsed_base = urlparse(base_url)
            base_domain = parsed_base.netloc

            discovered = set()
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)

                # Only same-domain links
                if parsed.netloc != base_domain:
                    continue
                # Skip anchors, javascript, mailto, etc.
                if parsed.scheme not in ('http', 'https'):
                    continue
                # Skip files (images, PDFs, etc.)
                path_lower = parsed.path.lower()
                if any(path_lower.endswith(ext) for ext in ('.pdf', '.jpg', '.png', '.gif', '.svg', '.css', '.js', '.zip')):
                    continue

                # Normalize: strip fragment and trailing slash
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
                if clean_url and clean_url != base_url.rstrip('/'):
                    discovered.add(clean_url)

            # Sort: priority keyword links first, then the rest
            priority_links = []
            other_links = []
            for link in discovered:
                path_lower = urlparse(link).path.lower()
                if any(kw in path_lower for kw in priority_keywords):
                    priority_links.append(link)
                else:
                    other_links.append(link)

            logger.info(f"[MarketResearchAgent] Discovered {len(priority_links)} priority + {len(other_links)} other internal links")
            return priority_links + other_links

        except Exception as e:
            logger.warning(f"[MarketResearchAgent] Link discovery failed: {e}")
            return []

    def _scrape_multiple_pages(self, base_url: str, subpages: List[str] = None) -> Dict[str, Any]:
        """
        Scrape multiple pages from a website for comprehensive analysis.
        Uses Tavily first, falls back to BeautifulSoup if Tavily fails.
        Dynamically discovers internal links from the homepage when no subpages are provided.

        Args:
            base_url: The main website URL
            subpages: List of subpage paths to scrape (e.g., ['/about', '/services', '/contact'])
        """
        # Validate URL upfront
        is_valid, final_url = self._validate_url(base_url)
        if not is_valid:
            return {
                "pages": [], "combined_content": "",
                "all_contacts": {"emails": [], "phones": [], "social_media": {}},
                "all_statistics": [], "success_count": 0, "source": "none",
                "error": f"Invalid or unreachable URL: {base_url}"
            }
        base_url = final_url

        # Default subpages: try dynamic discovery first, fall back to hardcoded list
        hardcoded_subpages = [
            '', '/about', '/about-us', '/services', '/products',
            '/solutions', '/contact', '/contact-us', '/partners',
            '/team', '/leadership', '/pricing'
        ]

        if subpages is None:
            discovered_links = self._discover_internal_links(base_url)
            if discovered_links:
                # Use discovered links (homepage + discovered, up to 8)
                urls_to_scrape = [base_url.rstrip('/')]
                for link in discovered_links:
                    if link not in urls_to_scrape and len(urls_to_scrape) < 8:
                        urls_to_scrape.append(link)
                logger.info(f"[MarketResearchAgent] Using {len(urls_to_scrape)} dynamically discovered URLs")
            else:
                subpages = hardcoded_subpages
                logger.info(f"[MarketResearchAgent] Link discovery failed, using hardcoded subpages")

        results = {
            "pages": [],
            "combined_content": "",
            "all_contacts": {"emails": [], "phones": [], "social_media": {}},
            "all_statistics": [],
            "success_count": 0,
            "source": "none"
        }

        parsed_base = urlparse(base_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

        # Build URL list from subpages if not already built by discovery
        if subpages is not None:
            urls_to_scrape = []
            for subpage in subpages[:8]:  # Limit to 8 pages to avoid rate limits
                full_url = urljoin(base_domain, subpage)
                if full_url not in urls_to_scrape:
                    urls_to_scrape.append(full_url)

        # Try Tavily first
        tavily_success = False
        if self.tavily:
            try:
                logger.info(f"[MarketResearchAgent] Scraping {len(urls_to_scrape)} pages with Tavily from {base_domain}")

                extract_result = self.tavily.extract(urls=urls_to_scrape)

                if extract_result and extract_result.get("results"):
                    for page_result in extract_result["results"]:
                        content = page_result.get("raw_content", "")
                        page_url = page_result.get("url", "")

                        if content:
                            tavily_success = True
                            results["pages"].append({
                                "url": page_url,
                                "content": content[:5000],
                                "success": True
                            })
                            results["combined_content"] += f"\n\n--- PAGE: {page_url} ---\n{content[:5000]}"
                            results["success_count"] += 1
                            results["source"] = "tavily"

                            # Aggregate contacts
                            page_contacts = self._extract_contact_info(content)
                            results["all_contacts"]["emails"].extend(page_contacts["emails"])
                            results["all_contacts"]["phones"].extend(page_contacts["phones"])
                            for platform, links in page_contacts["social_media"].items():
                                if platform not in results["all_contacts"]["social_media"]:
                                    results["all_contacts"]["social_media"][platform] = []
                                results["all_contacts"]["social_media"][platform].extend(links)

                            # Aggregate statistics
                            page_stats = self._extract_statistics(content)
                            results["all_statistics"].extend(page_stats)

            except Exception as e:
                logger.error(f"[MarketResearchAgent] Tavily multi-page scrape error: {e}")

        # Fallback to BeautifulSoup if Tavily failed
        if not tavily_success and BS4_AVAILABLE:
            logger.info(f"[MarketResearchAgent] Falling back to BeautifulSoup for multi-page scrape")
            results["source"] = "beautifulsoup"

            for page_url in urls_to_scrape[:5]:  # Limit to 5 pages for BeautifulSoup
                try:
                    bs_result = self._scrape_with_beautifulsoup(page_url)
                    if bs_result.get("success") and bs_result.get("content"):
                        results["pages"].append({
                            "url": page_url,
                            "content": bs_result["content"][:5000],
                            "success": True
                        })
                        results["combined_content"] += f"\n\n--- PAGE: {page_url} ---\n{bs_result['content'][:5000]}"
                        results["success_count"] += 1

                        # Aggregate contacts
                        if bs_result.get("contact_info"):
                            results["all_contacts"]["emails"].extend(bs_result["contact_info"].get("emails", []))
                            results["all_contacts"]["phones"].extend(bs_result["contact_info"].get("phones", []))
                            for platform, links in bs_result["contact_info"].get("social_media", {}).items():
                                if platform not in results["all_contacts"]["social_media"]:
                                    results["all_contacts"]["social_media"][platform] = []
                                results["all_contacts"]["social_media"][platform].extend(links)

                        # Aggregate statistics
                        if bs_result.get("statistics"):
                            results["all_statistics"].extend(bs_result["statistics"])

                except Exception as e:
                    logger.error(f"[MarketResearchAgent] BeautifulSoup error for {page_url}: {e}")

        # Deduplicate
        results["all_contacts"]["emails"] = list(set(results["all_contacts"]["emails"]))
        results["all_contacts"]["phones"] = list(set(results["all_contacts"]["phones"]))
        for platform in results["all_contacts"]["social_media"]:
            results["all_contacts"]["social_media"][platform] = list(set(results["all_contacts"]["social_media"][platform]))

        return results

    async def _extract_structured_website_data(self, content: str, url: str) -> Dict[str, Any]:
        """
        Use AI to extract structured data from website content.
        Extracts: navigation, services, products, partners, leadership, value propositions
        """
        # Check cache keyed by content hash
        content_hash = hashlib.md5(content[:8000].encode()).hexdigest()
        cache_key = f"mra:structured:{content_hash}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"[MarketResearchAgent] Cache HIT for structured extraction: {url}")
            return cached_result

        extraction_prompt = ChatPromptTemplate.from_template("""
Analyze the following website content and extract structured information.
Return a JSON object with the extracted data.

Website URL: {url}
Website Content:
{content}

Extract and return a JSON object with these fields:
{{
    "company_name": "The company/organization name",
    "tagline": "Main tagline or slogan if present",
    "industry": "Primary industry/sector",
    "navigation_structure": [
        {{"section": "Section name", "items": ["Item 1", "Item 2"]}}
    ],
    "services_products": [
        {{"name": "Service/Product name", "description": "Brief description", "category": "Category if applicable"}}
    ],
    "value_propositions": ["Key value prop 1", "Key value prop 2"],
    "target_audiences": ["Audience segment 1", "Audience segment 2"],
    "partners_members": ["Partner/Member 1", "Partner/Member 2"],
    "leadership": [
        {{"name": "Person name", "title": "Job title", "quote": "Any quote if present"}}
    ],
    "certifications_awards": ["Certification 1", "Award 1"],
    "key_features": ["Feature 1", "Feature 2"],
    "call_to_actions": ["CTA 1", "CTA 2"],
    "pricing_info": "Any pricing information found or 'Not available'",
    "geographic_coverage": "Countries/regions served"
}}

Only include fields where you found relevant information. Be accurate and only extract what's explicitly stated.
Return ONLY valid JSON, no other text.
""")

        try:
            from modules.openrouter.context import set_ai_context
            chain = extraction_prompt | self.llm | StrOutputParser()
            with set_ai_context(agent_name="market_research"):
                result = await chain.ainvoke({
                    "url": url,
                    "content": content[:8000]  # Limit content for extraction
                })

            # Parse the JSON response
            # Clean up the response - remove markdown code blocks if present
            result = result.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            parsed = json.loads(result.strip())
            self.cache.set(cache_key, parsed, ttl=CacheConfig.TTL_LONG)
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"[MarketResearchAgent] Failed to parse structured data: {e}")
            return {}
        except Exception as e:
            logger.error(f"[MarketResearchAgent] Structured extraction error: {e}")
            return {}

    def _search_competitors(self, business_type: str, location: str, products: List[str]) -> List[Dict[str, Any]]:
        """Search for real competitors in the market using Tavily (basic)."""
        if not self.tavily:
            return []

        try:
            products_str = ", ".join(products[:3]) if products else business_type
            query = f"{business_type} companies {location} {products_str} competitors"

            cache_key = generate_cache_key(query, prefix="mra:competitors:")
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                logger.info(f"[MarketResearchAgent] Cache HIT for competitor search")
                return cached_result

            logger.info(f"[MarketResearchAgent] Searching competitors via Tavily: {query}")

            search_result = self.tavily.search(
                query=query,
                search_depth="advanced",
                max_results=10
            )

            competitors = []
            for result in search_result.get("results", []):
                competitors.append({
                    "name": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("content", "")[:500],
                    "source": "tavily"
                })

            self.cache.set(cache_key, competitors, ttl=CacheConfig.TTL_LONG)
            return competitors

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Competitor search error: {e}")
            return []

    def _search_competitors_enhanced(
        self,
        business_type: str,
        location: str,
        products: List[str],
        domain: str = None,
        country_code: str = "US"
    ) -> List[Dict[str, Any]]:
        """
        Enhanced competitor search: tries DataForSEO (deep, data-backed) first,
        falls back to Tavily (basic search) if DataForSEO is not configured.

        DataForSEO provides: actual keyword overlap, traffic estimates, competitor domains
        ranked by intersection score — far richer than a Google search.
        """
        # Try DataForSEO-backed competitive intelligence first
        if domain:
            try:
                from .competitive_intelligence_agent import CompetitiveIntelligenceAgent, DATAFORSEO_AVAILABLE
                if DATAFORSEO_AVAILABLE:
                    logger.info(f"[MarketResearchAgent] Using DataForSEO for competitor analysis: {domain}")

                    agent = CompetitiveIntelligenceAgent()

                    # Step 1: Get domain categories
                    categories = agent.get_domain_categories(domain, country_code)

                    # Step 2: Discover competitors via keyword overlap
                    ci_competitors = agent.discover_competitors(domain, country_code, limit=10)

                    if ci_competitors:
                        # Step 3: Get top competitor keywords
                        top_domains = [c["domain"] for c in ci_competitors[:5]]
                        all_keywords, top_keywords = agent.analyze_competitor_keywords(
                            top_domains, country_code
                        )

                        # Enrich with Tavily summaries
                        if self.tavily:
                            ci_competitors = agent._enrich_single_competitor(ci_competitors[0])
                            # Just enrich the top one for efficiency

                        # Format into standard competitor list
                        competitors = []
                        for comp in ci_competitors:
                            competitors.append({
                                "name": comp.get("domain", ""),
                                "url": f"https://{comp.get('domain', '')}",
                                "description": comp.get("tavily_summary", "")[:500] if comp.get("tavily_summary") else "",
                                "source": "dataforseo",
                                "organic_keywords": comp.get("organic_keywords"),
                                "organic_traffic": comp.get("organic_traffic"),
                                "intersections": comp.get("intersections"),
                                "competition_score": comp.get("competition_score")
                            })

                        # Add keyword intelligence as extra data
                        if top_keywords:
                            competitors.append({
                                "name": "__keyword_opportunities__",
                                "source": "dataforseo_keywords",
                                "keywords": [
                                    {
                                        "keyword": kw.get("keyword"),
                                        "search_volume": kw.get("search_volume"),
                                        "cpc": kw.get("cpc"),
                                        "source_domain": kw.get("source_domain")
                                    }
                                    for kw in top_keywords[:10]
                                ]
                            })

                        # Add category data
                        if categories:
                            competitors.append({
                                "name": "__business_categories__",
                                "source": "dataforseo_categories",
                                "categories": [
                                    {"category": c.get("category"), "traffic": c.get("organic_traffic")}
                                    for c in categories[:5]
                                ]
                            })

                        logger.info(
                            f"[MarketResearchAgent] DataForSEO found {len(ci_competitors)} competitors "
                            f"+ {len(top_keywords)} keyword opportunities for {domain}"
                        )

                        # Cache the result
                        cache_key = generate_cache_key(f"ci:{domain}:{country_code}", prefix="mra:competitors:")
                        self.cache.set(cache_key, competitors, ttl=CacheConfig.TTL_LONG)

                        return competitors

            except Exception as e:
                logger.warning(f"[MarketResearchAgent] DataForSEO competitor analysis failed, falling back to Tavily: {e}")

        # Fallback to basic Tavily search
        return self._search_competitors(business_type, location, products)

    def _search_industry_trends(self, industry: str, year: str = "2024") -> List[Dict[str, Any]]:
        """Search for real industry trends"""
        if not self.tavily:
            return []

        try:
            query = f"{industry} industry trends {year} market growth statistics"

            # Check cache
            cache_key = generate_cache_key(query, prefix="mra:trends:")
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                logger.info(f"[MarketResearchAgent] Cache HIT for trends search")
                return cached_result

            logger.info(f"[MarketResearchAgent] Searching trends: {query}")

            search_result = self.tavily.search(
                query=query,
                search_depth="advanced",
                max_results=8
            )

            trends = []
            for result in search_result.get("results", []):
                trends.append({
                    "title": result.get("title", ""),
                    "source": result.get("url", ""),
                    "insight": result.get("content", "")[:400]
                })

            self.cache.set(cache_key, trends, ttl=CacheConfig.TTL_LONG)
            return trends

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Trend search error: {e}")
            return []

    def _search_audience_insights(self, target_audience: str, industry: str) -> List[Dict[str, Any]]:
        """Search for audience behavior and preferences"""
        if not self.tavily:
            return []

        try:
            query = f"{target_audience} buying behavior preferences {industry} consumer insights"

            # Check cache
            cache_key = generate_cache_key(query, prefix="mra:audience:")
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                logger.info(f"[MarketResearchAgent] Cache HIT for audience search")
                return cached_result

            logger.info(f"[MarketResearchAgent] Searching audience insights: {query}")

            search_result = self.tavily.search(
                query=query,
                search_depth="advanced",
                max_results=6
            )

            insights = []
            for result in search_result.get("results", []):
                insights.append({
                    "title": result.get("title", ""),
                    "source": result.get("url", ""),
                    "insight": result.get("content", "")[:400]
                })

            self.cache.set(cache_key, insights, ttl=CacheConfig.TTL_LONG)
            return insights

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Audience search error: {e}")
            return []

    def _parse_research_response(self, response_text: str) -> Dict[str, str]:
        """Parse the AI response into structured sections"""
        sections = {
            "competitor_analysis": "",
            "audience_insights": "",
            "trend_data": "",
            "recommendations": ""
        }

        current_section = None
        current_content = []

        section_keywords = {
            "competitor": "competitor_analysis",
            "audience": "audience_insights",
            "trend": "trend_data",
            "recommendation": "recommendations"
        }

        for line in response_text.split('\n'):
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            header_found = False
            for keyword, section_key in section_keywords.items():
                if keyword.upper() in line_upper and (":" in line_stripped or line_stripped.startswith("#")):
                    if current_section and current_content:
                        sections[current_section] = '\n'.join(current_content).strip()
                    current_section = section_key
                    current_content = []
                    header_found = True
                    break

            if not header_found and current_section and line_stripped:
                if not any(kw.upper() in line_upper for kw in section_keywords.keys()):
                    current_content.append(line_stripped)
                elif ":" not in line_stripped and not line_stripped.startswith("#"):
                    current_content.append(line_stripped)

        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    async def conduct_research(
        self,
        campaign: Campaign,
        source_url: str = None,
        deep_scrape: bool = True,
        extract_structure: bool = True,
        keyword_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Conduct comprehensive market research with REAL data.

        Args:
            campaign: Campaign object with all campaign details
            source_url: Optional URL to scrape for business information
            deep_scrape: Whether to scrape multiple pages (default: True)
            extract_structure: Whether to extract structured data using AI (default: True)
            keyword_data: Optional keyword intelligence from DataForSEO/autocomplete with
                          search volume, CPC, competition, and intent clusters

        Returns:
            Dict containing research results with enhanced structured data
        """
        logger.info(f"[MarketResearchAgent] Starting enhanced research for campaign: {campaign.name}")

        # Validate URL upfront if provided
        if source_url:
            is_valid, final_url = self._validate_url(source_url)
            if not is_valid:
                logger.error(f"[MarketResearchAgent] Invalid source URL, skipping scrape: {source_url}")
                source_url = None
            else:
                source_url = final_url

        # Step 1: Scrape the website with enhanced extraction
        website_data = {}
        structured_data = {}
        multi_page_data = {}

        if source_url:
            # Basic scrape
            website_data = self._scrape_website(source_url)

            # Deep multi-page scrape if enabled
            if deep_scrape and self.tavily:
                logger.info(f"[MarketResearchAgent] Performing deep multi-page scrape")
                multi_page_data = self._scrape_multiple_pages(source_url)

            # AI-powered structured extraction if enabled
            if extract_structure and website_data.get("content"):
                logger.info(f"[MarketResearchAgent] Extracting structured data with AI")
                combined_content = website_data.get("content", "")
                if multi_page_data.get("combined_content"):
                    combined_content += "\n" + multi_page_data["combined_content"][:10000]
                structured_data = await self._extract_structured_website_data(combined_content, source_url)

        # Step 2: Extract business info from campaign or structured data
        business_type = structured_data.get("industry") or campaign.product_description or "business"
        location = structured_data.get("geographic_coverage") or "Zimbabwe"
        products = campaign.keywords or []

        # Enhance products list from structured data
        if structured_data.get("services_products"):
            for sp in structured_data["services_products"][:5]:
                if sp.get("name") and sp["name"] not in products:
                    products.append(sp["name"])

        target_audience_str = json.dumps(campaign.target_audience) if campaign.target_audience else "business professionals"

        # Enhance target audience from structured data
        if structured_data.get("target_audiences"):
            target_audience_str = ", ".join(structured_data["target_audiences"])

        # Step 3-5: Search for competitors, trends, and audience insights in parallel
        from datetime import datetime
        current_year = str(datetime.now().year)

        # Extract domain from source_url for DataForSEO-backed competitor analysis
        domain = None
        if source_url:
            parsed_url = urlparse(source_url)
            domain = parsed_url.netloc.replace("www.", "")

        # Determine country code from location
        location_upper = location.upper() if location else ""
        country_code = "US"  # Default
        country_map = {
            "ZIMBABWE": "ZW", "SOUTH AFRICA": "ZA", "BOTSWANA": "BW",
            "ZAMBIA": "ZM", "MOZAMBIQUE": "MZ", "NAMIBIA": "NA",
            "KENYA": "KE", "NIGERIA": "NG", "GHANA": "GH", "TANZANIA": "TZ",
            "UNITED STATES": "US", "UNITED KINGDOM": "GB", "CANADA": "CA",
            "AUSTRALIA": "AU", "GERMANY": "DE", "FRANCE": "FR", "INDIA": "IN"
        }
        for country_name, code in country_map.items():
            if country_name in location_upper:
                country_code = code
                break

        competitors, trends, audience_data = await asyncio.gather(
            asyncio.to_thread(
                self._search_competitors_enhanced,
                business_type, location, products, domain, country_code
            ),
            asyncio.to_thread(self._search_industry_trends, business_type, current_year),
            asyncio.to_thread(self._search_audience_insights, target_audience_str, business_type),
        )

        # Step 5.5: Fetch competitor ads from Meta Ad Library (if access token available)
        ad_library_data = []
        try:
            access_token = os.getenv("META_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN")
            if access_token:
                from modules.marketing.router import fetch_ads_library
                # Build search terms from products/services and company name
                search_keywords = []
                if products:
                    search_keywords.extend(products[:3])
                if structured_data.get("company_name"):
                    search_keywords.append(structured_data["company_name"])
                if business_type and business_type != "business":
                    search_keywords.append(business_type)

                search_term = " ".join(search_keywords[:3]) if search_keywords else business_type

                # Determine country from location
                country_map = {"zimbabwe": "ZW", "south africa": "ZA", "kenya": "KE", "nigeria": "NG"}
                ad_countries = ["ZW"]  # Default
                if location:
                    for name, code in country_map.items():
                        if name in location.lower():
                            ad_countries = [code]
                            break

                logger.info(f"[MarketResearchAgent] Fetching Ad Library ads for: '{search_term}' in {ad_countries}")
                try:
                    ad_lib_result = fetch_ads_library(
                        access_token=access_token,
                        search_term=search_term,
                        ad_type="ALL",
                        limit=10,
                        ad_reached_countries=ad_countries
                    )
                    ad_library_data = ad_lib_result.get("data", [])
                    logger.info(f"[MarketResearchAgent] Found {len(ad_library_data)} competitor ads in Ad Library")
                except Exception as e:
                    logger.warning(f"[MarketResearchAgent] Ad Library fetch failed: {e}")
        except Exception as e:
            logger.debug(f"[MarketResearchAgent] Ad Library not available: {e}")

        # Step 6: Build comprehensive prompt with REAL data including structured extraction
        prompt = ChatPromptTemplate.from_template("""
You are a senior market research analyst. Analyze the following REAL research data and provide actionable insights.

IMPORTANT: Base your analysis on the ACTUAL DATA provided below. Do not make up information.

## BUSINESS INFORMATION
Campaign Name: {campaign_name}
Business Type: {business_type}
Products/Services: {products}
Target Audience: {target_audience}

## EXTRACTED WEBSITE STRUCTURE
Company Name: {company_name}
Tagline: {tagline}
Navigation Structure: {navigation}
Services/Products Offered: {services_products}
Value Propositions: {value_props}
Partners/Members: {partners}
Leadership: {leadership}
Key Features: {key_features}

## CONTACT & STATISTICS
Contact Info: {contact_info}
Statistics Found: {statistics}

## RAW WEBSITE CONTENT
{website_content}

## COMPETITOR ADS FROM META AD LIBRARY
{ad_library_text}

## REAL COMPETITOR DATA (from web search)
{competitor_data}

## REAL INDUSTRY TRENDS (from web search)
{trend_data}

## REAL AUDIENCE INSIGHTS (from web search)
{audience_data}

## KEYWORD INTELLIGENCE (search volume, CPC & competition data)
{keyword_intelligence}

---

Based on the REAL DATA above, provide analysis in these sections:

1. COMPETITOR ANALYSIS:
- List the actual competitors found with their strengths/weaknesses
- Identify gaps in the market that this business can exploit
- Compare messaging and positioning strategies
- Provide specific competitor URLs and what they do well/poorly

2. AUDIENCE INSIGHTS:
- Based on the real audience data, describe the target customer profile
- Identify actual pain points mentioned in the research
- Note specific buying behaviors and preferences found
- Recommend targeting strategies based on real data

3. TREND DATA:
- Summarize the actual industry trends found
- Note specific statistics and growth figures from the research
- Identify opportunities aligned with current trends
- Highlight any threats or challenges in the market

4. RECOMMENDATIONS:
- Provide 5-7 specific, actionable recommendations
- Base each recommendation on the real data found
- Include specific tactics for Facebook/Instagram ads
- Suggest unique selling propositions based on competitor gaps
- If keyword intelligence data is available, recommend which high-volume keywords to target in ads and which intent clusters (transactional, commercial, informational) to prioritize for different campaign objectives

Format your response with clear section headers.
""")

        # Prepare data for prompt
        competitor_text = "\n".join([
            f"- {c['name']}: {c['description'][:200]}... (URL: {c['url']})"
            for c in competitors[:8]
        ]) if competitors else "No competitor data found - provide general industry analysis"

        trend_text = "\n".join([
            f"- {t['title']}: {t['insight'][:200]}... (Source: {t['source']})"
            for t in trends[:6]
        ]) if trends else "No trend data found - provide general industry trends"

        audience_text = "\n".join([
            f"- {a['title']}: {a['insight'][:200]}... (Source: {a['source']})"
            for a in audience_data[:5]
        ]) if audience_data else "No audience data found - provide general audience analysis"

        # Format Ad Library data
        ad_library_text = ""
        if ad_library_data:
            ad_entries = []
            for ad in ad_library_data[:8]:
                page_name = ad.get("page_name", "Unknown")
                body = (ad.get("ad_creative_bodies") or [""])[0][:200] if ad.get("ad_creative_bodies") else ""
                title = (ad.get("ad_creative_link_titles") or [""])[0][:100] if ad.get("ad_creative_link_titles") else ""
                start = ad.get("ad_delivery_start_time", "")
                ad_entries.append(f"- {page_name}: {title} | {body}... (Started: {start})")
            ad_library_text = "\n".join(ad_entries)
        else:
            ad_library_text = "No competitor ads found in Meta Ad Library"

        # Format structured data for prompt
        services_text = ""
        if structured_data.get("services_products"):
            services_text = "\n".join([
                f"- {sp.get('name', 'Unknown')}: {sp.get('description', 'N/A')}"
                for sp in structured_data["services_products"][:10]
            ])

        navigation_text = ""
        if structured_data.get("navigation_structure"):
            navigation_text = json.dumps(structured_data["navigation_structure"], indent=2)

        partners_text = ""
        if structured_data.get("partners_members"):
            partners_text = ", ".join(structured_data["partners_members"][:20])

        leadership_text = ""
        if structured_data.get("leadership"):
            leadership_text = "\n".join([
                f"- {l.get('name', 'Unknown')} ({l.get('title', 'N/A')}): {l.get('quote', '')[:100]}"
                for l in structured_data["leadership"][:5]
            ])

        # Format contact info
        contact_text = ""
        all_contacts = multi_page_data.get("all_contacts") or website_data.get("contact_info", {})
        if all_contacts:
            if all_contacts.get("emails"):
                contact_text += f"Emails: {', '.join(all_contacts['emails'][:5])}\n"
            if all_contacts.get("phones"):
                contact_text += f"Phones: {', '.join(all_contacts['phones'][:5])}\n"
            if all_contacts.get("social_media"):
                for platform, links in all_contacts["social_media"].items():
                    if links:
                        contact_text += f"{platform.title()}: {links[0]}\n"

        # Format statistics
        stats_text = ""
        all_stats = multi_page_data.get("all_statistics") or website_data.get("statistics", [])
        if all_stats:
            stats_text = "\n".join([
                f"- {s.get('value', 'N/A')} {s.get('metric', 'N/A')}"
                for s in all_stats[:10]
            ])

        # Format keyword intelligence data
        keyword_intel_text = "No keyword data available"
        if keyword_data and keyword_data.get("success"):
            kw_lines = []
            kw_source = keyword_data.get("source", "unknown")
            kw_lines.append(f"Source: {kw_source} | Total keywords found: {keyword_data.get('total_found', 0)}")

            # Top keywords by search volume
            top_keywords = keyword_data.get("keywords", [])[:15]
            if top_keywords:
                kw_lines.append("\nTop Keywords by Search Volume:")
                for kw in top_keywords:
                    vol = kw.get("search_volume")
                    cpc = kw.get("cpc")
                    comp = kw.get("competition_level") or kw.get("competition")
                    vol_str = f"vol: {vol}" if vol is not None else "vol: N/A"
                    cpc_str = f"CPC: ${cpc}" if cpc is not None else "CPC: N/A"
                    comp_str = f"competition: {comp}" if comp else ""
                    kw_lines.append(f"  - \"{kw.get('keyword', '')}\" ({vol_str}, {cpc_str}{', ' + comp_str if comp_str else ''})")

            # Intent clusters
            clusters = keyword_data.get("clusters", {})
            if clusters:
                kw_lines.append("\nKeyword Intent Clusters:")
                for intent in ["transactional", "commercial", "informational", "navigational"]:
                    cluster_kws = clusters.get(intent, [])
                    if cluster_kws:
                        names = [k.get("keyword", "") for k in cluster_kws[:5]]
                        kw_lines.append(f"  {intent.title()} ({len(cluster_kws)} keywords): {', '.join(names)}")

                recs = clusters.get("ad_recommendations", [])
                if recs:
                    kw_lines.append("\nKeyword-Based Ad Recommendations:")
                    for rec in recs:
                        kw_lines.append(f"  - {rec}")

            keyword_intel_text = "\n".join(kw_lines)

        campaign_data = {
            "campaign_name": campaign.name,
            "business_type": business_type,
            "products": ", ".join(products) if products else "Not specified",
            "target_audience": target_audience_str,
            "company_name": structured_data.get("company_name", "Not extracted"),
            "tagline": structured_data.get("tagline", "Not found"),
            "navigation": navigation_text or "Not extracted",
            "services_products": services_text or "Not extracted",
            "value_props": ", ".join(structured_data.get("value_propositions", [])) or "Not found",
            "partners": partners_text or "Not found",
            "leadership": leadership_text or "Not found",
            "key_features": ", ".join(structured_data.get("key_features", [])) or "Not found",
            "contact_info": contact_text or "Not found",
            "statistics": stats_text or "Not found",
            "website_content": website_data.get("content", "")[:3000] or "No website content available",
            "ad_library_text": ad_library_text,
            "competitor_data": competitor_text,
            "trend_data": trend_text,
            "audience_data": audience_text,
            "keyword_intelligence": keyword_intel_text
        }

        # Run the LLM chain
        from modules.openrouter.context import set_ai_context
        chain = prompt | self.llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="market_research"):
            research_text = await chain.ainvoke(campaign_data)

        # Parse the response
        sections = self._parse_research_response(research_text)

        # Generate embedding for the full research
        embedding = self.embeddings.embed_query(research_text)

        # Store in database
        db = SessionLocal()
        try:
            research = MarketResearch(
                campaign_id=campaign.id,
                competitor_analysis=sections.get('competitor_analysis', ''),
                audience_insights=sections.get('audience_insights', ''),
                trend_data=sections.get('trend_data', ''),
                recommendations=sections.get('recommendations', ''),
                raw_response=research_text,
                embedding=embedding
            )
            db.add(research)
            db.commit()
            db.refresh(research)

            return {
                "id": str(research.id),
                "campaign_id": str(campaign.id),
                "competitor_analysis": sections.get('competitor_analysis', ''),
                "audience_insights": sections.get('audience_insights', ''),
                "trend_data": sections.get('trend_data', ''),
                "recommendations": sections.get('recommendations', ''),
                "sources": {
                    "competitors_found": len(competitors),
                    "trends_found": len(trends),
                    "audience_insights_found": len(audience_data),
                    "ad_library_ads_found": len(ad_library_data),
                    "website_scraped": website_data.get("success", False),
                    "pages_scraped": multi_page_data.get("success_count", 1) if multi_page_data else 1,
                    "structured_data_extracted": bool(structured_data)
                },
                # NEW: Include extracted structured data in response
                "extracted_data": {
                    "company_info": {
                        "name": structured_data.get("company_name"),
                        "tagline": structured_data.get("tagline"),
                        "industry": structured_data.get("industry"),
                        "geographic_coverage": structured_data.get("geographic_coverage")
                    },
                    "navigation_structure": structured_data.get("navigation_structure", []),
                    "services_products": structured_data.get("services_products", []),
                    "value_propositions": structured_data.get("value_propositions", []),
                    "target_audiences": structured_data.get("target_audiences", []),
                    "partners_members": structured_data.get("partners_members", []),
                    "leadership": structured_data.get("leadership", []),
                    "key_features": structured_data.get("key_features", []),
                    "certifications_awards": structured_data.get("certifications_awards", []),
                    "call_to_actions": structured_data.get("call_to_actions", []),
                    "pricing_info": structured_data.get("pricing_info"),
                    "contact_info": all_contacts if all_contacts else website_data.get("contact_info", {}),
                    "statistics": all_stats if all_stats else website_data.get("statistics", []),
                    "keyword_intelligence": {
                        "source": keyword_data.get("source", "none") if keyword_data else "none",
                        "total_found": keyword_data.get("total_found", 0) if keyword_data else 0,
                        "top_keywords": keyword_data.get("keywords", [])[:20] if keyword_data else [],
                        "clusters": keyword_data.get("clusters", {}) if keyword_data else {}
                    }
                },
                "created_at": research.created_at.isoformat()
            }
        finally:
            db.close()

    def conduct_research_sync(self, campaign: Campaign, source_url: str = None) -> Dict[str, Any]:
        """Synchronous version of conduct_research."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.conduct_research(campaign, source_url))
                return future.result()
        except RuntimeError:
            return asyncio.run(self.conduct_research(campaign, source_url))


# Convenience function for direct use
async def conduct_market_research(campaign_id: str, source_url: str = None) -> Dict[str, Any]:
    """
    Conduct market research for a campaign by ID.

    Args:
        campaign_id: UUID of the campaign
        source_url: Optional URL to scrape

    Returns:
        Dict containing research results with real data
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        agent = MarketResearchAgent()
        return await agent.conduct_research(campaign, source_url)
    finally:
        db.close()


async def research_website_directly(
    url: str,
    business_name: str = None,
    deep_scrape: bool = True,
    extract_structure: bool = True
) -> Dict[str, Any]:
    """
    Research a website directly without requiring a campaign.
    Useful for quick website analysis and comparison.

    Args:
        url: The website URL to research
        business_name: Optional business name (will be extracted if not provided)
        deep_scrape: Whether to scrape multiple pages (default: True)
        extract_structure: Whether to extract structured data using AI (default: True)

    Returns:
        Dict containing comprehensive website research
    """
    agent = MarketResearchAgent()

    # Validate URL upfront
    is_valid, final_url = agent._validate_url(url)
    if not is_valid:
        return {
            "url": url,
            "error": f"Invalid or unreachable URL: {url}",
            "research_summary": {"company_name": business_name or "Unknown"},
            "extracted_data": {},
            "market_data": {"competitors": [], "industry_trends": [], "audience_insights": []},
            "raw_content": {"main_page": "", "scraped_pages": []},
            "website_data": {"success": False, "source": "none", "error": f"Invalid or unreachable URL: {url}", "content_length": 0},
            "multi_page_data": {"source": None, "success_count": 0, "total_content_length": 0}
        }
    url = final_url

    logger.info(f"[MarketResearchAgent] Starting direct website research for: {url}")

    # Step 1: Scrape the main page
    website_data = agent._scrape_website(url)

    # Step 2: Deep scrape if enabled
    multi_page_data = {}
    if deep_scrape:
        multi_page_data = agent._scrape_multiple_pages(url)

    # Step 3: Extract structured data if enabled
    structured_data = {}
    if extract_structure and website_data.get("content"):
        combined_content = website_data.get("content", "")
        if multi_page_data.get("combined_content"):
            combined_content += "\n" + multi_page_data["combined_content"][:10000]
        structured_data = await agent._extract_structured_website_data(combined_content, url)

    # Step 4: Determine business type for competitor search
    industry = structured_data.get("industry", "business")
    location = structured_data.get("geographic_coverage", "Global")

    # Extract products/services for competitor search
    products = []
    if structured_data.get("services_products"):
        products = [sp.get("name", "") for sp in structured_data["services_products"][:5]]

    # Step 5-7: Search for competitors, trends, and audience insights in parallel
    from datetime import datetime
    current_year = str(datetime.now().year)
    target_audience_str = ", ".join(structured_data.get("target_audiences", ["business professionals"]))

    # Extract domain for DataForSEO-backed competitor analysis
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace("www.", "")

    competitors, trends, audience_insights = await asyncio.gather(
        asyncio.to_thread(agent._search_competitors_enhanced, industry, location, products, domain),
        asyncio.to_thread(agent._search_industry_trends, industry, current_year),
        asyncio.to_thread(agent._search_audience_insights, target_audience_str, industry),
    )

    # Compile results
    all_contacts = multi_page_data.get("all_contacts") or website_data.get("contact_info", {})
    all_stats = multi_page_data.get("all_statistics") or website_data.get("statistics", [])

    return {
        "url": url,
        "research_summary": {
            "company_name": structured_data.get("company_name") or business_name or "Unknown",
            "tagline": structured_data.get("tagline"),
            "industry": industry,
            "geographic_coverage": location,
            "pages_scraped": multi_page_data.get("success_count", 1) if multi_page_data else 1,
            "competitors_found": len(competitors),
            "trends_found": len(trends),
            "audience_insights_found": len(audience_insights)
        },
        "extracted_data": {
            "company_info": {
                "name": structured_data.get("company_name"),
                "tagline": structured_data.get("tagline"),
                "industry": structured_data.get("industry"),
                "geographic_coverage": structured_data.get("geographic_coverage")
            },
            "navigation_structure": structured_data.get("navigation_structure", []),
            "services_products": structured_data.get("services_products", []),
            "value_propositions": structured_data.get("value_propositions", []),
            "target_audiences": structured_data.get("target_audiences", []),
            "partners_members": structured_data.get("partners_members", []),
            "leadership": structured_data.get("leadership", []),
            "key_features": structured_data.get("key_features", []),
            "certifications_awards": structured_data.get("certifications_awards", []),
            "call_to_actions": structured_data.get("call_to_actions", []),
            "pricing_info": structured_data.get("pricing_info"),
            "contact_info": all_contacts,
            "statistics": all_stats
        },
        "market_data": {
            "competitors": [
                {
                    "name": c.get("name", ""),
                    "url": c.get("url", ""),
                    "description": c.get("description", "")[:300]
                }
                for c in competitors[:10]
            ],
            "industry_trends": [
                {
                    "title": t.get("title", ""),
                    "source": t.get("source", ""),
                    "insight": t.get("insight", "")[:300]
                }
                for t in trends[:8]
            ],
            "audience_insights": [
                {
                    "title": a.get("title", ""),
                    "source": a.get("source", ""),
                    "insight": a.get("insight", "")[:300]
                }
                for a in audience_insights[:6]
            ]
        },
        "raw_content": {
            "main_page": website_data.get("content", "")[:5000],
            "scraped_pages": [
                {"url": p.get("url", ""), "excerpt": p.get("content", "")[:500]}
                for p in multi_page_data.get("pages", [])[:5]
            ] if multi_page_data else []
        },
        "website_data": {
            "success": website_data.get("success", False),
            "source": website_data.get("source", "unknown"),
            "error": website_data.get("error"),
            "content_length": len(website_data.get("content", "")),
            "screenshot_url": website_data.get("screenshot_url"),
        },
        "multi_page_data": {
            "source": multi_page_data.get("source", "unknown") if multi_page_data else None,
            "success_count": multi_page_data.get("success_count", 0) if multi_page_data else 0,
            "total_content_length": len(multi_page_data.get("combined_content", "")) if multi_page_data else 0,
        }
    }

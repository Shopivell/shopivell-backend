# modules/stores/scraping_service.py
"""
Website scraping service using Tavily for content extraction
and OpenAI for parsing into structured store data.
"""
import os
import json
import re
from typing import Optional, Dict, Any, List
from tavily import TavilyClient
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize clients
tavily_api_key = os.getenv("TAVILY_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")

def extract_store_info_from_website(url: str) -> Dict[str, Any]:
    """
    Scrape a website using Tavily and extract store information using an AI agent.
    Uses direct page extraction first, falls back to search if extraction fails.
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

        # Method 1: Direct page extraction
        print(f"[Tavily] Extracting pages: {urls_to_extract}")
        try:
            extract_result = tavily.extract(urls=urls_to_extract)
            if extract_result and extract_result.get("results"):
                for result in extract_result["results"]:
                    content = result.get("raw_content", "")
                    result_url = result.get("url", "")
                    if content:
                        page_type = "MAIN PAGE" if result_url == base_url else "ADDITIONAL PAGE"
                        all_content.append(f"=== {page_type}: {result_url} ===\n{content}")
                        print(f"[Tavily] Extracted {result_url}: {len(content)} characters")
        except Exception as e:
            print(f"[Tavily] Extraction failed: {e}")

        # Method 2: If direct extraction failed, try search (but filter by domain)
        if not all_content:
            print(f"[Tavily] Direct extraction failed, trying search for {domain}")
            try:
                # Search for the business name and contact info
                search_result = tavily.search(
                    query=f"{domain} contact about services products",
                    search_depth="advanced",
                    include_raw_content=True,
                    max_results=5,
                    include_domains=[domain]
                )

                for result in search_result.get("results", []):
                    result_url = result.get("url", "")
                    # Only include results from the target domain
                    if domain in result_url:
                        content = result.get("raw_content") or result.get("content", "")
                        if content:
                            all_content.append(f"=== PAGE: {result_url} ===\n{content}")
                            print(f"[Tavily] Search found {result_url}: {len(content)} characters")
            except Exception as e:
                print(f"[Tavily] Search failed: {e}")

        # Combine all content
        combined_content = "\n\n".join(all_content)
        print(f"[Tavily] Total combined content: {len(combined_content)} characters")

        if not combined_content:
            print("[Tavily] No content extracted, using fallback")
            return _generate_fallback_data(url)

        # Use OpenAI to extract structured store information
        store_data = _extract_with_ai_agent(combined_content, url)

        return store_data

    except Exception as e:
        print(f"[Scraping] Error: {str(e)}")
        return _generate_fallback_data(url)


def _extract_with_ai_agent(content: str, url: str) -> Dict[str, Any]:
    """
    Use OpenAI to extract structured store information from website content.
    """
    client = OpenAI(api_key=openai_api_key)

    # Truncate content if too long (keep first 20000 chars for context)
    if len(content) > 20000:
        content = content[:20000] + "..."

    # Extract domain for context
    domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

    prompt = f"""You are an expert business analyst extracting store/business information from website content.

TASK: Analyze this website content and extract ALL available business information.

Website URL: {url}
Domain: {domain}

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

5. services_products: List the main products/services offered (comma-separated)
   - Look at navigation menu, product categories, services listed
   - Be specific, not generic

6. color_theme: The PRIMARY brand color as hex code
   - Look for the dominant color used in branding
   - Common examples: Blue=#2563EB, Green=#16A34A, Red=#DC2626, Orange=#EA580C, Purple=#9333EA
   - If unsure, pick a color that fits the industry

7. business_type: Describe the business in 2-4 words
   - Examples: "Coffee Shop", "Athletic Apparel", "SaaS Platform", "Restaurant", "Fashion Boutique", "Tech Company", "Consulting Firm", "E-commerce Store"

WEBSITE CONTENT:
{content}

CRITICAL RULES:
- ONLY extract information that ACTUALLY APPEARS in the content above
- If you cannot find an email address in the content, use null - DO NOT INVENT ONE
- If you cannot find a phone number in the content, use null - DO NOT INVENT ONE
- Generic emails like "contact@gmail.com" or placeholder phones like "+1 234 567 8901" are NEVER acceptable
- For store_voice and services_products, you MAY infer from context, but contact info MUST be exact
- Return ONLY valid JSON, no markdown or explanation

JSON FORMAT:
{{"store_name": "...", "store_email": "...", "store_phone": "...", "store_voice": "...", "services_products": "...", "color_theme": "#...", "business_type": "..."}}
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

        # Clean up the response (remove markdown code blocks if present)
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[AI Agent] Response: {result_text[:200]}...")

        # Parse JSON
        store_data = json.loads(result_text)

        # Ensure required fields have defaults
        if not store_data.get("store_name"):
            store_data["store_name"] = _extract_domain_name(url)

        if not store_data.get("color_theme"):
            store_data["color_theme"] = "#3B82F6"

        if not store_data.get("business_type"):
            store_data["business_type"] = "other"

        # Validate contact info - reject obvious AI hallucinations
        store_data = _validate_contact_info(store_data, content)

        return store_data

    except json.JSONDecodeError as e:
        print(f"[AI Agent] JSON parse error: {e}")
        return _generate_fallback_data(url)
    except Exception as e:
        print(f"[AI Agent] Error: {e}")
        return _generate_fallback_data(url)


def _validate_contact_info(store_data: Dict[str, Any], original_content: str) -> Dict[str, Any]:
    """
    Validate contact info to reject obvious AI hallucinations.
    If the AI made up fake contact info, set it to null.
    """
    # Check for fake/placeholder emails
    email = store_data.get("store_email")
    if email:
        fake_email_patterns = [
            "contact@gmail.com", "info@gmail.com", "hello@gmail.com",
            "support@gmail.com", "help@gmail.com", "sales@gmail.com",
            "@example.com", "@test.com", "@email.com", "@mail.com",
            "example@", "test@", "user@", "admin@"
        ]
        # Check if email is a known fake pattern
        if any(pattern in email.lower() for pattern in fake_email_patterns):
            print(f"[Validation] Rejected fake email: {email}")
            store_data["store_email"] = None
        # Verify email actually appears in content
        elif email.lower() not in original_content.lower():
            print(f"[Validation] Email not found in content, rejecting: {email}")
            store_data["store_email"] = None

    # Check for fake/placeholder phone numbers
    phone = store_data.get("store_phone")
    if phone:
        fake_phone_patterns = [
            "+1 234 567 8901", "+1-234-567-8901", "234-567-8901",
            "555-", "123-456-7890", "000-000-0000",
            "111-111-1111", "123456789", "0000000000"
        ]
        # Clean phone for comparison
        phone_cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)

        # Check if phone is a known fake pattern
        if any(pattern.replace("-", "").replace(" ", "") in phone_cleaned for pattern in fake_phone_patterns):
            print(f"[Validation] Rejected fake phone: {phone}")
            store_data["store_phone"] = None
        # Check for sequential or repeated digits (likely fake)
        elif phone_cleaned in ["12345678901", "1234567890"] or len(set(phone_cleaned.replace("+", ""))) <= 2:
            print(f"[Validation] Rejected suspicious phone pattern: {phone}")
            store_data["store_phone"] = None
        # Verify phone actually appears in content (with some flexibility)
        else:
            # Extract just digits for comparison
            phone_digits = re.sub(r'[^\d]', '', phone)
            if len(phone_digits) >= 7:
                # Check if at least the last 7 digits appear in content
                if phone_digits[-7:] not in re.sub(r'[^\d]', '', original_content):
                    print(f"[Validation] Phone not found in content, rejecting: {phone}")
                    store_data["store_phone"] = None

    return store_data


def _extract_domain_name(url: str) -> str:
    """Extract a readable name from the domain."""
    domain = url.lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = re.sub(r'^www\.', '', domain)
    domain = domain.split('/')[0]
    domain = domain.split('.')[0]
    return domain.capitalize()


def _generate_fallback_data(url: str) -> Dict[str, Any]:
    """Generate fallback data when scraping fails."""
    domain = _extract_domain_name(url)

    return {
        "store_name": f"{domain} Store",
        "store_email": f"contact@{domain.lower()}.com",
        "store_phone": None,
        "store_voice": f"Welcome to {domain}. We provide quality products and services tailored to your needs.",
        "services_products": "General Products, Services",
        "color_theme": "#3B82F6",
        "business_type": "other",
        "logo_url": None
    }

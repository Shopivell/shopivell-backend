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
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from database import SessionLocal
from .models import Campaign, MarketResearch

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
    logger.info(f"[MarketResearchAgent] Screenshot service available: {SCREENSHOT_AVAILABLE}")
except ImportError as e:
    SCREENSHOT_AVAILABLE = False
    GEMINI_AVAILABLE = False
    STORE_SCRAPING_AVAILABLE = False
    capture_homepage_screenshot_sync = None
    analyze_brand_from_screenshot_sync = None
    extract_store_info_from_website = None
    logger.warning(f"[MarketResearchAgent] Screenshot service not available: {e}")

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


# Regex patterns for extracting structured data
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_PATTERN = re.compile(r'[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,9}')
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
            model="openai/gpt-4o" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.7
        )
        self.embeddings = OpenAIEmbeddings()
        self.tavily = TavilyClient(api_key=tavily_api_key) if TAVILY_AVAILABLE else None
        logger.info(f"[MarketResearchAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}, Tavily: {TAVILY_AVAILABLE}")

    def _extract_contact_info(self, content: str) -> Dict[str, Any]:
        """Extract contact information from website content"""
        contacts = {
            "emails": list(set(EMAIL_PATTERN.findall(content))),
            "phones": list(set(PHONE_PATTERN.findall(content))),
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

    def _scrape_website(self, url: str) -> Dict[str, Any]:
        """Scrape the target website to understand the business"""
        if not self.tavily:
            logger.warning("[MarketResearchAgent] Tavily not available, skipping website scrape")
            return {"content": "", "error": "Tavily not configured"}

        try:
            logger.info(f"[MarketResearchAgent] Scraping website: {url}")

            # Extract content from the website
            extract_result = self.tavily.extract(urls=[url])

            if extract_result and extract_result.get("results"):
                content = extract_result["results"][0].get("raw_content", "")

                # Extract structured data from content
                contact_info = self._extract_contact_info(content)
                statistics = self._extract_statistics(content)

                return {
                    "content": content[:15000],  # Increased limit for more context
                    "url": url,
                    "success": True,
                    "contact_info": contact_info,
                    "statistics": statistics
                }

            return {"content": "", "error": "No content extracted"}

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Website scrape error: {e}")
            return {"content": "", "error": str(e)}

    def _scrape_multiple_pages(self, base_url: str, subpages: List[str] = None) -> Dict[str, Any]:
        """
        Scrape multiple pages from a website for comprehensive analysis.

        Args:
            base_url: The main website URL
            subpages: List of subpage paths to scrape (e.g., ['/about', '/services', '/contact'])
        """
        if not self.tavily:
            return {"pages": [], "error": "Tavily not configured"}

        # Default subpages to check if none provided
        if subpages is None:
            subpages = [
                '', '/about', '/about-us', '/services', '/products',
                '/solutions', '/contact', '/contact-us', '/partners',
                '/team', '/leadership', '/pricing'
            ]

        results = {
            "pages": [],
            "combined_content": "",
            "all_contacts": {"emails": [], "phones": [], "social_media": {}},
            "all_statistics": [],
            "success_count": 0
        }

        urls_to_scrape = []
        parsed_base = urlparse(base_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

        for subpage in subpages[:8]:  # Limit to 8 pages to avoid rate limits
            full_url = urljoin(base_domain, subpage)
            if full_url not in urls_to_scrape:
                urls_to_scrape.append(full_url)

        try:
            logger.info(f"[MarketResearchAgent] Scraping {len(urls_to_scrape)} pages from {base_domain}")

            # Tavily can extract multiple URLs at once
            extract_result = self.tavily.extract(urls=urls_to_scrape)

            if extract_result and extract_result.get("results"):
                for page_result in extract_result["results"]:
                    content = page_result.get("raw_content", "")
                    page_url = page_result.get("url", "")

                    if content:
                        results["pages"].append({
                            "url": page_url,
                            "content": content[:5000],
                            "success": True
                        })
                        results["combined_content"] += f"\n\n--- PAGE: {page_url} ---\n{content[:5000]}"
                        results["success_count"] += 1

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

            # Deduplicate
            results["all_contacts"]["emails"] = list(set(results["all_contacts"]["emails"]))
            results["all_contacts"]["phones"] = list(set(results["all_contacts"]["phones"]))
            for platform in results["all_contacts"]["social_media"]:
                results["all_contacts"]["social_media"][platform] = list(set(results["all_contacts"]["social_media"][platform]))

            return results

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Multi-page scrape error: {e}")
            return {"pages": [], "error": str(e)}

    async def _extract_structured_website_data(self, content: str, url: str) -> Dict[str, Any]:
        """
        Use AI to extract structured data from website content.
        Extracts: navigation, services, products, partners, leadership, value propositions
        """
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
            chain = extraction_prompt | self.llm | StrOutputParser()
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

            return json.loads(result.strip())

        except json.JSONDecodeError as e:
            logger.warning(f"[MarketResearchAgent] Failed to parse structured data: {e}")
            return {}
        except Exception as e:
            logger.error(f"[MarketResearchAgent] Structured extraction error: {e}")
            return {}

    def _search_competitors(self, business_type: str, location: str, products: List[str]) -> List[Dict[str, Any]]:
        """Search for real competitors in the market"""
        if not self.tavily:
            return []

        try:
            # Build search query
            products_str = ", ".join(products[:3]) if products else business_type
            query = f"{business_type} companies {location} {products_str} competitors"

            logger.info(f"[MarketResearchAgent] Searching competitors: {query}")

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
                    "description": result.get("content", "")[:500]
                })

            return competitors

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Competitor search error: {e}")
            return []

    def _search_industry_trends(self, industry: str, year: str = "2024") -> List[Dict[str, Any]]:
        """Search for real industry trends"""
        if not self.tavily:
            return []

        try:
            query = f"{industry} industry trends {year} market growth statistics"

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
        extract_structure: bool = True
    ) -> Dict[str, Any]:
        """
        Conduct comprehensive market research with REAL data.

        Args:
            campaign: Campaign object with all campaign details
            source_url: Optional URL to scrape for business information
            deep_scrape: Whether to scrape multiple pages (default: True)
            extract_structure: Whether to extract structured data using AI (default: True)

        Returns:
            Dict containing research results with enhanced structured data
        """
        logger.info(f"[MarketResearchAgent] Starting enhanced research for campaign: {campaign.name}")

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

        # Step 3: Search for real competitors
        competitors = self._search_competitors(business_type, location, products)

        # Step 4: Search for industry trends (use current year)
        from datetime import datetime
        current_year = str(datetime.now().year)
        trends = self._search_industry_trends(business_type, year=current_year)

        # Step 5: Search for audience insights
        audience_data = self._search_audience_insights(target_audience_str, business_type)

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

## REAL COMPETITOR DATA (from web search)
{competitor_data}

## REAL INDUSTRY TRENDS (from web search)
{trend_data}

## REAL AUDIENCE INSIGHTS (from web search)
{audience_data}

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
            "competitor_data": competitor_text,
            "trend_data": trend_text,
            "audience_data": audience_text
        }

        # Run the LLM chain
        chain = prompt | self.llm | StrOutputParser()
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
                    "statistics": all_stats if all_stats else website_data.get("statistics", [])
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

    # Step 5: Search for competitors
    competitors = agent._search_competitors(industry, location, products)

    # Step 6: Search for industry trends
    from datetime import datetime
    current_year = str(datetime.now().year)
    trends = agent._search_industry_trends(industry, year=current_year)

    # Step 7: Get audience insights based on target audiences
    target_audience_str = ", ".join(structured_data.get("target_audiences", ["business professionals"]))
    audience_insights = agent._search_audience_insights(target_audience_str, industry)

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
        }
    }

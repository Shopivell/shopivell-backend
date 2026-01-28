# market_research_agent.py - AI Agent for Market Research
"""
Enhanced Market Research Agent that performs REAL research:
1. Scrapes the actual website using Tavily
2. Searches for real competitors
3. Finds actual industry trends
4. Provides data-driven insights
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
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

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


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
                return {
                    "content": content[:10000],  # Limit content size
                    "url": url,
                    "success": True
                }

            return {"content": "", "error": "No content extracted"}

        except Exception as e:
            logger.error(f"[MarketResearchAgent] Website scrape error: {e}")
            return {"content": "", "error": str(e)}

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

    async def conduct_research(self, campaign: Campaign, source_url: str = None) -> Dict[str, Any]:
        """
        Conduct comprehensive market research with REAL data.

        Args:
            campaign: Campaign object with all campaign details
            source_url: Optional URL to scrape for business information

        Returns:
            Dict containing research results
        """
        logger.info(f"[MarketResearchAgent] Starting research for campaign: {campaign.name}")

        # Step 1: Scrape the website if URL provided
        website_data = {}
        if source_url:
            website_data = self._scrape_website(source_url)

        # Step 2: Extract business info from campaign
        business_type = campaign.product_description or "business"
        location = "Zimbabwe"  # Default, can be extracted from campaign
        products = campaign.keywords or []
        target_audience_str = json.dumps(campaign.target_audience) if campaign.target_audience else "business professionals"

        # Step 3: Search for real competitors
        competitors = self._search_competitors(business_type, location, products)

        # Step 4: Search for industry trends
        trends = self._search_industry_trends(business_type)

        # Step 5: Search for audience insights
        audience_data = self._search_audience_insights(target_audience_str, business_type)

        # Step 6: Build comprehensive prompt with REAL data
        prompt = ChatPromptTemplate.from_template("""
You are a senior market research analyst. Analyze the following REAL research data and provide actionable insights.

IMPORTANT: Base your analysis on the ACTUAL DATA provided below. Do not make up information.

## BUSINESS INFORMATION
Campaign Name: {campaign_name}
Business Type: {business_type}
Products/Services: {products}
Target Audience: {target_audience}
Website Content: {website_content}

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

        campaign_data = {
            "campaign_name": campaign.name,
            "business_type": business_type,
            "products": ", ".join(products) if products else "Not specified",
            "target_audience": target_audience_str,
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
                    "website_scraped": website_data.get("success", False)
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

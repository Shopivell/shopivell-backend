# market_research_agent.py - AI Agent for Market Research

import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, MarketResearch

load_dotenv()


class MarketResearchAgent:
    """AI Agent for conducting comprehensive market research"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.7
        )
        self.embeddings = OpenAIEmbeddings()

        self.prompt = ChatPromptTemplate.from_template("""
As a market research expert, analyze the following campaign brief and provide insights:

Campaign Name: {campaign_name}
Objective: {objective}
Product: {product_description}
Target Audience: {target_audience}
Keywords: {keywords}

Provide analysis in these sections:

1. COMPETITOR ANALYSIS:
- Identify main competitors in this space
- Analyze their messaging strategies
- Note their strengths and weaknesses

2. AUDIENCE INSIGHTS:
- Psychographic profile of target audience
- Pain points and desires
- Media consumption habits

3. TREND DATA:
- Current trends in this industry
- Seasonal factors to consider
- Platform-specific trends (Facebook/Instagram)

4. RECOMMENDATIONS:
- Key opportunities to exploit
- Potential challenges to avoid
- Suggested positioning strategy

Format your response exactly with the section headers above.
""")

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

        # Keywords to identify each section (case insensitive)
        section_keywords = {
            "competitor": "competitor_analysis",
            "audience": "audience_insights",
            "trend": "trend_data",
            "recommendation": "recommendations"
        }

        for line in response_text.split('\n'):
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            # Check if this line is a section header (contains keyword + ":" or starts with #)
            header_found = False
            for keyword, section_key in section_keywords.items():
                if keyword.upper() in line_upper and (":" in line_stripped or line_stripped.startswith("#")):
                    # Save previous section if exists
                    if current_section and current_content:
                        sections[current_section] = '\n'.join(current_content).strip()

                    current_section = section_key
                    current_content = []
                    header_found = True
                    break

            if not header_found and current_section and line_stripped:
                # Skip lines that are just the header repeated
                if not any(kw.upper() in line_upper for kw in section_keywords.keys()):
                    current_content.append(line_stripped)
                elif ":" not in line_stripped and not line_stripped.startswith("#"):
                    current_content.append(line_stripped)

        # Save the last section
        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content).strip()

        return sections

    async def conduct_research(self, campaign: Campaign) -> Dict[str, Any]:
        """
        Conduct comprehensive market research for a campaign.

        Args:
            campaign: Campaign object with all campaign details

        Returns:
            Dict containing research results
        """
        # Prepare campaign data for the prompt
        campaign_data = {
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "product_description": campaign.product_description or "Not specified",
            "target_audience": json.dumps(campaign.target_audience) if campaign.target_audience else "Not specified",
            "keywords": ", ".join(campaign.keywords) if campaign.keywords else "Not specified"
        }

        # Run the LLM chain
        chain = self.prompt | self.llm | StrOutputParser()
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
                "created_at": research.created_at.isoformat()
            }
        finally:
            db.close()

    def conduct_research_sync(self, campaign: Campaign) -> Dict[str, Any]:
        """
        Synchronous version of conduct_research.

        Args:
            campaign: Campaign object with all campaign details

        Returns:
            Dict containing research results
        """
        import asyncio

        # Check if there's already an event loop running
        try:
            loop = asyncio.get_running_loop()
            # If we're in an async context, we need to use a different approach
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.conduct_research(campaign))
                return future.result()
        except RuntimeError:
            # No event loop running, safe to use asyncio.run
            return asyncio.run(self.conduct_research(campaign))


# Convenience function for direct use
async def conduct_market_research(campaign_id: str) -> Dict[str, Any]:
    """
    Conduct market research for a campaign by ID.

    Args:
        campaign_id: UUID of the campaign

    Returns:
        Dict containing research results
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        agent = MarketResearchAgent()
        return await agent.conduct_research(campaign)
    finally:
        db.close()

# monitor_optimizer_agent.py - AI Agent for Ad Performance Optimization
"""Uses OpenRouter API via ChatOpenRouter adapter for AI generation."""

import os
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, PerformanceMetrics, AdCopy

# Import OpenRouter adapter (with fallback to ChatOpenAI)
try:
    from modules.openrouter.langchain_adapter import ChatOpenRouter
    OPENROUTER_AVAILABLE = True
except ImportError:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class MonitorOptimizerAgent:
    """AI Agent for analyzing ad performance and providing optimization recommendations"""

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
            temperature=0.3  # Lower temperature for more analytical outputs
        )
        logger.info(f"[MonitorOptimizerAgent] Initialized with {'OpenRouter' if OPENROUTER_AVAILABLE else 'OpenAI'}")

        self.optimization_prompt = ChatPromptTemplate.from_template("""
Analyze the ad performance data and provide optimization recommendations.

CAMPAIGN: {campaign_name}
OBJECTIVE: {objective}
BUDGET: ${budget}

PERFORMANCE DATA:
{performance_data}

ANALYSIS CRITERIA:
1. CTR (Click-Through Rate): Above 2% is good, below 1% needs attention
2. CPC (Cost Per Click): Compare against industry average ($0.50-$2.00)
3. ROAS (Return on Ad Spend): Above 300% is good, below 200% needs optimization
4. Conversion Rate: Analyze against objective
5. Spend Efficiency: How well is the budget being utilized

Provide optimization recommendations in this format:

RECOMMENDATION 1:
ACTION: [Specific action to take]
REASONING: [Why this action is recommended]
EXPECTED IMPACT: [Expected outcome]
PRIORITY: [HIGH/MEDIUM/LOW]

Provide 3-5 actionable recommendations.
Separate each recommendation with "---"
""")

        self.summary_prompt = ChatPromptTemplate.from_template("""
Provide a brief executive summary of the campaign performance.

CAMPAIGN: {campaign_name}
OBJECTIVE: {objective}

PERFORMANCE METRICS:
- Total Impressions: {total_impressions:,}
- Total Clicks: {total_clicks:,}
- Average CTR: {avg_ctr:.2f}%
- Average CPC: ${avg_cpc:.2f}
- Total Conversions: {total_conversions}
- Total Spend: ${total_spend:.2f}
- Overall ROAS: {overall_roas:.0f}%

Provide a 2-3 sentence summary of the campaign health and key focus areas.
Format: SUMMARY: [Your summary here]
HEALTH_SCORE: [1-10 rating]
""")

    def _parse_recommendations(self, analysis: str) -> List[Dict[str, str]]:
        """Parse the AI response into structured recommendations"""
        recommendations = []
        current_rec = {}

        for line in analysis.split('\n'):
            line = line.strip()

            if line.upper().startswith('ACTION:'):
                if current_rec and 'action' in current_rec:
                    recommendations.append(current_rec)
                    current_rec = {}
                current_rec['action'] = line.split(':', 1)[-1].strip()
            elif line.upper().startswith('REASONING:'):
                current_rec['reasoning'] = line.split(':', 1)[-1].strip()
            elif line.upper().startswith('EXPECTED IMPACT:'):
                current_rec['expected_impact'] = line.split(':', 1)[-1].strip()
            elif line.upper().startswith('PRIORITY:'):
                current_rec['priority'] = line.split(':', 1)[-1].strip().upper()
            elif line == '---' and current_rec:
                if 'action' in current_rec:
                    recommendations.append(current_rec)
                current_rec = {}

        # Don't forget the last recommendation
        if current_rec and 'action' in current_rec:
            recommendations.append(current_rec)

        return recommendations

    def _parse_summary(self, summary_text: str) -> Dict[str, Any]:
        """Parse the summary response"""
        result = {
            "summary": "",
            "health_score": 5
        }

        for line in summary_text.split('\n'):
            line = line.strip()
            if line.upper().startswith('SUMMARY:'):
                result['summary'] = line.split(':', 1)[-1].strip()
            elif line.upper().startswith('HEALTH_SCORE:'):
                try:
                    score = line.split(':', 1)[-1].strip()
                    # Extract just the number
                    score = ''.join(filter(str.isdigit, score.split('/')[0]))
                    result['health_score'] = int(score) if score else 5
                except (ValueError, IndexError):
                    result['health_score'] = 5

        return result

    async def analyze_performance(
        self,
        campaign: Campaign,
        performance_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze ad performance and provide optimization recommendations.

        Args:
            campaign: Campaign object
            performance_data: List of performance metrics dictionaries

        Returns:
            Dict containing recommendations and analysis
        """
        if not performance_data:
            return {
                "recommendations": [],
                "message": "No performance data available for analysis"
            }

        # Format performance data for the prompt
        perf_text = ""
        for perf in performance_data:
            perf_text += f"""
Ad ID: {perf.get('ad_id', 'N/A')}
Ad Copy: {perf.get('headline', 'N/A')}
Impressions: {perf.get('impressions', 0):,}
Clicks: {perf.get('clicks', 0):,}
CTR: {perf.get('ctr', 0):.2f}%
CPC: ${perf.get('cpc', 0):.2f}
Conversions: {perf.get('conversions', 0)}
Spend: ${perf.get('spend', 0):.2f}
ROAS: {perf.get('roas', 0):.0f}%
---
"""

        # Run the optimization analysis
        chain = self.optimization_prompt | self.llm | StrOutputParser()
        analysis = await chain.ainvoke({
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "budget": campaign.budget or 0,
            "performance_data": perf_text
        })

        # Parse recommendations
        recommendations = self._parse_recommendations(analysis)

        return {
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "recommendations": recommendations,
            "raw_analysis": analysis
        }

    async def get_performance_summary(
        self,
        campaign: Campaign,
        metrics: List[PerformanceMetrics]
    ) -> Dict[str, Any]:
        """
        Get an executive summary of campaign performance.

        Args:
            campaign: Campaign object
            metrics: List of PerformanceMetrics objects

        Returns:
            Dict containing summary and health score
        """
        if not metrics:
            return {
                "summary": "No performance data available yet.",
                "health_score": 0,
                "metrics": {}
            }

        # Aggregate metrics
        total_impressions = sum(m.impressions or 0 for m in metrics)
        total_clicks = sum(m.clicks or 0 for m in metrics)
        total_conversions = sum(m.conversions or 0 for m in metrics)
        total_spend = sum(m.spend or 0 for m in metrics)

        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
        avg_cpc = (total_spend / total_clicks) if total_clicks > 0 else 0
        overall_roas = (sum(m.roas or 0 for m in metrics) / len(metrics)) if metrics else 0

        # Generate summary
        chain = self.summary_prompt | self.llm | StrOutputParser()
        summary_text = await chain.ainvoke({
            "campaign_name": campaign.name,
            "objective": campaign.objective,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "avg_ctr": avg_ctr,
            "avg_cpc": avg_cpc,
            "total_conversions": total_conversions,
            "total_spend": total_spend,
            "overall_roas": overall_roas
        })

        summary_data = self._parse_summary(summary_text)

        return {
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "summary": summary_data['summary'],
            "health_score": summary_data['health_score'],
            "metrics": {
                "total_impressions": total_impressions,
                "total_clicks": total_clicks,
                "total_conversions": total_conversions,
                "total_spend": round(total_spend, 2),
                "avg_ctr": round(avg_ctr, 2),
                "avg_cpc": round(avg_cpc, 2),
                "overall_roas": round(overall_roas, 2)
            }
        }


# Convenience function for direct use
async def analyze_campaign_performance(
    campaign_id: str,
    performance_data: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Analyze campaign performance and get optimization recommendations.

    Args:
        campaign_id: UUID of the campaign
        performance_data: Optional list of performance data dicts

    Returns:
        Dict containing recommendations
    """
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} not found")

        # If no performance data provided, fetch from database
        if not performance_data:
            metrics = db.query(PerformanceMetrics).filter(
                PerformanceMetrics.campaign_id == campaign_id
            ).all()

            performance_data = []
            for m in metrics:
                # Get associated ad copy if exists
                ad_copy = db.query(AdCopy).filter(AdCopy.id == m.ad_copy_id).first() if m.ad_copy_id else None

                performance_data.append({
                    "ad_id": str(m.ad_copy_id) if m.ad_copy_id else "N/A",
                    "headline": ad_copy.headline if ad_copy else "N/A",
                    "impressions": m.impressions or 0,
                    "clicks": m.clicks or 0,
                    "ctr": m.ctr or 0,
                    "cpc": m.cpc or 0,
                    "conversions": m.conversions or 0,
                    "spend": m.spend or 0,
                    "roas": m.roas or 0
                })

        agent = MonitorOptimizerAgent()
        return await agent.analyze_performance(campaign, performance_data)

    finally:
        db.close()

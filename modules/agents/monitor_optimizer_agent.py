# monitor_optimizer_agent.py - AI Agent for Ad Performance Optimization
"""
Uses OpenRouter API via ChatOpenRouter adapter for AI generation.

Includes Automated Rules Engine for 24/7 ad optimization:
- Scale: Increase budget +20% when ROAS ≥ target × 1.25 for 3 consecutive days
- Kill: Cut budget 50% if CPA > 2 × target & zero purchases after ≥ 2000 impressions
"""

import os
import json
import logging
import uuid
import httpx
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from database import SessionLocal
from .models import Campaign, PerformanceMetrics, AdCopy


# --- Structured output models for LLM parsing ---

class LLMRecommendation(BaseModel):
    """Single optimization recommendation from LLM"""
    action: str = Field(..., description="Specific action to take")
    reasoning: str = Field(..., description="Why this action is recommended")
    expected_impact: str = Field(..., description="Expected outcome")
    priority: str = Field(..., description="HIGH, MEDIUM, or LOW")


class LLMRecommendationsResponse(BaseModel):
    """Complete recommendations response from LLM"""
    recommendations: List[LLMRecommendation]


class LLMSummaryResponse(BaseModel):
    """Performance summary response from LLM"""
    summary: str = Field(..., description="2-3 sentence executive summary")
    health_score: int = Field(..., ge=1, le=10, description="Campaign health 1-10")


class LLMProposedRule(BaseModel):
    """A rule proposed by the LLM based on pattern analysis"""
    name: str = Field(..., description="Rule name")
    conditions: List[Dict[str, Any]] = Field(..., description="Condition list")
    action_type: str = Field(..., description="scale_up, scale_down, pause, notify")
    adjustment_percent: Optional[float] = None
    reasoning: str = Field(..., description="Why this rule would help")


class LLMRuleProposalResponse(BaseModel):
    """Complete rule proposal response from LLM"""
    proposed_rules: List[LLMProposedRule]

# Import OpenRouter adapter (with fallback to ChatOpenAI)
_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
if _OPENROUTER_KEY:
    try:
        from modules.openrouter.langchain_adapter import ChatOpenRouter
        OPENROUTER_AVAILABLE = True
    except ImportError:
        from langchain_openai import ChatOpenAI as ChatOpenRouter
        OPENROUTER_AVAILABLE = False
else:
    from langchain_openai import ChatOpenAI as ChatOpenRouter
    OPENROUTER_AVAILABLE = False

load_dotenv()
logger = logging.getLogger(__name__)


class MonitorOptimizerAgent:
    """AI Agent for analyzing ad performance and providing optimization recommendations"""

    def __init__(self):
        self.llm = ChatOpenRouter(
            model="openai/gpt-4o-mini" if OPENROUTER_AVAILABLE else "gpt-4o-mini",
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

{trend_section}

{recent_actions_section}

{upcoming_events_section}

ANALYSIS CRITERIA:
1. CTR (Click-Through Rate): Above 2% is good, below 1% needs attention
2. CPC (Cost Per Click): Compare against industry average ($0.50-$2.00)
3. ROAS (Return on Ad Spend): Above 300% is good, below 200% needs optimization
4. Conversion Rate: Analyze against objective
5. Spend Efficiency: How well is the budget being utilized
6. If trend data is provided, identify sustained trends, anomalies, cyclical patterns, ad fatigue, and budget exhaustion
7. If recent automated actions are listed, evaluate whether each action improved or degraded metrics

Provide 3-5 actionable recommendations.

IMPORTANT: Return your response as valid JSON with this exact structure:
{{
  "recommendations": [
    {{
      "action": "Specific action to take",
      "reasoning": "Why this action is recommended",
      "expected_impact": "Expected outcome",
      "priority": "HIGH or MEDIUM or LOW"
    }}
  ]
}}

Return ONLY valid JSON, no other text.
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

IMPORTANT: Return your response as valid JSON with this exact structure:
{{
  "summary": "Your 2-3 sentence summary here",
  "health_score": 7
}}

Return ONLY valid JSON, no other text.
""")

        self.rule_proposal_prompt = ChatPromptTemplate.from_template("""
Based on the performance data, recent automated actions, and current rules, propose new optimization rules.

CURRENT ACTIVE RULES:
{current_rules}

RECENT ACTIONS AND OUTCOMES:
{execution_history}

PERFORMANCE PATTERNS:
{performance_data}

Propose 1-3 new rules that would improve performance based on patterns you observe.
Each rule should have clear conditions and an action.

Available metrics: roas, cpa, ctr, impressions, conversions, spend, cpc, frequency, ctr_decline_pct, lead_quality_score
Available operators: gt, gte, lt, lte, eq, neq
Available actions: scale_up, scale_down, pause, unpause, notify

IMPORTANT: Return your response as valid JSON with this exact structure:
{{
  "proposed_rules": [
    {{
      "name": "Descriptive rule name",
      "conditions": [
        {{"metric": "roas", "operator": "gte", "value": 3.0, "consecutive_days": 2}}
      ],
      "action_type": "scale_up",
      "adjustment_percent": 15,
      "reasoning": "Why this rule would help based on observed patterns"
    }}
  ]
}}

Return ONLY valid JSON, no other text.
""")

    def _parse_recommendations(self, analysis: str) -> Tuple[List[Dict[str, str]], str]:
        """Parse the AI response into structured recommendations.

        Tries JSON parsing first (Pydantic), falls back to string parsing.
        Returns: (recommendations, parse_method)
        """
        # Try JSON parsing first
        try:
            cleaned = analysis.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            data = LLMRecommendationsResponse.model_validate_json(cleaned)
            return [r.model_dump() for r in data.recommendations], "json"
        except Exception:
            pass

        # Try plain JSON parse (LLM may return valid JSON but not match Pydantic exactly)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "recommendations" in parsed:
                return parsed["recommendations"], "json"
        except Exception:
            pass

        logger.warning("[MonitorOptimizerAgent] JSON parse failed, falling back to string parsing")

        # Fallback: original string parsing
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

        if current_rec and 'action' in current_rec:
            recommendations.append(current_rec)

        return recommendations, "string_fallback"

    def _parse_summary(self, summary_text: str) -> Dict[str, Any]:
        """Parse the summary response. Tries JSON first, falls back to string parsing."""
        # Try JSON parsing first
        try:
            cleaned = summary_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            data = LLMSummaryResponse.model_validate_json(cleaned)
            return {"summary": data.summary, "health_score": data.health_score}
        except Exception:
            pass

        try:
            parsed = json.loads(cleaned)
            return {
                "summary": parsed.get("summary", ""),
                "health_score": min(max(int(parsed.get("health_score", 5)), 1), 10)
            }
        except Exception:
            pass

        logger.warning("[MonitorOptimizerAgent] JSON summary parse failed, falling back to string parsing")

        # Fallback: original string parsing
        result = {"summary": "", "health_score": 5}

        for line in summary_text.split('\n'):
            line = line.strip()
            if line.upper().startswith('SUMMARY:'):
                result['summary'] = line.split(':', 1)[-1].strip()
            elif line.upper().startswith('HEALTH_SCORE:'):
                try:
                    score = line.split(':', 1)[-1].strip()
                    score = ''.join(filter(str.isdigit, score.split('/')[0]))
                    result['health_score'] = int(score) if score else 5
                except (ValueError, IndexError):
                    result['health_score'] = 5

        return result

    def _log_optimization_decision(
        self,
        campaign_id: Optional[str] = None,
        store_id: Optional[str] = None,
        raw_analysis: Optional[str] = None,
        recommendations: Optional[List[Dict]] = None,
        parse_method: Optional[str] = None,
        health_score: Optional[int] = None,
        summary: Optional[str] = None
    ) -> None:
        """Persist an optimization decision to the database."""
        db = SessionLocal()
        try:
            from .models import OptimizationDecisionLog
            log = OptimizationDecisionLog(
                campaign_id=campaign_id if campaign_id else None,
                store_id=store_id if store_id else None,
                raw_analysis=raw_analysis,
                recommendations=recommendations,
                health_score=health_score,
                summary=summary,
                parse_method=parse_method,
                model_used="openai/gpt-4o-mini" if OPENROUTER_AVAILABLE else "gpt-4o-mini"
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error(f"[MonitorOptimizerAgent] Failed to log optimization decision: {e}")
            db.rollback()
        finally:
            db.close()

    def _get_recent_actions_for_campaign(self, campaign_id: str, days: int = 14) -> List[Dict]:
        """Query RuleExecutionLog for entities related to this campaign (closed-loop feedback)."""
        db = SessionLocal()
        try:
            from .models import RuleExecutionLog
            from modules.marketing.models import MetaAdSet, MetaAd

            cutoff = datetime.utcnow() - timedelta(days=days)

            # Get entity IDs associated with this campaign
            entity_ids = []
            try:
                adsets = db.query(MetaAdSet).filter(MetaAdSet.campaign_id == campaign_id).all()
                entity_ids.extend([adset.adset_id for adset in adsets])
                ads = db.query(MetaAd).filter(MetaAd.campaign_id == campaign_id).all()
                entity_ids.extend([ad.ad_id for ad in ads])
            except Exception:
                pass

            if not entity_ids:
                return []

            logs = db.query(RuleExecutionLog).filter(
                RuleExecutionLog.entity_id.in_(entity_ids),
                RuleExecutionLog.executed_at >= cutoff,
                RuleExecutionLog.success == True,
                RuleExecutionLog.is_simulation == False
            ).order_by(RuleExecutionLog.executed_at.desc()).limit(20).all()

            return [{
                "action": log.action_taken,
                "entity": log.entity_id,
                "rule": log.rule_name,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "date": log.executed_at.strftime("%b %d") if log.executed_at else "N/A",
                "message": log.message
            } for log in logs]
        except Exception as e:
            logger.error(f"[MonitorOptimizerAgent] Failed to get recent actions: {e}")
            return []
        finally:
            db.close()

    def _format_trend_data(self, trend_data: List[Dict[str, Any]], trend_days: int = 30) -> str:
        """Format time-series data showing weekly aggregates and week-over-week changes."""
        if not trend_data or len(trend_data) < 7:
            return ""

        # Group by week (data should be sorted newest-first)
        weeks = []
        for i in range(0, min(len(trend_data), trend_days), 7):
            week_data = trend_data[i:i + 7]
            if not week_data:
                continue
            n = len(week_data)
            weeks.append({
                "period": f"Week {len(weeks) + 1} (most recent)" if i == 0 else f"Week {len(weeks) + 1}",
                "avg_ctr": sum(d.get("ctr", 0) for d in week_data) / n,
                "avg_cpc": sum(d.get("cpc", 0) for d in week_data) / n,
                "total_spend": sum(d.get("spend", 0) for d in week_data),
                "total_conversions": sum(d.get("conversions", 0) for d in week_data),
                "avg_roas": sum(d.get("roas", 0) for d in week_data) / n,
            })

        # Build trend text with week-over-week changes
        lines = []
        for i, week in enumerate(weeks):
            lines.append(f"\n{week['period']}:")
            lines.append(f"  CTR: {week['avg_ctr']:.2f}% | CPC: ${week['avg_cpc']:.2f} | Spend: ${week['total_spend']:.2f} | Conversions: {week['total_conversions']}")
            if i > 0:
                prev = weeks[i - 1]
                changes = []
                for metric, label in [("avg_ctr", "CTR"), ("avg_cpc", "CPC"), ("total_spend", "Spend")]:
                    old_val = prev[metric]
                    new_val = week[metric]
                    if old_val > 0:
                        pct = ((new_val - old_val) / old_val) * 100
                        changes.append(f"{label}: {'+' if pct > 0 else ''}{pct:.1f}%")
                if changes:
                    lines.append(f"  WoW changes: {', '.join(changes)}")

        return "\n".join(lines)

    async def analyze_performance(
        self,
        campaign: Campaign,
        performance_data: List[Dict[str, Any]],
        trend_data: Optional[List[Dict[str, Any]]] = None,
        trend_days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze ad performance and provide optimization recommendations.

        Args:
            campaign: Campaign object
            performance_data: List of performance metrics dictionaries
            trend_data: Optional 30-day time series for trend analysis
            trend_days: Number of days for trend analysis

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

        # Step 3: Closed-loop feedback - get recent automated actions
        recent_actions = self._get_recent_actions_for_campaign(str(campaign.id))
        if recent_actions:
            actions_text = "RECENT AUTOMATED ACTIONS (consider their impact on metrics):\n" + "\n".join([
                f"- {a['date']}: {a['rule']} -> {a['message']}"
                for a in recent_actions
            ])
        else:
            actions_text = ""

        # Step 4.5: Upcoming events context
        events_text = ""
        try:
            from .calendar_engine import get_upcoming_events
            # Try to get store's country code
            country = "US"
            store_id_str = None
            if campaign.store_id:
                store_id_str = str(campaign.store_id)
                try:
                    from modules.stores.models import Store
                    store_db = SessionLocal()
                    store = store_db.query(Store).filter(Store.id == campaign.store_id).first()
                    if store and store.country_code:
                        country = store.country_code
                    store_db.close()
                except Exception:
                    pass

            upcoming = get_upcoming_events(country, store_id_str, days_ahead=14)
            if upcoming:
                events_text = "UPCOMING EVENTS (next 14 days):\n" + "\n".join([
                    f"- {e['name']} in {e['days_until']} days ({e['impact'].upper()} impact, "
                    f"suggest +{int((e['budget_multiplier'] - 1) * 100)}% budget) [{e['source']}]"
                    if e['days_until'] > 0 else
                    f"- {e['name']} HAPPENING NOW ({e['impact'].upper()} impact, "
                    f"suggest +{int((e['budget_multiplier'] - 1) * 100)}% budget) [{e['source']}]"
                    for e in upcoming[:8]
                ])
        except Exception as e:
            logger.warning(f"[MonitorOptimizerAgent] Events context error: {e}")

        # Step 4: Historical trend analysis
        if trend_data:
            trend_text = f"TREND ANALYSIS (past {trend_days} days):\n" + self._format_trend_data(trend_data, trend_days)
        else:
            trend_text = ""

        # Run the optimization analysis with JSON structured output
        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"})
        chain = self.optimization_prompt | json_llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="monitor_optimizer"):
            analysis = await chain.ainvoke({
                "campaign_name": campaign.name,
                "objective": campaign.objective,
                "budget": campaign.budget or 0,
                "performance_data": perf_text,
                "trend_section": trend_text,
                "recent_actions_section": actions_text,
                "upcoming_events_section": events_text
            })

        # Parse recommendations (JSON-first with fallback)
        recommendations, parse_method = self._parse_recommendations(analysis)

        # Log the optimization decision to DB
        self._log_optimization_decision(
            campaign_id=str(campaign.id),
            store_id=str(campaign.store_id) if campaign.store_id else None,
            raw_analysis=analysis,
            recommendations=recommendations,
            parse_method=parse_method
        )

        return {
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "recommendations": recommendations,
            "raw_analysis": analysis,
            "parse_method": parse_method,
            "recent_actions_count": len(recent_actions),
            "trend_analysis_included": bool(trend_data)
        }

    async def propose_rules(
        self,
        campaign: Campaign,
        performance_data: List[Dict[str, Any]],
        current_rules: List["AutomatedRule"],
        execution_history: List[Dict]
    ) -> List[Dict]:
        """
        Ask the LLM to propose new optimization rules based on observed patterns.

        Args:
            campaign: Campaign object for context
            performance_data: Recent performance metrics
            current_rules: Currently active rules
            execution_history: Recent rule execution results

        Returns:
            List of proposed rule dicts
        """
        # Format current rules
        rules_text = "\n".join([
            f"- {r.name}: {r.description or 'No description'} (triggered {r.trigger_count} times)"
            for r in current_rules
        ]) if current_rules else "No active rules."

        # Format execution history
        history_text = "\n".join([
            f"- {h.get('date', 'N/A')}: {h.get('rule', 'N/A')} -> {h.get('message', 'N/A')}"
            for h in execution_history[:15]
        ]) if execution_history else "No recent actions."

        # Format performance data
        perf_text = "\n".join([
            f"- Ad {p.get('ad_id', 'N/A')}: CTR={p.get('ctr', 0):.2f}%, CPC=${p.get('cpc', 0):.2f}, "
            f"ROAS={p.get('roas', 0):.0f}%, Spend=${p.get('spend', 0):.2f}"
            for p in performance_data[:10]
        ]) if performance_data else "No performance data."

        # Invoke LLM
        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"})
        chain = self.rule_proposal_prompt | json_llm | StrOutputParser()
        with set_ai_context(
            store_id=str(campaign.store_id) if campaign.store_id else None,
            campaign_id=str(campaign.id),
            agent_name="rule_proposer"
        ):
            response = await chain.ainvoke({
                "current_rules": rules_text,
                "execution_history": history_text,
                "performance_data": perf_text
            })

        # Parse proposals
        proposals = []
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = LLMRuleProposalResponse.model_validate_json(cleaned)
            proposals = [p.model_dump() for p in data.proposed_rules]
        except Exception:
            try:
                parsed = json.loads(cleaned)
                proposals = parsed.get("proposed_rules", [])
            except Exception as e:
                logger.error(f"[MonitorOptimizerAgent] Failed to parse rule proposals: {e}")

        # Store proposals in DB
        if proposals:
            db = SessionLocal()
            try:
                from .models import ProposedRule
                for prop in proposals:
                    db_proposal = ProposedRule(
                        campaign_id=campaign.id,
                        name=prop.get("name", "Unnamed Rule"),
                        conditions=prop.get("conditions", []),
                        action_type=prop.get("action_type", "notify"),
                        adjustment_percent=prop.get("adjustment_percent"),
                        reasoning=prop.get("reasoning", "")
                    )
                    db.add(db_proposal)
                db.commit()
                logger.info(f"[MonitorOptimizerAgent] Stored {len(proposals)} rule proposals")
            except Exception as e:
                logger.error(f"[MonitorOptimizerAgent] Failed to store proposals: {e}")
                db.rollback()
            finally:
                db.close()

        return proposals

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

        # Generate summary with JSON structured output
        from modules.openrouter.context import set_ai_context
        json_llm = self.llm.bind(response_format={"type": "json_object"})
        chain = self.summary_prompt | json_llm | StrOutputParser()
        with set_ai_context(store_id=str(campaign.store_id) if campaign.store_id else None, campaign_id=str(campaign.id), agent_name="monitor_optimizer"):
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

        # Log summary decision to DB
        self._log_optimization_decision(
            campaign_id=str(campaign.id),
            store_id=str(campaign.store_id) if campaign.store_id else None,
            raw_analysis=summary_text,
            recommendations=None,
            parse_method="json" if summary_data.get("summary") else "string_fallback",
            health_score=summary_data.get("health_score"),
            summary=summary_data.get("summary")
        )

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


# ==================== AUTOMATED RULES ENGINE ====================

class RuleType(str, Enum):
    """Types of automated rules"""
    SCALE_UP = "scale_up"       # Increase budget
    SCALE_DOWN = "scale_down"   # Decrease budget
    PAUSE = "pause"             # Pause ad/adset
    UNPAUSE = "unpause"         # Unpause ad/adset
    NOTIFY = "notify"           # Send notification only
    REFRESH_CREATIVE = "refresh_creative"  # Auto-generate new creative and swap fatigued ad


class RuleConditionOperator(str, Enum):
    """Operators for rule conditions"""
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "eq"
    NOT_EQUAL = "neq"


class RuleCondition(BaseModel):
    """Single condition for an automated rule"""
    metric: str  # roas, cpa, ctr, impressions, conversions, spend, cpc
    operator: RuleConditionOperator
    value: float
    consecutive_days: int = 1  # Number of consecutive days condition must be met


class ConditionLogic(str, Enum):
    """Logic operators for condition groups"""
    AND = "and"
    OR = "or"


class ConditionGroup(BaseModel):
    """A group of conditions joined by a logic operator, supporting nesting."""
    logic: ConditionLogic = ConditionLogic.AND
    conditions: List["RuleCondition | ConditionGroup"] = []
    negate: bool = False  # NOT operator -- inverts the group result


# Resolve forward reference for recursive nesting
ConditionGroup.model_rebuild()


class RuleAction(BaseModel):
    """Action to take when rule conditions are met"""
    type: RuleType
    adjustment_percent: Optional[float] = None  # For SCALE_UP/SCALE_DOWN
    max_budget: Optional[float] = None  # Cap for budget increases
    min_budget: Optional[float] = None  # Floor for budget decreases
    notification_message: Optional[str] = None


class AutomatedRule(BaseModel):
    """Complete automated rule definition"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    entity_type: str = "adset"  # campaign, adset, ad
    is_enabled: bool = True
    conditions: List[RuleCondition]
    action: RuleAction
    target_roas: Optional[float] = None  # Target ROAS for reference
    target_cpa: Optional[float] = None   # Target CPA for reference
    created_at: Optional[datetime] = None
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0
    condition_groups: Optional[ConditionGroup] = None  # Nested AND/OR/NOT logic (overrides flat conditions)
    cooldown_minutes: int = 60           # Minimum time between triggers for same entity
    max_triggers_per_day: int = 3        # Maximum triggers per day per entity


class RuleExecutionResult(BaseModel):
    """Result of rule execution"""
    rule_id: str
    rule_name: str
    entity_id: str
    entity_type: str
    action_taken: str
    old_value: Optional[float] = None
    new_value: Optional[float] = None
    success: bool
    message: str
    # NOTE: must be default_factory, not `datetime.utcnow()`. A plain default is
    # evaluated once at import and frozen for the process lifetime, which makes the
    # per-day throttle and daily-spend circuit breaker always see "today_count = 0".
    executed_at: datetime = Field(default_factory=datetime.utcnow)


class AutomatedRulesEngine:
    """
    Automated Rules Engine for 24/7 ad optimization.

    Evaluates rules against ad performance data and executes actions
    like scaling budgets or pausing underperforming ads.

    Built-in Rules:
    1. SCALE_UP: +20% budget when ROAS ≥ target × 1.25 for 3 consecutive days
    2. SCALE_DOWN: -50% budget when CPA > 2 × target AND 0 purchases after ≥2000 impressions
    """

    # Pre-defined rule templates
    RULE_TEMPLATES = {
        "scale_winner": {
            "name": "Scale Winners (+20%)",
            "description": "Increase budget by 20% when ROAS exceeds target by 25% for 3 consecutive days",
            "conditions": [
                {"metric": "roas", "operator": "gte", "value": 1.25, "consecutive_days": 3}
            ],
            "action": {"type": "scale_up", "adjustment_percent": 20, "max_budget": 10000},
            "cooldown_minutes": 360,
            "max_triggers_per_day": 1
        },
        "kill_loser": {
            "name": "Kill Losers (-50%)",
            "description": "Cut budget 50% when CPA > 2x target AND zero purchases after 2000+ impressions",
            "conditions": [
                {"metric": "cpa_ratio", "operator": "gt", "value": 2.0, "consecutive_days": 1},
                {"metric": "conversions", "operator": "eq", "value": 0, "consecutive_days": 1},
                {"metric": "impressions", "operator": "gte", "value": 2000, "consecutive_days": 1}
            ],
            "action": {"type": "scale_down", "adjustment_percent": 50, "min_budget": 5},
            "cooldown_minutes": 720,
            "max_triggers_per_day": 1
        },
        "pause_no_spend": {
            "name": "Pause No Spend",
            "description": "Pause ad sets with zero spend after 24 hours",
            "conditions": [
                {"metric": "spend", "operator": "eq", "value": 0, "consecutive_days": 1}
            ],
            "action": {"type": "pause"},
            "cooldown_minutes": 1440,
            "max_triggers_per_day": 1
        },
        "scale_high_ctr": {
            "name": "Scale High CTR (+15%)",
            "description": "Increase budget by 15% when CTR > 3% for 2 consecutive days",
            "conditions": [
                {"metric": "ctr", "operator": "gt", "value": 3.0, "consecutive_days": 2}
            ],
            "action": {"type": "scale_up", "adjustment_percent": 15, "max_budget": 5000},
            "cooldown_minutes": 360,
            "max_triggers_per_day": 2
        },
        "reduce_high_cpc": {
            "name": "Reduce High CPC (-25%)",
            "description": "Reduce budget by 25% when CPC > $5 for 2 consecutive days",
            "conditions": [
                {"metric": "cpc", "operator": "gt", "value": 5.0, "consecutive_days": 2}
            ],
            "action": {"type": "scale_down", "adjustment_percent": 25, "min_budget": 10},
            "cooldown_minutes": 360,
            "max_triggers_per_day": 2
        },
        "creative_fatigue": {
            "name": "Creative Fatigue Detection",
            "description": "Pause ad when frequency > 3 AND CTR declines > 30% over 3 consecutive days",
            "conditions": [
                {"metric": "frequency", "operator": "gt", "value": 3.0, "consecutive_days": 3},
                {"metric": "ctr_decline_pct", "operator": "gt", "value": 30.0, "consecutive_days": 3}
            ],
            "action": {"type": "pause", "notification_message": "Creative fatigue detected — ad paused due to high frequency and declining CTR."},
            "cooldown_minutes": 1440,
            "max_triggers_per_day": 1
        },
        "creative_fatigue_refresh": {
            "name": "Creative Fatigue Auto-Refresh",
            "description": "Auto-generate new creative when frequency > 3 AND CTR declines > 30% for 3 days. Pauses old ad, creates fresh replacement.",
            "conditions": [
                {"metric": "frequency", "operator": "gt", "value": 3.0, "consecutive_days": 3},
                {"metric": "ctr_decline_pct", "operator": "gt", "value": 30.0, "consecutive_days": 3}
            ],
            "action": {"type": "refresh_creative", "notification_message": "Creative fatigue detected — auto-refreshing with new creative."},
            "cooldown_minutes": 1440,
            "max_triggers_per_day": 1
        },
        "scale_high_lead_quality": {
            "name": "Scale High Lead Quality (+20%)",
            "description": "Increase budget by 20% when lead quality score is high for the ad set",
            "conditions": [
                {"metric": "lead_quality_score", "operator": "gte", "value": 70.0, "consecutive_days": 2},
                {"metric": "conversions", "operator": "gte", "value": 3, "consecutive_days": 2}
            ],
            "action": {"type": "scale_up", "adjustment_percent": 20, "max_budget": 10000},
            "cooldown_minutes": 360,
            "max_triggers_per_day": 1
        },
        "event_budget_boost": {
            "name": "Event Budget Boost",
            "description": "Increase budget when a high-impact event is within 3 days",
            "conditions": [
                {"metric": "days_to_next_event", "operator": "lte", "value": 3, "consecutive_days": 1},
                {"metric": "event_budget_multiplier", "operator": "gt", "value": 1.0, "consecutive_days": 1}
            ],
            "action": {"type": "scale_up", "adjustment_percent": 30, "max_budget": 15000},
            "cooldown_minutes": 1440,
            "max_triggers_per_day": 1
        },
        "prune_creative_test": {
            "name": "Prune Creative Test Losers",
            "description": "Pause ad variants with CTR < 80% of best performer after 500+ impressions",
            "conditions": [
                {"metric": "impressions", "operator": "gte", "value": 500, "consecutive_days": 1},
                {"metric": "ctr_ratio_to_best", "operator": "lt", "value": 0.8, "consecutive_days": 1}
            ],
            "action": {"type": "pause", "notification_message": "Creative test: variant paused — underperforming vs best."},
            "entity_type": "ad",
            "cooldown_minutes": 1440,
            "max_triggers_per_day": 1
        }
    }

    def __init__(self, meta_access_token: Optional[str] = None):
        self.access_token = meta_access_token or os.getenv("META_ACCESS_TOKEN")
        self.api_version = "v21.0"
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        self.rules: List[AutomatedRule] = []
        self.execution_history: List[RuleExecutionResult] = []
        logger.info("[AutomatedRulesEngine] Initialized")

    def create_rule_from_template(
        self,
        template_name: str,
        target_roas: Optional[float] = None,
        target_cpa: Optional[float] = None
    ) -> AutomatedRule:
        """Create a rule from a pre-defined template"""
        if template_name not in self.RULE_TEMPLATES:
            raise ValueError(f"Unknown template: {template_name}. Available: {list(self.RULE_TEMPLATES.keys())}")

        template = self.RULE_TEMPLATES[template_name].copy()

        # Adjust conditions based on targets
        conditions = []
        for cond in template["conditions"]:
            condition = RuleCondition(**cond)

            # Adjust ROAS condition based on target
            if condition.metric == "roas" and target_roas:
                condition.value = target_roas * condition.value

            # Adjust CPA ratio based on target
            if condition.metric == "cpa_ratio" and target_cpa:
                # Store target for evaluation
                pass

            conditions.append(condition)

        return AutomatedRule(
            id=str(uuid.uuid4()),
            name=template["name"],
            description=template["description"],
            conditions=conditions,
            action=RuleAction(**template["action"]),
            target_roas=target_roas,
            target_cpa=target_cpa,
            created_at=datetime.utcnow(),
            cooldown_minutes=template.get("cooldown_minutes", 60),
            max_triggers_per_day=template.get("max_triggers_per_day", 3)
        )

    def add_rule(self, rule: AutomatedRule) -> None:
        """Add a rule to the engine"""
        if not rule.id:
            rule.id = str(uuid.uuid4())
        self.rules.append(rule)
        logger.info(f"[AutomatedRulesEngine] Added rule: {rule.name}")

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID"""
        for i, rule in enumerate(self.rules):
            if rule.id == rule_id:
                self.rules.pop(i)
                logger.info(f"[AutomatedRulesEngine] Removed rule: {rule_id}")
                return True
        return False

    def get_performance_history(
        self,
        entity_id: str,
        entity_type: str,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Get performance history for an entity from database.

        Returns daily aggregated metrics for the past N days.
        """
        db = SessionLocal()
        try:
            from modules.marketing.models import MetaAdInsight, MetaAd, MetaAdSet

            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            history = []

            if entity_type == "adset":
                # Get all ads in the adset and aggregate their insights
                adset = db.query(MetaAdSet).filter(MetaAdSet.adset_id == entity_id).first()
                if not adset:
                    return []

                ads = db.query(MetaAd).filter(MetaAd.adset_id == adset.id).all()
                ad_ids = [ad.id for ad in ads]

                # Group insights by date
                from sqlalchemy import func
                insights = db.query(
                    func.date(MetaAdInsight.date).label('date'),
                    func.sum(MetaAdInsight.impressions).label('impressions'),
                    func.sum(MetaAdInsight.clicks).label('clicks'),
                    func.sum(MetaAdInsight.spend).label('spend'),
                    func.sum(MetaAdInsight.conversions).label('conversions'),
                    func.sum(MetaAdInsight.revenue).label('revenue')
                ).filter(
                    MetaAdInsight.ad_id.in_(ad_ids),
                    MetaAdInsight.date >= start_date,
                    MetaAdInsight.date <= end_date
                ).group_by(func.date(MetaAdInsight.date)).order_by(func.date(MetaAdInsight.date).desc()).all()

                for insight in insights:
                    impressions = insight.impressions or 0
                    clicks = insight.clicks or 0
                    spend = insight.spend or 0
                    conversions = insight.conversions or 0
                    revenue = insight.revenue or 0

                    ctr = (clicks / impressions * 100) if impressions > 0 else 0
                    cpc = (spend / clicks) if clicks > 0 else 0
                    cpa = (spend / conversions) if conversions > 0 else float('inf')
                    roas = (revenue / spend) if spend > 0 else 0

                    history.append({
                        "date": insight.date,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": spend,
                        "conversions": conversions,
                        "revenue": revenue,
                        "ctr": ctr,
                        "cpc": cpc,
                        "cpa": cpa,
                        "roas": roas
                    })

            elif entity_type == "ad":
                ad = db.query(MetaAd).filter(MetaAd.ad_id == entity_id).first()
                if not ad:
                    return []

                insights = db.query(MetaAdInsight).filter(
                    MetaAdInsight.ad_id == ad.id,
                    MetaAdInsight.date >= start_date,
                    MetaAdInsight.date <= end_date
                ).order_by(MetaAdInsight.date.desc()).all()

                for insight in insights:
                    impressions = insight.impressions or 0
                    clicks = insight.clicks or 0
                    spend = insight.spend or 0
                    conversions = insight.conversions or 0
                    revenue = insight.revenue or 0

                    history.append({
                        "date": insight.date,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": spend,
                        "conversions": conversions,
                        "revenue": revenue,
                        "ctr": insight.ctr or 0,
                        "cpc": insight.cpc or 0,
                        "cpa": insight.cost_per_conversion or 0,
                        "roas": (revenue / spend) if spend > 0 else 0
                    })

            return history

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Error getting performance history: {e}")
            return []
        finally:
            db.close()

    def evaluate_condition(
        self,
        condition: RuleCondition,
        performance_history: List[Dict[str, Any]],
        target_roas: Optional[float] = None,
        target_cpa: Optional[float] = None,
        entity_id: Optional[str] = None
    ) -> bool:
        """
        Evaluate a single condition against performance history.

        Returns True if condition is met for the required consecutive days.
        """
        if len(performance_history) < condition.consecutive_days:
            return False

        # Check the required number of consecutive days
        for i in range(condition.consecutive_days):
            if i >= len(performance_history):
                return False

            day_data = performance_history[i]
            metric_value = day_data.get(condition.metric, 0)

            # Handle computed metric: CTR decline percentage
            # Compares current day's CTR against the earliest day in the window
            if condition.metric == "ctr_decline_pct":
                if len(performance_history) < 2:
                    return False
                baseline_ctr = performance_history[-1].get("ctr", 0)  # Earliest day
                current_ctr = day_data.get("ctr", 0)
                if baseline_ctr > 0:
                    metric_value = ((baseline_ctr - current_ctr) / baseline_ctr) * 100
                else:
                    metric_value = 0

            # Handle computed metric: Event-aware metrics
            if condition.metric in ("days_to_next_event", "event_budget_multiplier", "is_event_active"):
                try:
                    from .calendar_engine import get_current_event_context
                    event_ctx = getattr(self, '_event_context', None)
                    if not event_ctx:
                        country = getattr(self, '_current_country_code', 'US')
                        store = getattr(self, '_current_store_id', None)
                        event_ctx = get_current_event_context(country, store)
                        self._event_context = event_ctx  # Cache for this cycle
                    metric_value = event_ctx.get(condition.metric, 0)
                except Exception:
                    metric_value = 999 if condition.metric == "days_to_next_event" else 0

            # Handle computed metric: CTR ratio to best in creative test group
            if condition.metric == "ctr_ratio_to_best":
                best_ctr = self._get_best_ctr_in_test(entity_id)
                current_ctr = day_data.get("ctr", 0)
                metric_value = current_ctr / best_ctr if best_ctr > 0 else 1.0

            # Handle computed metric: Composite optimization score
            if condition.metric == "composite_score":
                metric_value = self.compute_composite_score(day_data)

            # Handle computed metric: Lead quality score from WhatsApp leads
            if condition.metric == "lead_quality_score":
                lead_signal = self.get_lead_quality_signal("")
                metric_value = lead_signal.get("average_score", 0)

            # Handle special metrics
            if condition.metric == "cpa_ratio" and target_cpa:
                actual_cpa = day_data.get("cpa", float('inf'))
                metric_value = actual_cpa / target_cpa if target_cpa > 0 else float('inf')

            if condition.metric == "roas_ratio" and target_roas:
                actual_roas = day_data.get("roas", 0)
                metric_value = actual_roas / target_roas if target_roas > 0 else 0

            # Evaluate the condition
            threshold = condition.value

            if condition.operator == RuleConditionOperator.GREATER_THAN:
                if not (metric_value > threshold):
                    return False
            elif condition.operator == RuleConditionOperator.GREATER_THAN_OR_EQUAL:
                if not (metric_value >= threshold):
                    return False
            elif condition.operator == RuleConditionOperator.LESS_THAN:
                if not (metric_value < threshold):
                    return False
            elif condition.operator == RuleConditionOperator.LESS_THAN_OR_EQUAL:
                if not (metric_value <= threshold):
                    return False
            elif condition.operator == RuleConditionOperator.EQUAL:
                if not (metric_value == threshold):
                    return False
            elif condition.operator == RuleConditionOperator.NOT_EQUAL:
                if not (metric_value != threshold):
                    return False

        return True

    def evaluate_condition_group(
        self,
        group: ConditionGroup,
        performance_history: List[Dict[str, Any]],
        target_roas: Optional[float] = None,
        target_cpa: Optional[float] = None,
        entity_id: Optional[str] = None
    ) -> bool:
        """Recursively evaluate a condition group with AND/OR/NOT logic."""
        results = []
        for item in group.conditions:
            if isinstance(item, ConditionGroup):
                result = self.evaluate_condition_group(item, performance_history, target_roas, target_cpa, entity_id)
            else:
                result = self.evaluate_condition(item, performance_history, target_roas, target_cpa, entity_id)
            results.append(result)

        if not results:
            return True  # empty group passes

        if group.logic == ConditionLogic.AND:
            combined = all(results)
        else:  # OR
            combined = any(results)

        return not combined if group.negate else combined

    def evaluate_rule(
        self,
        rule: AutomatedRule,
        entity_id: str,
        performance_history: List[Dict[str, Any]]
    ) -> bool:
        """
        Evaluate if a rule should be triggered for an entity.

        Uses nested condition_groups if available (AND/OR/NOT),
        otherwise falls back to flat conditions list (AND logic).
        """
        if not rule.is_enabled:
            return False

        if not performance_history:
            return False

        # Use nested groups if available
        if rule.condition_groups:
            return self.evaluate_condition_group(
                rule.condition_groups, performance_history,
                rule.target_roas, rule.target_cpa, entity_id
            )

        # Legacy: flat conditions list = AND
        for condition in rule.conditions:
            if not self.evaluate_condition(
                condition,
                performance_history,
                rule.target_roas,
                rule.target_cpa,
                entity_id
            ):
                return False

        return True

    async def execute_action(
        self,
        rule: AutomatedRule,
        entity_id: str,
        entity_type: str,
        current_budget: float,
        dry_run: bool = False
    ) -> RuleExecutionResult:
        """
        Execute the action specified by a rule.

        Supports:
        - SCALE_UP: Increase budget by specified percentage
        - SCALE_DOWN: Decrease budget by specified percentage
        - PAUSE: Pause the entity
        - UNPAUSE: Unpause the entity
        """
        action = rule.action
        result = RuleExecutionResult(
            rule_id=rule.id,
            rule_name=rule.name,
            entity_id=entity_id,
            entity_type=entity_type,
            action_taken=action.type.value,
            old_value=current_budget,
            success=False,
            message=""
        )

        dry_prefix = "[DRY RUN] " if dry_run else ""

        try:
            if action.type == RuleType.SCALE_UP:
                # Calculate new budget
                adjustment = current_budget * (action.adjustment_percent / 100)
                new_budget = current_budget + adjustment

                # Apply max cap if specified
                if action.max_budget and new_budget > action.max_budget:
                    new_budget = action.max_budget

                # Update via Meta API (skip in dry run)
                if not dry_run:
                    success = await self._update_entity_budget(entity_id, entity_type, new_budget)
                else:
                    success = True

                result.new_value = new_budget
                result.success = success
                result.message = f"{dry_prefix}Budget increased from ${current_budget:.2f} to ${new_budget:.2f} (+{action.adjustment_percent}%)"

            elif action.type == RuleType.SCALE_DOWN:
                # Calculate new budget
                adjustment = current_budget * (action.adjustment_percent / 100)
                new_budget = current_budget - adjustment

                # Apply min floor if specified
                if action.min_budget and new_budget < action.min_budget:
                    new_budget = action.min_budget

                # Ensure budget doesn't go negative
                new_budget = max(new_budget, 1)

                # Update via Meta API (skip in dry run)
                if not dry_run:
                    success = await self._update_entity_budget(entity_id, entity_type, new_budget)
                else:
                    success = True

                result.new_value = new_budget
                result.success = success
                result.message = f"{dry_prefix}Budget decreased from ${current_budget:.2f} to ${new_budget:.2f} (-{action.adjustment_percent}%)"

            elif action.type == RuleType.PAUSE:
                if not dry_run:
                    success = await self._update_entity_status(entity_id, entity_type, "PAUSED")
                else:
                    success = True
                result.success = success
                result.message = f"{dry_prefix}{entity_type.title()} paused due to rule: {rule.name}"

            elif action.type == RuleType.UNPAUSE:
                if not dry_run:
                    success = await self._update_entity_status(entity_id, entity_type, "ACTIVE")
                else:
                    success = True
                result.success = success
                result.message = f"{dry_prefix}{entity_type.title()} unpaused due to rule: {rule.name}"

            elif action.type == RuleType.NOTIFY:
                result.success = True
                result.message = f"{dry_prefix}{action.notification_message or f'Rule triggered: {rule.name}'}"

            elif action.type == RuleType.REFRESH_CREATIVE:
                if not dry_run:
                    # Use multi-variant creative test (generates 3-5 variants, keeps original)
                    refresh_result = await self._refresh_creative_multi_variant(entity_id, entity_type)
                    if not refresh_result.get("success"):
                        # Fallback to single refresh if multi-variant fails
                        logger.warning("[AutomatedRulesEngine] Multi-variant failed, falling back to single refresh")
                        refresh_result = await self._refresh_creative(entity_id, entity_type)
                    result.success = refresh_result.get("success", False)
                    result.message = refresh_result.get("message", "Creative refresh attempted")
                else:
                    result.success = True
                    result.message = f"{dry_prefix}Creative test would be triggered for {entity_type} {entity_id} (3-5 variants)"

            # Update rule stats (skip in dry run to avoid side effects)
            if not dry_run:
                rule.last_triggered = datetime.utcnow()
                rule.trigger_count += 1

        except Exception as e:
            result.success = False
            result.message = f"Action failed: {str(e)}"
            logger.error(f"[AutomatedRulesEngine] Action execution failed: {e}")

        # Store in both in-memory cache and DB
        self.execution_history.append(result)

        # Log to AI Decision Audit Trail
        try:
            from .meta_learner import log_ai_decision
            log_ai_decision(
                decision_type="rule_execution",
                agent_name="rules_engine",
                input_context={
                    "entity": entity_id, "entity_type": entity_type,
                    "rule": rule.name, "current_budget": current_budget,
                    "dry_run": dry_run
                },
                decision={
                    "action": result.action_taken,
                    "old_value": result.old_value,
                    "new_value": result.new_value,
                    "success": result.success
                },
                reasoning=result.message,
                confidence=1.0 if not dry_run else 0.0,
                ad_account_id=getattr(self, '_current_ad_account_id', None)
            )
        except Exception:
            pass  # Don't fail execution over logging

        return result

    # ============ Persistent Execution Logging ============

    def _log_execution(
        self,
        ad_account_id: str,
        result: RuleExecutionResult,
        rollback_eligible: bool = False,
        performance_snapshot: Optional[Dict] = None,
        rollback_hours: int = 6,
        is_simulation: bool = False
    ) -> None:
        """Persist a rule execution result to the database."""
        db = SessionLocal()
        try:
            from .models import RuleExecutionLog
            log = RuleExecutionLog(
                ad_account_id=ad_account_id,
                rule_id=result.rule_id,
                rule_name=result.rule_name,
                entity_id=result.entity_id,
                entity_type=result.entity_type,
                action_taken=result.action_taken,
                old_value=result.old_value,
                new_value=result.new_value,
                success=result.success,
                message=result.message,
                is_simulation=is_simulation,
                rollback_eligible=rollback_eligible and result.success,
                rollback_check_at=(
                    datetime.utcnow() + timedelta(hours=rollback_hours)
                ) if rollback_eligible and result.success else None,
                performance_at_action=performance_snapshot,
                executed_at=result.executed_at
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Failed to log execution: {e}")
            db.rollback()
        finally:
            db.close()

    # ============ Circuit Breakers ============

    def check_circuit_breakers(self, ad_account_id: str) -> Tuple[bool, str]:
        """
        Check if any circuit breaker is tripped for this ad account.

        Checks:
        1. Manual trip state (with auto-reset expiry)
        2. Daily spend cap
        3. Data freshness

        Returns: (is_safe_to_proceed, reason_if_blocked)
        """
        db = SessionLocal()
        try:
            from .models import CircuitBreakerState, RuleExecutionLog
            from modules.marketing.models import MetaAdAccount

            # Get or create circuit breaker state
            cb = db.query(CircuitBreakerState).filter(
                CircuitBreakerState.ad_account_id == ad_account_id
            ).first()

            if not cb:
                cb = CircuitBreakerState(ad_account_id=ad_account_id)
                db.add(cb)
                db.commit()
                db.refresh(cb)

            # Check if manually tripped and not auto-reset yet
            if cb.is_tripped:
                if cb.auto_reset_at and datetime.utcnow() > cb.auto_reset_at:
                    cb.is_tripped = False
                    cb.trip_reason = None
                    db.commit()
                else:
                    return False, f"Circuit breaker tripped: {cb.trip_reason}"

            # 1. Daily spend cap check
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_logs = db.query(RuleExecutionLog).filter(
                RuleExecutionLog.ad_account_id == ad_account_id,
                RuleExecutionLog.executed_at >= today_start,
                RuleExecutionLog.success == True,
                RuleExecutionLog.action_taken.in_(["scale_up"])
            ).all()
            total_new_budgets = sum(log.new_value or 0 for log in today_logs)
            if total_new_budgets > cb.daily_spend_cap:
                cb.is_tripped = True
                cb.trip_reason = f"Daily spend cap exceeded: ${total_new_budgets:.2f} > ${cb.daily_spend_cap:.2f}"
                cb.tripped_at = datetime.utcnow()
                cb.auto_reset_at = today_start + timedelta(days=1)
                db.commit()
                logger.warning(f"[CircuitBreaker] {cb.trip_reason}")
                return False, cb.trip_reason

            # 2. Data freshness check
            account = db.query(MetaAdAccount).filter(
                MetaAdAccount.ad_account_id == ad_account_id
            ).first()
            if account and account.last_synced_at:
                hours_since_sync = (datetime.utcnow() - account.last_synced_at).total_seconds() / 3600
                if hours_since_sync > cb.data_freshness_hours:
                    return False, f"Data stale: last sync {hours_since_sync:.1f}h ago (limit: {cb.data_freshness_hours}h)"

            return True, ""

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Circuit breaker check error: {e}")
            return True, ""  # Fail open to avoid blocking all operations
        finally:
            db.close()

    def _check_volatility(self, entity_id: str, entity_type: str, threshold_pct: float = 50.0) -> bool:
        """Check if key metrics changed >threshold% in 24h. Returns True if volatile."""
        history = self.get_performance_history(entity_id, entity_type, days=2)
        if len(history) < 2:
            return False

        today = history[0]
        yesterday = history[1]

        for metric in ["ctr", "cpc", "cpa", "spend"]:
            old_val = yesterday.get(metric, 0)
            new_val = today.get(metric, 0)
            if old_val > 0:
                pct_change = abs(new_val - old_val) / old_val * 100
                if pct_change > threshold_pct:
                    logger.warning(
                        f"[CircuitBreaker] Volatility detected: {metric} changed {pct_change:.1f}% "
                        f"for {entity_type} {entity_id}"
                    )
                    return True
        return False

    # ============ Cooldown & Throttling ============

    def _check_cooldown_and_throttle(self, rule: AutomatedRule, entity_id: str) -> Tuple[bool, str]:
        """
        Check if a rule can fire for this entity based on cooldown and daily limits.

        Returns: (can_fire, reason_if_blocked)
        """
        # 1. Cooldown check using in-memory last_triggered
        if rule.last_triggered:
            elapsed_min = (datetime.utcnow() - rule.last_triggered).total_seconds() / 60
            if elapsed_min < rule.cooldown_minutes:
                remaining = rule.cooldown_minutes - elapsed_min
                return False, f"Cooldown: {remaining:.0f}min remaining"

        # 2. Daily throttle: count today's triggers from execution log
        db = SessionLocal()
        try:
            from .models import RuleExecutionLog
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(RuleExecutionLog).filter(
                RuleExecutionLog.rule_id == rule.id,
                RuleExecutionLog.entity_id == entity_id,
                RuleExecutionLog.executed_at >= today_start,
                RuleExecutionLog.success == True
            ).count()

            if today_count >= rule.max_triggers_per_day:
                return False, f"Throttled: {today_count}/{rule.max_triggers_per_day} triggers today"

            return True, ""

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Cooldown check error: {e}")
            return True, ""  # Fail open
        finally:
            db.close()

    # ============ Rollback Mechanism ============

    async def check_rollbacks(self, roas_decline_threshold_pct: float = 30.0) -> List[Dict]:
        """
        Check all rollback-eligible executions that are past their check time.
        If performance degraded, revert the budget change.

        Returns list of rollback actions taken.
        """
        db = SessionLocal()
        rollback_results = []
        try:
            from .models import RuleExecutionLog

            eligible = db.query(RuleExecutionLog).filter(
                RuleExecutionLog.rollback_eligible == True,
                RuleExecutionLog.rollback_checked == False,
                RuleExecutionLog.rollback_check_at <= datetime.utcnow(),
                RuleExecutionLog.success == True
            ).all()

            for log in eligible:
                log.rollback_checked = True

                # Get current performance
                current_history = self.get_performance_history(log.entity_id, log.entity_type, days=1)
                if not current_history:
                    continue

                current_perf = current_history[0]
                snapshot = log.performance_at_action or {}

                should_rollback = False
                reason = ""

                # Compare ROAS
                old_roas = snapshot.get("roas", 0)
                new_roas = current_perf.get("roas", 0)
                if old_roas > 0:
                    roas_change = ((new_roas - old_roas) / old_roas) * 100
                    if roas_change < -roas_decline_threshold_pct:
                        should_rollback = True
                        reason = f"ROAS declined {roas_change:.1f}% (from {old_roas:.2f} to {new_roas:.2f})"

                # Also check CPA spike (>50% increase)
                old_cpa = snapshot.get("cpa", 0)
                new_cpa = current_perf.get("cpa", 0)
                if not should_rollback and old_cpa > 0 and new_cpa > old_cpa * 1.5:
                    should_rollback = True
                    reason = f"CPA spiked {((new_cpa - old_cpa) / old_cpa * 100):.1f}% (from ${old_cpa:.2f} to ${new_cpa:.2f})"

                if should_rollback and log.old_value is not None:
                    # Revert budget
                    success = await self._update_entity_budget(
                        log.entity_id, log.entity_type, log.old_value
                    )
                    log.rollback_executed = True

                    rollback_results.append({
                        "entity_id": log.entity_id,
                        "entity_type": log.entity_type,
                        "reverted_from": log.new_value,
                        "reverted_to": log.old_value,
                        "reason": reason,
                        "success": success
                    })

                    # Log the rollback as a new execution entry
                    self._log_execution(
                        ad_account_id=log.ad_account_id,
                        result=RuleExecutionResult(
                            rule_id=log.rule_id,
                            rule_name=f"ROLLBACK: {log.rule_name}",
                            entity_id=log.entity_id,
                            entity_type=log.entity_type,
                            action_taken="rollback",
                            old_value=log.new_value,
                            new_value=log.old_value,
                            success=success,
                            message=f"Rollback: {reason}"
                        ),
                        rollback_eligible=False
                    )

                    logger.info(
                        f"[AutomatedRulesEngine] Rollback: {log.entity_type} {log.entity_id} "
                        f"budget reverted from ${log.new_value:.2f} to ${log.old_value:.2f} - {reason}"
                    )

            db.commit()
        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Rollback check error: {e}")
            db.rollback()
        finally:
            db.close()

        return rollback_results

    async def _update_entity_budget(
        self,
        entity_id: str,
        entity_type: str,
        new_budget: float
    ) -> bool:
        """Update entity budget via Meta Marketing API"""
        if not self.access_token:
            # This is a real (non-dry-run) execution path. With no token we cannot
            # change anything on Meta, so report failure rather than a fake success
            # that would corrupt the audit trail and spend accounting.
            logger.error("[AutomatedRulesEngine] No Meta access token; budget update NOT applied")
            return False

        try:
            endpoint = f"{self.base_url}/{entity_id}"

            # Budget is in cents for Meta API
            budget_cents = int(new_budget * 100)

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    endpoint,
                    params={
                        "access_token": self.access_token,
                        "daily_budget": budget_cents
                    }
                )

                if response.status_code == 200:
                    logger.info(f"[AutomatedRulesEngine] Updated {entity_type} {entity_id} budget to ${new_budget:.2f}")
                    return True
                else:
                    logger.error(f"[AutomatedRulesEngine] Failed to update budget: {response.text}")
                    return False

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] API error updating budget: {e}")
            return False

    async def _update_entity_status(
        self,
        entity_id: str,
        entity_type: str,
        status: str
    ) -> bool:
        """Update entity status (ACTIVE/PAUSED) via Meta Marketing API"""
        if not self.access_token:
            # Real execution path; with no token nothing changes on Meta. Report
            # failure instead of a fake success (see _update_entity_budget).
            logger.error("[AutomatedRulesEngine] No Meta access token; status update NOT applied")
            return False

        try:
            endpoint = f"{self.base_url}/{entity_id}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    endpoint,
                    params={
                        "access_token": self.access_token,
                        "status": status
                    }
                )

                if response.status_code == 200:
                    logger.info(f"[AutomatedRulesEngine] Updated {entity_type} {entity_id} status to {status}")
                    return True
                else:
                    logger.error(f"[AutomatedRulesEngine] Failed to update status: {response.text}")
                    return False

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] API error updating status: {e}")
            return False

    async def _refresh_creative_multi_variant(self, entity_id: str, entity_type: str) -> Dict[str, Any]:
        """
        Multi-variant creative refresh: generate 3-5 variants in the same ad set.
        Keeps the original ad running as baseline. Meta distributes impressions.
        The prune_creative_test rule will later pause underperformers.
        """
        db = SessionLocal()
        try:
            from modules.marketing.models import MetaAd, MetaAdSet, MetaAdAccount
            from modules.marketing.router import create_meta_ad

            # Get the fatigued ad
            ad = db.query(MetaAd).filter(MetaAd.ad_id == entity_id).first()
            if not ad:
                return {"success": False, "message": f"Ad {entity_id} not found"}

            adset = db.query(MetaAdSet).filter(MetaAdSet.id == ad.adset_id).first()
            if not adset:
                return {"success": False, "message": f"Ad set not found for ad {entity_id}"}

            ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == ad.ad_account_id).first()
            if not ad_account:
                return {"success": False, "message": "Ad account not found"}

            # Generate multiple ad copy variations
            try:
                from modules.agents.ad_copy_agent import AdCopyAgent
                ad_agent = AdCopyAgent()

                research_data = {
                    "extracted_data": {
                        "company_info": {"name": ad.name.split(" - ")[0] if " - " in ad.name else ad.name},
                        "services_products": [],
                    },
                    "research_summary": {"company_name": ad.name}
                }
                audience = {"name": adset.name, "type": "B2C", "demographics": "Target audience"}

                new_copy = await ad_agent.generate_b2c_ad_copy(research_data, audience, "facebook")

                if not new_copy or not new_copy.get("variations"):
                    return {"success": False, "message": "Failed to generate ad copy variations"}

                variations = new_copy["variations"]
                if isinstance(variations, list):
                    variations = variations[:4]  # Cap at 4 new variants
                else:
                    return {"success": False, "message": "Invalid variations format"}

            except Exception as e:
                logger.error(f"[AutomatedRulesEngine] Multi-variant copy generation failed: {e}")
                return {"success": False, "message": f"Copy generation failed: {str(e)}"}

            # DO NOT pause the original — keep as baseline
            facebook_page_id = ad_account.business_id

            # Create a creative test record
            from .models import CreativeTest, CreativeTestVariant
            test = CreativeTest(
                ad_account_id=ad_account.ad_account_id,
                adset_id=adset.adset_id,
                campaign_id=str(ad.campaign_id) if ad.campaign_id else None,
                original_ad_id=entity_id,
                num_variants=len(variations) + 1,  # +1 for original
                status="running"
            )
            db.add(test)
            db.flush()  # Get test.id

            # Add original as variant 0
            original_variant = CreativeTestVariant(
                test_id=test.id,
                ad_id=entity_id,
                variant_number=0,
                headline=ad.name,
                is_original=True,
                status="active"
            )
            db.add(original_variant)

            # Create new ads for each variation
            created_ads = []
            for i, variation in enumerate(variations):
                new_headline = variation.get("headline", f"Variant {i + 1}")
                new_primary_text = variation.get("primary_text", "")
                new_description = variation.get("description", "")

                # Optionally generate image for each variant
                new_image_url = None
                try:
                    from modules.agents.media_generator_agent import MediaGeneratorAgent
                    media_agent = MediaGeneratorAgent()
                    image_result = await media_agent.generate_image(
                        prompt=f"Professional advertising image for: {new_headline}. {new_primary_text[:200]}",
                        style="photorealistic",
                        aspect_ratio="1:1"
                    )
                    if image_result and image_result.get("success"):
                        new_image_url = image_result.get("image_url") or image_result.get("url")
                except Exception:
                    pass  # Continue without image

                # Create ad via Meta API
                try:
                    link_data = {
                        "message": new_primary_text,
                        "name": new_headline,
                        "description": new_description,
                        "call_to_action": {"type": "LEARN_MORE"}
                    }
                    if new_image_url:
                        link_data["picture"] = new_image_url

                    meta_ad_data = {
                        "name": f"{adset.name} - Test V{i + 1}",
                        "adset_id": adset.adset_id,
                        "status": "ACTIVE",
                        "creative": json.dumps({
                            "object_story_spec": {
                                "page_id": facebook_page_id,
                                "link_data": link_data
                            }
                        })
                    }

                    meta_ad_result = create_meta_ad(
                        ad_account.ad_account_id,
                        ad_account.access_token,
                        meta_ad_data
                    )
                    new_ad_id = meta_ad_result.get("id", f"sim_{uuid.uuid4().hex[:8]}")

                    # Save to DB
                    new_db_ad = MetaAd(
                        ad_id=new_ad_id,
                        ad_account_id=ad_account.id,
                        adset_id=adset.id,
                        campaign_id=ad.campaign_id,
                        name=f"{adset.name} - Test V{i + 1}",
                        status="ACTIVE",
                        effective_status="ACTIVE",
                        created_time=datetime.utcnow(),
                        updated_time=datetime.utcnow(),
                        is_active=True
                    )
                    db.add(new_db_ad)

                    # Add as test variant
                    variant_record = CreativeTestVariant(
                        test_id=test.id,
                        ad_id=new_ad_id,
                        variant_number=i + 1,
                        headline=new_headline,
                        primary_text=new_primary_text,
                        image_url=new_image_url,
                        is_original=False,
                        status="active"
                    )
                    db.add(variant_record)

                    created_ads.append({
                        "ad_id": new_ad_id,
                        "headline": new_headline,
                        "has_image": bool(new_image_url)
                    })

                except Exception as e:
                    logger.error(f"[AutomatedRulesEngine] Failed to create variant {i + 1}: {e}")

            db.commit()

            logger.info(
                f"[AutomatedRulesEngine] Creative test started: {len(created_ads)} variants + original "
                f"in ad set {adset.adset_id}, test_id={test.id}"
            )

            return {
                "success": True,
                "message": f"Creative test started: {len(created_ads)} new variants created alongside original",
                "test_id": str(test.id),
                "variants_created": len(created_ads),
                "original_kept_running": True,
                "new_ads": created_ads
            }

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Multi-variant creative refresh failed: {e}")
            db.rollback()
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    async def _refresh_creative(self, entity_id: str, entity_type: str) -> Dict[str, Any]:
        """
        Auto-refresh creative for a fatigued ad.

        Steps:
        1. Get the current ad's content (headline, text, description)
        2. Generate new ad copy via AdCopyAgent
        3. Create new Meta ad creative + ad in the same ad set
        4. Pause the old ad

        Returns:
            Dict with success status and message
        """
        db = SessionLocal()
        try:
            from modules.marketing.models import MetaAd, MetaAdSet, MetaAdCreative, MetaAdAccount
            from modules.marketing.router import create_meta_ad, create_meta_adcreative

            # Get the fatigued ad
            ad = db.query(MetaAd).filter(MetaAd.ad_id == entity_id).first()
            if not ad:
                return {"success": False, "message": f"Ad {entity_id} not found"}

            adset = db.query(MetaAdSet).filter(MetaAdSet.id == ad.adset_id).first()
            if not adset:
                return {"success": False, "message": f"Ad set not found for ad {entity_id}"}

            ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == ad.ad_account_id).first()
            if not ad_account:
                return {"success": False, "message": "Ad account not found"}

            # Generate new ad copy using AdCopyAgent
            try:
                from modules.agents.ad_copy_agent import AdCopyAgent
                ad_agent = AdCopyAgent()

                # Build context from existing ad
                research_data = {
                    "extracted_data": {
                        "company_info": {"name": ad.name.split(" - ")[0] if " - " in ad.name else ad.name},
                        "services_products": [],
                    },
                    "research_summary": {"company_name": ad.name}
                }

                audience = {
                    "name": adset.name,
                    "type": "B2C",
                    "demographics": "Target audience",
                }

                new_copy = await ad_agent.generate_b2c_ad_copy(research_data, audience, "facebook")

                if not new_copy or not new_copy.get("variations"):
                    return {"success": False, "message": "Failed to generate new ad copy"}

                # Get the first variation
                variation = new_copy["variations"][0] if isinstance(new_copy.get("variations"), list) else {}
                new_headline = variation.get("headline", ad.name)
                new_primary_text = variation.get("primary_text", "")
                new_description = variation.get("description", "")

            except Exception as e:
                logger.error(f"[AutomatedRulesEngine] Ad copy generation failed: {e}")
                return {"success": False, "message": f"Copy generation failed: {str(e)}"}

            # Pause the old ad
            await self._update_entity_status(entity_id, "ad", "PAUSED")
            ad.status = "PAUSED"
            ad.effective_status = "PAUSED"

            # Generate new image if possible
            new_image_url = None
            try:
                from modules.agents.media_generator_agent import MediaGeneratorAgent
                media_agent = MediaGeneratorAgent()

                # Build image prompt from new copy + ad set context
                image_prompt = (
                    f"Professional advertising image for: {new_headline}. "
                    f"{new_primary_text[:200] if new_primary_text else adset.name}"
                )

                # Try to get store_id from campaign for brand awareness
                store_id = None
                try:
                    from modules.campaigns.models import Campaign as URLCampaign
                    url_campaign = db.query(URLCampaign).filter(
                        URLCampaign.platform_campaign_ids.contains({"meta": str(ad.campaign_id)})
                    ).first()
                    if url_campaign:
                        store_id = str(url_campaign.store_id)
                except Exception:
                    pass

                image_result = await media_agent.generate_image(
                    prompt=image_prompt,
                    style="photorealistic",
                    aspect_ratio="1:1",
                    store_id=store_id
                )

                if image_result and image_result.get("success"):
                    new_image_url = image_result.get("image_url") or image_result.get("url")
                    logger.info(f"[AutomatedRulesEngine] Generated new image for refreshed ad")
                else:
                    logger.warning("[AutomatedRulesEngine] Image generation failed, creating ad with text only")

            except Exception as img_err:
                logger.warning(f"[AutomatedRulesEngine] Image generation skipped: {img_err}")

            # Create new ad with refreshed copy + image
            try:
                import json
                # Get the page ID from existing ad's creative or use business_id
                facebook_page_id = ad_account.business_id

                link_data = {
                    "message": new_primary_text,
                    "name": new_headline,
                    "description": new_description,
                    "call_to_action": {"type": "LEARN_MORE"}
                }

                # Include new image if generated
                if new_image_url:
                    link_data["picture"] = new_image_url

                meta_ad_data = {
                    "name": f"{adset.name} - Refreshed Ad",
                    "adset_id": adset.adset_id,
                    "status": "ACTIVE",
                    "creative": json.dumps({
                        "object_story_spec": {
                            "page_id": facebook_page_id,
                            "link_data": link_data
                        }
                    })
                }

                meta_ad_result = create_meta_ad(
                    ad_account.ad_account_id,
                    ad_account.access_token,
                    meta_ad_data
                )

                new_ad_id = meta_ad_result.get("id")

                # Save new ad to database
                new_db_ad = MetaAd(
                    ad_id=new_ad_id,
                    ad_account_id=ad_account.id,
                    adset_id=adset.id,
                    campaign_id=ad.campaign_id,
                    name=f"{adset.name} - Refreshed Ad",
                    status="ACTIVE",
                    effective_status="ACTIVE",
                    created_time=datetime.utcnow(),
                    updated_time=datetime.utcnow(),
                    is_active=True
                )
                db.add(new_db_ad)
                db.commit()

                logger.info(
                    f"[AutomatedRulesEngine] Creative refresh: paused {entity_id}, "
                    f"created new ad {new_ad_id} (new_image={'yes' if new_image_url else 'no'})"
                )

                return {
                    "success": True,
                    "message": f"Creative refreshed: old ad {entity_id} paused, new ad {new_ad_id} created",
                    "old_ad_id": entity_id,
                    "new_ad_id": new_ad_id,
                    "new_image_generated": bool(new_image_url)
                }

            except Exception as e:
                logger.error(f"[AutomatedRulesEngine] Failed to create refreshed ad: {e}")
                return {"success": False, "message": f"Failed to create refreshed ad: {str(e)}"}

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Creative refresh failed: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_lead_quality_signal(self, ad_account_id: str) -> Dict[str, Any]:
        """
        Get lead quality signal from WhatsApp leads for an ad account.

        Queries WhatsAppLead model to compute average lead quality score
        for leads generated in the last 7 days.

        Returns:
            Dict with average_score, hot_leads, warm_leads, total_leads
        """
        db = SessionLocal()
        try:
            from modules.whatsapp.models import WhatsAppLead
            from sqlalchemy import func

            seven_days_ago = datetime.utcnow() - timedelta(days=7)

            # Get recent leads
            leads = db.query(WhatsAppLead).filter(
                WhatsAppLead.created_at >= seven_days_ago
            ).all()

            if not leads:
                return {
                    "average_score": 0,
                    "hot_leads": 0,
                    "warm_leads": 0,
                    "cool_leads": 0,
                    "total_leads": 0
                }

            scores = [lead.lead_score or 0 for lead in leads]
            avg_score = sum(scores) / len(scores) if scores else 0

            hot = sum(1 for s in scores if s >= 70)
            warm = sum(1 for s in scores if 40 <= s < 70)
            cool = sum(1 for s in scores if s < 40)

            return {
                "average_score": round(avg_score, 1),
                "hot_leads": hot,
                "warm_leads": warm,
                "cool_leads": cool,
                "total_leads": len(leads),
                "conversion_rate": round((hot / len(leads)) * 100, 1) if leads else 0
            }

        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Lead quality signal error: {e}")
            return {"average_score": 0, "total_leads": 0, "error": str(e)}
        finally:
            db.close()

    def compute_composite_score(
        self,
        performance: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Multi-objective optimization score: weighted combination of key metrics.
        Returns a score from 0-100.

        Default weights: ROAS 40%, conversion volume 30%, CPC efficiency 20%, CTR 10%
        """
        if not weights:
            weights = {"roas": 0.4, "conversions": 0.3, "cpc_efficiency": 0.2, "ctr": 0.1}

        # Normalize each metric to 0-100 scale
        roas = min(performance.get("roas", 0) / 5.0 * 100, 100)  # 5.0 ROAS = 100
        conversions = min(performance.get("conversions", 0) / 10.0 * 100, 100)  # 10 conversions/day = 100
        cpc = performance.get("cpc", 0)
        cpc_efficiency = max(0, min((5.0 - cpc) / 5.0 * 100, 100))  # Lower CPC = higher score
        ctr = min(performance.get("ctr", 0) / 5.0 * 100, 100)  # 5% CTR = 100

        score = (
            roas * weights.get("roas", 0.4) +
            conversions * weights.get("conversions", 0.3) +
            cpc_efficiency * weights.get("cpc_efficiency", 0.2) +
            ctr * weights.get("ctr", 0.1)
        )

        return round(score, 1)

    def _get_best_ctr_in_test(self, ad_id: str) -> float:
        """Get the best CTR among all active variants in the same creative test as this ad."""
        db = SessionLocal()
        try:
            from .models import CreativeTestVariant, CreativeTest
            from modules.marketing.models import MetaAdInsight, MetaAd

            # Find which test this ad belongs to
            variant = db.query(CreativeTestVariant).filter(
                CreativeTestVariant.ad_id == ad_id,
                CreativeTestVariant.status == "active"
            ).first()

            if not variant:
                return 0.0

            # Get all active variants in this test
            all_variants = db.query(CreativeTestVariant).filter(
                CreativeTestVariant.test_id == variant.test_id,
                CreativeTestVariant.status == "active"
            ).all()

            best_ctr = 0.0
            for v in all_variants:
                # Get latest insight for this ad
                ad = db.query(MetaAd).filter(MetaAd.ad_id == v.ad_id).first()
                if not ad:
                    continue
                insight = db.query(MetaAdInsight).filter(
                    MetaAdInsight.ad_id == ad.id
                ).order_by(MetaAdInsight.date.desc()).first()
                if insight and (insight.ctr or 0) > best_ctr:
                    best_ctr = insight.ctr or 0

            return best_ctr
        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Error getting best CTR in test: {e}")
            return 0.0
        finally:
            db.close()

    async def evaluate_creative_tests(self) -> List[Dict]:
        """
        Evaluate all running creative tests. Finalize those where all variants
        have sufficient impressions — pick the winner and pause losers.
        """
        db = SessionLocal()
        completed_tests = []
        try:
            from .models import CreativeTest, CreativeTestVariant
            from modules.marketing.models import MetaAdInsight, MetaAd

            running_tests = db.query(CreativeTest).filter(
                CreativeTest.status == "running"
            ).all()

            for test in running_tests:
                variants = db.query(CreativeTestVariant).filter(
                    CreativeTestVariant.test_id == test.id,
                    CreativeTestVariant.status == "active"
                ).all()

                if not variants:
                    continue

                # Get performance for each variant
                variant_perf = []
                all_have_enough = True
                for v in variants:
                    ad = db.query(MetaAd).filter(MetaAd.ad_id == v.ad_id).first()
                    if not ad:
                        all_have_enough = False
                        continue

                    # Sum impressions across all insights for this ad
                    from sqlalchemy import func
                    total = db.query(
                        func.sum(MetaAdInsight.impressions).label("impressions"),
                        func.sum(MetaAdInsight.clicks).label("clicks"),
                        func.sum(MetaAdInsight.conversions).label("conversions"),
                        func.sum(MetaAdInsight.spend).label("spend")
                    ).filter(MetaAdInsight.ad_id == ad.id).first()

                    impressions = total.impressions or 0
                    clicks = total.clicks or 0
                    conversions = total.conversions or 0
                    spend = total.spend or 0
                    ctr = (clicks / impressions * 100) if impressions > 0 else 0
                    cpc = (spend / clicks) if clicks > 0 else 0

                    variant_perf.append({
                        "variant": v,
                        "impressions": impressions,
                        "ctr": ctr,
                        "cpc": cpc,
                        "conversions": conversions
                    })

                    if impressions < test.min_impressions_per_variant:
                        all_have_enough = False

                if not all_have_enough or not variant_perf:
                    continue

                # Find the winner (highest CTR)
                variant_perf.sort(key=lambda x: x["ctr"], reverse=True)
                winner = variant_perf[0]

                # Update winner variant
                winner["variant"].status = "winner"
                winner["variant"].final_impressions = winner["impressions"]
                winner["variant"].final_ctr = winner["ctr"]
                winner["variant"].final_cpc = winner["cpc"]
                winner["variant"].final_conversions = winner["conversions"]

                # Pause losers
                for vp in variant_perf[1:]:
                    vp["variant"].status = "paused"
                    vp["variant"].final_impressions = vp["impressions"]
                    vp["variant"].final_ctr = vp["ctr"]
                    vp["variant"].final_cpc = vp["cpc"]
                    vp["variant"].final_conversions = vp["conversions"]

                    # Pause via Meta API
                    await self._update_entity_status(vp["variant"].ad_id, "ad", "PAUSED")

                # Finalize test
                test.status = "completed"
                test.winner_ad_id = winner["variant"].ad_id
                test.completed_at = datetime.utcnow()
                test.results = {
                    "winner": {
                        "ad_id": winner["variant"].ad_id,
                        "headline": winner["variant"].headline,
                        "ctr": winner["ctr"],
                        "impressions": winner["impressions"],
                        "is_original": winner["variant"].is_original
                    },
                    "variants_tested": len(variant_perf),
                    "losers_paused": len(variant_perf) - 1
                }

                completed_tests.append({
                    "test_id": str(test.id),
                    "winner_ad_id": winner["variant"].ad_id,
                    "winner_ctr": winner["ctr"],
                    "variants_tested": len(variant_perf),
                    "original_won": winner["variant"].is_original
                })

                logger.info(
                    f"[AutomatedRulesEngine] Creative test {test.id} completed: "
                    f"winner={winner['variant'].ad_id} (CTR={winner['ctr']:.2f}%), "
                    f"original_won={winner['variant'].is_original}"
                )

            db.commit()
        except Exception as e:
            logger.error(f"[AutomatedRulesEngine] Creative test evaluation error: {e}")
            db.rollback()
        finally:
            db.close()

        return completed_tests

    async def run_rules_for_entity(
        self,
        entity_id: str,
        entity_type: str,
        current_budget: float,
        dry_run: bool = False
    ) -> List[RuleExecutionResult]:
        """
        Run all enabled rules for a single entity.

        Includes cooldown/throttle checks and volatility detection.
        Returns list of execution results for triggered rules.
        """
        results = []

        # Get performance history
        history = self.get_performance_history(entity_id, entity_type, days=7)

        if not history:
            logger.debug(f"[AutomatedRulesEngine] No history for {entity_type} {entity_id}")
            return results

        # Check volatility before evaluating rules
        if self._check_volatility(entity_id, entity_type):
            logger.warning(f"[AutomatedRulesEngine] Skipping {entity_type} {entity_id} due to metric volatility")
            return results

        # Evaluate and execute each rule
        for rule in self.rules:
            if not rule.is_enabled:
                continue

            if rule.entity_type != entity_type:
                continue

            # Check cooldown and throttle before evaluating
            can_fire, cooldown_reason = self._check_cooldown_and_throttle(rule, entity_id)
            if not can_fire:
                logger.debug(f"[AutomatedRulesEngine] Rule '{rule.name}' blocked for {entity_id}: {cooldown_reason}")
                continue

            if self.evaluate_rule(rule, entity_id, history):
                logger.info(f"[AutomatedRulesEngine] Rule '{rule.name}' triggered for {entity_type} {entity_id}{' (DRY RUN)' if dry_run else ''}")
                result = await self.execute_action(rule, entity_id, entity_type, current_budget, dry_run=dry_run)

                # Persist to DB with performance snapshot for rollback
                is_budget_action = rule.action.type in [RuleType.SCALE_UP, RuleType.SCALE_DOWN]
                self._log_execution(
                    ad_account_id=getattr(self, '_current_ad_account_id', ''),
                    result=result,
                    rollback_eligible=is_budget_action and not dry_run,
                    performance_snapshot=history[0] if history else None,
                    is_simulation=dry_run
                )

                results.append(result)

        return results

    async def run_all_rules(self, ad_account_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run all rules for all entities in an ad account.

        This is the main entry point for scheduled execution.
        Includes circuit breaker checks before processing.
        Set dry_run=True to simulate without making API calls.
        """
        # Store current ad account for logging context
        self._current_ad_account_id = ad_account_id

        db = SessionLocal()
        execution_summary = {
            "ad_account_id": ad_account_id,
            "executed_at": datetime.utcnow().isoformat(),
            "rules_evaluated": 0,
            "rules_triggered": 0,
            "actions_taken": [],
            "errors": [],
            "circuit_breaker_blocked": False,
            "simulated": dry_run
        }

        # Check circuit breakers before processing (skip in dry run)
        is_safe, block_reason = self.check_circuit_breakers(ad_account_id) if not dry_run else (True, "")
        if not is_safe:
            execution_summary["circuit_breaker_blocked"] = True
            execution_summary["block_reason"] = block_reason
            logger.warning(f"[AutomatedRulesEngine] Circuit breaker blocked: {block_reason}")
            return execution_summary

        try:
            from modules.marketing.models import MetaAdAccount, MetaAdSet

            # Get ad account
            ad_account = db.query(MetaAdAccount).filter(
                MetaAdAccount.ad_account_id == ad_account_id
            ).first()

            if not ad_account:
                execution_summary["errors"].append(f"Ad account {ad_account_id} not found")
                return execution_summary

            # Get all active ad sets
            adsets = db.query(MetaAdSet).filter(
                MetaAdSet.ad_account_id == ad_account.id,
                MetaAdSet.status == "ACTIVE",
                MetaAdSet.is_active == True
            ).all()

            logger.info(f"[AutomatedRulesEngine] Running rules for {len(adsets)} ad sets in account {ad_account_id}")

            for adset in adsets:
                execution_summary["rules_evaluated"] += len(self.rules)

                # Get current budget (convert from cents)
                current_budget = (adset.daily_budget or 0) / 100

                try:
                    results = await self.run_rules_for_entity(
                        entity_id=adset.adset_id,
                        entity_type="adset",
                        current_budget=current_budget,
                        dry_run=dry_run
                    )

                    for result in results:
                        execution_summary["rules_triggered"] += 1
                        execution_summary["actions_taken"].append({
                            "rule": result.rule_name,
                            "entity": result.entity_id,
                            "action": result.action_taken,
                            "success": result.success,
                            "message": result.message
                        })

                except Exception as e:
                    execution_summary["errors"].append(f"Error processing adset {adset.adset_id}: {str(e)}")

            # Run ad-level rules for ads in active creative tests
            try:
                from .models import CreativeTest, CreativeTestVariant
                active_tests = db.query(CreativeTest).filter(
                    CreativeTest.status == "running",
                    CreativeTest.ad_account_id == ad_account_id
                ).all()

                for test in active_tests:
                    variants = db.query(CreativeTestVariant).filter(
                        CreativeTestVariant.test_id == test.id,
                        CreativeTestVariant.status == "active"
                    ).all()

                    for variant in variants:
                        try:
                            results = await self.run_rules_for_entity(
                                entity_id=variant.ad_id,
                                entity_type="ad",
                                current_budget=0,  # Budget is at adset level
                                dry_run=dry_run
                            )
                            for result in results:
                                execution_summary["rules_triggered"] += 1
                                execution_summary["actions_taken"].append({
                                    "rule": result.rule_name,
                                    "entity": result.entity_id,
                                    "action": result.action_taken,
                                    "success": result.success,
                                    "message": result.message
                                })
                                # Update variant status if paused
                                if result.action_taken == "pause" and result.success and not dry_run:
                                    variant.status = "paused"
                        except Exception as e:
                            execution_summary["errors"].append(f"Error processing ad {variant.ad_id}: {str(e)}")

                if active_tests:
                    db.commit()
            except Exception as e:
                logger.error(f"[AutomatedRulesEngine] Ad-level rules error: {e}")
                execution_summary["errors"].append(f"Ad-level rules: {str(e)}")

        except Exception as e:
            execution_summary["errors"].append(f"Fatal error: {str(e)}")
            logger.error(f"[AutomatedRulesEngine] Fatal error running rules: {e}")
        finally:
            db.close()

        return execution_summary

    def get_execution_history(self, limit: int = 100, ad_account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent execution history from database (falls back to in-memory)."""
        db = SessionLocal()
        try:
            from .models import RuleExecutionLog
            query = db.query(RuleExecutionLog).order_by(RuleExecutionLog.executed_at.desc())
            if ad_account_id:
                query = query.filter(RuleExecutionLog.ad_account_id == ad_account_id)
            logs = query.limit(limit).all()

            if logs:
                return [
                    {
                        "id": str(log.id),
                        "rule_id": log.rule_id,
                        "rule_name": log.rule_name,
                        "entity_id": log.entity_id,
                        "entity_type": log.entity_type,
                        "action_taken": log.action_taken,
                        "old_value": log.old_value,
                        "new_value": log.new_value,
                        "success": log.success,
                        "message": log.message,
                        "rollback_eligible": log.rollback_eligible,
                        "rollback_executed": log.rollback_executed,
                        "executed_at": log.executed_at.isoformat() if log.executed_at else None
                    }
                    for log in logs
                ]
        except Exception as e:
            logger.warning(f"[AutomatedRulesEngine] DB history read failed, using in-memory: {e}")
        finally:
            db.close()

        # Fallback to in-memory history
        return [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "entity_id": r.entity_id,
                "entity_type": r.entity_type,
                "action_taken": r.action_taken,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "success": r.success,
                "message": r.message,
                "executed_at": r.executed_at.isoformat()
            }
            for r in self.execution_history[-limit:]
        ]

    def get_rule_templates(self) -> Dict[str, Any]:
        """Get all available rule templates"""
        return self.RULE_TEMPLATES


# Singleton instance for easy access
automated_rules_engine = AutomatedRulesEngine()

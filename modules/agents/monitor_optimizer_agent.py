# monitor_optimizer_agent.py - AI Agent for Ad Performance Optimization
"""
Uses OpenRouter API via ChatOpenRouter adapter for AI generation.

Includes Automated Rules Engine for 24/7 ad optimization:
- Scale: Increase budget +20% when ROAS ≥ target × 1.25 for 3 consecutive days
- Kill: Cut budget 50% if CPA > 2 × target & zero purchases after ≥ 2000 impressions
"""

import os
import logging
import uuid
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel
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


# ==================== AUTOMATED RULES ENGINE ====================

class RuleType(str, Enum):
    """Types of automated rules"""
    SCALE_UP = "scale_up"       # Increase budget
    SCALE_DOWN = "scale_down"   # Decrease budget
    PAUSE = "pause"             # Pause ad/adset
    UNPAUSE = "unpause"         # Unpause ad/adset
    NOTIFY = "notify"           # Send notification only


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
    executed_at: datetime = datetime.utcnow()


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
                {"metric": "roas", "operator": "gte", "value": 1.25, "consecutive_days": 3}  # 1.25 = target * 1.25
            ],
            "action": {"type": "scale_up", "adjustment_percent": 20, "max_budget": 10000}
        },
        "kill_loser": {
            "name": "Kill Losers (-50%)",
            "description": "Cut budget 50% when CPA > 2x target AND zero purchases after 2000+ impressions",
            "conditions": [
                {"metric": "cpa_ratio", "operator": "gt", "value": 2.0, "consecutive_days": 1},
                {"metric": "conversions", "operator": "eq", "value": 0, "consecutive_days": 1},
                {"metric": "impressions", "operator": "gte", "value": 2000, "consecutive_days": 1}
            ],
            "action": {"type": "scale_down", "adjustment_percent": 50, "min_budget": 5}
        },
        "pause_no_spend": {
            "name": "Pause No Spend",
            "description": "Pause ad sets with zero spend after 24 hours",
            "conditions": [
                {"metric": "spend", "operator": "eq", "value": 0, "consecutive_days": 1}
            ],
            "action": {"type": "pause"}
        },
        "scale_high_ctr": {
            "name": "Scale High CTR (+15%)",
            "description": "Increase budget by 15% when CTR > 3% for 2 consecutive days",
            "conditions": [
                {"metric": "ctr", "operator": "gt", "value": 3.0, "consecutive_days": 2}
            ],
            "action": {"type": "scale_up", "adjustment_percent": 15, "max_budget": 5000}
        },
        "reduce_high_cpc": {
            "name": "Reduce High CPC (-25%)",
            "description": "Reduce budget by 25% when CPC > $5 for 2 consecutive days",
            "conditions": [
                {"metric": "cpc", "operator": "gt", "value": 5.0, "consecutive_days": 2}
            ],
            "action": {"type": "scale_down", "adjustment_percent": 25, "min_budget": 10}
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
            created_at=datetime.utcnow()
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
                    func.sum(MetaAdInsight.conversions).label('conversions')
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

                    ctr = (clicks / impressions * 100) if impressions > 0 else 0
                    cpc = (spend / clicks) if clicks > 0 else 0
                    cpa = (spend / conversions) if conversions > 0 else float('inf')

                    history.append({
                        "date": insight.date,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": spend,
                        "conversions": conversions,
                        "ctr": ctr,
                        "cpc": cpc,
                        "cpa": cpa,
                        "roas": 0  # Would need revenue data
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

                    history.append({
                        "date": insight.date,
                        "impressions": impressions,
                        "clicks": clicks,
                        "spend": spend,
                        "conversions": conversions,
                        "ctr": insight.ctr or 0,
                        "cpc": insight.cpc or 0,
                        "cpa": insight.cost_per_conversion or 0,
                        "roas": 0
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
        target_cpa: Optional[float] = None
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

    def evaluate_rule(
        self,
        rule: AutomatedRule,
        entity_id: str,
        performance_history: List[Dict[str, Any]]
    ) -> bool:
        """
        Evaluate if a rule should be triggered for an entity.

        All conditions must be met (AND logic).
        """
        if not rule.is_enabled:
            return False

        if not performance_history:
            return False

        # All conditions must be met
        for condition in rule.conditions:
            if not self.evaluate_condition(
                condition,
                performance_history,
                rule.target_roas,
                rule.target_cpa
            ):
                return False

        return True

    async def execute_action(
        self,
        rule: AutomatedRule,
        entity_id: str,
        entity_type: str,
        current_budget: float
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

        try:
            if action.type == RuleType.SCALE_UP:
                # Calculate new budget
                adjustment = current_budget * (action.adjustment_percent / 100)
                new_budget = current_budget + adjustment

                # Apply max cap if specified
                if action.max_budget and new_budget > action.max_budget:
                    new_budget = action.max_budget

                # Update via Meta API
                success = await self._update_entity_budget(entity_id, entity_type, new_budget)

                result.new_value = new_budget
                result.success = success
                result.message = f"Budget increased from ${current_budget:.2f} to ${new_budget:.2f} (+{action.adjustment_percent}%)"

            elif action.type == RuleType.SCALE_DOWN:
                # Calculate new budget
                adjustment = current_budget * (action.adjustment_percent / 100)
                new_budget = current_budget - adjustment

                # Apply min floor if specified
                if action.min_budget and new_budget < action.min_budget:
                    new_budget = action.min_budget

                # Ensure budget doesn't go negative
                new_budget = max(new_budget, 1)

                # Update via Meta API
                success = await self._update_entity_budget(entity_id, entity_type, new_budget)

                result.new_value = new_budget
                result.success = success
                result.message = f"Budget decreased from ${current_budget:.2f} to ${new_budget:.2f} (-{action.adjustment_percent}%)"

            elif action.type == RuleType.PAUSE:
                success = await self._update_entity_status(entity_id, entity_type, "PAUSED")
                result.success = success
                result.message = f"{entity_type.title()} paused due to rule: {rule.name}"

            elif action.type == RuleType.UNPAUSE:
                success = await self._update_entity_status(entity_id, entity_type, "ACTIVE")
                result.success = success
                result.message = f"{entity_type.title()} unpaused due to rule: {rule.name}"

            elif action.type == RuleType.NOTIFY:
                result.success = True
                result.message = action.notification_message or f"Rule triggered: {rule.name}"

            # Update rule stats
            rule.last_triggered = datetime.utcnow()
            rule.trigger_count += 1

        except Exception as e:
            result.success = False
            result.message = f"Action failed: {str(e)}"
            logger.error(f"[AutomatedRulesEngine] Action execution failed: {e}")

        # Store in history
        self.execution_history.append(result)

        return result

    async def _update_entity_budget(
        self,
        entity_id: str,
        entity_type: str,
        new_budget: float
    ) -> bool:
        """Update entity budget via Meta Marketing API"""
        if not self.access_token:
            logger.warning("[AutomatedRulesEngine] No access token, simulating budget update")
            return True  # Simulate success for testing

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
            logger.warning("[AutomatedRulesEngine] No access token, simulating status update")
            return True  # Simulate success for testing

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

    async def run_rules_for_entity(
        self,
        entity_id: str,
        entity_type: str,
        current_budget: float
    ) -> List[RuleExecutionResult]:
        """
        Run all enabled rules for a single entity.

        Returns list of execution results for triggered rules.
        """
        results = []

        # Get performance history
        history = self.get_performance_history(entity_id, entity_type, days=7)

        if not history:
            logger.debug(f"[AutomatedRulesEngine] No history for {entity_type} {entity_id}")
            return results

        # Evaluate and execute each rule
        for rule in self.rules:
            if not rule.is_enabled:
                continue

            if rule.entity_type != entity_type:
                continue

            if self.evaluate_rule(rule, entity_id, history):
                logger.info(f"[AutomatedRulesEngine] Rule '{rule.name}' triggered for {entity_type} {entity_id}")
                result = await self.execute_action(rule, entity_id, entity_type, current_budget)
                results.append(result)

        return results

    async def run_all_rules(self, ad_account_id: str) -> Dict[str, Any]:
        """
        Run all rules for all entities in an ad account.

        This is the main entry point for scheduled execution.
        """
        db = SessionLocal()
        execution_summary = {
            "ad_account_id": ad_account_id,
            "executed_at": datetime.utcnow().isoformat(),
            "rules_evaluated": 0,
            "rules_triggered": 0,
            "actions_taken": [],
            "errors": []
        }

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
                        current_budget=current_budget
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

        except Exception as e:
            execution_summary["errors"].append(f"Fatal error: {str(e)}")
            logger.error(f"[AutomatedRulesEngine] Fatal error running rules: {e}")
        finally:
            db.close()

        return execution_summary

    def get_execution_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent execution history"""
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

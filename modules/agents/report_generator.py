# report_generator.py - Weekly Report Generator
"""
Generates weekly performance reports for ad campaigns.

Aggregates 7 days of MetaAdInsight data and uses LLM to create
narrative summaries with actionable recommendations.

Usage:
    from modules.agents.report_generator import WeeklyReportGenerator
    generator = WeeklyReportGenerator()
    report = await generator.generate_weekly_report(ad_account_id)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import func

from database import SessionLocal

logger = logging.getLogger(__name__)


class WeeklyReportGenerator:
    """Generates weekly performance reports with LLM narrative."""

    def __init__(self):
        try:
            from modules.openrouter import ChatOpenRouter
            self.llm = ChatOpenRouter(model="gpt-4o-mini", temperature=0.4)
            self.llm_available = True
        except Exception:
            self.llm_available = False
            logger.warning("[ReportGenerator] LLM not available, reports will be data-only")

    async def generate_weekly_report(
        self,
        ad_account_id: str,
        access_token: str = None
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive weekly report for an ad account.

        Args:
            ad_account_id: Meta ad account ID string (e.g., "act_123456")
            access_token: Optional access token for demographic data

        Returns:
            Dict with metrics, trends, top performers, and narrative summary
        """
        db = SessionLocal()
        try:
            from modules.marketing.models import (
                MetaAdAccount, MetaAdInsight, MetaAd, MetaAdSet, MetaCampaign
            )

            # Find the account
            account = db.query(MetaAdAccount).filter(
                MetaAdAccount.ad_account_id == ad_account_id
            ).first()

            if not account:
                return {"success": False, "error": f"Account {ad_account_id} not found"}

            # Date ranges
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=7)
            prev_start = start_date - timedelta(days=7)

            # Current week metrics
            current_metrics = self._aggregate_metrics(db, account.id, start_date, end_date)

            # Previous week metrics (for comparison)
            prev_metrics = self._aggregate_metrics(db, account.id, prev_start, start_date)

            # Top performing ads
            top_ads = self._get_top_ads(db, account.id, start_date, end_date)

            # Worst performing ads
            worst_ads = self._get_worst_ads(db, account.id, start_date, end_date)

            # Daily breakdown
            daily_data = self._get_daily_breakdown(db, account.id, start_date, end_date)

            # Calculate week-over-week changes
            wow_changes = self._calculate_wow(current_metrics, prev_metrics)

            # Build report
            report = {
                "success": True,
                "account_name": account.account_name,
                "account_id": ad_account_id,
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "summary_metrics": current_metrics,
                "previous_week_metrics": prev_metrics,
                "week_over_week": wow_changes,
                "top_performing_ads": top_ads,
                "worst_performing_ads": worst_ads,
                "daily_breakdown": daily_data,
                "generated_at": datetime.utcnow().isoformat()
            }

            # Generate LLM narrative if available
            if self.llm_available:
                narrative = await self._generate_narrative(report)
                report["narrative"] = narrative

            logger.info(f"[ReportGenerator] Weekly report generated for {ad_account_id}")
            return report

        except Exception as e:
            logger.error(f"[ReportGenerator] Report generation failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def _aggregate_metrics(self, db, account_id, start_date, end_date) -> Dict[str, Any]:
        """Aggregate metrics for a date range."""
        from modules.marketing.models import MetaAdInsight, MetaAd

        results = db.query(
            func.sum(MetaAdInsight.impressions).label("impressions"),
            func.sum(MetaAdInsight.clicks).label("clicks"),
            func.sum(MetaAdInsight.spend).label("spend"),
            func.sum(MetaAdInsight.conversions).label("conversions"),
            func.sum(MetaAdInsight.reach).label("reach"),
            func.sum(MetaAdInsight.revenue).label("revenue"),
            func.avg(MetaAdInsight.frequency).label("avg_frequency"),
        ).join(MetaAd, MetaAdInsight.ad_id == MetaAd.id).filter(
            MetaAd.ad_account_id == account_id,
            MetaAdInsight.date >= start_date,
            MetaAdInsight.date < end_date
        ).first()

        impressions = int(results.impressions or 0)
        clicks = int(results.clicks or 0)
        spend = float(results.spend or 0)
        conversions = int(results.conversions or 0)
        revenue = float(results.revenue or 0)

        # Rates are derived from the summed totals, NOT an average of per-row rates.
        # Averaging daily/per-ad CTR (or CPC/CPM) is statistically wrong: the mean of
        # rates != total clicks / total impressions once rows have different volumes.
        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        cpc = (spend / clicks) if clicks > 0 else 0
        cpm = (spend / impressions * 1000) if impressions > 0 else 0
        roas = (revenue / spend) if spend > 0 else 0

        return {
            "impressions": impressions,
            "clicks": clicks,
            "spend": round(spend, 2),
            "conversions": conversions,
            "revenue": round(revenue, 2),
            "reach": int(results.reach or 0),
            "ctr": round(ctr, 2),
            "cpc": round(cpc, 2),
            "cpm": round(cpm, 2),
            "frequency": round(float(results.avg_frequency or 0), 2),
            "cost_per_conversion": round(spend / conversions, 2) if conversions > 0 else 0,
            "conversion_rate": round((conversions / clicks * 100), 2) if clicks > 0 else 0,
            "roas": round(roas, 2),
            # Revenue is only meaningful when purchase-value tracking is live; before
            # that, revenue rows are all 0 and ROAS should be read as "not tracked".
            "revenue_tracked": revenue > 0,
        }

    def _get_top_ads(self, db, account_id, start_date, end_date, limit=5) -> List[Dict]:
        """Get top performing ads by CTR."""
        from modules.marketing.models import MetaAdInsight, MetaAd

        results = db.query(
            MetaAd.name,
            MetaAd.ad_id,
            func.sum(MetaAdInsight.impressions).label("impressions"),
            func.sum(MetaAdInsight.clicks).label("clicks"),
            func.sum(MetaAdInsight.spend).label("spend"),
            func.sum(MetaAdInsight.conversions).label("conversions"),
            func.sum(MetaAdInsight.revenue).label("revenue"),
        ).join(MetaAd, MetaAdInsight.ad_id == MetaAd.id).filter(
            MetaAd.ad_account_id == account_id,
            MetaAdInsight.date >= start_date,
            MetaAdInsight.date < end_date
        ).group_by(MetaAd.id, MetaAd.name, MetaAd.ad_id
        ).having(func.sum(MetaAdInsight.impressions) > 100
        ).order_by((func.sum(MetaAdInsight.clicks) * 1.0 / func.sum(MetaAdInsight.impressions)).desc()
        ).limit(limit).all()

        out = []
        for r in results:
            impressions = int(r.impressions or 0)
            clicks = int(r.clicks or 0)
            spend = float(r.spend or 0)
            revenue = float(r.revenue or 0)
            out.append({
                "name": r.name,
                "ad_id": r.ad_id,
                "impressions": impressions,
                "clicks": clicks,
                "spend": round(spend, 2),
                "conversions": int(r.conversions or 0),
                "revenue": round(revenue, 2),
                # Derived from totals, consistent with _aggregate_metrics.
                "ctr": round((clicks / impressions * 100) if impressions > 0 else 0, 2),
                "roas": round((revenue / spend) if spend > 0 else 0, 2),
            })
        return out

    def _get_worst_ads(self, db, account_id, start_date, end_date, limit=3) -> List[Dict]:
        """Get worst performing ads by CTR (with minimum impressions)."""
        from modules.marketing.models import MetaAdInsight, MetaAd

        results = db.query(
            MetaAd.name,
            MetaAd.ad_id,
            func.sum(MetaAdInsight.impressions).label("impressions"),
            func.sum(MetaAdInsight.clicks).label("clicks"),
            func.sum(MetaAdInsight.spend).label("spend"),
        ).join(MetaAd, MetaAdInsight.ad_id == MetaAd.id).filter(
            MetaAd.ad_account_id == account_id,
            MetaAdInsight.date >= start_date,
            MetaAdInsight.date < end_date
        ).group_by(MetaAd.id, MetaAd.name, MetaAd.ad_id
        ).having(func.sum(MetaAdInsight.impressions) > 100
        ).order_by((func.sum(MetaAdInsight.clicks) * 1.0 / func.sum(MetaAdInsight.impressions)).asc()
        ).limit(limit).all()

        out = []
        for r in results:
            impressions = int(r.impressions or 0)
            clicks = int(r.clicks or 0)
            out.append({
                "name": r.name,
                "ad_id": r.ad_id,
                "impressions": impressions,
                "clicks": clicks,
                "spend": round(float(r.spend or 0), 2),
                "ctr": round((clicks / impressions * 100) if impressions > 0 else 0, 2),
            })
        return out

    def _get_daily_breakdown(self, db, account_id, start_date, end_date) -> List[Dict]:
        """Get daily aggregated metrics."""
        from modules.marketing.models import MetaAdInsight, MetaAd

        results = db.query(
            func.date(MetaAdInsight.date).label("day"),
            func.sum(MetaAdInsight.impressions).label("impressions"),
            func.sum(MetaAdInsight.clicks).label("clicks"),
            func.sum(MetaAdInsight.spend).label("spend"),
            func.sum(MetaAdInsight.conversions).label("conversions"),
            func.avg(MetaAdInsight.ctr).label("ctr"),
        ).join(MetaAd, MetaAdInsight.ad_id == MetaAd.id).filter(
            MetaAd.ad_account_id == account_id,
            MetaAdInsight.date >= start_date,
            MetaAdInsight.date < end_date
        ).group_by(func.date(MetaAdInsight.date)
        ).order_by(func.date(MetaAdInsight.date)).all()

        return [
            {
                "date": str(r.day),
                "impressions": int(r.impressions or 0),
                "clicks": int(r.clicks or 0),
                "spend": round(float(r.spend or 0), 2),
                "conversions": int(r.conversions or 0),
                "ctr": round(float(r.ctr or 0), 2)
            }
            for r in results
        ]

    def _calculate_wow(self, current: Dict, previous: Dict) -> Dict[str, Any]:
        """Calculate week-over-week percentage changes."""
        changes = {}
        for key in ["impressions", "clicks", "spend", "conversions", "revenue", "roas", "ctr", "cpc"]:
            curr_val = current.get(key, 0)
            prev_val = previous.get(key, 0)
            if prev_val > 0:
                pct_change = ((curr_val - prev_val) / prev_val) * 100
                changes[key] = {
                    "current": curr_val,
                    "previous": prev_val,
                    "change_pct": round(pct_change, 1),
                    "direction": "up" if pct_change > 0 else "down" if pct_change < 0 else "flat"
                }
            else:
                changes[key] = {
                    "current": curr_val,
                    "previous": prev_val,
                    "change_pct": 0,
                    "direction": "new"
                }
        return changes

    async def _generate_narrative(self, report: Dict[str, Any]) -> str:
        """Generate an LLM narrative summary of the weekly report."""
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser
            from modules.openrouter.context import set_ai_context

            prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a digital marketing analyst writing a concise weekly ad performance report.
Write 3-4 short paragraphs covering:
1. Overall performance. If revenue_tracked is true, LEAD with ROAS and revenue (the
   bottom line), then impressions, clicks, spend, conversions. If revenue_tracked is
   false, do NOT report ROAS as a real number — state that purchase-value tracking is
   not set up and focus on CTR, CPC, conversions instead.
2. Week-over-week trends (what improved, what declined). For cost metrics (spend, cpc)
   a decrease is good; for ROAS/revenue/conversions an increase is good.
3. Top performers and why they might be working (reference their ROAS when available)
4. 2-3 actionable recommendations for next week

Keep it concise and data-driven. Use specific numbers from the data."""),
                ("human", """Weekly Report Data:
Account: {account_name}
Period: {period}

This Week: {current_metrics}
Last Week: {previous_metrics}
WoW Changes: {wow_changes}

Top Ads: {top_ads}
Worst Ads: {worst_ads}""")
            ])

            chain = prompt | self.llm | StrOutputParser()
            with set_ai_context(agent_name="report_generator"):
                narrative = await chain.ainvoke({
                    "account_name": report.get("account_name", "Unknown"),
                    "period": f"{report['period']['start'][:10]} to {report['period']['end'][:10]}",
                    "current_metrics": json.dumps(report.get("summary_metrics", {})),
                    "previous_metrics": json.dumps(report.get("previous_week_metrics", {})),
                    "wow_changes": json.dumps(report.get("week_over_week", {})),
                    "top_ads": json.dumps(report.get("top_performing_ads", [])),
                    "worst_ads": json.dumps(report.get("worst_performing_ads", []))
                })

            return narrative

        except Exception as e:
            logger.error(f"[ReportGenerator] Narrative generation failed: {e}")
            return f"Narrative generation failed: {str(e)}"

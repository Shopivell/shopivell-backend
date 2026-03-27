# modules/campaigns/optimizer.py
"""
Auto-optimization for URL-based campaigns.

Pulls performance data from Meta Insights, evaluates ad content variants,
pauses underperformers, and scales winners.
"""
import logging
import requests
import uuid
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import UrlCampaign, UrlAdSet, UrlAdContent, AdContentMetrics, CampaignStatus

logger = logging.getLogger(__name__)

FB_GRAPH_API_BASE = "https://graph.facebook.com/v24.0"


class CampaignOptimizer:
    """Evaluates ad content variant performance and auto-optimizes campaigns."""

    # Minimum impressions before evaluating a variant
    DEFAULT_MIN_IMPRESSIONS = 1000
    # Variants with CTR below this fraction of the best are paused
    LOSER_CTR_THRESHOLD = 0.5
    # Budget increase factor for winning ad sets
    WINNER_BUDGET_BOOST = 1.3

    def __init__(self, db: Session):
        self.db = db

    def collect_metrics(self, campaign_id: uuid.UUID) -> Dict[str, Any]:
        """
        Pull metrics from Meta Insights for all ad content variants with a meta_ad_id.
        Bridges UrlAdContent → MetaAd → MetaAdInsight → AdContentMetrics.
        """
        campaign = self.db.query(UrlCampaign).filter(UrlCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}

        if campaign.status != CampaignStatus.ACTIVE:
            return {"error": f"Campaign is {campaign.status.value}, not active"}

        # Get all ad contents with a Meta ad ID
        ad_contents = (
            self.db.query(UrlAdContent)
            .join(UrlAdSet, UrlAdContent.ad_set_id == UrlAdSet.id)
            .filter(UrlAdSet.campaign_id == campaign_id)
            .filter(UrlAdContent.meta_ad_id.isnot(None))
            .filter(UrlAdContent.is_active == True)
            .all()
        )

        if not ad_contents:
            return {"campaign_id": str(campaign_id), "synced": 0, "message": "No ad contents with meta_ad_id"}

        synced = 0
        errors = []

        for content in ad_contents:
            try:
                # Find the corresponding MetaAd by ad_id string
                from modules.marketing.models import MetaAd
                meta_ad = self.db.query(MetaAd).filter(MetaAd.ad_id == content.meta_ad_id).first()

                if not meta_ad:
                    logger.warning(f"[Optimizer] No MetaAd found for ad_id={content.meta_ad_id}")
                    continue

                # Sync insights using existing service
                from modules.marketing.insights_service import sync_ad_insights
                end = date.today()
                start = end - timedelta(days=7)
                sync_ad_insights(meta_ad, start, end, self.db)

                # Read the synced MetaAdInsight rows and create/update AdContentMetrics
                from modules.marketing.models import MetaAdInsight
                insights = (
                    self.db.query(MetaAdInsight)
                    .filter(MetaAdInsight.ad_id == meta_ad.id)
                    .filter(MetaAdInsight.date >= start)
                    .all()
                )

                for insight in insights:
                    existing = self.db.query(AdContentMetrics).filter(
                        AdContentMetrics.ad_content_id == content.id,
                        AdContentMetrics.date == insight.date,
                    ).first()

                    metrics_data = {
                        "impressions": insight.impressions or 0,
                        "reach": insight.reach or 0,
                        "clicks": insight.clicks or 0,
                        "conversions": insight.conversions or 0,
                        "spend": float(insight.spend or 0),
                        "ctr": float(insight.ctr or 0),
                        "cpc": float(insight.cpc or 0),
                        "cpm": float(insight.cpm or 0),
                        "frequency": float(insight.frequency or 0),
                        "roas": float(insight.roas or 0) if hasattr(insight, 'roas') else 0.0,
                        "collected_at": datetime.utcnow(),
                    }

                    if existing:
                        for k, v in metrics_data.items():
                            setattr(existing, k, v)
                    else:
                        new_metric = AdContentMetrics(
                            ad_content_id=content.id,
                            campaign_id=campaign_id,
                            date=insight.date,
                            **metrics_data,
                        )
                        self.db.add(new_metric)

                synced += 1

            except Exception as e:
                logger.error(f"[Optimizer] Error syncing metrics for content {content.id}: {e}")
                errors.append(str(e))

        self.db.commit()
        return {
            "campaign_id": str(campaign_id),
            "synced": synced,
            "total_contents": len(ad_contents),
            "errors": errors,
        }

    def evaluate_variants(self, campaign_id: uuid.UUID, min_impressions: int = None) -> Dict[str, Any]:
        """
        Compare variant performance within each ad set.
        Returns evaluation with winners and losers.
        """
        if min_impressions is None:
            min_impressions = self.DEFAULT_MIN_IMPRESSIONS

        ad_sets = (
            self.db.query(UrlAdSet)
            .filter(UrlAdSet.campaign_id == campaign_id)
            .filter(UrlAdSet.is_active == True)
            .all()
        )

        evaluation = {
            "campaign_id": str(campaign_id),
            "ad_sets": [],
            "total_winners": 0,
            "total_losers": 0,
        }

        for ad_set in ad_sets:
            contents = (
                self.db.query(UrlAdContent)
                .filter(UrlAdContent.ad_set_id == ad_set.id)
                .filter(UrlAdContent.is_active == True)
                .all()
            )

            if len(contents) <= 1:
                continue  # Nothing to compare

            # Aggregate metrics per content
            content_stats = []
            for content in contents:
                totals = self.db.query(
                    func.sum(AdContentMetrics.impressions).label("impressions"),
                    func.sum(AdContentMetrics.clicks).label("clicks"),
                    func.sum(AdContentMetrics.spend).label("spend"),
                    func.sum(AdContentMetrics.conversions).label("conversions"),
                ).filter(AdContentMetrics.ad_content_id == content.id).first()

                impressions = totals.impressions or 0
                clicks = totals.clicks or 0
                spend = float(totals.spend or 0)
                ctr = (clicks / impressions * 100) if impressions > 0 else 0
                cpc = (spend / clicks) if clicks > 0 else 0

                content_stats.append({
                    "ad_content_id": str(content.id),
                    "variation_label": content.variation_label,
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr": round(ctr, 3),
                    "cpc": round(cpc, 3),
                    "spend": round(spend, 2),
                    "status": "active",
                })

            # Check if we have enough data
            total_impressions = sum(s["impressions"] for s in content_stats)
            if total_impressions < min_impressions:
                ad_set_eval = {
                    "ad_set_id": str(ad_set.id),
                    "ad_set_name": ad_set.name,
                    "status": "insufficient_data",
                    "total_impressions": total_impressions,
                    "min_required": min_impressions,
                    "variants": content_stats,
                }
                evaluation["ad_sets"].append(ad_set_eval)
                continue

            # Find best CTR
            best_ctr = max(s["ctr"] for s in content_stats) if content_stats else 0
            threshold = best_ctr * self.LOSER_CTR_THRESHOLD

            for stat in content_stats:
                if stat["impressions"] < 100:
                    stat["status"] = "insufficient_data"
                elif stat["ctr"] >= best_ctr * 0.9:
                    stat["status"] = "winner"
                    evaluation["total_winners"] += 1
                elif stat["ctr"] < threshold:
                    stat["status"] = "loser"
                    evaluation["total_losers"] += 1
                else:
                    stat["status"] = "active"

            ad_set_eval = {
                "ad_set_id": str(ad_set.id),
                "ad_set_name": ad_set.name,
                "status": "evaluated",
                "total_impressions": total_impressions,
                "best_ctr": round(best_ctr, 3),
                "loser_threshold": round(threshold, 3),
                "variants": content_stats,
            }
            evaluation["ad_sets"].append(ad_set_eval)

        return evaluation

    def optimize_campaign(
        self,
        campaign_id: uuid.UUID,
        min_impressions: int = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Full optimization: collect metrics → evaluate → pause losers → scale winners.

        Args:
            dry_run: If True, returns what would happen without making changes.
        """
        # Step 1: Collect latest metrics
        collect_result = self.collect_metrics(campaign_id)
        if collect_result.get("error"):
            return {"error": collect_result["error"], "dry_run": dry_run}

        # Step 2: Evaluate variants
        evaluation = self.evaluate_variants(campaign_id, min_impressions)

        actions = []
        budget_changes = []

        for ad_set_eval in evaluation.get("ad_sets", []):
            if ad_set_eval["status"] != "evaluated":
                continue

            ad_set_id = ad_set_eval["ad_set_id"]
            has_winner = any(v["status"] == "winner" for v in ad_set_eval["variants"])

            for variant in ad_set_eval["variants"]:
                if variant["status"] == "loser":
                    action = {
                        "action": "pause",
                        "ad_content_id": variant["ad_content_id"],
                        "variation_label": variant["variation_label"],
                        "reason": f"CTR {variant['ctr']}% below threshold {ad_set_eval['loser_threshold']}%",
                    }
                    actions.append(action)

                    if not dry_run:
                        content = self.db.query(UrlAdContent).filter(
                            UrlAdContent.id == variant["ad_content_id"]
                        ).first()
                        if content:
                            content.is_active = False
                            # Pause on Meta if published
                            if content.meta_ad_id:
                                self._pause_meta_ad(content.meta_ad_id)

            # Scale winning ad set budget
            if has_winner and not dry_run:
                ad_set = self.db.query(UrlAdSet).filter(UrlAdSet.id == ad_set_id).first()
                if ad_set and ad_set.daily_budget:
                    old_budget = ad_set.daily_budget
                    ad_set.daily_budget = round(old_budget * self.WINNER_BUDGET_BOOST, 2)
                    budget_changes.append({
                        "ad_set_id": ad_set_id,
                        "ad_set_name": ad_set_eval["ad_set_name"],
                        "old_budget": old_budget,
                        "new_budget": ad_set.daily_budget,
                    })

        if not dry_run:
            self.db.commit()

        return {
            "campaign_id": str(campaign_id),
            "dry_run": dry_run,
            "metrics_synced": collect_result.get("synced", 0),
            "evaluation": evaluation,
            "actions_taken": actions,
            "paused_count": len([a for a in actions if a["action"] == "pause"]),
            "budget_changes": budget_changes,
        }

    def _pause_meta_ad(self, meta_ad_id: str):
        """Pause an ad on Meta via the Graph API."""
        try:
            from modules.marketing.models import MetaAd
            meta_ad = self.db.query(MetaAd).filter(MetaAd.ad_id == meta_ad_id).first()
            if not meta_ad or not meta_ad.ad_account:
                logger.warning(f"[Optimizer] Cannot pause ad {meta_ad_id}: no MetaAd or account found")
                return

            access_token = meta_ad.ad_account.access_token
            url = f"{FB_GRAPH_API_BASE}/{meta_ad_id}"
            response = requests.post(url, data={
                "status": "PAUSED",
                "access_token": access_token,
            })
            response.raise_for_status()
            logger.info(f"[Optimizer] Paused Meta ad {meta_ad_id}")
        except Exception as e:
            logger.error(f"[Optimizer] Failed to pause Meta ad {meta_ad_id}: {e}")

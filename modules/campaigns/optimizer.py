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

    def publish_replacement_ad(self, new_content, old_meta_ad_id: str, campaign) -> Optional[str]:
        """
        Create a fresh Meta ad for a refreshed creative, inside the same Meta ad set
        the fatigued ad belonged to. Returns the new Meta ad id, or None on failure.

        Mirrors the link_data creative built by the /publish-to-meta-ads endpoint so a
        refreshed ad is structurally identical to a hand-published one.

        Safety gate: the new ad goes live ACTIVE only when the campaign has
        auto_publish_refresh enabled; otherwise it is created PAUSED for a human to
        approve before it spends.
        """
        import json
        from modules.marketing.models import MetaAd
        from modules.marketing.router import create_meta_ad

        try:
            old_meta_ad = self.db.query(MetaAd).filter(MetaAd.ad_id == old_meta_ad_id).first()
            if not old_meta_ad or not old_meta_ad.ad_set or not old_meta_ad.ad_account:
                logger.warning(
                    f"[Optimizer] Cannot publish replacement for {old_meta_ad_id}: "
                    f"missing MetaAd/ad_set/account"
                )
                return None

            ad_account = old_meta_ad.ad_account
            meta_adset_id = old_meta_ad.ad_set.adset_id  # Meta string ad set id

            # Resolve a Facebook Page that belongs to the SAME business account as this
            # ad account. Never fall back to "first connected Page" — that could publish
            # one client's ad under another client's Page (cross-client identity leak).
            facebook_page_id = None
            if not ad_account.business_account_id:
                logger.warning(
                    f"[Optimizer] Ad account {ad_account.ad_account_id} has no linked business "
                    f"account; cannot safely resolve a Page. Skipping replacement for {old_meta_ad_id}."
                )
                return None
            try:
                from modules.business.models import FacebookPage
                fb_page = (
                    self.db.query(FacebookPage)
                    .filter(
                        FacebookPage.business_account_id == ad_account.business_account_id,
                        FacebookPage.is_connected == True,
                        FacebookPage.is_active == True,
                    )
                    .first()
                )
                if fb_page:
                    facebook_page_id = fb_page.page_id
            except Exception as page_err:
                logger.warning(f"[Optimizer] Could not resolve Facebook page: {page_err}")

            if not facebook_page_id:
                logger.warning(
                    f"[Optimizer] No Facebook page for this account's business; cannot publish "
                    f"replacement for {old_meta_ad_id}"
                )
                return None

            # Safety gate: auto-refreshed creative goes live ONLY if the store owner
            # chose auto-publish in settings AND the campaign opted in. Default is
            # review (PAUSED) so nothing an AI produced is published unseen.
            store_auto_publish = False
            try:
                from modules.stores.models import Store
                store = self.db.query(Store).filter(Store.id == campaign.store_id).first()
                store_auto_publish = bool(store and store.ai_creative_auto_publish)
            except Exception as store_err:
                logger.warning(f"[Optimizer] Could not read store auto-publish setting: {store_err}")

            opted_in = store_auto_publish and getattr(campaign, "auto_publish_refresh", False)
            new_status = "ACTIVE" if opted_in else "PAUSED"

            # Compliance gate: FAIL CLOSED. If the copy trips prohibited content, or the
            # check errors out at all, force PAUSED for human review rather than risk
            # auto-publishing something non-compliant.
            if new_status == "ACTIVE":
                try:
                    from modules.agents.compliance_agent import ComplianceAgent
                    verdict = ComplianceAgent().check_ad_copy(
                        new_content.headline, new_content.primary_text, new_content.description
                    )
                    if not verdict["compliant"]:
                        new_status = "PAUSED"
                        logger.warning(
                            f"[Optimizer] Refreshed ad copy flagged by compliance "
                            f"{verdict['blocked_words']}; forcing PAUSED for human review."
                        )
                except Exception as comp_err:
                    new_status = "PAUSED"  # fail closed
                    logger.warning(f"[Optimizer] Compliance check errored; forcing PAUSED: {comp_err}")

            link = new_content.destination_url or getattr(campaign, "source_url", None)
            meta_ad_data = {
                "name": f"{new_content.variation_label or 'Refresh'} - Ad",
                "adset_id": meta_adset_id,
                "status": new_status,  # ACTIVE only when auto_publish_refresh is on
                "creative": json.dumps({
                    "object_story_spec": {
                        "page_id": facebook_page_id,
                        "link_data": {
                            "link": link,
                            "message": new_content.primary_text or campaign.name,
                            "name": new_content.headline or campaign.name,
                            "description": new_content.description or "",
                            "call_to_action": {
                                "type": "LEARN_MORE",
                                "value": {"link": link},
                            },
                        },
                    }
                }),
            }

            result = create_meta_ad(ad_account.ad_account_id, ad_account.access_token, meta_ad_data)
            new_meta_ad_id = result.get("id") if isinstance(result, dict) else None
            if not new_meta_ad_id:
                logger.error(f"[Optimizer] create_meta_ad returned no id for replacement: {result}")
                return None

            # Persist the Meta ad row so future insight syncs and pauses can find it
            db_meta_ad = MetaAd(
                ad_id=new_meta_ad_id,
                ad_account_id=ad_account.id,
                adset_id=old_meta_ad.adset_id,
                campaign_id=old_meta_ad.campaign_id,
                name=meta_ad_data["name"],
                status=new_status,
                effective_status=new_status,
                created_time=datetime.utcnow(),
                updated_time=datetime.utcnow(),
                is_active=True,
            )
            self.db.add(db_meta_ad)

            logger.info(
                f"[Optimizer] Published replacement Meta ad {new_meta_ad_id} in ad set {meta_adset_id}"
            )
            return new_meta_ad_id
        except Exception as e:
            logger.error(f"[Optimizer] Failed to publish replacement ad for {old_meta_ad_id}: {e}")
            return None

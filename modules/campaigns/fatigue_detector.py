# modules/campaigns/fatigue_detector.py
"""
Ad fatigue detection and automatic creative refresh.

Monitors ad frequency, CTR trends, and performance drops to identify
fatigued creatives, then generates fresh replacements.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    UrlCampaign, UrlAdSet, UrlAdContent, AdContentMetrics, CampaignStatus,
)

logger = logging.getLogger(__name__)


class FatigueDetector:
    """Detects ad fatigue and triggers creative refresh."""

    # Fatigue thresholds
    FREQUENCY_THRESHOLD = 3.0  # Avg impressions/person — above this = overexposure
    CTR_DECLINE_DAYS = 3       # Consecutive days of CTR decline = fatigue signal
    CTR_DROP_PERCENT = 30      # % drop from peak CTR = fatigue signal
    FATIGUE_SCORE_THRESHOLD = 60  # Score above this = fatigued

    def __init__(self, db: Session):
        self.db = db

    def check_fatigue(self, campaign_id: uuid.UUID) -> Dict[str, Any]:
        """
        Check all active ad contents for fatigue signals.

        Fatigue score (0-100):
        - Frequency score (0-50): how much frequency exceeds threshold
        - CTR decline score (0-25): consecutive declining days
        - CTR drop score (0-25): % drop from peak CTR
        """
        campaign = self.db.query(UrlCampaign).filter(UrlCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}

        # Get all active ad contents for this campaign
        ad_contents = (
            self.db.query(UrlAdContent)
            .join(UrlAdSet, UrlAdContent.ad_set_id == UrlAdSet.id)
            .filter(UrlAdSet.campaign_id == campaign_id)
            .filter(UrlAdContent.is_active == True)
            .all()
        )

        results = []
        fatigued_ids = []

        for content in ad_contents:
            # Get last 7 days of metrics ordered by date
            metrics = (
                self.db.query(AdContentMetrics)
                .filter(AdContentMetrics.ad_content_id == content.id)
                .order_by(AdContentMetrics.date.desc())
                .limit(7)
                .all()
            )

            if not metrics:
                results.append({
                    "ad_content_id": str(content.id),
                    "variation_label": content.variation_label,
                    "fatigue_score": 0.0,
                    "frequency": 0.0,
                    "ctr_trend": "no_data",
                    "action": None,
                })
                continue

            # --- Calculate fatigue signals ---

            # 1. Frequency score (0-50)
            avg_frequency = sum(m.frequency for m in metrics) / len(metrics) if metrics else 0
            freq_score = min((avg_frequency / self.FREQUENCY_THRESHOLD) * 50, 50) if self.FREQUENCY_THRESHOLD > 0 else 0

            # 2. CTR decline score (0-25) — check consecutive declining days
            ctrs = [m.ctr for m in reversed(metrics)]  # oldest → newest
            decline_days = 0
            for j in range(1, len(ctrs)):
                if ctrs[j] < ctrs[j - 1]:
                    decline_days += 1
                else:
                    decline_days = 0  # Reset on any uptick
            ctr_decline_score = min((decline_days / self.CTR_DECLINE_DAYS) * 25, 25)

            # 3. CTR drop from peak (0-25)
            peak_ctr = max(ctrs) if ctrs else 0
            current_ctr = ctrs[-1] if ctrs else 0
            drop_pct = ((peak_ctr - current_ctr) / peak_ctr * 100) if peak_ctr > 0 else 0
            ctr_drop_score = min((drop_pct / self.CTR_DROP_PERCENT) * 25, 25)

            fatigue_score = round(freq_score + ctr_decline_score + ctr_drop_score, 1)

            # Determine CTR trend
            if decline_days >= self.CTR_DECLINE_DAYS:
                ctr_trend = "declining"
            elif drop_pct >= self.CTR_DROP_PERCENT:
                ctr_trend = "dropped"
            else:
                ctr_trend = "stable"

            # Determine action
            action = None
            if fatigue_score > 80:
                action = "refresh_both"  # Refresh copy AND image
            elif fatigue_score > self.FATIGUE_SCORE_THRESHOLD:
                action = "refresh_copy"  # Refresh copy only (cheaper)

            # Update fatigue score on the content
            content.fatigue_score = fatigue_score

            if action:
                fatigued_ids.append(content.id)

            results.append({
                "ad_content_id": str(content.id),
                "variation_label": content.variation_label,
                "fatigue_score": fatigue_score,
                "frequency": round(avg_frequency, 2),
                "ctr_trend": ctr_trend,
                "peak_ctr": round(peak_ctr, 3),
                "current_ctr": round(current_ctr, 3),
                "decline_days": decline_days,
                "action": action,
            })

        self.db.commit()

        return {
            "campaign_id": str(campaign_id),
            "total_checked": len(ad_contents),
            "fatigued_count": len(fatigued_ids),
            "fatigued_content_ids": [str(fid) for fid in fatigued_ids],
            "variants": results,
        }

    async def refresh_creatives(
        self,
        campaign_id: uuid.UUID,
        fatigued_content_ids: List[uuid.UUID],
    ) -> Dict[str, Any]:
        """
        Generate fresh creatives for fatigued ad contents.

        - fatigue_score > 80: refresh both copy AND image
        - fatigue_score 60-80: refresh copy only (cheaper)
        """
        from modules.agents.copywriter_agent import CopywriterAgent
        from modules.agents.media_generator_agent import MediaGeneratorAgent

        campaign = self.db.query(UrlCampaign).filter(UrlCampaign.id == campaign_id).first()
        if not campaign:
            return {"error": "Campaign not found"}

        copywriter = CopywriterAgent()
        media_generator = MediaGeneratorAgent()
        refreshed = []
        errors = []

        for content_id in fatigued_content_ids:
            try:
                old_content = self.db.query(UrlAdContent).filter(UrlAdContent.id == content_id).first()
                if not old_content or not old_content.is_active:
                    continue

                ad_set = self.db.query(UrlAdSet).filter(UrlAdSet.id == old_content.ad_set_id).first()
                if not ad_set:
                    continue

                refresh_image = old_content.fatigue_score > 80
                scraped_data = campaign.scraped_data or {}

                # Generate new copy
                logger.info(f"[FatigueDetector] Refreshing content {content_id} (score={old_content.fatigue_score})")
                new_copies = await copywriter.generate_copy_variations_for_url_ad(
                    business_name=campaign.name,
                    product_description=old_content.primary_text or "",
                    target_audience=ad_set.name,
                    base_headline=old_content.headline or "",
                    base_primary_text=old_content.primary_text or "",
                    features=ad_set.audience_tags or [],
                    cta=old_content.call_to_action or "Learn More",
                    num_variations=1,
                    store_id=str(campaign.store_id) if campaign.store_id else None,
                )

                new_copy = new_copies[0] if new_copies else {
                    "headline": old_content.headline,
                    "primary_text": old_content.primary_text,
                    "description": old_content.description,
                    "call_to_action": old_content.call_to_action,
                }

                # Generate new image if needed
                new_image_base64 = None
                new_cloudinary_url = old_content.media_url  # Keep old image by default

                if refresh_image:
                    try:
                        logo_url = scraped_data.get("logo_url")
                        color_theme = scraped_data.get("color_theme") or scraped_data.get("brand_color")
                        brand_colors = scraped_data.get("brand_colors", [])
                        accent = color_theme or (brand_colors[0] if brand_colors else "#FFB800")

                        ad_result = await media_generator.generate_campaign_ad(
                            store_name=campaign.name,
                            store_description=new_copy.get("primary_text", ""),
                            business_type=scraped_data.get("business_identity", {}).get("industry", "business") if isinstance(scraped_data.get("business_identity"), dict) else "business",
                            logo_url=logo_url,
                            screenshot_url=scraped_data.get("screenshot_url"),
                            color_theme=color_theme,
                            accent_color=accent,
                            scene_prompt=f"Fresh creative variation for refreshed ad. Different angle and mood from previous.",
                            headline=new_copy.get("headline", ""),
                            cta_text=new_copy.get("call_to_action", "Learn More"),
                            upload_to_cloud=True,
                        )

                        if ad_result.get("success"):
                            new_image_base64 = ad_result.get("image_base64")
                            new_cloudinary_url = ad_result.get("cloudinary_url")
                            logger.info(f"[FatigueDetector] Generated new image: {new_cloudinary_url}")
                    except Exception as img_err:
                        logger.error(f"[FatigueDetector] Image refresh failed: {img_err}")

                # Pause old content
                old_content.is_active = False

                # Pause on Meta if published, and remember its ad id so we can
                # publish the fresh creative into the same ad set.
                old_meta_ad_id = old_content.meta_ad_id
                optimizer = None
                if old_meta_ad_id:
                    from .optimizer import CampaignOptimizer
                    optimizer = CampaignOptimizer(self.db)
                    optimizer._pause_meta_ad(old_meta_ad_id)

                # Create new content
                new_content = UrlAdContent(
                    ad_set_id=ad_set.id,
                    headline=new_copy.get("headline"),
                    primary_text=new_copy.get("primary_text"),
                    description=new_copy.get("description"),
                    call_to_action=new_copy.get("call_to_action"),
                    destination_url=old_content.destination_url,
                    media_url=new_cloudinary_url,
                    media_type=old_content.media_type,
                    generated_image_base64=new_image_base64,
                    is_primary=True,
                    is_active=True,
                    parent_content_id=old_content.id,
                    last_refreshed_at=datetime.utcnow(),
                    variation_label=f"Refresh-{old_content.variation_label or 'A'}",
                )
                self.db.add(new_content)
                self.db.flush()

                # Publish the replacement to Meta so the ad set keeps a live ad.
                # Without this, refresh would only pause the fatigued ad and leave
                # the fresh creative sitting unpublished in the database.
                new_meta_ad_id = None
                if old_meta_ad_id and optimizer is not None:
                    new_meta_ad_id = optimizer.publish_replacement_ad(
                        new_content, old_meta_ad_id, campaign
                    )
                    if new_meta_ad_id:
                        new_content.meta_ad_id = new_meta_ad_id

                refreshed.append({
                    "old_content_id": str(content_id),
                    "new_content_id": str(new_content.id),
                    "refresh_type": "copy_and_image" if refresh_image else "copy_only",
                    "new_headline": new_copy.get("headline"),
                    "published_to_meta": bool(new_meta_ad_id),
                })

            except Exception as e:
                logger.error(f"[FatigueDetector] Error refreshing content {content_id}: {e}")
                errors.append({"content_id": str(content_id), "error": str(e)})

        self.db.commit()

        return {
            "campaign_id": str(campaign_id),
            "refreshed_count": len(refreshed),
            "refreshed": refreshed,
            "errors": errors,
        }

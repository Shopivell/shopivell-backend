# modules/marketing/insights_service.py
"""
Extracted insights sync logic for reuse by scheduler and other services.

Usage:
    from modules.marketing.insights_service import sync_insights_for_all_accounts

    # In scheduler cycle:
    await sync_insights_for_all_accounts(days=3)
"""

import json
import logging
import requests
from datetime import datetime, timedelta, date
from typing import Optional
import uuid

from sqlalchemy.orm import Session
from database import SessionLocal
from .models import MetaAdAccount, MetaAd, MetaAdInsight

logger = logging.getLogger(__name__)

# Facebook Graph API base URL
FB_GRAPH_API_BASE = "https://graph.facebook.com/v24.0"


def _get_meta_insights(ad_account_id: str, access_token: str, params: dict) -> dict:
    """Get insights from Meta Ads API"""
    try:
        url = f"{FB_GRAPH_API_BASE}/{ad_account_id}/insights"
        query_params = {"access_token": access_token, **params}
        response = requests.get(url, params=query_params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        error_detail = str(e)
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except Exception:
            pass
        logger.error(f"[InsightsService] Meta API error: {error_detail}")
        return {"data": [], "error": error_detail}


def sync_ad_insights(ad: MetaAd, start_date: date, end_date: date, db: Session):
    """Sync insights for a specific ad from Meta API into the database."""
    try:
        params = {
            "level": "ad",
            "time_range": json.dumps({
                "since": start_date.strftime("%Y-%m-%d"),
                "until": end_date.strftime("%Y-%m-%d")
            }),
            "fields": "impressions,clicks,spend,cpm,cpc,ctr,frequency,reach,actions,conversions"
        }

        insights_data = _get_meta_insights(
            ad.ad_account.ad_account_id,
            ad.ad_account.access_token,
            params
        )

        insights_list = insights_data.get("data", [])

        for insight in insights_list:
            if insight.get("ad_id") != ad.ad_id:
                continue

            date_str = insight.get("date_start")
            if not date_str:
                continue

            insight_date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Check if insight already exists for this date
            existing_insight = db.query(MetaAdInsight).filter(
                MetaAdInsight.ad_id == ad.id,
                MetaAdInsight.date == insight_date
            ).first()

            # Parse metrics
            impressions = int(insight.get("impressions", 0))
            clicks = int(insight.get("clicks", 0))
            spend = float(insight.get("spend", 0))
            cpm = float(insight.get("cpm", 0))
            cpc = float(insight.get("cpc", 0))
            ctr = float(insight.get("ctr", 0))
            frequency = float(insight.get("frequency", 0))
            reach = int(insight.get("reach", 0))

            # Parse conversions from actions
            conversions = 0
            actions = insight.get("actions", [])
            for action in actions:
                if action.get("action_type") in ["offsite_conversion", "purchase", "lead"]:
                    conversions += int(action.get("value", 0))

            cost_per_conversion = spend / conversions if conversions > 0 else 0
            conversion_rate = (conversions / clicks * 100) if clicks > 0 else 0

            insight_info = {
                "ad_id": ad.id,
                "date": insight_date,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "cpm": cpm,
                "cpc": cpc,
                "ctr": ctr,
                "frequency": frequency,
                "reach": reach,
                "conversions": conversions,
                "cost_per_conversion": cost_per_conversion,
                "conversion_rate": conversion_rate,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "raw_data": insight
            }

            if existing_insight:
                for key, value in insight_info.items():
                    setattr(existing_insight, key, value)
                existing_insight.updated_at = datetime.utcnow()
            else:
                new_insight = MetaAdInsight(**insight_info)
                db.add(new_insight)

        db.commit()

        # Update ad's last_synced_at
        ad.last_synced_at = datetime.utcnow()
        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[InsightsService] Failed to sync insights for ad {ad.id}: {str(e)}")
        raise


def sync_insights_background(db: Session, days: int, account_id: Optional[uuid.UUID] = None):
    """Sync insights for all active ads (background task compatible)."""
    try:
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)

        query = db.query(MetaAd).join(MetaAdAccount).filter(
            MetaAd.is_active == True,
            MetaAd.status == "ACTIVE",
            MetaAdAccount.is_connected == True
        )

        if account_id:
            query = query.filter(MetaAdAccount.id == account_id)

        ads = query.all()

        synced = 0
        errors = 0
        for ad in ads:
            try:
                sync_ad_insights(ad, start_date, end_date, db)
                synced += 1
            except Exception as e:
                logger.warning(f"[InsightsService] Failed to sync ad {ad.id}: {str(e)}")
                errors += 1
                continue

        logger.info(f"[InsightsService] Sync complete: {synced} synced, {errors} errors out of {len(ads)} ads")
        return {"synced": synced, "errors": errors, "total": len(ads)}

    except Exception as e:
        logger.error(f"[InsightsService] Background sync failed: {str(e)}")
        return {"synced": 0, "errors": 1, "error": str(e)}


def get_demographic_breakdown(ad_account_id: str, access_token: str, days: int = 7) -> dict:
    """
    Get demographic breakdown (age, gender, placement) from Meta Insights API.

    Calls Meta API with breakdowns=age,gender,placement to understand
    which demographics are converting best.

    Args:
        ad_account_id: Meta ad account ID (e.g., "act_123456")
        access_token: Meta API access token
        days: Number of days to look back

    Returns:
        Dict with demographic breakdown data
    """
    try:
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)

        import json as _json
        params = {
            "time_range": _json.dumps({
                "since": start_date.strftime("%Y-%m-%d"),
                "until": end_date.strftime("%Y-%m-%d")
            }),
            "fields": "impressions,clicks,spend,conversions,ctr,cpc",
            "breakdowns": "age,gender",
            "level": "account"
        }

        result = _get_meta_insights(ad_account_id, access_token, params)
        breakdown_data = result.get("data", [])

        # Parse into structured format
        age_performance = {}
        gender_performance = {}

        for row in breakdown_data:
            age = row.get("age", "unknown")
            gender = row.get("gender", "unknown")
            impressions = int(row.get("impressions", 0))
            clicks = int(row.get("clicks", 0))
            spend = float(row.get("spend", 0))
            ctr = float(row.get("ctr", 0))

            # Aggregate by age
            if age not in age_performance:
                age_performance[age] = {"impressions": 0, "clicks": 0, "spend": 0}
            age_performance[age]["impressions"] += impressions
            age_performance[age]["clicks"] += clicks
            age_performance[age]["spend"] += spend

            # Aggregate by gender
            if gender not in gender_performance:
                gender_performance[gender] = {"impressions": 0, "clicks": 0, "spend": 0}
            gender_performance[gender]["impressions"] += impressions
            gender_performance[gender]["clicks"] += clicks
            gender_performance[gender]["spend"] += spend

        # Calculate CTR for each group
        for group in [age_performance, gender_performance]:
            for key, data in group.items():
                data["ctr"] = round((data["clicks"] / data["impressions"] * 100), 2) if data["impressions"] > 0 else 0

        # Find best performing segments
        best_age = max(age_performance.items(), key=lambda x: x[1].get("ctr", 0))[0] if age_performance else None
        best_gender = max(gender_performance.items(), key=lambda x: x[1].get("ctr", 0))[0] if gender_performance else None

        return {
            "success": True,
            "age_breakdown": age_performance,
            "gender_breakdown": gender_performance,
            "best_performing_age": best_age,
            "best_performing_gender": best_gender,
            "raw_data": breakdown_data,
            "period_days": days
        }

    except Exception as e:
        logger.error(f"[InsightsService] Demographic breakdown error: {str(e)}")
        return {"success": False, "error": str(e), "age_breakdown": {}, "gender_breakdown": {}}


async def sync_insights_for_all_accounts(days: int = 3) -> dict:
    """
    Async wrapper for scheduler use — creates its own DB session.

    Args:
        days: Number of days to sync (default 3 for scheduler, saves API calls)

    Returns:
        Dict with sync results
    """
    db = SessionLocal()
    try:
        result = sync_insights_background(db, days)
        logger.info(f"[InsightsService] Scheduler sync: {result}")
        return result
    except Exception as e:
        logger.error(f"[InsightsService] Scheduler sync failed: {str(e)}")
        return {"synced": 0, "errors": 1, "error": str(e)}
    finally:
        db.close()

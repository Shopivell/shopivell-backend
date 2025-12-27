# modules/campaigns/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import logging

from database import get_db
from .models import UrlCampaign, CampaignStatus, UrlAdSet, UrlAdContent

# Aliases for readability
Campaign = UrlCampaign
AdSet = UrlAdSet
AdContent = UrlAdContent
from .schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse, CampaignListResponse,
    ScrapeUrlRequest, ScrapeUrlResponse, AdSetResponse, AdContentResponse,
    GenerateAdsRequest
)
from .service import CampaignService

# Import Facebook posting functionality
try:
    from modules.business.router import post_to_facebook_page
    from modules.business.schemas import FacebookPostCreate
    from modules.business.models import FacebookPage
    FACEBOOK_AVAILABLE = True
except ImportError:
    FACEBOOK_AVAILABLE = False

logger = logging.getLogger(__name__)

campaign_router = APIRouter(prefix="/api/url-campaigns", tags=["url-campaigns"])


@campaign_router.post("/scrape", response_model=ScrapeUrlResponse)
def scrape_url_and_create_campaign(
    request: ScrapeUrlRequest,
    db: Session = Depends(get_db)
):
    """Scrape a URL and create a campaign with generated ad content."""
    service = CampaignService(db)
    campaign, error = service.scrape_url_for_campaign(
        url=request.url,
        store_id=request.store_id,
        campaign_name=request.campaign_name,
        asset_ids=request.asset_ids
    )

    if error and not campaign:
        raise HTTPException(status_code=500, detail=error)

    return ScrapeUrlResponse(
        campaign_id=campaign.id,
        status=campaign.status.value,
        message="Campaign created successfully" if not error else error,
        scraped_data=campaign.scraped_data
    )


@campaign_router.get("/store/{store_id}", response_model=CampaignListResponse)
def get_store_campaigns(
    store_id: uuid.UUID,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status: Optional[CampaignStatus] = None,
    db: Session = Depends(get_db)
):
    """Get all campaigns for a store."""
    query = db.query(Campaign).filter(Campaign.store_id == store_id)

    if status:
        query = query.filter(Campaign.status == status)

    total = query.count()
    campaigns = query.order_by(Campaign.created_at.desc()).offset((page - 1) * size).limit(size).all()

    return CampaignListResponse(
        campaigns=[CampaignResponse.model_validate(c) for c in campaigns],
        total=total,
        page=page,
        size=size
    )


@campaign_router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific campaign with all its ad sets and content."""
    from sqlalchemy.orm import joinedload

    campaign = db.query(Campaign).options(
        joinedload(Campaign.ad_sets).joinedload(AdSet.ad_contents)
    ).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@campaign_router.put("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: uuid.UUID,
    update_data: CampaignUpdate,
    db: Session = Depends(get_db)
):
    """Update campaign settings."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(campaign, field, value)

    db.commit()
    db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@campaign_router.delete("/{campaign_id}")
def delete_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted successfully"}


@campaign_router.put("/ad-content/{ad_content_id}")
def update_ad_content(
    ad_content_id: uuid.UUID,
    data: dict,
    db: Session = Depends(get_db)
):
    """Update ad content (headline, primary_text, description, media_url, asset_id, generated_image_base64)."""
    ad_content = db.query(AdContent).filter(AdContent.id == ad_content_id).first()
    if not ad_content:
        raise HTTPException(status_code=404, detail="Ad content not found")

    # Update text fields if provided
    if "headline" in data:
        ad_content.headline = data["headline"]
    if "primary_text" in data:
        ad_content.primary_text = data["primary_text"]
    if "description" in data:
        ad_content.description = data["description"]

    # Update media fields if provided
    if "media_url" in data:
        ad_content.media_url = data["media_url"]
    if "asset_id" in data:
        ad_content.asset_id = uuid.UUID(data["asset_id"]) if data["asset_id"] else None
    if "generated_image_base64" in data:
        ad_content.generated_image_base64 = data["generated_image_base64"]

    db.commit()
    db.refresh(ad_content)
    return {"message": "Ad content updated successfully", "id": str(ad_content.id)}


@campaign_router.post("/{campaign_id}/publish", response_model=CampaignResponse)
def publish_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Publish a campaign to ad platforms."""
    service = CampaignService(db)
    campaign, error = service.publish_campaign(campaign_id)

    if error:
        raise HTTPException(status_code=400, detail=error)

    return CampaignResponse.model_validate(campaign)


@campaign_router.post("/{campaign_id}/publish-to-facebook")
def publish_campaign_to_facebook(
    campaign_id: uuid.UUID,
    page_id: uuid.UUID = Query(..., description="Facebook page ID to publish to"),
    db: Session = Depends(get_db)
):
    """
    Publish campaign ads to a selected Facebook page.

    This endpoint posts the selected ad sets from a campaign to the specified Facebook page.
    Each ad set's primary content is posted as a separate Facebook post.

    Args:
        campaign_id: UUID of the campaign to publish
        page_id: UUID of the Facebook page to post to

    Returns:
        Dictionary with success status, message, and list of posted post IDs
    """
    if not FACEBOOK_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Facebook integration is not available"
        )

    # Get the campaign
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get the Facebook page
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Facebook page not found")

    if not page.is_connected or not page.page_access_token:
        raise HTTPException(
            status_code=400,
            detail="Facebook page is not connected or missing access token"
        )

    # Get selected ad sets with their content
    ad_sets = db.query(AdSet).filter(
        AdSet.campaign_id == campaign_id,
        AdSet.is_selected == True
    ).all()

    if not ad_sets:
        raise HTTPException(
            status_code=400,
            detail="No ad sets selected for publishing"
        )

    posted_ids = []
    errors = []

    for ad_set in ad_sets:
        # Get primary ad content for this ad set
        ad_content = db.query(AdContent).filter(
            AdContent.ad_set_id == ad_set.id,
            AdContent.is_primary == True
        ).first()

        if not ad_content:
            continue

        # Prepare post content
        message_parts = []
        if ad_content.headline:
            message_parts.append(ad_content.headline)
        if ad_content.primary_text:
            message_parts.append(ad_content.primary_text)
        if ad_content.description:
            message_parts.append(ad_content.description)
        if ad_content.call_to_action:
            message_parts.append(f"\n{ad_content.call_to_action}")

        message = "\n\n".join(message_parts) if message_parts else f"Check out {campaign.name}!"

        post_data = FacebookPostCreate(
            message=message,
            link=ad_content.destination_url or campaign.source_url,
            published=True
        )

        try:
            result = post_to_facebook_page(
                page.page_id,
                page.page_access_token,
                post_data
            )
            if result and result.get("id"):
                posted_ids.append({
                    "ad_set_id": str(ad_set.id),
                    "ad_set_name": ad_set.name,
                    "facebook_post_id": result.get("id")
                })
                logger.info(f"[Facebook] Posted ad set {ad_set.name} to page {page.page_name}")
        except Exception as e:
            errors.append({
                "ad_set_id": str(ad_set.id),
                "ad_set_name": ad_set.name,
                "error": str(e)
            })
            logger.error(f"[Facebook] Failed to post ad set {ad_set.name}: {e}")

    return {
        "success": len(posted_ids) > 0,
        "message": f"Published {len(posted_ids)} ads to Facebook" if posted_ids else "No ads were published",
        "published_posts": posted_ids,
        "errors": errors if errors else None,
        "campaign_id": str(campaign_id),
        "page_name": page.page_name
    }


@campaign_router.post("/{campaign_id}/pause", response_model=CampaignResponse)
def pause_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Pause an active campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Only active campaigns can be paused")

    campaign.status = CampaignStatus.PAUSED
    db.commit()
    db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@campaign_router.post("/{campaign_id}/resume", response_model=CampaignResponse)
def resume_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Resume a paused campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != CampaignStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Only paused campaigns can be resumed")

    campaign.status = CampaignStatus.ACTIVE
    db.commit()
    db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@campaign_router.post("/{campaign_id}/regenerate", response_model=CampaignResponse)
def regenerate_ads(
    campaign_id: uuid.UUID,
    request: GenerateAdsRequest,
    db: Session = Depends(get_db)
):
    """Regenerate ad content for a campaign."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if not campaign.scraped_data:
        raise HTTPException(status_code=400, detail="No scraped data available for regeneration")

    service = CampaignService(db)

    # Delete existing ad sets if regenerating
    if request.regenerate:
        db.query(AdContent).filter(
            AdContent.ad_set_id.in_(
                db.query(AdSet.id).filter(AdSet.campaign_id == campaign_id)
            )
        ).delete(synchronize_session=False)
        db.query(AdSet).filter(AdSet.campaign_id == campaign_id).delete(synchronize_session=False)

    # Generate new ad content
    ad_content = service._generate_ad_content(campaign.scraped_data, campaign.source_url)
    if ad_content:
        campaign.generated_headlines = ad_content.get("headlines", [])
        campaign.generated_descriptions = ad_content.get("descriptions", [])
        service._create_ad_sets(campaign, ad_content)

    db.commit()
    db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


# Ad Set endpoints
@campaign_router.get("/{campaign_id}/ad-sets", response_model=List[AdSetResponse])
def get_campaign_ad_sets(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all ad sets for a campaign."""
    ad_sets = db.query(AdSet).filter(AdSet.campaign_id == campaign_id).all()
    return [AdSetResponse.model_validate(ad_set) for ad_set in ad_sets]


@campaign_router.put("/ad-sets/{ad_set_id}/toggle")
def toggle_ad_set(ad_set_id: uuid.UUID, db: Session = Depends(get_db)):
    """Toggle ad set selection."""
    ad_set = db.query(AdSet).filter(AdSet.id == ad_set_id).first()
    if not ad_set:
        raise HTTPException(status_code=404, detail="Ad set not found")

    ad_set.is_selected = not ad_set.is_selected
    db.commit()
    return {"is_selected": ad_set.is_selected}

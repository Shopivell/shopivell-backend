# modules/campaigns/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

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
        campaign_name=request.campaign_name
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
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
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


@campaign_router.post("/{campaign_id}/publish", response_model=CampaignResponse)
def publish_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Publish a campaign to ad platforms."""
    service = CampaignService(db)
    campaign, error = service.publish_campaign(campaign_id)

    if error:
        raise HTTPException(status_code=400, detail=error)

    return CampaignResponse.model_validate(campaign)


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

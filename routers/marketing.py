import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import MarketingCampaign
from schemas.marketing_schema import (
    MarketingCampaignCreateSchema,
    MarketingCampaignResponseSchema,
    MarketingCampaignUpdateSchema,
)


logger = logging.getLogger(__name__)

marketing_router = APIRouter(prefix="/marketing", tags=["Marketing"])


@marketing_router.get("/", response_model=List[MarketingCampaignResponseSchema])
def list_marketing_campaigns(db: Session = Depends(get_db)) -> List[MarketingCampaign]:
    return db.query(MarketingCampaign).order_by(MarketingCampaign.created_at.desc()).all()


@marketing_router.post("/", response_model=MarketingCampaignResponseSchema, status_code=status.HTTP_201_CREATED)
def create_marketing_campaign(
    campaign_data: MarketingCampaignCreateSchema,
    db: Session = Depends(get_db),
) -> MarketingCampaign:
    payload = campaign_data.model_dump()
    campaign = MarketingCampaign(**payload)

    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@marketing_router.put("/{campaign_id}", response_model=MarketingCampaignResponseSchema)
def update_marketing_campaign(
    campaign_id: UUID,
    campaign_update: MarketingCampaignUpdateSchema,
    db: Session = Depends(get_db),
) -> MarketingCampaign:
    campaign = db.query(MarketingCampaign).filter(MarketingCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marketing campaign not found.")

    update_data = campaign_update.model_dump(exclude_unset=True)
    if not update_data:
        return campaign

    for key, value in update_data.items():
        setattr(campaign, key, value)

    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@marketing_router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_marketing_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    campaign = db.query(MarketingCampaign).filter(MarketingCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marketing campaign not found.")

    db.delete(campaign)
    db.commit()


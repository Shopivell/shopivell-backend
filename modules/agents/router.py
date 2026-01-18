# router.py - API endpoints for Marketing Agents Module

import uuid
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from .models import Campaign, MarketResearch, CreativeAngle, AdCopy, PerformanceMetrics
from .schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse,
    MarketResearchRequest, MarketResearchResponse,
    CreativeAngleRequest, CreativeAngleResponse,
    AdCopyRequest, AdCopyResponse,
    PerformanceMetricsResponse
)
from .market_research_agent import MarketResearchAgent
from .creative_angles_agent import CreativeAnglesAgent
from .ad_copy_agent import AdCopyAgent
from .monitor_optimizer_agent import MonitorOptimizerAgent
from .media_generator_agent import MediaGeneratorAgent
from .vision_compliance_service import vision_compliance_service
from .monitor_optimizer_agent import automated_rules_engine, AutomatedRule, RuleCondition, RuleAction, RuleType
from .scheduler import rules_scheduler, start_rules_scheduler, stop_rules_scheduler

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

agents_router = APIRouter(prefix="/api/agents", tags=["marketing-agents"])


# ============ Campaign Endpoints ============

@agents_router.post("/campaigns", response_model=CampaignResponse)
def create_campaign(
    campaign_data: CampaignCreate,
    db: Session = Depends(get_db)
):
    """Create a new marketing campaign"""
    try:
        campaign = Campaign(
            name=campaign_data.name,
            objective=campaign_data.objective.value,
            product_description=campaign_data.product_description,
            keywords=campaign_data.keywords,
            target_audience=campaign_data.target_audience,
            budget=campaign_data.budget,
            store_id=campaign_data.store_id,
            status="draft"
        )

        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        logger.info(f"Created campaign: {campaign.id} - {campaign.name}")

        return CampaignResponse.model_validate(campaign)

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign: {str(e)}"
        )


@agents_router.get("/campaigns", response_model=List[CampaignResponse])
def get_campaigns(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    store_id: Optional[uuid.UUID] = Query(None, description="Filter by store"),
    db: Session = Depends(get_db)
):
    """Get all campaigns"""
    query = db.query(Campaign)

    if status_filter:
        query = query.filter(Campaign.status == status_filter)

    if store_id:
        query = query.filter(Campaign.store_id == store_id)

    campaigns = query.order_by(Campaign.created_at.desc()).offset(skip).limit(limit).all()

    return [CampaignResponse.model_validate(c) for c in campaigns]


@agents_router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific campaign"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    return CampaignResponse.model_validate(campaign)


@agents_router.put("/campaigns/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: uuid.UUID,
    campaign_data: CampaignUpdate,
    db: Session = Depends(get_db)
):
    """Update a campaign"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        update_data = campaign_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key == "objective" and value:
                value = value.value  # Convert enum to string
            if key == "status" and value:
                value = value.value
            setattr(campaign, key, value)

        campaign.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(campaign)

        return CampaignResponse.model_validate(campaign)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update campaign: {str(e)}"
        )


@agents_router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a campaign and all related data"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        db.delete(campaign)
        db.commit()
        return {"success": True, "message": "Campaign deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete campaign: {str(e)}"
        )


# ============ Market Research Endpoints ============

@agents_router.post("/campaigns/{campaign_id}/research")
async def generate_market_research(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Generate AI-powered market research for a campaign.

    This endpoint uses GPT-4 to analyze the campaign and provide:
    - Competitor analysis
    - Audience insights
    - Trend data
    - Recommendations
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        logger.info(f"Generating market research for campaign: {campaign.name}")

        agent = MarketResearchAgent()
        result = await agent.conduct_research(campaign)

        logger.info(f"Market research generated for campaign: {campaign.id}")

        return {
            "success": True,
            "message": "Market research generated successfully",
            "research": result
        }

    except Exception as e:
        logger.error(f"Failed to generate market research: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate market research: {str(e)}"
        )


@agents_router.get("/campaigns/{campaign_id}/research", response_model=List[MarketResearchResponse])
def get_market_research(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all market research for a campaign"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    research = db.query(MarketResearch).filter(
        MarketResearch.campaign_id == campaign_id
    ).order_by(MarketResearch.created_at.desc()).all()

    return [MarketResearchResponse.model_validate(r) for r in research]


@agents_router.get("/research/{research_id}", response_model=MarketResearchResponse)
def get_research_by_id(research_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get specific market research by ID"""
    research = db.query(MarketResearch).filter(MarketResearch.id == research_id).first()

    if not research:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Market research not found"
        )

    return MarketResearchResponse.model_validate(research)


# ============ Creative Angle Endpoints ============

@agents_router.post("/campaigns/{campaign_id}/angles")
async def generate_creative_angles(
    campaign_id: uuid.UUID,
    num_angles: int = Query(5, ge=1, le=10, description="Number of angles to generate"),
    db: Session = Depends(get_db)
):
    """
    Generate AI-powered creative angles for a campaign.

    This endpoint uses GPT-4 to generate creative advertising angles based on:
    - Campaign brief
    - Market research (if available)

    Each angle includes:
    - Angle name
    - Value proposition
    - Target emotion
    - Visual direction
    - Reasoning
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        logger.info(f"Generating {num_angles} creative angles for campaign: {campaign.name}")

        agent = CreativeAnglesAgent()
        angles = await agent.generate_angles(campaign, num_angles=num_angles)

        logger.info(f"Generated {len(angles)} creative angles for campaign: {campaign.id}")

        return {
            "success": True,
            "message": f"Generated {len(angles)} creative angles",
            "campaign_id": str(campaign_id),
            "angles": angles
        }

    except Exception as e:
        logger.error(f"Failed to generate creative angles: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate creative angles: {str(e)}"
        )


@agents_router.get("/campaigns/{campaign_id}/angles", response_model=List[CreativeAngleResponse])
def get_creative_angles(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all creative angles for a campaign"""
    angles = db.query(CreativeAngle).filter(
        CreativeAngle.campaign_id == campaign_id
    ).order_by(CreativeAngle.created_at.desc()).all()

    return [CreativeAngleResponse.model_validate(a) for a in angles]


@agents_router.get("/angles/{angle_id}", response_model=CreativeAngleResponse)
def get_angle_by_id(angle_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific creative angle by ID"""
    angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()

    if not angle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creative angle not found"
        )

    return CreativeAngleResponse.model_validate(angle)


@agents_router.delete("/angles/{angle_id}")
def delete_angle(angle_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a creative angle"""
    angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()

    if not angle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creative angle not found"
        )

    try:
        db.delete(angle)
        db.commit()
        return {"success": True, "message": "Creative angle deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete angle: {str(e)}"
        )


# ============ Ad Copy Endpoints ============

@agents_router.post("/campaigns/{campaign_id}/copies")
async def generate_ad_copies(
    campaign_id: uuid.UUID,
    angle_id: Optional[uuid.UUID] = Query(None, description="Generate for specific angle only"),
    db: Session = Depends(get_db)
):
    """
    Generate AI-powered ad copy for a campaign.

    If angle_id is provided, generates copy for that specific angle.
    Otherwise, generates copy for ALL creative angles of the campaign.

    Each ad copy includes:
    - Headline (max 40 chars)
    - Primary text
    - Description
    - Call to action
    - 3 headline variations
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        agent = AdCopyAgent()

        if angle_id:
            # Generate for specific angle
            angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()
            if not angle:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Creative angle not found"
                )

            logger.info(f"Generating ad copy for angle: {angle.angle_name}")
            ad_copy = await agent.generate_ad_copy(campaign, angle)

            return {
                "success": True,
                "message": "Generated ad copy for angle",
                "campaign_id": str(campaign_id),
                "copies": [ad_copy]
            }
        else:
            # Generate for all angles
            angles = db.query(CreativeAngle).filter(
                CreativeAngle.campaign_id == campaign_id
            ).all()

            if not angles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No creative angles found. Generate creative angles first."
                )

            logger.info(f"Generating ad copies for {len(angles)} angles")
            ad_copies = await agent.generate_all_ad_copies(campaign, angles)

            return {
                "success": True,
                "message": f"Generated {len(ad_copies)} ad copies",
                "campaign_id": str(campaign_id),
                "copies": ad_copies
            }

    except Exception as e:
        logger.error(f"Failed to generate ad copies: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ad copies: {str(e)}"
        )


@agents_router.get("/campaigns/{campaign_id}/copies", response_model=List[AdCopyResponse])
def get_ad_copies(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all ad copies for a campaign"""
    copies = db.query(AdCopy).filter(
        AdCopy.campaign_id == campaign_id
    ).order_by(AdCopy.created_at.desc()).all()

    return [AdCopyResponse.model_validate(c) for c in copies]


@agents_router.get("/copies/{copy_id}", response_model=AdCopyResponse)
def get_ad_copy_by_id(copy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific ad copy by ID"""
    copy = db.query(AdCopy).filter(AdCopy.id == copy_id).first()

    if not copy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad copy not found"
        )

    return AdCopyResponse.model_validate(copy)


@agents_router.delete("/copies/{copy_id}")
def delete_ad_copy(copy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete an ad copy"""
    copy = db.query(AdCopy).filter(AdCopy.id == copy_id).first()

    if not copy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad copy not found"
        )

    try:
        db.delete(copy)
        db.commit()
        return {"success": True, "message": "Ad copy deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete ad copy: {str(e)}"
        )


# ============ Performance Metrics Endpoints ============

@agents_router.get("/campaigns/{campaign_id}/metrics", response_model=List[PerformanceMetricsResponse])
def get_performance_metrics(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get performance metrics for a campaign"""
    metrics = db.query(PerformanceMetrics).filter(
        PerformanceMetrics.campaign_id == campaign_id
    ).order_by(PerformanceMetrics.collected_at.desc()).all()

    return [PerformanceMetricsResponse.model_validate(m) for m in metrics]


# ============ Full Campaign Pipeline ============

@agents_router.post("/campaigns/{campaign_id}/run-pipeline")
async def run_campaign_pipeline(
    campaign_id: uuid.UUID,
    num_angles: int = Query(4, ge=1, le=10, description="Number of creative angles to generate"),
    db: Session = Depends(get_db)
):
    """
    Run the full AI campaign pipeline:
    1. Market Research - Analyze competitors, audience, trends
    2. Creative Angles - Generate advertising angles based on research
    3. Ad Copy Generation - Create ad copies for each angle

    This is an async operation that generates all campaign assets.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        results = {}
        print(f"DEBUG: Starting pipeline for campaign {campaign.name}")

        # Step 1: Market Research
        logger.info(f"Pipeline Step 1: Market Research for {campaign.name}")
        print("DEBUG: Starting Step 1 - Market Research")
        research_agent = MarketResearchAgent()
        research_result = await research_agent.conduct_research(campaign)
        results["market_research"] = research_result
        print("DEBUG: Step 1 complete")

        # Step 2: Creative Angles
        logger.info(f"Pipeline Step 2: Generating {num_angles} Creative Angles")
        print(f"DEBUG: Starting Step 2 - Creative Angles ({num_angles})")
        angles_agent = CreativeAnglesAgent()
        angles_result = await angles_agent.generate_angles(campaign, num_angles=num_angles)
        results["creative_angles"] = angles_result
        print(f"DEBUG: Step 2 complete - generated {len(angles_result)} angles")

        # Step 3: Ad Copy Generation
        logger.info(f"Pipeline Step 3: Generating Ad Copies for {len(angles_result)} angles")
        print(f"DEBUG: Starting Step 3 - Ad Copies for {len(angles_result)} angles")
        ad_agent = AdCopyAgent()

        # Get the angles from database (they were just saved)
        angles = db.query(CreativeAngle).filter(
            CreativeAngle.campaign_id == campaign_id
        ).all()

        ad_copies_result = await ad_agent.generate_all_ad_copies(campaign, angles)
        results["ad_copies"] = ad_copies_result
        print(f"DEBUG: Step 3 complete - generated {len(ad_copies_result)} ad copies")

        # Update campaign status
        campaign.status = "active"
        db.commit()

        return {
            "success": True,
            "message": "Campaign pipeline completed successfully",
            "campaign_id": str(campaign_id),
            "summary": {
                "market_research": 1,
                "creative_angles": len(angles_result),
                "ad_copies": len(ad_copies_result)
            },
            "results": results
        }

    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {str(e)}"
        )


# ============ Performance Optimization Endpoints ============

@agents_router.post("/campaigns/{campaign_id}/optimize")
async def optimize_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Analyze campaign performance and get AI-powered optimization recommendations.

    This endpoint uses GPT-4 to analyze:
    - CTR (Click-Through Rate)
    - CPC (Cost Per Click)
    - ROAS (Return on Ad Spend)
    - Conversion rates
    - Spend efficiency

    Returns actionable recommendations with priority levels.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        # Get performance metrics from database
        metrics = db.query(PerformanceMetrics).filter(
            PerformanceMetrics.campaign_id == campaign_id
        ).all()

        if not metrics:
            return {
                "success": True,
                "message": "No performance data available for optimization",
                "campaign_id": str(campaign_id),
                "recommendations": []
            }

        # Prepare performance data for analysis
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

        logger.info(f"Analyzing performance for campaign: {campaign.name}")

        agent = MonitorOptimizerAgent()
        result = await agent.analyze_performance(campaign, performance_data)

        return {
            "success": True,
            "message": f"Generated {len(result.get('recommendations', []))} optimization recommendations",
            **result
        }

    except Exception as e:
        logger.error(f"Failed to optimize campaign: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to optimize campaign: {str(e)}"
        )


@agents_router.get("/campaigns/{campaign_id}/summary")
async def get_campaign_summary(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get an AI-generated executive summary of campaign performance.

    Returns:
    - Overall health score (1-10)
    - Performance summary
    - Aggregated metrics
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        metrics = db.query(PerformanceMetrics).filter(
            PerformanceMetrics.campaign_id == campaign_id
        ).all()

        agent = MonitorOptimizerAgent()
        result = await agent.get_performance_summary(campaign, metrics)

        return {
            "success": True,
            **result
        }

    except Exception as e:
        logger.error(f"Failed to get campaign summary: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get campaign summary: {str(e)}"
        )


@agents_router.post("/campaigns/{campaign_id}/metrics")
async def add_performance_metrics(
    campaign_id: uuid.UUID,
    metrics_data: dict,
    db: Session = Depends(get_db)
):
    """
    Add performance metrics for a campaign.

    This endpoint allows you to submit performance data for analysis.
    Typically used to sync metrics from Meta Ads API or manual input.

    Required fields:
    - impressions: int
    - clicks: int

    Optional fields:
    - ad_copy_id: UUID
    - conversions: int
    - spend: float
    - ctr: float (calculated if not provided)
    - cpc: float (calculated if not provided)
    - roas: float
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    try:
        impressions = metrics_data.get('impressions', 0)
        clicks = metrics_data.get('clicks', 0)
        spend = metrics_data.get('spend', 0)

        # Calculate CTR if not provided
        ctr = metrics_data.get('ctr')
        if ctr is None and impressions > 0:
            ctr = (clicks / impressions) * 100

        # Calculate CPC if not provided
        cpc = metrics_data.get('cpc')
        if cpc is None and clicks > 0:
            cpc = spend / clicks

        metrics = PerformanceMetrics(
            campaign_id=campaign_id,
            ad_copy_id=metrics_data.get('ad_copy_id'),
            impressions=impressions,
            clicks=clicks,
            conversions=metrics_data.get('conversions', 0),
            spend=spend,
            ctr=ctr or 0,
            cpc=cpc or 0,
            roas=metrics_data.get('roas', 0)
        )

        db.add(metrics)
        db.commit()
        db.refresh(metrics)

        return {
            "success": True,
            "message": "Performance metrics added successfully",
            "metrics": PerformanceMetricsResponse.model_validate(metrics)
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add metrics: {str(e)}"
        )


# ============ Media Generation Endpoints ============

@agents_router.post("/generate-image")
async def generate_image(
    prompt: str,
    style: str = "professional",
    aspect_ratio: str = "1:1"
):
    """
    Generate an AI image using multiple providers with automatic fallback.

    Supported providers (in priority order):
    - DALL-E 3 (OpenAI)
    - Stability AI (SD3)
    - Replicate (Flux)
    - Gemini (Imagen 3)

    Args:
        prompt: The image generation prompt
        style: Visual style (professional, vibrant, minimal, luxury, lifestyle, bold, cinematic)
        aspect_ratio: Image aspect ratio (1:1, 16:9, 9:16, 4:5)
    """
    try:
        agent = MediaGeneratorAgent()
        result = await agent.generate_image(
            prompt=prompt,
            style=style,
            aspect_ratio=aspect_ratio,
            upload_to_cloud=True,
            cloudinary_folder="shopivell/generated/ads"
        )

        return {
            "success": True,
            "image_base64": result.get("image_base64"),
            "cloudinary_url": result.get("cloudinary_url"),
            "thumbnail_url": result.get("thumbnail_url"),
            "provider_used": result.get("provider_used"),
            "model": result.get("model"),
            "is_placeholder": result.get("is_placeholder", False),
            "cloudinary": result.get("cloudinary"),
            "provider_errors": result.get("provider_errors", [])  # For debugging
        }

    except Exception as e:
        logger.error(f"Failed to generate image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate image: {str(e)}"
        )


@agents_router.post("/generate-video")
async def generate_video(
    prompt: str,
    image_base64: Optional[str] = None,
    duration: int = 5,
    aspect_ratio: str = "16:9"
):
    """
    Generate an AI video using multiple providers with automatic fallback.

    Supported providers:
    - Replicate (Stable Video Diffusion, AnimateDiff)
    - Runway ML (Gen-3)
    - Luma AI (Dream Machine)

    Args:
        prompt: The video generation prompt
        image_base64: Optional starting image for image-to-video
        duration: Video duration in seconds (3-10)
        aspect_ratio: Video aspect ratio (16:9, 9:16, 1:1)
    """
    try:
        agent = MediaGeneratorAgent()
        result = await agent.generate_video(
            prompt=prompt,
            image_base64=image_base64,
            duration=duration,
            aspect_ratio=aspect_ratio
        )

        return {
            "success": bool(result.get("video_base64") or result.get("video_url")),
            "video_base64": result.get("video_base64"),
            "video_url": result.get("video_url"),
            "provider_used": result.get("provider_used"),
            "model": result.get("model"),
            "duration": result.get("duration"),
            "error": result.get("error")
        }

    except Exception as e:
        logger.error(f"Failed to generate video: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate video: {str(e)}"
        )


@agents_router.post("/generate-ad-media")
async def generate_ad_media(
    product_name: str,
    product_description: str,
    visual_direction: str = "Professional and engaging",
    emotion_target: str = "Trust",
    generate_video: bool = False
):
    """
    Generate complete ad media (image + optional video) for a product.

    This endpoint combines the MediaGeneratorAgent with ad-specific prompting
    to create ready-to-use advertising visuals.
    """
    try:
        agent = MediaGeneratorAgent()

        product_info = {
            "product_name": product_name,
            "product_description": product_description
        }

        ad_angle = {
            "visual_direction": visual_direction,
            "emotion_target": emotion_target,
            "visual_style": "professional",
            "aspect_ratio": "1:1"
        }

        result = await agent.generate_ad_media(
            product_info=product_info,
            ad_angle=ad_angle,
            generate_video=generate_video
        )

        return {
            "success": True,
            "image": {
                "base64": result["image"].get("image_base64"),
                "provider": result["image"].get("provider_used"),
                "model": result["image"].get("model")
            },
            "video": result.get("video") if generate_video else None,
            "prompt_used": result.get("prompt_used")
        }

    except Exception as e:
        logger.error(f"Failed to generate ad media: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ad media: {str(e)}"
        )


@agents_router.get("/media-providers")
async def get_media_providers():
    """
    Get list of available media generation providers.

    Returns which image and video providers are configured and available.
    """
    agent = MediaGeneratorAgent()

    return {
        "image_providers": [p.value for p in agent.available_image_providers],
        "video_providers": [p.value for p in agent.available_video_providers],
        "configured_keys": {
            "openai": bool(agent.openai_api_key),
            "stability": bool(agent.stability_api_key),
            "replicate": bool(agent.replicate_api_key),
            "gemini": bool(agent.gemini_api_key),
            "runway": bool(agent.runway_api_key),
            "luma": bool(agent.luma_api_key),
            "fal": bool(agent.fal_api_key)
        }
    }


@agents_router.post("/generate-luxury-assets")
async def generate_luxury_assets(
    product_name: str,
    product_description: str,
    num_assets: int = 5,
    brand_colors: Optional[str] = None,
    generate_images: bool = False
):
    """
    Generate varied luxury ad asset specifications with unique creative directions.

    Each asset varies:
    - backgroundTone: Visually attractive, brand-aligned
    - surfaceType: Creative but not distracting (marble, linen, satin, etc.)
    - accentProp: Luxurious and elegant (flowers, ribbon, crystal, etc.)
    - lighting: Varies by mood and format
    - cameraAngle: Changes perspective and storytelling
    - overlayText: Short, attractive copy (CTA, launch offer, etc.)

    Returns structured JSON with all asset specifications.
    """
    try:
        agent = MediaGeneratorAgent()

        # Parse brand colors if provided
        colors = None
        if brand_colors:
            colors = [c.strip() for c in brand_colors.split(",")]

        if generate_images:
            # Generate with actual images (async)
            result = await agent.generate_luxury_ad_assets(
                product_name=product_name,
                product_description=product_description,
                num_assets=num_assets,
                brand_colors=colors,
                generate_images=True
            )
        else:
            # Just generate specifications (sync)
            asset_specs = agent.generate_luxury_asset_prompts(
                product_name=product_name,
                product_description=product_description,
                num_assets=num_assets,
                brand_colors=colors
            )
            result = {
                "product": {
                    "name": product_name,
                    "description": product_description
                },
                "brand_colors": colors,
                "total_assets": num_assets,
                "assets": asset_specs
            }

        return result

    except Exception as e:
        logger.error(f"Failed to generate luxury assets: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate luxury assets: {str(e)}"
        )


# ============ Vision Compliance Endpoints ============

@agents_router.post("/compliance/check-image")
async def check_image_compliance(
    image_base64: str,
    industry: Optional[str] = None,
    brand_name: Optional[str] = None,
    competitor_brands: Optional[List[str]] = None
):
    """
    Manually check an image for advertising compliance issues using OpenAI Vision.

    This endpoint analyzes images for:
    - Nudity/sexual content
    - Violence/weapons
    - Brand risk (competitor logos, trademarks)
    - Prohibited text content
    - Political/controversial content
    - Misleading claims
    - Age-restricted content (alcohol, tobacco, gambling)

    Args:
        image_base64: Base64-encoded image data
        industry: Optional industry context for more accurate checks (security, food, tech, etc.)
        brand_name: The advertiser's brand name
        competitor_brands: List of competitor brand names to check for

    Returns:
        Compliance result with issues, suggestions, and risk level
    """
    try:
        logger.info(f"Running manual compliance check (industry: {industry})")

        result = await vision_compliance_service.analyze_image(
            image_base64=image_base64,
            industry=industry,
            brand_name=brand_name,
            competitor_brands=competitor_brands
        )

        return {
            "success": True,
            "compliance": {
                "is_compliant": result.is_compliant,
                "risk_level": result.risk_level,
                "confidence": result.confidence,
                "analysis_time_ms": result.analysis_time_ms,
                "issues": [
                    {
                        "category": issue.category,
                        "severity": issue.severity,
                        "description": issue.description,
                        "location": issue.location
                    }
                    for issue in result.issues
                ],
                "detected_text": result.detected_text,
                "detected_logos": result.detected_logos,
                "suggestions": result.suggestions
            }
        }

    except Exception as e:
        logger.error(f"Failed to check image compliance: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check image compliance: {str(e)}"
        )


@agents_router.post("/compliance/check-brand-safety")
async def check_brand_safety(
    image_base64: str,
    brand_name: str,
    competitor_brands: List[str]
):
    """
    Check image specifically for brand safety issues.

    Detects:
    - Competitor logos in images
    - Trademarked content
    - Inappropriate brand associations
    - Text mentioning competitor brands

    Args:
        image_base64: Base64-encoded image data
        brand_name: The advertiser's brand name
        competitor_brands: List of competitor brand names to check for

    Returns:
        Brand safety result with detected logos and risks
    """
    try:
        logger.info(f"Running brand safety check for {brand_name}")

        result = await vision_compliance_service.check_brand_safety(
            image_base64=image_base64,
            brand_name=brand_name,
            competitor_brands=competitor_brands
        )

        return {
            "success": True,
            "brand_safety": {
                "is_safe": result.is_safe,
                "detected_logos": result.detected_logos,
                "detected_text": result.detected_text,
                "competitor_detected": result.competitor_detected,
                "trademark_risk": result.trademark_risk,
                "issues": result.issues
            }
        }

    except Exception as e:
        logger.error(f"Failed to check brand safety: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check brand safety: {str(e)}"
        )


@agents_router.post("/compliance/extract-text")
async def extract_image_text(image_base64: str):
    """
    Extract all visible text from an image using OCR via Vision API.

    Useful for:
    - Checking what text is in generated images
    - Verifying headline rendering
    - Finding prohibited words in images

    Args:
        image_base64: Base64-encoded image data

    Returns:
        List of text strings found in the image
    """
    try:
        logger.info("Extracting text from image")

        text_list = await vision_compliance_service.extract_text_from_image(image_base64)

        return {
            "success": True,
            "extracted_text": text_list,
            "text_count": len(text_list)
        }

    except Exception as e:
        logger.error(f"Failed to extract text from image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract text from image: {str(e)}"
        )


# ============ Automated Rules Endpoints ============

@agents_router.get("/rules/templates")
async def get_rule_templates():
    """
    Get all available automated rule templates.

    Templates include:
    - scale_winner: +20% budget when ROAS ≥ target × 1.25 for 3 consecutive days
    - kill_loser: -50% budget when CPA > 2× target AND 0 purchases after ≥2000 impressions
    - pause_no_spend: Pause ad sets with zero spend after 24 hours
    - scale_high_ctr: +15% budget when CTR > 3% for 2 consecutive days
    - reduce_high_cpc: -25% budget when CPC > $5 for 2 consecutive days
    """
    return {
        "success": True,
        "templates": automated_rules_engine.get_rule_templates()
    }


@agents_router.post("/rules/create-from-template")
async def create_rule_from_template(
    template_name: str,
    target_roas: Optional[float] = None,
    target_cpa: Optional[float] = None
):
    """
    Create an automated rule from a predefined template.

    Args:
        template_name: Name of the template (scale_winner, kill_loser, etc.)
        target_roas: Target ROAS for scaling rules (e.g., 3.0 for 300%)
        target_cpa: Target CPA for killing rules (e.g., 50.0 for $50)

    Example:
        - template_name: "scale_winner", target_roas: 3.0
        - template_name: "kill_loser", target_cpa: 50.0
    """
    try:
        rule = automated_rules_engine.create_rule_from_template(
            template_name=template_name,
            target_roas=target_roas,
            target_cpa=target_cpa
        )
        automated_rules_engine.add_rule(rule)

        return {
            "success": True,
            "message": f"Rule '{rule.name}' created and activated",
            "rule": {
                "id": rule.id,
                "name": rule.name,
                "description": rule.description,
                "conditions": [c.model_dump() for c in rule.conditions],
                "action": rule.action.model_dump(),
                "target_roas": rule.target_roas,
                "target_cpa": rule.target_cpa,
                "is_enabled": rule.is_enabled
            }
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to create rule: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create rule: {str(e)}"
        )


@agents_router.post("/rules/create-custom")
async def create_custom_rule(
    name: str,
    description: Optional[str] = None,
    entity_type: str = "adset",
    conditions: List[dict] = [],
    action_type: str = "scale_up",
    adjustment_percent: Optional[float] = None,
    max_budget: Optional[float] = None,
    min_budget: Optional[float] = None,
    target_roas: Optional[float] = None,
    target_cpa: Optional[float] = None
):
    """
    Create a custom automated rule with specific conditions and actions.

    Args:
        name: Rule name
        description: Rule description
        entity_type: "campaign", "adset", or "ad"
        conditions: List of condition objects with:
            - metric: roas, cpa, ctr, impressions, conversions, spend, cpc
            - operator: gt, gte, lt, lte, eq, neq
            - value: Threshold value
            - consecutive_days: Days condition must be met (default 1)
        action_type: scale_up, scale_down, pause, unpause, notify
        adjustment_percent: Budget adjustment percentage (for scale actions)
        max_budget: Maximum budget cap (for scale_up)
        min_budget: Minimum budget floor (for scale_down)
        target_roas: Target ROAS for reference
        target_cpa: Target CPA for reference

    Example:
        {
            "name": "My Custom Rule",
            "conditions": [
                {"metric": "roas", "operator": "gte", "value": 4.0, "consecutive_days": 2}
            ],
            "action_type": "scale_up",
            "adjustment_percent": 25,
            "max_budget": 500
        }
    """
    try:
        # Parse conditions
        parsed_conditions = []
        for cond in conditions:
            parsed_conditions.append(RuleCondition(
                metric=cond.get("metric", "ctr"),
                operator=cond.get("operator", "gt"),
                value=cond.get("value", 0),
                consecutive_days=cond.get("consecutive_days", 1)
            ))

        # Create action
        action = RuleAction(
            type=RuleType(action_type),
            adjustment_percent=adjustment_percent,
            max_budget=max_budget,
            min_budget=min_budget
        )

        # Create rule
        rule = AutomatedRule(
            name=name,
            description=description,
            entity_type=entity_type,
            conditions=parsed_conditions,
            action=action,
            target_roas=target_roas,
            target_cpa=target_cpa
        )

        automated_rules_engine.add_rule(rule)

        return {
            "success": True,
            "message": f"Custom rule '{rule.name}' created and activated",
            "rule": {
                "id": rule.id,
                "name": rule.name,
                "description": rule.description,
                "entity_type": rule.entity_type,
                "conditions": [c.model_dump() for c in rule.conditions],
                "action": rule.action.model_dump(),
                "is_enabled": rule.is_enabled
            }
        }

    except Exception as e:
        logger.error(f"Failed to create custom rule: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create custom rule: {str(e)}"
        )


@agents_router.get("/rules")
async def get_active_rules():
    """
    Get all active automated rules.

    Returns list of all rules currently loaded in the engine.
    """
    return {
        "success": True,
        "total_rules": len(automated_rules_engine.rules),
        "rules": [
            {
                "id": rule.id,
                "name": rule.name,
                "description": rule.description,
                "entity_type": rule.entity_type,
                "is_enabled": rule.is_enabled,
                "conditions": [c.model_dump() for c in rule.conditions],
                "action": rule.action.model_dump(),
                "target_roas": rule.target_roas,
                "target_cpa": rule.target_cpa,
                "trigger_count": rule.trigger_count,
                "last_triggered": rule.last_triggered.isoformat() if rule.last_triggered else None
            }
            for rule in automated_rules_engine.rules
        ]
    }


@agents_router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str):
    """Delete an automated rule by ID"""
    success = automated_rules_engine.remove_rule(rule_id)

    if success:
        return {"success": True, "message": f"Rule {rule_id} deleted"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule {rule_id} not found"
        )


@agents_router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, enabled: bool = True):
    """Enable or disable an automated rule"""
    for rule in automated_rules_engine.rules:
        if rule.id == rule_id:
            rule.is_enabled = enabled
            return {
                "success": True,
                "message": f"Rule {'enabled' if enabled else 'disabled'}",
                "rule_id": rule_id,
                "is_enabled": enabled
            }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Rule {rule_id} not found"
    )


@agents_router.post("/rules/run/{ad_account_id}")
async def run_rules_for_account(ad_account_id: str):
    """
    Manually trigger rule execution for an ad account.

    This runs all enabled rules against all active ad sets in the account.
    In production, this runs automatically on a schedule (every 15 minutes or hourly).

    Returns:
        - Number of rules evaluated
        - Number of rules triggered
        - Actions taken (budget changes, pauses, etc.)
        - Any errors encountered
    """
    try:
        result = await automated_rules_engine.run_all_rules(ad_account_id)

        return {
            "success": True,
            **result
        }

    except Exception as e:
        logger.error(f"Failed to run rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run rules: {str(e)}"
        )


@agents_router.get("/rules/history")
async def get_rule_execution_history(limit: int = 100):
    """
    Get history of rule executions.

    Shows recent actions taken by automated rules including:
    - Which rule was triggered
    - What entity was affected
    - What action was taken (budget change, pause, etc.)
    - Old and new values
    - Success/failure status
    """
    history = automated_rules_engine.get_execution_history(limit=limit)

    return {
        "success": True,
        "total_executions": len(history),
        "executions": history
    }


@agents_router.post("/rules/setup-defaults")
async def setup_default_rules(
    target_roas: float = 3.0,
    target_cpa: float = 50.0
):
    """
    Quick setup: Create the two main automated rules with your targets.

    Creates:
    1. Scale Winners: +20% budget when ROAS ≥ target × 1.25 for 3 days
    2. Kill Losers: -50% budget when CPA > 2× target AND 0 purchases after 2000 impressions

    Args:
        target_roas: Your target ROAS (e.g., 3.0 for 300% return)
        target_cpa: Your target CPA in dollars (e.g., 50.0 for $50)
    """
    try:
        rules_created = []

        # Create Scale Winners rule
        scale_rule = automated_rules_engine.create_rule_from_template(
            template_name="scale_winner",
            target_roas=target_roas
        )
        automated_rules_engine.add_rule(scale_rule)
        rules_created.append({
            "id": scale_rule.id,
            "name": scale_rule.name,
            "trigger_condition": f"ROAS ≥ {target_roas * 1.25:.2f} for 3 consecutive days",
            "action": "+20% budget (max $10,000)"
        })

        # Create Kill Losers rule
        kill_rule = automated_rules_engine.create_rule_from_template(
            template_name="kill_loser",
            target_cpa=target_cpa
        )
        automated_rules_engine.add_rule(kill_rule)
        rules_created.append({
            "id": kill_rule.id,
            "name": kill_rule.name,
            "trigger_condition": f"CPA > ${target_cpa * 2:.2f} AND 0 conversions after 2000+ impressions",
            "action": "-50% budget (min $5)"
        })

        return {
            "success": True,
            "message": "Default automated rules created and activated",
            "target_roas": target_roas,
            "target_cpa": target_cpa,
            "rules_created": rules_created,
            "next_steps": [
                f"Rules will automatically run when you call POST /api/agents/rules/run/{{ad_account_id}}",
                "Set up a cron job or scheduler to call this endpoint every 15-60 minutes for 24/7 automation"
            ]
        }

    except Exception as e:
        logger.error(f"Failed to setup default rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup default rules: {str(e)}"
        )


# ============ Scheduler Endpoints (24/7 Automation) ============

@agents_router.post("/scheduler/start")
async def start_scheduler(
    interval_minutes: int = 15,
    ad_account_ids: Optional[List[str]] = None
):
    """
    Start the 24/7 automated rules scheduler.

    The scheduler runs in the background and executes all enabled rules
    for configured ad accounts at the specified interval.

    Args:
        interval_minutes: How often to run rules (default: 15 minutes, recommended: 15-60)
        ad_account_ids: List of Meta ad account IDs to process

    Example:
        POST /api/agents/scheduler/start?interval_minutes=30
        Body: {"ad_account_ids": ["act_123456789"]}
    """
    try:
        # Add ad accounts if provided
        if ad_account_ids:
            for account_id in ad_account_ids:
                rules_scheduler.add_ad_account(account_id)

        # Start scheduler
        success = start_rules_scheduler(interval_minutes=interval_minutes)

        if success:
            return {
                "success": True,
                "message": f"Scheduler started with {interval_minutes} minute interval",
                "status": rules_scheduler.get_status()
            }
        else:
            return {
                "success": False,
                "message": "Scheduler already running",
                "status": rules_scheduler.get_status()
            }

    except Exception as e:
        logger.error(f"Failed to start scheduler: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start scheduler: {str(e)}"
        )


@agents_router.post("/scheduler/stop")
async def stop_scheduler():
    """
    Stop the 24/7 automated rules scheduler.

    Gracefully shuts down the background scheduler.
    """
    try:
        success = stop_rules_scheduler()

        if success:
            return {
                "success": True,
                "message": "Scheduler stopped"
            }
        else:
            return {
                "success": False,
                "message": "Scheduler was not running"
            }

    except Exception as e:
        logger.error(f"Failed to stop scheduler: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop scheduler: {str(e)}"
        )


@agents_router.get("/scheduler/status")
async def get_scheduler_status():
    """
    Get the current status of the automated rules scheduler.

    Returns:
        - running: Whether scheduler is active
        - interval_minutes: Current run interval
        - ad_accounts: List of accounts being processed
        - last_run: Timestamp of last execution
        - total_runs: Number of completed cycles
        - active_rules: Number of rules configured
    """
    return {
        "success": True,
        "scheduler": rules_scheduler.get_status()
    }


@agents_router.post("/scheduler/add-account")
async def add_account_to_scheduler(ad_account_id: str):
    """
    Add an ad account to the scheduler for 24/7 monitoring.

    The scheduler will run all enabled rules for this account
    at each scheduled interval.
    """
    rules_scheduler.add_ad_account(ad_account_id)

    return {
        "success": True,
        "message": f"Account {ad_account_id} added to scheduler",
        "accounts": rules_scheduler.get_status()["ad_accounts"]
    }


@agents_router.delete("/scheduler/remove-account/{ad_account_id}")
async def remove_account_from_scheduler(ad_account_id: str):
    """Remove an ad account from the scheduler"""
    success = rules_scheduler.remove_ad_account(ad_account_id)

    if success:
        return {
            "success": True,
            "message": f"Account {ad_account_id} removed from scheduler",
            "accounts": rules_scheduler.get_status()["ad_accounts"]
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {ad_account_id} not found in scheduler"
        )


@agents_router.post("/scheduler/run-now")
async def trigger_immediate_run():
    """
    Manually trigger an immediate rule execution cycle.

    Runs all enabled rules for all configured ad accounts immediately,
    without waiting for the next scheduled interval.
    """
    try:
        result = await rules_scheduler.run_now()

        return {
            "success": True,
            "message": "Manual execution completed",
            "result": result
        }

    except Exception as e:
        logger.error(f"Failed to run immediate cycle: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run immediate cycle: {str(e)}"
        )

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
            aspect_ratio=aspect_ratio
        )

        return {
            "success": True,
            "image_base64": result.get("image_base64"),
            "provider_used": result.get("provider_used"),
            "model": result.get("model"),
            "is_placeholder": result.get("is_placeholder", False)
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

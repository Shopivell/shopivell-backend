# router.py - API endpoints for Marketing Agents Module

import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from .models import Campaign, MarketResearch, CreativeAngle, AdCopy, PerformanceMetrics
from .schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse,
    MarketResearchRequest, MarketResearchResponse,
    CreativeAngleRequest, CreativeAngleResponse,
    AdCopyRequest, AdCopyResponse,
    PerformanceMetricsResponse,
    CompetitiveIntelligenceRequest
)
from .market_research_agent import MarketResearchAgent
from .creative_angles_agent import CreativeAnglesAgent
from .ad_copy_agent import AdCopyAgent
from .monitor_optimizer_agent import MonitorOptimizerAgent
from .media_generator_agent import MediaGeneratorAgent
from .visual_director_agent import VisualDirectorAgent
from modules.stores.models import Store
from modules.openrouter.ai_usage_service import require_ai_quota
from utils.jwt_auth import get_current_user, CurrentUser
from .vision_compliance_service import vision_compliance_service
from .monitor_optimizer_agent import automated_rules_engine, AutomatedRule, RuleCondition, RuleAction, RuleType, ConditionGroup, ConditionLogic
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

    # Check AI quota before proceeding
    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

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


@agents_router.post("/research/website")
async def research_website(
    url: str = Query(..., description="Website URL to research"),
    business_name: Optional[str] = Query(None, description="Optional business name"),
    deep_scrape: bool = Query(True, description="Scrape multiple pages for comprehensive analysis"),
    extract_structure: bool = Query(True, description="Use AI to extract structured data"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Research a website directly without requiring a campaign.

    This enhanced endpoint performs:
    - Deep multi-page scraping (home, about, services, contact, etc.)
    - AI-powered structured data extraction:
        - Company info (name, tagline, industry)
        - Navigation structure
        - Services/Products list
        - Value propositions
        - Partners/Members
        - Leadership/Team
        - Contact information (emails, phones, social media)
        - Statistics and metrics
    - Competitor search
    - Industry trends research
    - Audience insights

    Args:
        url: The website URL to research (e.g., https://zimswitch.co.zw)
        business_name: Optional business name (auto-extracted if not provided)
        deep_scrape: Whether to scrape multiple pages (default: True)
        extract_structure: Whether to use AI extraction (default: True)

    Returns:
        Comprehensive research data including:
        - extracted_data: Structured website information
        - market_data: Competitors, trends, audience insights
        - research_summary: Overview statistics
    """
    try:
        from .market_research_agent import research_website_directly

        logger.info(f"Starting direct website research for: {url}")

        result = await research_website_directly(
            url=url,
            business_name=business_name,
            deep_scrape=deep_scrape,
            extract_structure=extract_structure
        )

        return {
            "success": True,
            "message": "Website research completed successfully",
            "data": result
        }

    except Exception as e:
        logger.error(f"Failed to research website: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to research website: {str(e)}"
        )


# ============ Audience Targeting Endpoints ============

@agents_router.post("/audience/generate")
async def generate_audience_targeting(
    url: str = Query(..., description="Website URL to analyze"),
    include_hooks: bool = Query(False, description="Also generate creative hooks"),
    num_hooks: int = Query(5, ge=1, le=10, description="Number of hooks if include_hooks=True"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Generate Meta/Facebook audience targeting from a website URL.

    This enhanced endpoint performs:
    1. Website scraping and analysis via Market Research Agent
    2. AI-powered audience segment generation
    3. Facebook interest targeting tag generation
    4. Job title and industry targeting suggestions
    5. Ad set recommendations ready for Meta Ads Manager

    Returns structured targeting data including:
    - **audience_segments**: Target segments like "Corporate Finance Departments", "E-commerce Businesses"
    - **demographics**: Age range, gender, locations
    - **interest_tags**: Categorized Facebook interests (25-40 tags)
        - core_interests: Primary business-related interests
        - technology_interests: Tech and software interests
        - business_interests: B2B and professional interests
        - behavioral_interests: Mindset and behavior interests
    - **job_titles**: Relevant job titles to target
    - **ad_set_recommendations**: Ready-to-use ad set configurations
    - **creative_hooks**: (optional) Creative hooks for ads

    Example interests for Fintech:
    - Payment system, Mobile payment, Financial technology, Mobile banking
    - Business-to-business, LinkedIn, Web conferencing, Leadership

    Example interests for Security:
    - Anti-theft system, CCTV, Smart Technologies, Property management
    - Commercial property, Fire safety, Small and medium enterprises
    """
    try:
        from .creative_strategist_agent import generate_audience_from_url

        logger.info(f"Generating Meta audience targeting for: {url}")

        result = await generate_audience_from_url(
            url=url,
            include_hooks=include_hooks,
            num_hooks=num_hooks
        )

        return {
            "success": result.get("success", False),
            "message": "Audience targeting generated successfully" if result.get("success") else "Failed to generate audience",
            "data": result
        }

    except Exception as e:
        logger.error(f"Failed to generate audience targeting: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate audience targeting: {str(e)}"
        )


@agents_router.post("/audience/compare")
async def compare_audience_targeting(
    urls: List[str] = Query(..., description="List of website URLs to compare (max 5)"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Compare audience targeting across multiple websites.

    Useful for:
    - Analyzing competitor audiences
    - Finding common targeting opportunities
    - Identifying unique audience segments

    Returns:
    - Individual audience analysis for each URL
    - Common interests shared across websites
    - Unique interests per website
    - Combined segment list
    """
    try:
        from .creative_strategist_agent import generate_audience_comparison

        if len(urls) > 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 5 URLs allowed for comparison"
            )

        logger.info(f"Comparing audience targeting for {len(urls)} URLs")

        result = await generate_audience_comparison(urls)

        return {
            "success": True,
            "message": f"Compared {result['comparison']['total_urls_analyzed']} websites",
            "data": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare audiences: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compare audiences: {str(e)}"
        )


# ============ Creative Angle Endpoints ============

async def _localized_keyword_data(campaign, db):
    """Run keyword research for a campaign, localized to its store (country + city).
    Best-effort: returns None if seeds are missing or research fails, so callers
    can proceed without localization."""
    try:
        from .keyword_intelligence_agent import KeywordIntelligenceAgent
        seed_keywords = list(campaign.keywords) if campaign.keywords else []
        if not seed_keywords and campaign.product_description:
            seed_keywords = [campaign.product_description[:60]]
        if not seed_keywords:
            return None
        kw_country, kw_cities = "ZW", None
        if campaign.store_id:
            from modules.stores.models import Store
            store = db.query(Store).filter(Store.id == campaign.store_id).first()
            if store:
                if store.country_code:
                    kw_country = store.country_code.upper()
                if store.store_city:
                    kw_cities = [store.store_city]
        return await KeywordIntelligenceAgent().research_keywords(
            seed_keyword=seed_keywords[0],
            additional_seeds=seed_keywords[1:] or None,
            country_code=kw_country,
            limit=30,
            target_cities=kw_cities,
        )
    except Exception as e:
        logger.warning(f"Keyword localization skipped: {e}")
        return None


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

    # Check AI quota before proceeding
    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

    try:
        logger.info(f"Generating {num_angles} creative angles for campaign: {campaign.name}")

        agent = CreativeAnglesAgent()
        keyword_data = await _localized_keyword_data(campaign, db)
        angles = await agent.generate_angles(campaign, num_angles=num_angles, keyword_data=keyword_data)

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

    # Check AI quota before proceeding
    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

    try:
        agent = AdCopyAgent()

        # Localized keyword intelligence so headlines use local search terms
        # (e.g. "... in Harare") and foreign-market noise is filtered out.
        keyword_data = await _localized_keyword_data(campaign, db)

        if angle_id:
            # Generate for specific angle
            angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()
            if not angle:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Creative angle not found"
                )

            logger.info(f"Generating ad copy for angle: {angle.angle_name}")
            ad_copy = await agent.generate_ad_copy(campaign, angle, keyword_data=keyword_data)

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
            ad_copies = await agent.generate_all_ad_copies(campaign, angles, keyword_data=keyword_data)

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
    include_visuals: bool = Query(True, description="Generate image prompts for each angle"),
    include_video: bool = Query(False, description="Generate video concepts (slower)"),
    db: Session = Depends(get_db)
):
    """
    Run the full AI campaign pipeline:
    0. Keyword Intelligence - Research keyword search volume, CPC, competition & intent clusters
    1. Market Research - Analyze competitors, audience, trends (enriched with keyword data)
    2. Creative Angles - Generate advertising angles based on research + keyword insights
    3. Ad Copy Generation - Create ad copies for each angle (prioritized by search volume)
    4. Visual Direction - Generate image prompts and optional video concepts for each angle

    This is an async operation that generates all campaign assets.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    # Check AI quota before proceeding (pipeline uses multiple agents)
    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

    try:
        results = {}
        print(f"DEBUG: Starting pipeline for campaign {campaign.name}")

        # Step 0: Keyword Intelligence
        logger.info(f"Pipeline Step 0: Keyword Intelligence for {campaign.name}")
        print("DEBUG: Starting Step 0 - Keyword Intelligence")
        keyword_data = None
        try:
            from .keyword_intelligence_agent import KeywordIntelligenceAgent
            keyword_agent = KeywordIntelligenceAgent()

            # Use campaign keywords as seeds, fall back to product description
            seed_keywords = list(campaign.keywords) if campaign.keywords else []
            if not seed_keywords and campaign.product_description:
                seed_keywords = [campaign.product_description[:60]]

            if seed_keywords:
                seed = seed_keywords[0]
                additional = seed_keywords[1:] if len(seed_keywords) > 1 else None

                # Derive target market from the campaign's store so ranking is
                # local to wherever this store actually sells.
                kw_country = "ZW"
                kw_cities = None
                if campaign.store_id:
                    from modules.stores.models import Store
                    store = db.query(Store).filter(Store.id == campaign.store_id).first()
                    if store:
                        if store.country_code:
                            kw_country = store.country_code.upper()
                        if store.store_city:
                            kw_cities = [store.store_city]

                keyword_data = await keyword_agent.research_keywords(
                    seed_keyword=seed,
                    additional_seeds=additional,
                    country_code=kw_country,
                    limit=30,
                    target_cities=kw_cities
                )
                results["keyword_intelligence"] = keyword_data
                print(f"DEBUG: Step 0 complete - found {keyword_data.get('total_found', 0)} keywords (source: {keyword_data.get('source', 'unknown')})")
            else:
                print("DEBUG: Step 0 skipped - no seed keywords available")
        except Exception as e:
            logger.warning(f"Keyword Intelligence step failed (non-critical): {e}")
            print(f"DEBUG: Step 0 failed (continuing without keyword data): {e}")

        # Step 1: Market Research (enriched with keyword data)
        logger.info(f"Pipeline Step 1: Market Research for {campaign.name}")
        print("DEBUG: Starting Step 1 - Market Research")
        research_agent = MarketResearchAgent()
        research_result = await research_agent.conduct_research(campaign, keyword_data=keyword_data)
        results["market_research"] = research_result
        print("DEBUG: Step 1 complete")

        # Step 2: Creative Angles (enriched with keyword data)
        logger.info(f"Pipeline Step 2: Generating {num_angles} Creative Angles")
        print(f"DEBUG: Starting Step 2 - Creative Angles ({num_angles})")
        angles_agent = CreativeAnglesAgent()
        angles_result = await angles_agent.generate_angles(campaign, num_angles=num_angles, keyword_data=keyword_data)
        results["creative_angles"] = angles_result
        print(f"DEBUG: Step 2 complete - generated {len(angles_result)} angles")

        # Step 3: Ad Copy Generation (enriched with keyword data)
        logger.info(f"Pipeline Step 3: Generating Ad Copies for {len(angles_result)} angles")
        print(f"DEBUG: Starting Step 3 - Ad Copies for {len(angles_result)} angles")
        ad_agent = AdCopyAgent()

        # Get the angles from database (they were just saved)
        angles = db.query(CreativeAngle).filter(
            CreativeAngle.campaign_id == campaign_id
        ).all()

        ad_copies_result = await ad_agent.generate_all_ad_copies(campaign, angles, keyword_data=keyword_data)
        results["ad_copies"] = ad_copies_result
        print(f"DEBUG: Step 3 complete - generated {len(ad_copies_result)} ad copies")

        # Step 4: Visual Direction (Image Prompts)
        visual_packages = []
        if include_visuals and angles:
            logger.info(f"Pipeline Step 4: Generating Visual Direction for {len(angles)} angles")
            print(f"DEBUG: Starting Step 4 - Visual Direction for {len(angles)} angles")
            visual_agent = VisualDirectorAgent()

            for angle in angles:
                ad_copy = db.query(AdCopy).filter(AdCopy.angle_id == angle.id).first()
                package = await visual_agent.generate_full_visual_package(
                    campaign, angle, ad_copy, include_video=include_video
                )
                visual_packages.append(package)

            results["visual_packages"] = visual_packages
            print(f"DEBUG: Step 4 complete - generated {len(visual_packages)} visual packages")

        # Update campaign status
        campaign.status = "active"
        db.commit()

        summary = {
            "keyword_intelligence": keyword_data.get("total_found", 0) if keyword_data else 0,
            "keyword_source": keyword_data.get("source", "none") if keyword_data else "none",
            "market_research": 1,
            "creative_angles": len(angles_result),
            "ad_copies": len(ad_copies_result)
        }
        if include_visuals:
            summary["visual_packages"] = len(visual_packages)
            summary["total_image_concepts"] = sum(
                len(p.get("image_concepts", [])) for p in visual_packages
            )

        return {
            "success": True,
            "message": "Campaign pipeline completed successfully",
            "campaign_id": str(campaign_id),
            "summary": summary,
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


# ============ Visual Director Endpoints ============

@agents_router.post("/campaigns/{campaign_id}/visuals")
async def generate_campaign_visuals(
    campaign_id: uuid.UUID,
    angle_id: Optional[uuid.UUID] = Query(None, description="Generate for specific angle only"),
    include_video: bool = Query(False, description="Include video concepts"),
    db: Session = Depends(get_db)
):
    """
    Generate image prompts and visual direction for a campaign's creative angles.

    If angle_id is provided, generates visuals for that specific angle.
    Otherwise, generates visuals for ALL angles of the campaign.

    Each visual package includes:
    - 3 image concepts with detailed AI generation prompts
    - Composition guidelines (focal point, text zones, color palette)
    - Format variants (square, portrait, stories)
    - Optional video concepts with shot-by-shot breakdowns

    Prerequisites: Campaign must have creative angles and ad copies generated first.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

    try:
        visual_agent = VisualDirectorAgent()

        if angle_id:
            angle = db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()
            if not angle:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative angle not found")

            ad_copy = db.query(AdCopy).filter(AdCopy.angle_id == angle_id).first()
            package = await visual_agent.generate_full_visual_package(
                campaign, angle, ad_copy, include_video=include_video
            )

            return {
                "success": True,
                "message": f"Generated visual package for angle: {angle.angle_name}",
                "campaign_id": str(campaign_id),
                "visual_packages": [package]
            }
        else:
            angles = db.query(CreativeAngle).filter(
                CreativeAngle.campaign_id == campaign_id
            ).all()

            if not angles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No creative angles found. Generate creative angles first."
                )

            visual_packages = []
            for angle in angles:
                ad_copy = db.query(AdCopy).filter(AdCopy.angle_id == angle.id).first()
                package = await visual_agent.generate_full_visual_package(
                    campaign, angle, ad_copy, include_video=include_video
                )
                visual_packages.append(package)

            total_concepts = sum(len(p.get("image_concepts", [])) for p in visual_packages)

            return {
                "success": True,
                "message": f"Generated {len(visual_packages)} visual packages with {total_concepts} image concepts",
                "campaign_id": str(campaign_id),
                "summary": {
                    "angles_processed": len(angles),
                    "total_image_concepts": total_concepts,
                    "includes_video": include_video
                },
                "visual_packages": visual_packages
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate visuals: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate visuals: {str(e)}"
        )


@agents_router.post("/campaigns/{campaign_id}/generate-images")
async def generate_campaign_images(
    campaign_id: uuid.UUID,
    angle_id: Optional[uuid.UUID] = Query(None, description="Generate for specific angle only"),
    aspect_ratio: str = Query("1:1", description="Image aspect ratio: 1:1, 4:5, 9:16, 16:9"),
    style: str = Query("professional", description="Visual style"),
    db: Session = Depends(get_db)
):
    """
    Generate actual images for a campaign using the Visual Director prompts + Media Generator.

    This is a 2-step process:
    1. Visual Director generates detailed image prompts per angle
    2. Media Generator creates actual images from those prompts (Gemini/DALL-E/Stability)

    Each generated image is uploaded to Cloudinary and returned with URLs.

    Prerequisites: Campaign must have creative angles generated first.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

    try:
        visual_agent = VisualDirectorAgent()
        media_agent = MediaGeneratorAgent()

        if angle_id:
            angles = [db.query(CreativeAngle).filter(CreativeAngle.id == angle_id).first()]
            if not angles[0]:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative angle not found")
        else:
            angles = db.query(CreativeAngle).filter(
                CreativeAngle.campaign_id == campaign_id
            ).all()

        if not angles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No creative angles found. Generate creative angles first."
            )

        generated_assets = []

        for angle in angles:
            ad_copy = db.query(AdCopy).filter(AdCopy.angle_id == angle.id).first()

            # Step 1: Get image prompts from Visual Director
            prompts_result = await visual_agent.generate_image_prompts(campaign, angle, ad_copy)
            image_concepts = prompts_result.get("image_concepts", [])

            angle_assets = {
                "angle_id": str(angle.id),
                "angle_name": angle.angle_name,
                "images": []
            }

            # Step 2: Generate actual images from prompts
            for concept in image_concepts[:2]:  # Limit to 2 per angle to manage costs
                prompt = concept.get("ai_image_prompt", "")
                if not prompt:
                    continue

                image_result = await media_agent.generate_image(
                    prompt=prompt,
                    style=style,
                    aspect_ratio=aspect_ratio,
                    upload_to_cloud=True,
                    cloudinary_folder=f"shopivell/campaigns/{campaign_id}"
                )

                angle_assets["images"].append({
                    "concept_name": concept.get("concept_name"),
                    "prompt_used": prompt,
                    "cloudinary_url": image_result.get("cloudinary_url"),
                    "thumbnail_url": image_result.get("thumbnail_url"),
                    "provider_used": image_result.get("provider_used"),
                    "is_placeholder": image_result.get("is_placeholder", False)
                })

            generated_assets.append(angle_assets)

        total_images = sum(len(a["images"]) for a in generated_assets)

        return {
            "success": True,
            "message": f"Generated {total_images} images across {len(angles)} angles",
            "campaign_id": str(campaign_id),
            "generated_assets": generated_assets
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate campaign images: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate campaign images: {str(e)}"
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

    # Check AI quota before proceeding
    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

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
            ad_copy = db.query(AdCopy).filter(AdCopy.id == m.ad_id).first() if m.ad_id else None

            performance_data.append({
                "ad_id": str(m.ad_id) if m.ad_id else "N/A",
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

    # Check AI quota before proceeding
    if campaign.store_id:
        require_ai_quota(campaign.store_id, db)

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
            # Model column is `ad_id`; accept either key from callers for compatibility.
            ad_id=metrics_data.get('ad_id') or metrics_data.get('ad_copy_id'),
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
    aspect_ratio: str = "1:1",
    store_id: Optional[uuid.UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
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
        store_id: Optional store UUID to incorporate brand assets into prompt
    """
    try:
        agent = MediaGeneratorAgent()
        result = await agent.generate_image(
            prompt=prompt,
            style=style,
            aspect_ratio=aspect_ratio,
            upload_to_cloud=True,
            cloudinary_folder="shopivell/generated/ads",
            store_id=str(store_id) if store_id else None
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
    aspect_ratio: str = "16:9",
    current_user: CurrentUser = Depends(get_current_user)
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
    generate_video: bool = False,
    current_user: CurrentUser = Depends(get_current_user)
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
    generate_images: bool = False,
    current_user: CurrentUser = Depends(get_current_user)
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


# ============ Store Ad Generation ============

@agents_router.post("/generate-store-ad")
async def generate_store_ad(
    store_id: uuid.UUID,
    headline: Optional[str] = None,
    bullet_points: Optional[List[str]] = None,
    cta_text: str = "Learn More",
    aspect_ratio: str = "1:1",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Generate a modern ad image for a store using its profile data.

    Uses the store's screenshot as a Gemini reference image to generate a
    photorealistic scene background, then composites text overlays (headline,
    bullet points, CTA button) using PIL for pixel-perfect rendering.

    Args:
        store_id: UUID of the store to generate ad for
        headline: Optional headline text (auto-generated from store data if not provided)
        bullet_points: Optional bullet point list (auto-generated if not provided)
        cta_text: Call-to-action button text (default: "Learn More")
        aspect_ratio: Image aspect ratio (default: "1:1")

    Returns:
        Generated ad image with base64 data and Cloudinary URLs
    """
    # Look up the store
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store with id {store_id} not found"
        )

    # Verify the caller owns this store (admin roles exempt)
    if "admin" not in (current_user.role or "").lower():
        if str(store.owner_id) != current_user.id and current_user.store_id != str(store_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this store"
            )

    # Check AI quota before proceeding
    require_ai_quota(store_id, db)

    try:
        agent = MediaGeneratorAgent()
        result = await agent.generate_store_ad(
            store_name=store.store_name,
            store_description=store.store_description or "",
            business_type=store.business_type or "general",
            logo_url=store.logo_url,
            screenshot_url=store.screenshot_url,
            color_theme=store.color_theme,
            products_or_services=store.products_or_services,
            headline=headline,
            bullet_points=bullet_points,
            cta_text=cta_text,
            aspect_ratio=aspect_ratio,
            upload_to_cloud=True
        )

        return {
            "success": result.get("success", False),
            "store_id": str(store_id),
            "store_name": store.store_name,
            "image_base64": result.get("image_base64"),
            "cloudinary_url": result.get("cloudinary_url"),
            "thumbnail_url": result.get("thumbnail_url"),
            "metadata": result.get("metadata"),
            "error": result.get("error")
        }

    except Exception as e:
        logger.error(f"Failed to generate store ad: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate store ad: {str(e)}"
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
    target_cpa: Optional[float] = None,
    current_user: CurrentUser = Depends(get_current_user),
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
    target_cpa: Optional[float] = None,
    cooldown_minutes: int = 60,
    max_triggers_per_day: int = 3,
    condition_groups: Optional[dict] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Create a custom automated rule with specific conditions and actions.

    Args:
        name: Rule name
        description: Rule description
        entity_type: "campaign", "adset", or "ad"
        conditions: List of condition objects (flat AND logic)
        condition_groups: Optional nested AND/OR/NOT logic tree. Example:
            {"logic": "or", "conditions": [
                {"logic": "and", "conditions": [
                    {"metric": "roas", "operator": "gt", "value": 2},
                    {"metric": "ctr", "operator": "lt", "value": 1}
                ]},
                {"metric": "cpa", "operator": "gt", "value": 50}
            ]}
        action_type: scale_up, scale_down, pause, unpause, notify
        adjustment_percent: Budget adjustment percentage (for scale actions)
        max_budget: Maximum budget cap (for scale_up)
        cooldown_minutes: Minimum minutes between triggers (default 60)
        max_triggers_per_day: Maximum triggers per day per entity (default 3)
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

        # Parse condition groups if provided
        parsed_groups = None
        if condition_groups:
            try:
                parsed_groups = ConditionGroup.model_validate(condition_groups)
            except Exception as eg:
                raise HTTPException(status_code=400, detail=f"Invalid condition_groups: {str(eg)}")

        # Create rule
        rule = AutomatedRule(
            name=name,
            description=description,
            entity_type=entity_type,
            conditions=parsed_conditions,
            condition_groups=parsed_groups,
            action=action,
            target_roas=target_roas,
            target_cpa=target_cpa,
            cooldown_minutes=cooldown_minutes,
            max_triggers_per_day=max_triggers_per_day
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
async def delete_rule(rule_id: str, current_user: CurrentUser = Depends(get_current_user)):
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
async def toggle_rule(rule_id: str, enabled: bool = True, current_user: CurrentUser = Depends(get_current_user)):
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
async def run_rules_for_account(ad_account_id: str, current_user: CurrentUser = Depends(get_current_user)):
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
async def get_rule_execution_history(
    limit: int = 100,
    ad_account_id: Optional[str] = Query(None, description="Filter by ad account")
):
    """
    Get history of rule executions from persistent database storage.

    Shows recent actions taken by automated rules including:
    - Which rule was triggered
    - What entity was affected
    - What action was taken (budget change, pause, etc.)
    - Old and new values
    - Success/failure status
    - Rollback eligibility and status
    """
    history = automated_rules_engine.get_execution_history(limit=limit, ad_account_id=ad_account_id)

    return {
        "success": True,
        "total_executions": len(history),
        "executions": history
    }


@agents_router.post("/rules/setup-defaults")
async def setup_default_rules(
    target_roas: float = 3.0,
    target_cpa: float = 50.0,
    current_user: CurrentUser = Depends(get_current_user),
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
    ad_account_ids: Optional[List[str]] = None,
    current_user: CurrentUser = Depends(get_current_user),
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
async def stop_scheduler(current_user: CurrentUser = Depends(get_current_user)):
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
async def add_account_to_scheduler(ad_account_id: str, current_user: CurrentUser = Depends(get_current_user)):
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


@agents_router.post("/scheduler/autopilot")
async def set_autopilot(
    ad_account_id: str,
    enabled: bool = Query(..., description="True = live autonomous execution; False = advise-only (dry-run)"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Master switch for autonomous rule execution on an ad account.

    When disabled (default), the scheduler evaluates rules in advise-only/dry-run
    mode: it logs what it WOULD do but makes no spend-affecting Meta changes.
    When enabled, rules execute live (pausing ads, changing budgets) every cycle.
    """
    from modules.marketing.models import MetaAdAccount
    account = db.query(MetaAdAccount).filter(
        MetaAdAccount.ad_account_id == ad_account_id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail=f"Ad account {ad_account_id} not found")

    account.autopilot_enabled = enabled
    db.commit()
    logger.info(f"[Autopilot] {ad_account_id} autopilot set to {'LIVE' if enabled else 'advise-only'}")

    return {
        "success": True,
        "ad_account_id": ad_account_id,
        "autopilot_enabled": enabled,
        "mode": "live autonomous execution" if enabled else "advise-only (dry-run)",
    }


@agents_router.delete("/scheduler/remove-account/{ad_account_id}")
async def remove_account_from_scheduler(ad_account_id: str, current_user: CurrentUser = Depends(get_current_user)):
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
async def trigger_immediate_run(current_user: CurrentUser = Depends(get_current_user)):
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


# ============ Ad Copy Generation Endpoints ============

@agents_router.post("/ad-copy/generate")
async def generate_ad_copy_from_research(
    url: str = Query(..., description="Website URL to generate ad copy for"),
    platforms: List[str] = Query(["facebook", "instagram"], description="Target platforms"),
    include_b2b: bool = Query(True, description="Generate B2B-specific copy"),
    include_b2c: bool = Query(True, description="Generate B2C-specific copy")
):
    """
    Generate comprehensive ad copy from a website URL.

    This enhanced endpoint:
    1. Scrapes the website using market research agent
    2. Generates B2B and/or B2C specific ad copy
    3. Creates platform-optimized variations (Facebook, Instagram, LinkedIn)
    4. Includes hooks, headlines, primary text variations, and descriptions

    Returns ad copy organized by:
    - Audience segment (auto-detected from website)
    - Audience type (B2B vs B2C)
    - Platform (Facebook, Instagram, etc.)
    """
    try:
        from .market_research_agent import research_website_directly
        from .ad_copy_agent import generate_ad_copy_from_website

        logger.info(f"Generating ad copy for URL: {url}")

        # Step 1: Research the website
        research_data = await research_website_directly(
            url=url,
            deep_scrape=True,
            extract_structure=True
        )

        # Step 2: Generate ad copy from research
        ad_copy_result = await generate_ad_copy_from_website(
            research_data=research_data,
            platforms=platforms,
            include_b2b=include_b2b,
            include_b2c=include_b2c
        )

        return {
            "success": True,
            "message": f"Generated ad copy for {ad_copy_result.get('company_name', 'website')}",
            "data": {
                "company_name": ad_copy_result.get('company_name'),
                "industry": ad_copy_result.get('industry'),
                "ad_copy_count": len(ad_copy_result.get('ad_copy_sets', [])),
                "ad_copy_sets": ad_copy_result.get('ad_copy_sets', [])
            }
        }

    except Exception as e:
        logger.error(f"Failed to generate ad copy: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ad copy: {str(e)}"
        )


@agents_router.post("/ad-copy/from-research")
async def generate_ad_copy_from_existing_research(
    research_data: Dict[str, Any],
    platforms: List[str] = Query(["facebook", "instagram"], description="Target platforms"),
    audience_type: str = Query(None, description="Filter by audience type: B2B, B2C, or both (default)")
):
    """
    Generate ad copy from existing market research data.

    Use this endpoint when you already have research data from the market research agent
    and want to generate ad copy without re-scraping.

    Body should contain the research_data object from market_research_agent.
    """
    try:
        from .ad_copy_agent import generate_ad_copy_from_website

        include_b2b = audience_type is None or audience_type.upper() == "B2B"
        include_b2c = audience_type is None or audience_type.upper() == "B2C"

        ad_copy_result = await generate_ad_copy_from_website(
            research_data=research_data,
            platforms=platforms,
            include_b2b=include_b2b,
            include_b2c=include_b2c
        )

        return {
            "success": True,
            "message": f"Generated ad copy for {ad_copy_result.get('company_name', 'company')}",
            "data": ad_copy_result
        }

    except Exception as e:
        logger.error(f"Failed to generate ad copy from research: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ad copy: {str(e)}"
        )


@agents_router.post("/ad-copy/b2b")
async def generate_b2b_ad_copy(
    url: str = Query(..., description="Website URL"),
    audience_segment: str = Query("Business Decision Makers", description="Target B2B segment"),
    platform: str = Query("linkedin", description="Target platform: linkedin or facebook")
):
    """
    Generate B2B-specific ad copy optimized for business audiences.

    Features:
    - Professional tone
    - Industry credibility focus
    - ROI/results messaging
    - LinkedIn and Facebook B2B optimized
    """
    try:
        from .market_research_agent import research_website_directly
        from .ad_copy_agent import AdCopyAgent

        research_data = await research_website_directly(url=url, deep_scrape=True)

        agent = AdCopyAgent()
        audience = {
            "name": audience_segment,
            "type": "B2B",
            "job_titles": "Decision makers, managers, executives",
            "company_types": "SMEs, enterprises",
            "pain_points": "Efficiency, cost, quality, reliability"
        }

        ad_copy = await agent.generate_b2b_ad_copy(research_data, audience, platform)

        return {
            "success": True,
            "message": f"Generated B2B ad copy for {platform}",
            "data": ad_copy
        }

    except Exception as e:
        logger.error(f"Failed to generate B2B ad copy: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate B2B ad copy: {str(e)}"
        )


@agents_router.post("/ad-copy/b2c")
async def generate_b2c_ad_copy(
    url: str = Query(..., description="Website URL"),
    audience_segment: str = Query("Consumers", description="Target B2C segment"),
    platform: str = Query("facebook", description="Target platform: facebook or instagram")
):
    """
    Generate B2C-specific ad copy optimized for consumer audiences.

    Features:
    - Conversational tone
    - Emotional appeal
    - Benefit-focused messaging
    - Story-driven variations
    """
    try:
        from .market_research_agent import research_website_directly
        from .ad_copy_agent import AdCopyAgent

        research_data = await research_website_directly(url=url, deep_scrape=True)

        agent = AdCopyAgent()
        audience = {
            "name": audience_segment,
            "type": "B2C",
            "demographics": "Adults 25-54",
            "interests": "Quality, value, convenience",
            "desires": "Better lifestyle, savings, reliability"
        }

        ad_copy = await agent.generate_b2c_ad_copy(research_data, audience, platform)

        return {
            "success": True,
            "message": f"Generated B2C ad copy for {platform}",
            "data": ad_copy
        }

    except Exception as e:
        logger.error(f"Failed to generate B2C ad copy: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate B2C ad copy: {str(e)}"
        )


# ============ Interest Validation & Targeting Endpoints ============

@agents_router.post("/validate-interests")
async def validate_interests(
    interest_tags: List[str],
    access_token: str,
    ad_account_id: Optional[str] = None,
    countries: Optional[List[str]] = None,
    age_min: int = 18,
    age_max: int = 65,
):
    """
    Validate interest tags against Meta's Interest Search API.

    If ad_account_id and countries are provided, also returns a reach estimate.
    """
    try:
        from modules.marketing.meta_targeting_service import MetaTargetingService
        service = MetaTargetingService(access_token=access_token)

        if ad_account_id and countries:
            result = service.validate_and_estimate(
                ad_account_id=ad_account_id,
                interest_tags=interest_tags,
                countries=countries,
                age_min=age_min,
                age_max=age_max
            )
        else:
            validation = service.validate_interests(interest_tags)
            result = {"validation": validation}

        return {
            "success": True,
            "message": f"Validated {len(interest_tags)} interest tags",
            "data": result
        }

    except Exception as e:
        logger.error(f"Failed to validate interests: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate interests: {str(e)}"
        )


@agents_router.post("/audience-from-url-validated")
async def generate_audience_from_url_validated(
    url: str,
    access_token: str,
    ad_account_id: str,
    countries: Optional[List[str]] = None,
    deep_scrape: bool = True,
    db: Session = Depends(get_db)
):
    """
    Generate Meta audience from URL with interest validation and reach estimation.

    Chains: scrape URL → LLM audience generation → Meta interest validation → reach estimate.
    """
    try:
        from .creative_strategist_agent import CreativeStrategistAgent
        from .market_research_agent import research_website_directly

        # Step 1: Research the URL
        research_data = await research_website_directly(url, deep_scrape=deep_scrape)

        # Step 2: Generate validated audience
        strategist = CreativeStrategistAgent()
        result = await strategist.generate_meta_audience_validated(
            website_data=research_data,
            access_token=access_token,
            ad_account_id=ad_account_id,
            countries=countries
        )

        return {
            "success": True,
            "message": "Generated and validated audience targeting",
            "data": result
        }

    except Exception as e:
        logger.error(f"Failed to generate validated audience: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate validated audience: {str(e)}"
        )


# ============ Keyword Intelligence Endpoints ============

@agents_router.post("/keyword-research")
async def keyword_research(
    seed_keyword: str,
    country_code: str = "ZW",
    additional_seeds: Optional[List[str]] = None,
    limit: int = 50,
    target_cities: Optional[List[str]] = None
):
    """
    Research keywords with search volume, CPC, competition data, and intent clustering.

    Uses DataForSEO API if configured, falls back to Google Autocomplete.
    Keywords are automatically clustered by search intent (informational, commercial, transactional).
    target_cities boosts local relevance ranking (e.g. ["Harare"]).
    """
    try:
        from .keyword_intelligence_agent import KeywordIntelligenceAgent
        agent = KeywordIntelligenceAgent()

        result = await agent.research_keywords(
            seed_keyword=seed_keyword,
            country_code=country_code,
            additional_seeds=additional_seeds,
            limit=limit,
            target_cities=target_cities
        )

        return {
            "success": True,
            "message": f"Found {result.get('total_found', 0)} keywords for '{seed_keyword}'",
            "data": result
        }

    except Exception as e:
        logger.error(f"Keyword research failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Keyword research failed: {str(e)}"
        )


# ============ Optimization Decision Logs ============

@agents_router.get("/optimization/logs")
async def get_optimization_logs(
    campaign_id: Optional[uuid.UUID] = Query(None, description="Filter by campaign"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Get history of AI optimization analyses with parsed recommendations."""
    try:
        from .models import OptimizationDecisionLog
        query = db.query(OptimizationDecisionLog).order_by(OptimizationDecisionLog.created_at.desc())
        if campaign_id:
            query = query.filter(OptimizationDecisionLog.campaign_id == campaign_id)
        logs = query.limit(limit).all()
        return {
            "success": True,
            "total": len(logs),
            "logs": [
                {
                    "id": str(log.id),
                    "campaign_id": str(log.campaign_id) if log.campaign_id else None,
                    "recommendations": log.recommendations,
                    "health_score": log.health_score,
                    "summary": log.summary,
                    "parse_method": log.parse_method,
                    "model_used": log.model_used,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                }
                for log in logs
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get optimization logs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ Circuit Breaker Endpoints ============

@agents_router.get("/circuit-breaker/{ad_account_id}")
async def get_circuit_breaker_status(ad_account_id: str, db: Session = Depends(get_db)):
    """Get circuit breaker state for an ad account."""
    try:
        from .models import CircuitBreakerState
        cb = db.query(CircuitBreakerState).filter(
            CircuitBreakerState.ad_account_id == ad_account_id
        ).first()
        if not cb:
            return {"success": True, "state": "not_configured", "is_tripped": False}
        return {
            "success": True,
            "is_tripped": cb.is_tripped,
            "trip_reason": cb.trip_reason,
            "tripped_at": cb.tripped_at.isoformat() if cb.tripped_at else None,
            "auto_reset_at": cb.auto_reset_at.isoformat() if cb.auto_reset_at else None,
            "config": {
                "daily_spend_cap": cb.daily_spend_cap,
                "volatility_threshold_pct": cb.volatility_threshold_pct,
                "data_freshness_hours": cb.data_freshness_hours
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/circuit-breaker/{ad_account_id}/reset")
async def reset_circuit_breaker(ad_account_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Manually reset a tripped circuit breaker."""
    try:
        from .models import CircuitBreakerState
        cb = db.query(CircuitBreakerState).filter(
            CircuitBreakerState.ad_account_id == ad_account_id
        ).first()
        if not cb:
            return {"success": False, "message": "No circuit breaker found for this account"}
        cb.is_tripped = False
        cb.trip_reason = None
        cb.tripped_at = None
        cb.auto_reset_at = None
        db.commit()
        return {"success": True, "message": "Circuit breaker reset"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.put("/circuit-breaker/{ad_account_id}/config")
async def update_circuit_breaker_config(
    ad_account_id: str,
    daily_spend_cap: Optional[float] = Query(None, description="Max daily spend before tripping"),
    volatility_threshold_pct: Optional[float] = Query(None, description="Max % metric change before blocking"),
    data_freshness_hours: Optional[int] = Query(None, description="Max hours since last data sync"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update circuit breaker thresholds for an ad account."""
    try:
        from .models import CircuitBreakerState
        cb = db.query(CircuitBreakerState).filter(
            CircuitBreakerState.ad_account_id == ad_account_id
        ).first()
        if not cb:
            cb = CircuitBreakerState(ad_account_id=ad_account_id)
            db.add(cb)
        if daily_spend_cap is not None:
            cb.daily_spend_cap = daily_spend_cap
        if volatility_threshold_pct is not None:
            cb.volatility_threshold_pct = volatility_threshold_pct
        if data_freshness_hours is not None:
            cb.data_freshness_hours = data_freshness_hours
        db.commit()
        return {
            "success": True,
            "message": "Circuit breaker config updated",
            "config": {
                "daily_spend_cap": cb.daily_spend_cap,
                "volatility_threshold_pct": cb.volatility_threshold_pct,
                "data_freshness_hours": cb.data_freshness_hours
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============ Simulation Endpoints ============

@agents_router.post("/rules/simulate/{ad_account_id}")
async def simulate_rules(ad_account_id: str):
    """
    Run all rules in dry-run mode. Evaluates everything but makes no Meta API calls.
    Shows what WOULD happen if rules were executed right now.
    """
    try:
        result = await automated_rules_engine.run_all_rules(ad_account_id, dry_run=True)
        return {"success": True, "simulation": result}
    except Exception as e:
        logger.error(f"Rule simulation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ Rollback Endpoints ============

@agents_router.post("/rules/check-rollbacks")
async def check_rollbacks_now(current_user: CurrentUser = Depends(get_current_user)):
    """Manually trigger rollback checks for all pending budget actions."""
    try:
        rollbacks = await automated_rules_engine.check_rollbacks()
        return {
            "success": True,
            "rollbacks_executed": len(rollbacks),
            "details": rollbacks
        }
    except Exception as e:
        logger.error(f"Rollback check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ Rule Proposals Endpoints ============

@agents_router.get("/rules/proposals")
async def list_proposed_rules(
    status_filter: Optional[str] = Query("pending", description="Filter by status: pending, accepted, rejected"),
    ad_account_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """List all LLM-proposed rules, filterable by status."""
    try:
        from .models import ProposedRule
        query = db.query(ProposedRule).order_by(ProposedRule.created_at.desc())
        if status_filter:
            query = query.filter(ProposedRule.status == status_filter)
        if ad_account_id:
            query = query.filter(ProposedRule.ad_account_id == ad_account_id)
        proposals = query.limit(limit).all()
        return {
            "success": True,
            "total": len(proposals),
            "proposals": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "conditions": p.conditions,
                    "action_type": p.action_type,
                    "adjustment_percent": p.adjustment_percent,
                    "reasoning": p.reasoning,
                    "status": p.status,
                    "campaign_id": str(p.campaign_id) if p.campaign_id else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None
                }
                for p in proposals
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/rules/proposals/{proposal_id}/accept")
async def accept_proposed_rule(proposal_id: uuid.UUID, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Accept a proposed rule, converting it to an active AutomatedRule in the engine."""
    try:
        from .models import ProposedRule
        proposal = db.query(ProposedRule).filter(ProposedRule.id == proposal_id).first()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if proposal.status != "pending":
            raise HTTPException(status_code=400, detail=f"Proposal already {proposal.status}")

        # Convert to AutomatedRule
        conditions = []
        for cond in proposal.conditions:
            conditions.append(RuleCondition(
                metric=cond.get("metric", "ctr"),
                operator=cond.get("operator", "gt"),
                value=cond.get("value", 0),
                consecutive_days=cond.get("consecutive_days", 1)
            ))

        action = RuleAction(
            type=RuleType(proposal.action_type),
            adjustment_percent=proposal.adjustment_percent
        )

        rule = AutomatedRule(
            name=proposal.name,
            description=f"AI-proposed: {proposal.reasoning}",
            conditions=conditions,
            action=action
        )

        automated_rules_engine.add_rule(rule)

        # Update proposal status
        proposal.status = "accepted"
        proposal.accepted_at = datetime.utcnow()
        db.commit()

        return {
            "success": True,
            "message": f"Rule '{rule.name}' accepted and activated",
            "rule_id": rule.id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/rules/proposals/{proposal_id}/reject")
async def reject_proposed_rule(proposal_id: uuid.UUID, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Reject a proposed rule."""
    try:
        from .models import ProposedRule
        proposal = db.query(ProposedRule).filter(ProposedRule.id == proposal_id).first()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        proposal.status = "rejected"
        proposal.rejected_at = datetime.utcnow()
        db.commit()

        return {"success": True, "message": f"Proposal '{proposal.name}' rejected"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/rules/propose/{campaign_id}")
async def trigger_rule_proposal(campaign_id: uuid.UUID, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Manually trigger the LLM to propose optimization rules for a campaign."""
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Get performance data
        metrics = db.query(PerformanceMetrics).filter(
            PerformanceMetrics.campaign_id == campaign_id
        ).all()

        performance_data = [{
            "ad_id": str(m.ad_id) if m.ad_id else "N/A",
            "impressions": m.impressions or 0,
            "clicks": m.clicks or 0,
            "ctr": m.ctr or 0,
            "cpc": m.cpc or 0,
            "conversions": m.conversions or 0,
            "spend": m.spend or 0,
            "roas": m.roas or 0
        } for m in metrics]

        # Get execution history
        history = automated_rules_engine.get_execution_history(limit=20)

        # Propose rules
        agent = MonitorOptimizerAgent()
        proposals = await agent.propose_rules(
            campaign=campaign,
            performance_data=performance_data,
            current_rules=automated_rules_engine.rules,
            execution_history=history
        )

        return {
            "success": True,
            "proposals_generated": len(proposals),
            "proposals": proposals
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rule proposal failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ Meta-Learner & AI Decision Endpoints ============

@agents_router.get("/meta-learner/status/{ad_account_id}")
async def get_meta_learner_status(ad_account_id: str):
    """Get data maturity level and meta-learner stats for an ad account."""
    try:
        from .meta_learner import MetaLearner
        ml = MetaLearner()
        maturity, days = ml.check_data_maturity(ad_account_id)
        return {
            "success": True,
            "ad_account_id": ad_account_id,
            "data_maturity": maturity,
            "days_of_data": days,
            "features_enabled": {
                "rule_execution": maturity in ("basic", "intermediate", "full"),
                "outcome_measurement": maturity in ("basic", "intermediate", "full"),
                "proposal_backtesting": maturity in ("intermediate", "full"),
                "auto_tune_thresholds": maturity == "full",
                "auto_retire_rules": maturity == "full"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/meta-learner/run/{ad_account_id}")
async def run_meta_learner(ad_account_id: str):
    """Manually trigger a meta-learner cycle."""
    try:
        from .meta_learner import MetaLearner
        ml = MetaLearner()
        result = await ml.run_meta_learner_cycle(ad_account_id)
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Meta-learner cycle failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/meta-learner/backtest-results")
async def get_backtest_results(
    ad_account_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """View backtest history."""
    try:
        from .models import BacktestResult
        query = db.query(BacktestResult).order_by(BacktestResult.created_at.desc())
        if ad_account_id:
            query = query.filter(BacktestResult.ad_account_id == ad_account_id)
        results = query.limit(limit).all()
        return {
            "success": True,
            "total": len(results),
            "results": [
                {
                    "id": str(r.id),
                    "rule_id": r.rule_id,
                    "days_tested": r.days_tested,
                    "total_triggers": r.total_triggers,
                    "good_outcomes": r.good_outcomes,
                    "bad_outcomes": r.bad_outcomes,
                    "success_rate": r.success_rate,
                    "avg_cpa_change": r.avg_cpa_change,
                    "verdict": r.verdict,
                    "created_at": r.created_at.isoformat() if r.created_at else None
                }
                for r in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/meta-learner/backtest-rule")
async def backtest_rule_manually(
    ad_account_id: str,
    conditions: List[dict] = [],
    action_type: str = "scale_up",
    days: int = Query(30, ge=7, le=90)
):
    """Manually backtest a rule against historical data."""
    try:
        from .meta_learner import MetaLearner
        ml = MetaLearner()
        result = ml.backtest_rule(conditions, action_type, ad_account_id, days)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/ai-decisions")
async def get_ai_decisions(
    decision_type: Optional[str] = Query(None, description="Filter by type"),
    agent_name: Optional[str] = Query(None, description="Filter by agent"),
    ad_account_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Query the AI decision audit log. Each entry is a (context, decision, outcome) triple for fine-tuning."""
    try:
        from .models import AIDecisionLog
        query = db.query(AIDecisionLog).order_by(AIDecisionLog.created_at.desc())
        if decision_type:
            query = query.filter(AIDecisionLog.decision_type == decision_type)
        if agent_name:
            query = query.filter(AIDecisionLog.agent_name == agent_name)
        if ad_account_id:
            query = query.filter(AIDecisionLog.ad_account_id == ad_account_id)
        logs = query.limit(limit).all()
        return {
            "success": True,
            "total": len(logs),
            "decisions": [
                {
                    "id": str(l.id),
                    "decision_type": l.decision_type,
                    "agent_name": l.agent_name,
                    "input_context": l.input_context,
                    "decision": l.decision,
                    "reasoning": l.reasoning,
                    "outcome_measured": l.outcome_measured,
                    "outcome_data": l.outcome_data,
                    "outcome_score": l.outcome_score,
                    "confidence": l.confidence,
                    "data_maturity_level": l.data_maturity_level,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                    "outcome_measured_at": l.outcome_measured_at.isoformat() if l.outcome_measured_at else None
                }
                for l in logs
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/ai-decisions/stats")
async def get_ai_decision_stats(
    ad_account_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get aggregate stats on AI decisions — success rates by type and agent."""
    try:
        from .models import AIDecisionLog
        from sqlalchemy import func

        query = db.query(
            AIDecisionLog.decision_type,
            AIDecisionLog.agent_name,
            func.count(AIDecisionLog.id).label("total"),
            func.avg(AIDecisionLog.outcome_score).label("avg_score"),
            func.count(AIDecisionLog.outcome_score).label("measured")
        ).group_by(AIDecisionLog.decision_type, AIDecisionLog.agent_name)

        if ad_account_id:
            query = query.filter(AIDecisionLog.ad_account_id == ad_account_id)

        rows = query.all()
        return {
            "success": True,
            "stats": [
                {
                    "decision_type": r.decision_type,
                    "agent_name": r.agent_name,
                    "total_decisions": r.total,
                    "avg_outcome_score": round(float(r.avg_score), 3) if r.avg_score else None,
                    "outcomes_measured": r.measured
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/ai-decisions/outcomes")
async def get_ai_decision_outcomes(
    min_score: Optional[float] = Query(None, description="Min outcome score (-1 to 1)"),
    max_score: Optional[float] = Query(None, description="Max outcome score (-1 to 1)"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get decisions with measured outcomes — the fine-tuning dataset."""
    try:
        from .models import AIDecisionLog
        query = db.query(AIDecisionLog).filter(
            AIDecisionLog.outcome_measured == True,
            AIDecisionLog.outcome_score.isnot(None)
        ).order_by(AIDecisionLog.outcome_measured_at.desc())

        if min_score is not None:
            query = query.filter(AIDecisionLog.outcome_score >= min_score)
        if max_score is not None:
            query = query.filter(AIDecisionLog.outcome_score <= max_score)

        logs = query.limit(limit).all()
        return {
            "success": True,
            "total": len(logs),
            "dataset": [
                {
                    "input": l.input_context,
                    "decision": l.decision,
                    "reasoning": l.reasoning,
                    "outcome_score": l.outcome_score,
                    "outcome_data": l.outcome_data,
                    "decision_type": l.decision_type,
                    "agent_name": l.agent_name,
                    "created_at": l.created_at.isoformat() if l.created_at else None
                }
                for l in logs
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/rules/performance")
async def get_rule_performance(db: Session = Depends(get_db)):
    """Get per-rule performance stats from the tracker."""
    try:
        from .models import RulePerformanceTracker
        trackers = db.query(RulePerformanceTracker).order_by(
            RulePerformanceTracker.success_rate.desc()
        ).all()
        return {
            "success": True,
            "total": len(trackers),
            "rules": [
                {
                    "rule_id": t.rule_id,
                    "rule_name": t.rule_name,
                    "total_triggers": t.total_triggers,
                    "success_rate": t.success_rate,
                    "good_outcomes": t.good_outcomes,
                    "bad_outcomes": t.bad_outcomes,
                    "times_tightened": t.times_tightened,
                    "times_loosened": t.times_loosened,
                    "auto_disabled": t.auto_disabled,
                    "disabled_reason": t.disabled_reason,
                    "last_triggered_at": t.last_triggered_at.isoformat() if t.last_triggered_at else None,
                    "last_evaluated_at": t.last_evaluated_at.isoformat() if t.last_evaluated_at else None
                }
                for t in trackers
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Marketing Events & Calendar Endpoints ============

@agents_router.get("/marketing-events/{store_id}")
async def list_marketing_events(
    store_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """List all custom marketing events for a store."""
    try:
        from .models import MarketingEvent
        events = db.query(MarketingEvent).filter(
            MarketingEvent.store_id == store_id
        ).order_by(MarketingEvent.start_date).all()
        return {
            "success": True,
            "total": len(events),
            "events": [
                {
                    "id": str(e.id),
                    "name": e.name,
                    "event_type": e.event_type,
                    "start_date": e.start_date.isoformat() if e.start_date else None,
                    "end_date": e.end_date.isoformat() if e.end_date else None,
                    "budget_multiplier": e.budget_multiplier,
                    "is_active": e.is_active,
                    "notes": e.notes
                }
                for e in events
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/marketing-events/{store_id}")
async def create_marketing_event(
    store_id: uuid.UUID,
    name: str = Query(..., description="Event name"),
    event_type: str = Query("custom", description="sale, launch, seasonal, holiday, custom"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    budget_multiplier: float = Query(1.0, description="Budget multiplier (e.g., 1.3 = +30%)"),
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Add a custom marketing event for a store."""
    try:
        from .models import MarketingEvent
        event = MarketingEvent(
            store_id=store_id,
            name=name,
            event_type=event_type,
            start_date=datetime.fromisoformat(start_date),
            end_date=datetime.fromisoformat(end_date),
            budget_multiplier=budget_multiplier,
            notes=notes,
            is_active=True
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return {
            "success": True,
            "message": f"Event '{name}' created",
            "event_id": str(event.id)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.put("/marketing-events/{event_id}")
async def update_marketing_event(
    event_id: uuid.UUID,
    name: Optional[str] = None,
    event_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    budget_multiplier: Optional[float] = None,
    is_active: Optional[bool] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Update a custom marketing event."""
    try:
        from .models import MarketingEvent
        event = db.query(MarketingEvent).filter(MarketingEvent.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        if name is not None:
            event.name = name
        if event_type is not None:
            event.event_type = event_type
        if start_date is not None:
            event.start_date = datetime.fromisoformat(start_date)
        if end_date is not None:
            event.end_date = datetime.fromisoformat(end_date)
        if budget_multiplier is not None:
            event.budget_multiplier = budget_multiplier
        if is_active is not None:
            event.is_active = is_active
        if notes is not None:
            event.notes = notes
        db.commit()
        return {"success": True, "message": f"Event '{event.name}' updated"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.delete("/marketing-events/{event_id}")
async def delete_marketing_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a custom marketing event."""
    try:
        from .models import MarketingEvent
        event = db.query(MarketingEvent).filter(MarketingEvent.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        db.delete(event)
        db.commit()
        return {"success": True, "message": f"Event '{event.name}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/marketing-events/{store_id}/upcoming")
async def get_upcoming_events_for_store(
    store_id: uuid.UUID,
    days_ahead: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Get all upcoming events (public holidays + retail calendar + custom) for a store."""
    try:
        from .calendar_engine import get_upcoming_events
        from modules.stores.models import Store

        store = db.query(Store).filter(Store.id == store_id).first()
        country = store.country_code or "US" if store else "US"

        events = get_upcoming_events(country, str(store_id), days_ahead)
        return {
            "success": True,
            "country_code": country,
            "days_ahead": days_ahead,
            "total": len(events),
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/calendar/retail-events/{store_id}/overrides")
async def get_retail_event_overrides(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all retail calendar overrides for a store."""
    try:
        from .models import StoreCalendarOverride
        overrides = db.query(StoreCalendarOverride).filter(
            StoreCalendarOverride.store_id == store_id
        ).all()
        return {
            "success": True,
            "total": len(overrides),
            "overrides": [
                {
                    "id": str(o.id),
                    "event_key": o.event_key,
                    "is_enabled": o.is_enabled,
                    "custom_name": o.custom_name,
                    "custom_start_month": o.custom_start_month,
                    "custom_start_day": o.custom_start_day,
                    "custom_duration_days": o.custom_duration_days,
                    "custom_budget_multiplier": o.custom_budget_multiplier,
                    "custom_impact": o.custom_impact,
                }
                for o in overrides
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.put("/calendar/retail-events/{store_id}/{event_key}")
async def update_retail_event_override(
    store_id: uuid.UUID,
    event_key: str,
    is_enabled: Optional[bool] = None,
    custom_name: Optional[str] = None,
    custom_start_month: Optional[int] = Query(None, ge=1, le=12),
    custom_start_day: Optional[int] = Query(None, ge=1, le=31),
    custom_duration_days: Optional[int] = Query(None, ge=1, le=60),
    custom_budget_multiplier: Optional[float] = Query(None, ge=0.5, le=3.0),
    custom_impact: Optional[str] = Query(None, description="high, medium, or low"),
    db: Session = Depends(get_db)
):
    """
    Create or update a store's override for a built-in retail calendar event.
    Use this to toggle events on/off, adjust dates, budget impact, etc.
    """
    try:
        from .models import StoreCalendarOverride
        from .calendar_engine import RETAIL_CALENDAR

        if event_key not in RETAIL_CALENDAR:
            raise HTTPException(status_code=404, detail=f"Unknown retail event: {event_key}")

        # Get or create override
        override = db.query(StoreCalendarOverride).filter(
            StoreCalendarOverride.store_id == store_id,
            StoreCalendarOverride.event_key == event_key
        ).first()

        if not override:
            override = StoreCalendarOverride(store_id=store_id, event_key=event_key)
            db.add(override)

        if is_enabled is not None:
            override.is_enabled = is_enabled
        if custom_name is not None:
            override.custom_name = custom_name
        if custom_start_month is not None:
            override.custom_start_month = custom_start_month
        if custom_start_day is not None:
            override.custom_start_day = custom_start_day
        if custom_duration_days is not None:
            override.custom_duration_days = custom_duration_days
        if custom_budget_multiplier is not None:
            override.custom_budget_multiplier = custom_budget_multiplier
        if custom_impact is not None:
            override.custom_impact = custom_impact

        db.commit()

        return {
            "success": True,
            "message": f"Override for '{event_key}' saved",
            "event_key": event_key,
            "original": {
                "name": RETAIL_CALENDAR[event_key]["name"],
                "impact": RETAIL_CALENDAR[event_key].get("impact"),
                "budget_multiplier": RETAIL_CALENDAR[event_key].get("budget_multiplier")
            },
            "override": {
                "is_enabled": override.is_enabled,
                "custom_name": override.custom_name,
                "custom_budget_multiplier": override.custom_budget_multiplier,
                "custom_impact": override.custom_impact
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/calendar/holidays/{country_code}")
async def get_public_holidays(
    country_code: str,
    year: Optional[int] = None
):
    """Get public holidays for a country from Nager.Date API."""
    try:
        from .calendar_engine import fetch_public_holidays
        holidays = fetch_public_holidays(country_code.upper(), year)
        return {
            "success": True,
            "country_code": country_code.upper(),
            "year": year or datetime.utcnow().year,
            "total": len(holidays),
            "holidays": holidays
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/calendar/retail-events/{country_code}")
async def get_retail_events(
    country_code: str,
    year: Optional[int] = None,
    store_id: Optional[str] = Query(None, description="Store ID to apply overrides")
):
    """Get built-in retail calendar events for a country. Pass store_id to include user overrides."""
    try:
        from .calendar_engine import compute_retail_events
        events = compute_retail_events(country_code.upper(), year, store_id=store_id)
        return {
            "success": True,
            "country_code": country_code.upper(),
            "year": year or datetime.utcnow().year,
            "total": len(events),
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Creative Test Endpoints ============

@agents_router.get("/creative-tests")
async def list_creative_tests(
    status_filter: Optional[str] = Query(None, description="Filter by status: running, completed, failed"),
    ad_account_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """List all multi-variant creative tests."""
    try:
        from .models import CreativeTest
        query = db.query(CreativeTest).order_by(CreativeTest.created_at.desc())
        if status_filter:
            query = query.filter(CreativeTest.status == status_filter)
        if ad_account_id:
            query = query.filter(CreativeTest.ad_account_id == ad_account_id)
        tests = query.limit(limit).all()
        return {
            "success": True,
            "total": len(tests),
            "tests": [
                {
                    "id": str(t.id),
                    "adset_id": t.adset_id,
                    "original_ad_id": t.original_ad_id,
                    "status": t.status,
                    "num_variants": t.num_variants,
                    "winner_ad_id": t.winner_ad_id,
                    "results": t.results,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None
                }
                for t in tests
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.get("/creative-tests/{test_id}")
async def get_creative_test_detail(test_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get creative test details with all variant performance data."""
    try:
        from .models import CreativeTest, CreativeTestVariant
        test = db.query(CreativeTest).filter(CreativeTest.id == test_id).first()
        if not test:
            raise HTTPException(status_code=404, detail="Creative test not found")

        variants = db.query(CreativeTestVariant).filter(
            CreativeTestVariant.test_id == test_id
        ).order_by(CreativeTestVariant.variant_number).all()

        return {
            "success": True,
            "test": {
                "id": str(test.id),
                "adset_id": test.adset_id,
                "original_ad_id": test.original_ad_id,
                "status": test.status,
                "num_variants": test.num_variants,
                "min_impressions_per_variant": test.min_impressions_per_variant,
                "prune_threshold": test.prune_threshold,
                "winner_ad_id": test.winner_ad_id,
                "results": test.results,
                "created_at": test.created_at.isoformat() if test.created_at else None,
                "completed_at": test.completed_at.isoformat() if test.completed_at else None
            },
            "variants": [
                {
                    "id": str(v.id),
                    "ad_id": v.ad_id,
                    "variant_number": v.variant_number,
                    "headline": v.headline,
                    "primary_text": v.primary_text,
                    "image_url": v.image_url,
                    "is_original": v.is_original,
                    "status": v.status,
                    "final_impressions": v.final_impressions,
                    "final_ctr": v.final_ctr,
                    "final_cpc": v.final_cpc,
                    "final_conversions": v.final_conversions
                }
                for v in variants
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/creative-tests/{adset_id}/start")
async def start_creative_test(adset_id: str):
    """Manually trigger a multi-variant creative test for an ad set."""
    try:
        # Find an active ad in this ad set to use as the basis
        from database import SessionLocal as StartDB
        from modules.marketing.models import MetaAdSet, MetaAd
        sdb = StartDB()
        try:
            adset = sdb.query(MetaAdSet).filter(MetaAdSet.adset_id == adset_id).first()
            if not adset:
                raise HTTPException(status_code=404, detail=f"Ad set {adset_id} not found")

            # Find an active ad in this ad set
            active_ad = sdb.query(MetaAd).filter(
                MetaAd.adset_id == adset.id,
                MetaAd.status == "ACTIVE"
            ).first()

            if not active_ad:
                raise HTTPException(status_code=400, detail="No active ads found in this ad set")

            entity_id = active_ad.ad_id
        finally:
            sdb.close()

        result = await automated_rules_engine._refresh_creative_multi_variant(entity_id, "ad")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Creative test start failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@agents_router.post("/creative-tests/{test_id}/finalize")
async def finalize_creative_test(test_id: uuid.UUID):
    """Force-finalize a running creative test (picks winner immediately)."""
    try:
        from .models import CreativeTest
        from database import SessionLocal as FinalDB
        fdb = FinalDB()
        try:
            test = fdb.query(CreativeTest).filter(CreativeTest.id == test_id).first()
            if not test:
                raise HTTPException(status_code=404, detail="Creative test not found")
            if test.status != "running":
                raise HTTPException(status_code=400, detail=f"Test already {test.status}")
            # Set min impressions to 0 to force evaluation
            test.min_impressions_per_variant = 0
            fdb.commit()
        finally:
            fdb.close()

        results = await automated_rules_engine.evaluate_creative_tests()
        return {
            "success": True,
            "message": f"Force-finalized test {test_id}",
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ Competitive Intelligence Endpoints ============

@agents_router.post("/competitive-intelligence")
async def competitive_intelligence(
    request: CompetitiveIntelligenceRequest
):
    """
    Run a full competitive intelligence pipeline for a domain.

    4-step process:
    1. Categorize the domain's business verticals (DataForSEO Labs)
    2. Discover top competitors by keyword overlap (DataForSEO Labs)
    3. Analyze competitor keyword strategies - high CPC / commercial intent (DataForSEO Labs)
    4. Expand top opportunity keywords for campaign ideas (DataForSEO Keyword Data)

    Optionally enriched with Tavily web scraping for qualitative competitor insights.
    """
    try:
        from .competitive_intelligence_agent import CompetitiveIntelligenceAgent
        agent = CompetitiveIntelligenceAgent()
        result = await agent.run_pipeline(
            domain=request.domain,
            country_code=request.country_code,
            language_code=request.language_code,
            top_competitors=request.top_competitors,
            enrich_with_tavily=request.enrich_with_tavily,
            expand_keywords=request.expand_keywords
        )
        return result
    except Exception as e:
        logger.error(f"Competitive intelligence failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Competitive intelligence failed: {str(e)}"
        )


# ============ Weekly Report Endpoints ============

@agents_router.post("/weekly-report/{ad_account_id}")
async def generate_weekly_report(
    ad_account_id: str,
    db: Session = Depends(get_db)
):
    """
    Generate a weekly performance report for an ad account.

    Aggregates 7 days of insights data with LLM narrative summary,
    top/worst performers, and week-over-week trends.
    """
    try:
        from .report_generator import WeeklyReportGenerator
        from modules.marketing.models import MetaAdAccount

        # Find account for access token
        account = db.query(MetaAdAccount).filter(
            MetaAdAccount.ad_account_id == ad_account_id
        ).first()

        generator = WeeklyReportGenerator()
        report = await generator.generate_weekly_report(
            ad_account_id=ad_account_id,
            access_token=account.access_token if account else None
        )

        return report

    except Exception as e:
        logger.error(f"Weekly report failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Weekly report failed: {str(e)}"
        )


@agents_router.post("/dayparting/recommend")
async def recommend_dayparting_schedule(
    industry: str = Query(..., description="Business industry (e.g., technology, restaurant, ecommerce)"),
    business_type: str = Query(None, description="Optional business type for more specific matching"),
    business_description: str = Query(None, description="Brief business description for AI-powered scheduling"),
    countries: str = Query(None, description="Comma-separated target countries (e.g., ZW,ZA,US)"),
    use_ai: bool = Query(False, description="Use AI to generate schedule (slower but more precise)")
):
    """
    Get recommended ad schedule (dayparting) for a business.

    Returns optimal time blocks for Meta ad delivery based on industry.
    Used by the agent pipeline to automatically schedule lifetime budget campaigns.
    """
    try:
        from modules.marketing.dayparting_service import (
            get_schedule_for_industry,
            generate_schedule_with_ai,
            INDUSTRY_SCHEDULES,
            INDUSTRY_MAPPING
        )

        country_list = [c.strip() for c in countries.split(",")] if countries else None

        if use_ai and business_description:
            result = await generate_schedule_with_ai(
                industry=industry,
                business_type=business_type or "",
                business_description=business_description,
                target_countries=country_list
            )
        else:
            schedule = get_schedule_for_industry(industry, business_type)
            result = {
                "schedule": schedule,
                "reasoning": f"Rule-based schedule for {industry}" + (f"/{business_type}" if business_type else ""),
                "profile_used": "rule_based",
                "method": "rule_based"
            }

        # Add human-readable summary
        schedule = result.get("schedule", [])
        day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        readable_blocks = []
        for block in schedule:
            days = ", ".join(day_names[d] for d in block.get("days", []))
            readable_blocks.append(
                f"{days}: {block.get('start_hour', 0):02d}:00 - {block.get('end_hour', 0):02d}:00"
            )
        result["readable_schedule"] = readable_blocks
        result["total_blocks"] = len(schedule)
        result["available_profiles"] = list(INDUSTRY_SCHEDULES.keys())

        return result

    except Exception as e:
        logger.error(f"Dayparting recommendation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dayparting recommendation failed: {str(e)}"
        )


# ============ Video Generation Proxy ============
# The frontend previously called OpenRouter directly with API keys embedded
# in the browser bundle. These endpoints keep the key server-side, enforce
# auth + per-store quota, and record token usage.

from pydantic import BaseModel


class VideoGenerateProxyRequest(BaseModel):
    prompt: str
    length: str = "5"
    video_base64: Optional[str] = None  # data URL for video-to-video


class PromptEnhanceProxyRequest(BaseModel):
    prompt: str
    video_length: str = "5"


def _openrouter_chat(payload: dict, timeout: int = 300) -> dict:
    """Call OpenRouter chat completions with the server-side API key."""
    import os
    import requests

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI video service is not configured"
        )

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://shopivell.com",
            "X-Title": "Shopivell Video Studio",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if not response.ok:
        logger.error(f"[VideoProxy] OpenRouter error {response.status_code}: {response.text[:500]}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Video AI provider returned an error"
        )
    return response.json()


def _track_video_usage(result: dict, model: str, agent_name: str, current_user: CurrentUser) -> None:
    """Record OpenRouter token usage for cost tracking (fire-and-forget)."""
    try:
        from modules.openrouter.ai_usage_service import track_usage
        usage = result.get("usage", {}) or {}
        track_usage(
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            agent_name=agent_name,
            store_id=current_user.store_id,
            user_id=current_user.id,
        )
    except Exception as e:
        logger.error(f"[VideoProxy] Usage tracking failed: {e}")


@agents_router.post("/video/generate")
def generate_video_proxy(
    request: VideoGenerateProxyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate a video via OpenRouter (replaces direct frontend OpenRouter calls).
    Sync endpoint on purpose: FastAPI runs it in a threadpool, so the blocking
    `requests` call doesn't stall the event loop.
    """
    if current_user.store_id:
        require_ai_quota(current_user.store_id, db)

    content = [{
        "type": "text",
        "text": (
            f"{request.prompt} \n\nPlease create a {request.length}-second video with "
            "this description. Focus on smooth transitions and coherent visual storytelling."
        )
    }]
    if request.video_base64:
        content.append({"type": "video_url", "video_url": {"url": request.video_base64}})

    model = "google/gemini-3-pro-vision-preview"
    result = _openrouter_chat({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1000,
    })
    _track_video_usage(result, model, "video_generator", current_user)
    return result


@agents_router.post("/video/enhance-prompt")
def enhance_video_prompt_proxy(
    request: PromptEnhanceProxyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enhance a video prompt via OpenRouter (key stays server-side)."""
    if current_user.store_id:
        require_ai_quota(current_user.store_id, db)

    instruction = f"""Enhance this video prompt to be more cinematic and descriptive for a {request.video_length}-second video. Use these examples as reference:

Example 1: "Create a 5-second time-lapse of a bustling city transforming from day to night, with neon lights flickering on and cars flowing like rivers of light. Cinematic, smooth transitions, 4K quality."

Example 2: "Generate a 10-second animated explainer video showing how photosynthesis works in plants. Use vibrant colors, smooth animations, and clear visual storytelling with text labels appearing at key moments."

Example 3: "Transform this video into a vintage 8mm film style with film grain, light leaks, and nostalgic color grading. Add subtle camera shake and focus on creating a warm, nostalgic atmosphere."

Now enhance this prompt for a {request.video_length}-second video in a similar detailed, cinematic style, focusing on visual flow, transitions, mood, and timing. Return ONLY the enhanced prompt text without any additional explanations: "{request.prompt}\""""

    model = "google/gemma-3-27b-it:free"
    result = _openrouter_chat({
        "model": model,
        "messages": [{"role": "user", "content": instruction}],
    }, timeout=120)
    _track_video_usage(result, model, "prompt_enhancer", current_user)

    enhanced = (
        (result.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
        or ""
    ).strip()
    if not enhanced:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No enhanced prompt returned"
        )
    return {"enhanced_prompt": enhanced}


# Models the frontend may call through the generic proxy
_PROXY_ALLOWED_MODELS = {
    "google/gemma-3-27b-it:free",
    "google/gemini-3-pro-image-preview",
    "google/gemini-3-pro-vision-preview",
}


class OpenRouterChatProxyRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: Optional[int] = None


@agents_router.post("/ai/openrouter-chat")
def openrouter_chat_proxy(
    request: OpenRouterChatProxyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    General-purpose OpenRouter chat proxy for frontend AI features
    (post templates, hashtags, image studio). Replaces direct frontend
    OpenRouter calls that embedded API keys in the browser bundle.
    """
    if request.model not in _PROXY_ALLOWED_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{request.model}' is not allowed through this proxy"
        )

    if current_user.store_id:
        require_ai_quota(current_user.store_id, db)

    payload: Dict[str, Any] = {"model": request.model, "messages": request.messages}
    if request.max_tokens:
        payload["max_tokens"] = min(request.max_tokens, 4000)

    result = _openrouter_chat(payload)
    _track_video_usage(result, request.model, "frontend_ai_proxy", current_user)
    return result

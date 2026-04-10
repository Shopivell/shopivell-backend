# modules/campaigns/router.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, AsyncGenerator
import uuid
import logging
import json
import asyncio

from database import get_db
from .models import UrlCampaign, CampaignStatus, UrlAdSet, UrlAdContent

# Aliases for readability
Campaign = UrlCampaign
AdSet = UrlAdSet
AdContent = UrlAdContent
from .schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse, CampaignListResponse,
    ScrapeUrlRequest, ScrapeUrlResponse, AdSetResponse, AdContentResponse,
    GenerateAdsRequest, CreateCampaignFromStoreRequest, CreateCampaignFromStoreResponse,
    QuickLaunchRequest, QuickLaunchResponse
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

# Import Meta Ads functionality
try:
    from modules.marketing.router import (
        create_meta_campaign, create_meta_adset, create_meta_ad
    )
    from modules.marketing.models import MetaAdAccount, MetaCampaign, MetaAdSet, MetaAd
    from datetime import datetime
    import json
    META_ADS_AVAILABLE = True
except ImportError:
    META_ADS_AVAILABLE = False

# Import Notification functionality
try:
    from modules.notifications.models import Notification
    from modules.notifications.schemas import NotificationType, NotificationPriority
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False

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

    # Debug: Log screenshot URL
    screenshot_url = campaign.scraped_data.get("screenshot_url") if campaign.scraped_data else None
    print(f"[Router] Returning campaign with screenshot_url: {screenshot_url}")

    return ScrapeUrlResponse(
        campaign_id=campaign.id,
        status=campaign.status.value,
        message="Campaign created successfully" if not error else error,
        scraped_data=campaign.scraped_data
    )


@campaign_router.post("/from-store", response_model=CreateCampaignFromStoreResponse, tags=["campaigns"])
def create_campaign_from_store(
    request: CreateCampaignFromStoreRequest,
    db: Session = Depends(get_db)
):
    """
    Create a campaign directly from existing store data.

    This endpoint uses the store's saved information (name, business_type,
    store_voice, products_or_services, logo_url, color_theme) to generate
    ad content WITHOUT scraping the website again.

    This is more reliable and faster than scraping, especially when:
    - The store already has complete data
    - Web scraping is rate-limited or failing
    - You want to create campaigns based on curated store information
    """
    # Import Store model here to avoid circular imports
    from modules.stores.models import Store

    # Get the store
    store = db.query(Store).filter(Store.id == request.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if not store.is_setup_completed:
        raise HTTPException(status_code=400, detail="Store setup is not completed")

    service = CampaignService(db)
    campaign, error = service.create_campaign_from_store(
        store=store,
        campaign_name=request.campaign_name,
        asset_ids=request.asset_ids
    )

    if error and not campaign:
        raise HTTPException(status_code=500, detail=error)

    # Prepare store data summary for response
    store_data_used = {
        "store_name": store.store_name,
        "business_type": store.business_type,
        "store_voice": store.store_voice[:200] + "..." if store.store_voice and len(store.store_voice) > 200 else store.store_voice,
        "products_or_services": store.products_or_services[:10] if store.products_or_services else [],
        "logo_url": store.logo_url,
        "color_theme": store.color_theme,
        "store_link": store.store_link
    }

    return CreateCampaignFromStoreResponse(
        campaign_id=campaign.id,
        status=campaign.status.value,
        message="Campaign created successfully from store data",
        store_data_used=store_data_used
    )


@campaign_router.post("/manual")
def create_manual_campaign(
    request: dict,
    db: Session = Depends(get_db)
):
    """
    Create a campaign manually without AI scraping.
    Returns a draft campaign with one empty ad set and ad content.
    """
    store_id = request.get("store_id")
    name = request.get("name", "My Campaign")
    goal = request.get("goal", "sales")
    daily_budget = request.get("daily_budget", 50.0)

    if not store_id:
        raise HTTPException(status_code=400, detail="store_id is required")

    campaign = Campaign(
        id=uuid.uuid4(),
        store_id=store_id,
        name=name,
        source_type="manual",
        goal=goal,
        daily_budget=daily_budget,
        status=CampaignStatus.READY,
        countries=[],
        cities=[],
        age_range={"min": 18, "max": 65},
        gender="all",
        interests=[],
        platforms=["facebook"],
        generated_headlines=[],
        generated_descriptions=[],
        platform_campaign_ids={},
    )
    db.add(campaign)
    db.flush()

    ad_set = AdSet(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        name="Ad Set 1",
        title="Ad Set 1",
        audience_tags=[],
        hashtags=[],
        is_selected=True,
        is_active=True,
    )
    db.add(ad_set)
    db.flush()

    ad_content = AdContent(
        id=uuid.uuid4(),
        ad_set_id=ad_set.id,
        headline="",
        primary_text="",
        description="",
        call_to_action="LEARN_MORE",
        is_primary=True,
        is_active=True,
    )
    db.add(ad_content)
    db.commit()
    db.refresh(campaign)

    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status.value,
        "message": "Manual campaign created successfully"
    }


@campaign_router.get("/scrape-stream")
async def scrape_url_stream(
    url: str,
    store_id: uuid.UUID,
    campaign_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Stream scraping progress via Server-Sent Events (SSE).

    Events sent:
    - progress: {stage, message, percentage}
    - scraped_data: {business_name, business_type, products, brand_color, etc.}
    - ad_set: {name, title, audience_tags, hashtags, headline, primary_text}
    - competitor: {name, url, description, rating, reviews, source}
    - keyword: {keyword, source}
    - trend: {title, source, insight}
    - market_research_summary: {competitors_found, keywords_found, trends_found}
    - complete: {campaign_id, status}
    - error: {message}
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        service = CampaignService(db)

        try:
            # Stage 1: Start scraping
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'scraping', 'message': 'Connecting to website...', 'percentage': 5})}\n\n"
            await asyncio.sleep(0.1)

            # Scrape the URL
            scraped_data = service._scrape_website(url)

            if not scraped_data:
                yield f"data: {json.dumps({'event': 'error', 'message': 'Failed to scrape URL - no data returned'})}\n\n"
                return

            if scraped_data.get("error"):
                yield f"data: {json.dumps({'event': 'error', 'message': scraped_data.get('error', 'Failed to scrape URL')})}\n\n"
                return

            # Stage 2: Stream the scraped content word by word
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'reading', 'message': 'Reading website content...', 'percentage': 10})}\n\n"
            await asyncio.sleep(0.1)

            # Get the scraped content text
            content = scraped_data.get("content", "")
            if content:
                # Split into chunks (groups of words) for streaming
                words = content.split()
                total_words = len(words)
                chunk_size = 15  # Send 15 words at a time

                for i in range(0, min(total_words, 300), chunk_size):  # Limit to first 300 words
                    chunk = " ".join(words[i:i + chunk_size])
                    progress = 10 + int((i / min(total_words, 300)) * 20)  # Progress from 10% to 30%
                    yield f"data: {json.dumps({'event': 'content_chunk', 'text': chunk, 'percentage': progress})}\n\n"
                    await asyncio.sleep(0.05)  # Small delay for typewriter effect

            # Stage 3: Extract and stream business info
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'analyzing', 'message': 'Analyzing business information...', 'percentage': 35})}\n\n"
            await asyncio.sleep(0.2)

            brand_dna = scraped_data.get("brand_dna") or {}

            # Note: We'll get the actual business name from AI later, for now just show "Analyzing..."
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'analyzing', 'message': 'Identifying business information...', 'percentage': 35})}\n\n"
            await asyncio.sleep(0.2)

            # Stream brand color if found
            brand_color = scraped_data.get("brand_color")
            if brand_color:
                yield f"data: {json.dumps({'event': 'info_found', 'type': 'brand_color', 'label': 'Brand Color', 'value': brand_color})}\n\n"
                await asyncio.sleep(0.1)

            # Stream logo URL if found
            logo_url = scraped_data.get("logo_url")
            if logo_url:
                yield f"data: {json.dumps({'event': 'info_found', 'type': 'logo', 'label': 'Logo Found', 'value': logo_url})}\n\n"
                await asyncio.sleep(0.1)

            # Stream screenshot URL
            screenshot_url = scraped_data.get("screenshot_url")
            if screenshot_url:
                yield f"data: {json.dumps({'event': 'info_found', 'type': 'screenshot', 'label': 'Screenshot Captured', 'value': screenshot_url})}\n\n"
                await asyncio.sleep(0.2)

            # Stage 4: Generate ad content
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'generating', 'message': 'Generating ad content with AI...', 'percentage': 55})}\n\n"
            await asyncio.sleep(0.1)

            ad_content = service._generate_ad_content(scraped_data, url)

            if not ad_content:
                yield f"data: {json.dumps({'event': 'error', 'message': 'Failed to generate ad content'})}\n\n"
                return

            # Stream AI-generated business name (this is the accurate one)
            ai_business_name = ad_content.get("business_name")
            if ai_business_name:
                yield f"data: {json.dumps({'event': 'info_found', 'type': 'business_name', 'label': 'Business Name', 'value': ai_business_name})}\n\n"
                await asyncio.sleep(0.2)

            # Stream AI-generated business type
            ai_business_type = ad_content.get("business_type")
            if ai_business_type:
                yield f"data: {json.dumps({'event': 'info_found', 'type': 'industry', 'label': 'Business Type', 'value': ai_business_type})}\n\n"
                await asyncio.sleep(0.2)

            # Stream AI-generated products/services
            ai_products = ad_content.get("products_services", [])[:6]
            if ai_products:
                for product in ai_products:
                    yield f"data: {json.dumps({'event': 'info_found', 'type': 'product', 'label': 'Product/Service', 'value': product})}\n\n"
                    await asyncio.sleep(0.1)

            # Stage 5: Stream ad set creation
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'ad_sets', 'message': 'Creating ad sets...', 'percentage': 70})}\n\n"
            await asyncio.sleep(0.2)

            ad_sets_data = ad_content.get("ad_sets", [])[:1]
            headlines = ad_content.get("headlines", [])

            for i, ad_set_data in enumerate(ad_sets_data):
                # Stream ad set name
                ad_set_name = ad_set_data.get("name", f"Ad Set {i+1}")
                yield f"data: {json.dumps({'event': 'info_found', 'type': 'ad_set_name', 'label': 'Ad Set', 'value': ad_set_name})}\n\n"
                await asyncio.sleep(0.2)

                # Stream headline
                headline = headlines[0] if headlines else ad_set_data.get("title", "")
                if headline:
                    yield f"data: {json.dumps({'event': 'info_found', 'type': 'headline', 'label': 'Headline', 'value': headline})}\n\n"
                    await asyncio.sleep(0.2)

                # Stream audience tags one by one
                audience_tags = ad_set_data.get("audience_tags", [])[:8]
                if audience_tags:
                    yield f"data: {json.dumps({'event': 'progress', 'stage': 'targeting', 'message': 'Setting up audience targeting...', 'percentage': 80})}\n\n"
                    for tag in audience_tags:
                        yield f"data: {json.dumps({'event': 'info_found', 'type': 'audience_tag', 'label': 'Target', 'value': tag})}\n\n"
                        await asyncio.sleep(0.1)

                # Stream hashtags
                hashtags = ad_set_data.get("hashtags", [])[:5]
                if hashtags:
                    for hashtag in hashtags:
                        yield f"data: {json.dumps({'event': 'info_found', 'type': 'hashtag', 'label': 'Hashtag', 'value': f'#{hashtag}'})}\n\n"
                        await asyncio.sleep(0.1)

                # Send complete ad_set event for the preview card
                ad_set_complete = {
                    'event': 'ad_set',
                    'name': ad_set_name,
                    'title': ad_set_data.get("title", ""),
                    'audience_tags': audience_tags,
                    'hashtags': hashtags,
                    'headline': headline,
                    'primary_text': ad_set_data.get("primary_text", "")[:200] if ad_set_data.get("primary_text") else "",
                }
                yield f"data: {json.dumps(ad_set_complete)}\n\n"
                await asyncio.sleep(0.1)

            # Stage 6: Market Research (competitors, keywords, trends) — runs in parallel
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'research', 'message': 'Researching competitors & keywords...', 'percentage': 85})}\n\n"
            await asyncio.sleep(0.1)

            try:
                from modules.agents.market_research_agent import MarketResearchAgent
                from urllib.parse import urlparse

                research_agent = MarketResearchAgent()
                parsed_url = urlparse(url)
                research_domain = parsed_url.netloc.replace("www.", "")

                # Detect country from TLD
                tld_country_map = {
                    "zw": "ZW", "za": "ZA", "bw": "BW", "zm": "ZM",
                    "mz": "MZ", "na": "NA", "ke": "KE", "ng": "NG",
                    "gh": "GH", "tz": "TZ", "ug": "UG", "uk": "GB",
                    "au": "AU", "ca": "CA", "de": "DE", "fr": "FR", "in": "IN"
                }
                country_name_map = {
                    "ZW": "Zimbabwe", "ZA": "South Africa", "BW": "Botswana", "ZM": "Zambia",
                    "MZ": "Mozambique", "NA": "Namibia", "KE": "Kenya", "NG": "Nigeria",
                    "GH": "Ghana", "TZ": "Tanzania", "UG": "Uganda", "GB": "United Kingdom",
                    "AU": "Australia", "CA": "Canada", "DE": "Germany", "FR": "France",
                    "IN": "India", "US": "United States"
                }
                last_tld = research_domain.split(".")[-1].lower()
                country_code = tld_country_map.get(last_tld, "US")
                location = country_name_map.get(country_code, "")

                # Use AI-extracted business info for research queries
                business_type = ad_content.get("business_type", "")
                business_name = ad_content.get("business_name", "")
                products = ad_content.get("products_services", [])[:5]

                # Run competitors, keywords, and trends in parallel
                from datetime import datetime as dt
                current_year = str(dt.now().year)

                # Build keyword seeds from products/services
                def _build_seeds(prods, loc_suffix):
                    seeds = []
                    seen = set()
                    for name in prods[:6]:
                        if not name:
                            continue
                        seed = f"{name}{loc_suffix}"
                        if seed.lower() not in seen:
                            seen.add(seed.lower())
                            seeds.append(seed)
                    return seeds

                loc_suffix = f" {location}" if location else ""
                keyword_seeds = _build_seeds(products, loc_suffix)
                if business_name:
                    keyword_seeds.append(f"{business_name}{loc_suffix}")
                if not keyword_seeds:
                    keyword_seeds = [f"{business_type}{loc_suffix}"]

                competitors, keywords, trends = await asyncio.gather(
                    asyncio.to_thread(
                        research_agent._search_competitors_enhanced,
                        business_type, location, products,
                        research_domain, country_code, business_name
                    ),
                    asyncio.to_thread(
                        research_agent._search_keywords_autocomplete,
                        keyword_seeds[:8], country_code
                    ),
                    asyncio.to_thread(
                        research_agent._search_industry_trends,
                        business_type, current_year
                    ),
                )

                # Stream competitors
                clean_competitors = [
                    c for c in competitors
                    if not c.get("name", "").startswith("__") and c.get("name")
                ]
                for comp in clean_competitors[:12]:
                    yield f"data: {json.dumps({'event': 'competitor', 'name': comp.get('name', ''), 'url': comp.get('url', ''), 'description': (comp.get('description', '') or '')[:200], 'rating': comp.get('rating'), 'reviews': comp.get('reviews'), 'source': comp.get('source', '')})}\n\n"
                    await asyncio.sleep(0.05)

                # Stream keywords
                for kw in keywords[:20]:
                    yield f"data: {json.dumps({'event': 'keyword', 'keyword': kw.get('keyword', ''), 'source': kw.get('source', 'google_autocomplete')})}\n\n"
                    await asyncio.sleep(0.03)

                # Stream trends
                for trend in trends[:5]:
                    yield f"data: {json.dumps({'event': 'trend', 'title': trend.get('title', ''), 'source': trend.get('source', ''), 'insight': (trend.get('insight', '') or '')[:200]})}\n\n"
                    await asyncio.sleep(0.05)

                # Send summary
                yield f"data: {json.dumps({'event': 'market_research_summary', 'competitors_found': len(clean_competitors), 'keywords_found': len(keywords), 'trends_found': len(trends)})}\n\n"
                await asyncio.sleep(0.1)

                logger.info(f"Market research complete: {len(clean_competitors)} competitors, {len(keywords)} keywords, {len(trends)} trends")

            except Exception as research_err:
                logger.warning(f"Market research failed (non-fatal): {research_err}")
                yield f"data: {json.dumps({'event': 'progress', 'stage': 'research', 'message': 'Market research skipped', 'percentage': 88})}\n\n"

            # Stage 7: Save campaign
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'saving', 'message': 'Saving campaign...', 'percentage': 92})}\n\n"
            await asyncio.sleep(0.1)

            campaign, error = service.scrape_url_for_campaign(
                url=url,
                store_id=store_id,
                campaign_name=campaign_name
            )

            if error and not campaign:
                yield f"data: {json.dumps({'event': 'error', 'message': error})}\n\n"
                return

            # Complete
            yield f"data: {json.dumps({'event': 'progress', 'stage': 'complete', 'message': 'Campaign created successfully!', 'percentage': 100})}\n\n"
            await asyncio.sleep(0.1)

            yield f"data: {json.dumps({'event': 'complete', 'campaign_id': str(campaign.id), 'status': campaign.status.value})}\n\n"

        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
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


@campaign_router.post("/{campaign_id}/publish-to-meta-ads")
def publish_campaign_to_meta_ads(
    campaign_id: uuid.UUID,
    ad_account_id: uuid.UUID = Query(..., description="Meta Ad Account ID to publish to"),
    page_id: Optional[uuid.UUID] = Query(None, description="Facebook Page ID to use for ads (optional, will use first available if not provided)"),
    db: Session = Depends(get_db)
):
    """
    Publish campaign to Meta Ads Manager as paid advertising.

    This endpoint creates actual paid ad campaigns in Meta Ads Manager:
    1. Creates a Meta Campaign
    2. Creates Meta Ad Sets for each selected ad set
    3. Creates Meta Ads with the ad content

    Args:
        campaign_id: UUID of the URL campaign to publish
        ad_account_id: UUID of the Meta Ad Account to use
        page_id: Optional UUID of the Facebook Page (will use first available if not provided)

    Returns:
        Dictionary with success status, created IDs, and any errors
    """
    if not META_ADS_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta Ads integration is not available"
        )

    # Get the URL campaign with ad sets and content
    from sqlalchemy.orm import joinedload
    campaign = db.query(Campaign).options(
        joinedload(Campaign.ad_sets).joinedload(AdSet.ad_contents)
    ).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get the Meta Ad Account
    ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == ad_account_id).first()
    if not ad_account:
        raise HTTPException(status_code=404, detail="Meta Ad Account not found")

    if not ad_account.is_connected:
        raise HTTPException(
            status_code=400,
            detail="Meta Ad Account is not connected"
        )

    # Get Facebook Page ID for creating ads
    facebook_page_id = None
    if page_id:
        fb_page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
        if fb_page:
            facebook_page_id = fb_page.page_id

    # If no page_id provided or found, try to get from ad_account.business_id or first available page
    if not facebook_page_id:
        if ad_account.business_id:
            facebook_page_id = ad_account.business_id
        else:
            # Get the first connected Facebook page
            first_page = db.query(FacebookPage).filter(
                FacebookPage.is_connected == True,
                FacebookPage.is_active == True
            ).first()
            if first_page:
                facebook_page_id = first_page.page_id

    if not facebook_page_id:
        raise HTTPException(
            status_code=400,
            detail="No Facebook Page found. Please connect a Facebook Page first."
        )

    # Get selected ad sets
    selected_ad_sets = [ad_set for ad_set in campaign.ad_sets if ad_set.is_selected]
    if not selected_ad_sets:
        raise HTTPException(
            status_code=400,
            detail="No ad sets selected for publishing"
        )

    results = {
        "success": False,
        "campaign_id": str(campaign_id),
        "meta_campaign_id": None,
        "meta_ad_sets": [],
        "meta_ads": [],
        "errors": []
    }

    try:
        # Map URL campaign goal to Meta objective
        goal_to_objective = {
            "sales": "OUTCOME_SALES",
            "leads": "OUTCOME_LEADS",
            "traffic": "OUTCOME_TRAFFIC",
            "awareness": "OUTCOME_AWARENESS",
            "engagement": "OUTCOME_ENGAGEMENT"
        }
        objective = goal_to_objective.get(campaign.goal.value if hasattr(campaign.goal, 'value') else campaign.goal, "OUTCOME_TRAFFIC")

        # 1. Create Meta Campaign
        meta_campaign_data = {
            "name": campaign.name,
            "objective": objective,
            "status": "PAUSED",  # Start as paused, user can activate later
            "buying_type": "AUCTION",
            "special_ad_categories": '["NONE"]'
        }

        # Add budget if set
        if campaign.daily_budget:
            meta_campaign_data["daily_budget"] = str(int(campaign.daily_budget * 100))  # Convert to cents

        # Add schedule if set
        if campaign.start_date:
            meta_campaign_data["start_time"] = str(int(campaign.start_date.timestamp()))
        if campaign.end_date:
            meta_campaign_data["stop_time"] = str(int(campaign.end_date.timestamp()))

        logger.info(f"[Meta Ads] Creating campaign: {meta_campaign_data}")
        meta_campaign_result = create_meta_campaign(
            ad_account.ad_account_id,
            ad_account.access_token,
            meta_campaign_data
        )

        meta_campaign_id = meta_campaign_result.get("id")
        results["meta_campaign_id"] = meta_campaign_id

        # Save Meta Campaign to database
        db_meta_campaign = MetaCampaign(
            campaign_id=meta_campaign_id,
            ad_account_id=ad_account.id,
            name=campaign.name,
            objective=objective,
            status="PAUSED",
            special_ad_categories=["NONE"],
            buying_type="AUCTION",
            daily_budget=int(campaign.daily_budget * 100) if campaign.daily_budget else None,
            start_time=campaign.start_date,
            stop_time=campaign.end_date,
            created_time=datetime.utcnow(),
            updated_time=datetime.utcnow(),
            effective_status="PAUSED",
            is_draft=False,
            is_active=True
        )
        db.add(db_meta_campaign)
        db.commit()
        db.refresh(db_meta_campaign)

        # Country name to ISO code mapping
        country_name_to_code = {
            "zimbabwe": "ZW", "south africa": "ZA", "united states": "US", "usa": "US",
            "united kingdom": "GB", "uk": "GB", "canada": "CA", "australia": "AU",
            "germany": "DE", "france": "FR", "india": "IN", "china": "CN", "japan": "JP",
            "brazil": "BR", "mexico": "MX", "nigeria": "NG", "kenya": "KE", "ghana": "GH",
            "botswana": "BW", "zambia": "ZM", "mozambique": "MZ", "namibia": "NA",
            "tanzania": "TZ", "uganda": "UG", "malawi": "MW", "ethiopia": "ET",
        }

        # Convert country names to codes
        def get_country_codes(countries_list):
            if not countries_list:
                return ["ZW"]  # Default to Zimbabwe
            codes = []
            for country in countries_list:
                country_lower = country.lower().strip()
                if len(country_lower) == 2:
                    # Already a code
                    codes.append(country_lower.upper())
                elif country_lower in country_name_to_code:
                    codes.append(country_name_to_code[country_lower])
                else:
                    # Try to use first 2 letters as fallback (not ideal but better than failing)
                    logger.warning(f"Unknown country: {country}, skipping")
            return codes if codes else ["ZW"]

        country_codes = get_country_codes(campaign.countries)

        # 2. Create Meta Ad Sets for each selected ad set
        for ad_set in selected_ad_sets:
            try:
                # Build targeting from campaign settings
                targeting = {
                    "geo_locations": {
                        "countries": country_codes
                    },
                    "age_min": campaign.age_range.get("min", 18) if campaign.age_range else 18,
                    "age_max": campaign.age_range.get("max", 65) if campaign.age_range else 65
                }

                # Add gender targeting if specified
                if campaign.gender and campaign.gender != "all":
                    if campaign.gender == "male":
                        targeting["genders"] = [1]
                    elif campaign.gender == "female":
                        targeting["genders"] = [2]

                meta_adset_data = {
                    "name": ad_set.name,
                    "campaign_id": meta_campaign_id,
                    "status": "PAUSED",
                    "optimization_goal": "LINK_CLICKS",
                    "billing_event": "IMPRESSIONS",
                    "targeting": json.dumps(targeting),
                    "bid_amount": "100"  # $1.00 minimum bid
                }

                # Add schedule
                if campaign.start_date:
                    meta_adset_data["start_time"] = str(int(campaign.start_date.timestamp()))
                if campaign.end_date:
                    meta_adset_data["end_time"] = str(int(campaign.end_date.timestamp()))

                logger.info(f"[Meta Ads] Creating ad set: {ad_set.name}")
                meta_adset_result = create_meta_adset(
                    ad_account.ad_account_id,
                    ad_account.access_token,
                    meta_adset_data
                )

                meta_adset_id = meta_adset_result.get("id")
                results["meta_ad_sets"].append({
                    "url_ad_set_id": str(ad_set.id),
                    "url_ad_set_name": ad_set.name,
                    "meta_adset_id": meta_adset_id
                })

                # Save Meta Ad Set to database
                db_meta_adset = MetaAdSet(
                    adset_id=meta_adset_id,
                    ad_account_id=ad_account.id,
                    campaign_id=db_meta_campaign.id,
                    name=ad_set.name,
                    status="PAUSED",
                    optimization_goal="LINK_CLICKS",
                    billing_event="IMPRESSIONS",
                    targeting=targeting,
                    bid_amount=100,
                    start_time=campaign.start_date,
                    end_time=campaign.end_date,
                    created_time=datetime.utcnow(),
                    updated_time=datetime.utcnow(),
                    effective_status="PAUSED",
                    is_active=True
                )
                db.add(db_meta_adset)
                db.commit()
                db.refresh(db_meta_adset)

                # 3. Create Meta Ads for each ad content in this ad set
                for ad_content in ad_set.ad_contents:
                    if not ad_content.is_active:
                        continue

                    try:
                        # Create ad with link creative
                        meta_ad_data = {
                            "name": f"{ad_set.name} - Ad",
                            "adset_id": meta_adset_id,
                            "status": "PAUSED",
                            "creative": json.dumps({
                                "object_story_spec": {
                                    "page_id": facebook_page_id,
                                    "link_data": {
                                        "link": ad_content.destination_url or campaign.source_url,
                                        "message": ad_content.primary_text or campaign.name,
                                        "name": ad_content.headline or campaign.name,
                                        "description": ad_content.description or "",
                                        "call_to_action": {
                                            "type": "LEARN_MORE",
                                            "value": {
                                                "link": ad_content.destination_url or campaign.source_url
                                            }
                                        }
                                    }
                                }
                            })
                        }

                        logger.info(f"[Meta Ads] Creating ad for ad set: {ad_set.name}")
                        meta_ad_result = create_meta_ad(
                            ad_account.ad_account_id,
                            ad_account.access_token,
                            meta_ad_data
                        )

                        meta_ad_id = meta_ad_result.get("id")
                        results["meta_ads"].append({
                            "url_ad_content_id": str(ad_content.id),
                            "meta_ad_id": meta_ad_id,
                            "ad_set_name": ad_set.name
                        })

                        # Save Meta Ad to database
                        db_meta_ad = MetaAd(
                            ad_id=meta_ad_id,
                            ad_account_id=ad_account.id,
                            adset_id=db_meta_adset.id,
                            campaign_id=db_meta_campaign.id,
                            name=f"{ad_set.name} - Ad",
                            status="PAUSED",
                            effective_status="PAUSED",
                            created_time=datetime.utcnow(),
                            updated_time=datetime.utcnow(),
                            is_active=True
                        )
                        db.add(db_meta_ad)

                    except Exception as ad_error:
                        results["errors"].append({
                            "type": "ad",
                            "ad_set_name": ad_set.name,
                            "error": str(ad_error)
                        })
                        logger.error(f"[Meta Ads] Failed to create ad: {ad_error}")

            except Exception as adset_error:
                results["errors"].append({
                    "type": "ad_set",
                    "ad_set_name": ad_set.name,
                    "error": str(adset_error)
                })
                logger.error(f"[Meta Ads] Failed to create ad set: {adset_error}")

        # Update URL campaign with platform IDs
        platform_ids = campaign.platform_campaign_ids or {}
        platform_ids["meta"] = meta_campaign_id
        campaign.platform_campaign_ids = platform_ids
        campaign.status = CampaignStatus.ACTIVE
        campaign.published_at = datetime.utcnow()

        db.commit()

        results["success"] = True
        results["message"] = f"Published campaign to Meta Ads. Created {len(results['meta_ad_sets'])} ad sets and {len(results['meta_ads'])} ads."

        logger.info(f"[Meta Ads] Successfully published campaign {campaign_id} to Meta Ads")

        # Create system notification for campaign publish
        if NOTIFICATIONS_AVAILABLE:
            try:
                ad_sets_count = len(results['meta_ad_sets'])
                has_errors = len(results['errors']) > 0

                notification_title = "Campaign Published to Meta Ads"
                if has_errors:
                    notification_title = "Campaign Published with Warnings"

                notification_message = f"Your campaign '{campaign.name}' has been published to Meta Ads Manager with {ad_sets_count} ad sets."
                if has_errors:
                    error_types = set([e.get('type', 'unknown') for e in results['errors']])
                    notification_message += f" Some items had issues: {', '.join(error_types)}. Check Meta Ads Manager for details."

                notification = Notification(
                    store_id=campaign.store_id,
                    title=notification_title,
                    message=notification_message,
                    type=NotificationType.SYSTEM.value,
                    priority=NotificationPriority.HIGH.value if has_errors else NotificationPriority.NORMAL.value,
                    related_entity_type="campaign",
                    related_entity_id=campaign.id,
                    action_url=f"/marketing/campaigns",
                    action_data={
                        "campaign_id": str(campaign.id),
                        "campaign_name": campaign.name,
                        "meta_campaign_id": meta_campaign_id,
                        "ad_sets_count": ad_sets_count,
                        "has_errors": has_errors
                    }
                )
                db.add(notification)
                db.commit()
                logger.info(f"[Notification] Created campaign publish notification for store {campaign.store_id}")
            except Exception as notif_error:
                logger.error(f"[Notification] Failed to create notification: {notif_error}")

    except Exception as e:
        results["errors"].append({
            "type": "campaign",
            "error": str(e)
        })
        logger.error(f"[Meta Ads] Failed to publish campaign: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to publish to Meta Ads: {str(e)}"
        )

    return results


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

    # IMPORTANT: Do NOT pass any store context for regeneration
    # The AI should determine business name, type, and everything else from SCRAPED CONTENT ONLY
    # This prevents stale store data (e.g., "SecureSights") from appearing in campaigns
    # for completely different businesses (e.g., Edgars clothing store)
    store_context = None  # AI derives everything from scraped content

    # Generate new ad content with store context
    ad_content = service._generate_ad_content(campaign.scraped_data, campaign.source_url, store_context)
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


# ============ Quick Launch ============

@campaign_router.post("/quick-launch", response_model=QuickLaunchResponse)
async def quick_launch(request: QuickLaunchRequest, db: Session = Depends(get_db)):
    """
    Quick Launch: paste a URL → scrape → generate ads → publish to Meta → start scheduler.

    End-to-end pipeline that creates a full Meta Ads campaign from just a URL:
    1. Scrape the URL and create a campaign
    2. Run the AI pipeline (research → angles → copy → visuals)
    3. Publish to Meta Ads Manager
    4. Register with the scheduler for 24/7 optimization

    Returns:
        QuickLaunchResponse with campaign details and publish results
    """
    if not META_ADS_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta Ads integration is not available"
        )

    errors = []
    response_data = {
        "success": False,
        "campaign_id": None,
        "campaign_name": "",
        "meta_campaign_id": None,
        "ad_sets_created": 0,
        "ads_created": 0,
        "scheduler_registered": False,
        "pipeline_results": None,
        "publish_results": None,
        "errors": [],
        "message": ""
    }

    try:
        # Step 1: Scrape URL and create campaign
        logger.info(f"[QuickLaunch] Step 1: Scraping URL: {request.url}")
        service = CampaignService(db)
        campaign = service.scrape_url_for_campaign(
            url=request.url,
            store_id=request.store_id,
            campaign_name=request.campaign_name
        )

        # Set campaign settings from request
        campaign.daily_budget = request.daily_budget
        campaign.countries = request.countries
        campaign.age_range = request.age_range
        campaign.gender = request.gender
        campaign.goal = request.goal
        db.commit()

        response_data["campaign_id"] = campaign.id
        response_data["campaign_name"] = campaign.name

        # Step 2: Generate ad content
        logger.info(f"[QuickLaunch] Step 2: Generating ad content for '{campaign.name}'")
        store_context = None
        try:
            from modules.stores.models import Store
            store = db.query(Store).filter(Store.id == request.store_id).first()
            if store:
                store_context = {
                    "store_name": store.name,
                    "store_description": store.description,
                    "store_category": getattr(store, 'category', None),
                }
        except Exception:
            pass

        ad_content = service._generate_ad_content(campaign.scraped_data, campaign.source_url, store_context)
        if ad_content:
            campaign.generated_headlines = ad_content.get("headlines", [])
            campaign.generated_descriptions = ad_content.get("descriptions", [])
            service._create_ad_sets(campaign, ad_content)
            db.commit()
            db.refresh(campaign)

        # Ensure all ad sets are selected
        for ad_set in campaign.ad_sets:
            ad_set.is_selected = True
        db.commit()

        response_data["ad_sets_created"] = len(campaign.ad_sets)

        # Step 3: Publish to Meta Ads
        logger.info(f"[QuickLaunch] Step 3: Publishing to Meta Ads")
        ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == request.ad_account_id).first()
        if not ad_account:
            raise HTTPException(status_code=404, detail="Meta Ad Account not found")

        if not ad_account.is_connected:
            raise HTTPException(status_code=400, detail="Meta Ad Account is not connected")

        # Get Facebook Page — prefer top-performing page if available
        facebook_page_id = None
        if request.page_id:
            fb_page = db.query(FacebookPage).filter(FacebookPage.id == request.page_id).first()
            if fb_page:
                facebook_page_id = fb_page.page_id

        if not facebook_page_id:
            # Try to find the best-performing page based on historical ad insights
            try:
                from sqlalchemy import func, desc
                connected_pages = db.query(FacebookPage).filter(
                    FacebookPage.is_connected == True,
                    FacebookPage.is_active == True
                ).all()

                if connected_pages and len(connected_pages) > 1:
                    # Check which page has best CTR from past campaigns
                    # We look at MetaAdInsight aggregated by page (via ad → campaign → account → page)
                    best_page = None
                    best_score = -1

                    for page in connected_pages:
                        # Find campaigns that used this page's business account
                        page_campaigns = db.query(MetaCampaign).filter(
                            MetaCampaign.ad_account_id == ad_account.id,
                            MetaCampaign.is_active == True
                        ).all()

                        if not page_campaigns:
                            continue

                        campaign_ids = [c.id for c in page_campaigns]

                        # Get aggregated performance for ads under these campaigns
                        from modules.marketing.models import MetaAdInsight
                        perf = db.query(
                            func.sum(MetaAdInsight.clicks).label("total_clicks"),
                            func.sum(MetaAdInsight.impressions).label("total_impressions"),
                            func.sum(MetaAdInsight.conversions).label("total_conversions"),
                            func.avg(MetaAdInsight.ctr).label("avg_ctr")
                        ).join(
                            MetaAd, MetaAd.id == MetaAdInsight.ad_id
                        ).filter(
                            MetaAd.campaign_id.in_(campaign_ids)
                        ).first()

                        if perf and perf.total_impressions and perf.total_impressions > 0:
                            # Score: weighted combination of CTR and conversion rate
                            ctr = float(perf.avg_ctr or 0)
                            conv_rate = (float(perf.total_conversions or 0) / float(perf.total_impressions)) * 100
                            score = (ctr * 0.6) + (conv_rate * 0.4)

                            if score > best_score:
                                best_score = score
                                best_page = page
                                logger.info(
                                    f"[QuickLaunch] Page '{page.page_name}' score: {score:.4f} "
                                    f"(CTR={ctr:.2f}%, conv_rate={conv_rate:.4f}%)"
                                )

                    if best_page:
                        facebook_page_id = best_page.page_id
                        logger.info(f"[QuickLaunch] Selected top-performing page: {best_page.page_name} (score={best_score:.4f})")
                elif connected_pages:
                    facebook_page_id = connected_pages[0].page_id
            except Exception as page_err:
                logger.warning(f"[QuickLaunch] Top-performer page selection error: {page_err}")

        # Fallback: use business_id or first connected page
        if not facebook_page_id:
            if ad_account.business_id:
                facebook_page_id = ad_account.business_id
            else:
                first_page = db.query(FacebookPage).filter(
                    FacebookPage.is_connected == True,
                    FacebookPage.is_active == True
                ).first()
                if first_page:
                    facebook_page_id = first_page.page_id

        if not facebook_page_id:
            raise HTTPException(status_code=400, detail="No Facebook Page found. Connect a Facebook Page first.")

        # Country code mapping
        country_name_to_code = {
            "zimbabwe": "ZW", "south africa": "ZA", "united states": "US", "usa": "US",
            "united kingdom": "GB", "uk": "GB", "canada": "CA", "australia": "AU",
            "germany": "DE", "france": "FR", "india": "IN", "nigeria": "NG", "kenya": "KE",
            "ghana": "GH", "botswana": "BW", "zambia": "ZM", "mozambique": "MZ",
            "namibia": "NA", "tanzania": "TZ", "uganda": "UG",
        }

        def get_country_codes(countries_list):
            if not countries_list:
                return ["ZW"]
            codes = []
            for country in countries_list:
                cl = country.lower().strip()
                if len(cl) == 2:
                    codes.append(cl.upper())
                elif cl in country_name_to_code:
                    codes.append(country_name_to_code[cl])
            return codes if codes else ["ZW"]

        country_codes = get_country_codes(campaign.countries)

        # Map goal to Meta objective
        goal_to_objective = {
            "sales": "OUTCOME_SALES", "leads": "OUTCOME_LEADS", "traffic": "OUTCOME_TRAFFIC",
            "awareness": "OUTCOME_AWARENESS", "engagement": "OUTCOME_ENGAGEMENT"
        }
        objective = goal_to_objective.get(
            campaign.goal.value if hasattr(campaign.goal, 'value') else campaign.goal,
            "OUTCOME_TRAFFIC"
        )

        # Determine budget type and dayparting schedule
        use_lifetime = getattr(request, 'budget_type', 'daily') == 'lifetime'
        campaign_duration_days = getattr(request, 'campaign_duration_days', 30)
        dayparting_schedule = []
        dayparting_reasoning = ""

        if use_lifetime and campaign.daily_budget:
            try:
                from modules.marketing.dayparting_service import (
                    get_schedule_for_industry,
                    daily_budget_to_lifetime,
                    generate_schedule_with_ai,
                )
                # Extract industry/business_type from generated content
                ad_content_data = campaign.scraped_data or {}
                business_type = ""
                industry = ""

                # Try to get business type from generated ad content
                if campaign.ad_sets:
                    for aset in campaign.ad_sets:
                        if hasattr(aset, 'audience_description') and aset.audience_description:
                            business_type = aset.audience_description[:100]
                            break

                # Try scraped data for industry
                if isinstance(ad_content_data, dict):
                    content_text = str(ad_content_data.get("content", ""))[:500].lower()
                    industry = ad_content_data.get("industry", "")
                    if not industry:
                        # Infer from content
                        for keyword in ["restaurant", "ecommerce", "technology", "fashion",
                                       "health", "education", "real estate", "services",
                                       "fitness", "food", "retail", "software"]:
                            if keyword in content_text:
                                industry = keyword
                                break

                dayparting_schedule = get_schedule_for_industry(industry, business_type)
                dayparting_reasoning = f"Auto-scheduled for {industry or 'general'} business"
                logger.info(f"[QuickLaunch] Dayparting: {len(dayparting_schedule)} schedule blocks for industry='{industry}'")
            except Exception as dp_err:
                logger.warning(f"[QuickLaunch] Dayparting setup error: {dp_err}, continuing without schedule")
                dayparting_schedule = []

        # Create Meta Campaign
        meta_campaign_data = {
            "name": campaign.name,
            "objective": objective,
            "status": "PAUSED",
            "buying_type": "AUCTION",
            "special_ad_categories": '["NONE"]'
        }

        if use_lifetime and campaign.daily_budget:
            from modules.marketing.dayparting_service import daily_budget_to_lifetime
            lifetime_cents = daily_budget_to_lifetime(campaign.daily_budget, campaign_duration_days)
            meta_campaign_data["lifetime_budget"] = str(lifetime_cents)
            response_data["budget_type"] = "lifetime"
            response_data["dayparting_enabled"] = bool(dayparting_schedule)
            response_data["dayparting_schedule"] = dayparting_schedule if dayparting_schedule else None
            response_data["dayparting_reasoning"] = dayparting_reasoning
        elif campaign.daily_budget:
            meta_campaign_data["daily_budget"] = str(int(campaign.daily_budget * 100))
            response_data["budget_type"] = "daily"

        meta_campaign_result = create_meta_campaign(
            ad_account.ad_account_id, ad_account.access_token, meta_campaign_data
        )
        meta_campaign_id = meta_campaign_result.get("id")
        response_data["meta_campaign_id"] = meta_campaign_id

        # Save Meta Campaign to DB
        db_budget = None
        if use_lifetime and campaign.daily_budget:
            from modules.marketing.dayparting_service import daily_budget_to_lifetime
            db_budget = daily_budget_to_lifetime(campaign.daily_budget, campaign_duration_days)
        elif campaign.daily_budget:
            db_budget = int(campaign.daily_budget * 100)

        db_meta_campaign = MetaCampaign(
            campaign_id=meta_campaign_id,
            ad_account_id=ad_account.id,
            name=campaign.name,
            objective=objective,
            status="PAUSED",
            special_ad_categories=["NONE"],
            buying_type="AUCTION",
            daily_budget=db_budget,
            created_time=datetime.utcnow(),
            updated_time=datetime.utcnow(),
            effective_status="PAUSED",
            is_draft=False,
            is_active=True
        )
        db.add(db_meta_campaign)
        db.commit()
        db.refresh(db_meta_campaign)

        # Create Ad Sets and Ads
        ads_created = 0
        selected_ad_sets = [ad_set for ad_set in campaign.ad_sets if ad_set.is_selected]

        for ad_set in selected_ad_sets:
            try:
                targeting = {
                    "geo_locations": {"countries": country_codes},
                    "age_min": campaign.age_range.get("min", 18) if campaign.age_range else 18,
                    "age_max": campaign.age_range.get("max", 65) if campaign.age_range else 65
                }
                if campaign.gender and campaign.gender != "all":
                    targeting["genders"] = [1] if campaign.gender == "male" else [2]

                meta_adset_data = {
                    "name": ad_set.name,
                    "campaign_id": meta_campaign_id,
                    "status": "PAUSED",
                    "optimization_goal": "LINK_CLICKS",
                    "billing_event": "IMPRESSIONS",
                    "targeting": json.dumps(targeting),
                    "bid_amount": "100"
                }

                # Apply dayparting schedule for lifetime budget campaigns
                if use_lifetime and campaign.daily_budget:
                    from modules.marketing.dayparting_service import (
                        build_adset_schedule_params, daily_budget_to_lifetime
                    )
                    lifetime_cents = daily_budget_to_lifetime(
                        campaign.daily_budget, campaign_duration_days
                    )
                    schedule_params = build_adset_schedule_params(
                        schedule=dayparting_schedule,
                        lifetime_budget_cents=lifetime_cents,
                        campaign_duration_days=campaign_duration_days
                    )
                    # Remove daily budget params, add lifetime + schedule
                    meta_adset_data.pop("bid_amount", None)
                    meta_adset_data.update(schedule_params)
                    logger.info(
                        f"[QuickLaunch] Ad set '{ad_set.name}': lifetime budget "
                        f"${campaign.daily_budget * campaign_duration_days:.2f}, "
                        f"{len(dayparting_schedule)} schedule blocks"
                    )

                meta_adset_result = create_meta_adset(
                    ad_account.ad_account_id, ad_account.access_token, meta_adset_data
                )
                meta_adset_id = meta_adset_result.get("id")

                # Save Ad Set to DB
                db_meta_adset = MetaAdSet(
                    adset_id=meta_adset_id,
                    ad_account_id=ad_account.id,
                    campaign_id=db_meta_campaign.id,
                    name=ad_set.name,
                    status="PAUSED",
                    optimization_goal="LINK_CLICKS",
                    billing_event="IMPRESSIONS",
                    targeting=targeting,
                    bid_amount=100,
                    created_time=datetime.utcnow(),
                    updated_time=datetime.utcnow(),
                    effective_status="PAUSED",
                    is_active=True
                )
                db.add(db_meta_adset)
                db.commit()
                db.refresh(db_meta_adset)

                # Create Ads for each content
                for ad_content_item in ad_set.ad_contents:
                    if not ad_content_item.is_active:
                        continue
                    try:
                        meta_ad_data = {
                            "name": f"{ad_set.name} - Ad",
                            "adset_id": meta_adset_id,
                            "status": "PAUSED",
                            "creative": json.dumps({
                                "object_story_spec": {
                                    "page_id": facebook_page_id,
                                    "link_data": {
                                        "link": ad_content_item.destination_url or campaign.source_url,
                                        "message": ad_content_item.primary_text or campaign.name,
                                        "name": ad_content_item.headline or campaign.name,
                                        "description": ad_content_item.description or "",
                                        "call_to_action": {
                                            "type": "LEARN_MORE",
                                            "value": {"link": ad_content_item.destination_url or campaign.source_url}
                                        }
                                    }
                                }
                            })
                        }

                        meta_ad_result = create_meta_ad(
                            ad_account.ad_account_id, ad_account.access_token, meta_ad_data
                        )
                        meta_ad_id = meta_ad_result.get("id")

                        db_meta_ad = MetaAd(
                            ad_id=meta_ad_id,
                            ad_account_id=ad_account.id,
                            adset_id=db_meta_adset.id,
                            campaign_id=db_meta_campaign.id,
                            name=f"{ad_set.name} - Ad",
                            status="PAUSED",
                            effective_status="PAUSED",
                            created_time=datetime.utcnow(),
                            updated_time=datetime.utcnow(),
                            is_active=True
                        )
                        db.add(db_meta_ad)
                        ads_created += 1

                    except Exception as ad_err:
                        errors.append(f"Ad creation failed for {ad_set.name}: {str(ad_err)}")

            except Exception as adset_err:
                errors.append(f"Ad set creation failed for {ad_set.name}: {str(adset_err)}")

        # Update campaign status
        platform_ids = campaign.platform_campaign_ids or {}
        platform_ids["meta"] = meta_campaign_id
        campaign.platform_campaign_ids = platform_ids
        campaign.status = CampaignStatus.ACTIVE
        campaign.published_at = datetime.utcnow()
        db.commit()

        response_data["ads_created"] = ads_created

        # Step 4: Register with scheduler
        if request.auto_start_scheduler:
            try:
                from modules.agents.scheduler import add_ad_account_to_scheduler, start_rules_scheduler, rules_scheduler
                add_ad_account_to_scheduler(ad_account.ad_account_id)
                if not rules_scheduler._running:
                    start_rules_scheduler(interval_minutes=15)
                response_data["scheduler_registered"] = True
                logger.info(f"[QuickLaunch] Registered {ad_account.ad_account_id} with scheduler")
            except Exception as sched_err:
                errors.append(f"Scheduler registration failed: {str(sched_err)}")

        # Create notification
        if NOTIFICATIONS_AVAILABLE:
            try:
                notification = Notification(
                    store_id=campaign.store_id,
                    title="Quick Launch Campaign Published",
                    message=f"Campaign '{campaign.name}' published with {len(selected_ad_sets)} ad sets and {ads_created} ads. Scheduler {'active' if response_data['scheduler_registered'] else 'inactive'}.",
                    type=NotificationType.SYSTEM.value,
                    priority=NotificationPriority.HIGH.value,
                    related_entity_type="campaign",
                    related_entity_id=campaign.id,
                    action_url="/marketing/campaigns"
                )
                db.add(notification)
                db.commit()
            except Exception:
                pass

        response_data["success"] = True
        response_data["errors"] = errors
        response_data["message"] = (
            f"Quick Launch complete! Created {len(selected_ad_sets)} ad sets with {ads_created} ads. "
            f"Campaign is PAUSED — activate in Meta Ads Manager when ready."
        )

        logger.info(f"[QuickLaunch] Complete: {campaign.name} → {len(selected_ad_sets)} ad sets, {ads_created} ads")
        return QuickLaunchResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[QuickLaunch] Failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Quick Launch failed: {str(e)}"
        )


# ──────────────────────────────────────────────
# Optimization & Fatigue Detection Endpoints
# ──────────────────────────────────────────────

@campaign_router.post("/{campaign_id}/collect-metrics")
def collect_campaign_metrics(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Pull latest performance metrics from Meta for all ad content variants."""
    from .optimizer import CampaignOptimizer
    optimizer = CampaignOptimizer(db)
    result = optimizer.collect_metrics(campaign_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@campaign_router.post("/{campaign_id}/optimize")
def optimize_campaign(
    campaign_id: uuid.UUID,
    dry_run: bool = Query(False, description="Preview actions without executing"),
    min_impressions: int = Query(1000, description="Minimum impressions before evaluating"),
    db: Session = Depends(get_db),
):
    """
    Evaluate variant performance and auto-pause losers.

    - Collects latest metrics from Meta
    - Compares CTR across variants within each ad set
    - Pauses variants with CTR < 50% of the best performer
    - Increases budget on winning ad sets by 30%
    """
    from .optimizer import CampaignOptimizer
    optimizer = CampaignOptimizer(db)
    result = optimizer.optimize_campaign(campaign_id, min_impressions=min_impressions, dry_run=dry_run)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@campaign_router.post("/{campaign_id}/check-fatigue")
async def check_ad_fatigue(
    campaign_id: uuid.UUID,
    auto_refresh: bool = Query(False, description="Auto-generate fresh creatives for fatigued ads"),
    db: Session = Depends(get_db),
):
    """
    Check for ad fatigue and optionally auto-refresh stale creatives.

    Fatigue signals:
    - Frequency > 3.0 (audience seeing ad too often)
    - CTR declining 3+ consecutive days
    - CTR dropped > 30% from peak

    When auto_refresh=True, fatigued ads are paused and replaced with fresh copy/images.
    """
    from .fatigue_detector import FatigueDetector
    detector = FatigueDetector(db)
    result = detector.check_fatigue(campaign_id)

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # Auto-refresh if requested and fatigue detected
    if auto_refresh and result.get("fatigued_content_ids"):
        fatigued_ids = [uuid.UUID(fid) for fid in result["fatigued_content_ids"]]
        refresh_result = await detector.refresh_creatives(campaign_id, fatigued_ids)
        result["refresh_result"] = refresh_result

    return result

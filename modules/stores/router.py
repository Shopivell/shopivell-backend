# modules/stores/api.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Any, Dict, Optional, List
import uuid
from datetime import datetime

from database import get_db
from modules.users.models import User
from modules.stores.models import Store, StoreSetupStep, StoreSetupSession
from modules.stores.schemas import (
    MessageSend, ScrapeRequest, SimpleMessage, StoreCreate, StoreResponse, StoreUpdate, StoreListResponse,
    StoreSetupStepData, StoreSetupSessionResponse, StoreSetupStart
)
from modules.whatsapp.models import FAQ
from modules.agency.models import Agency
from modules.assets.models import Asset, AssetType
import re

store_router = APIRouter(prefix="/api/stores", tags=["stores"])

# Constants for setup progress
SETUP_STEPS = {
    "basic_info": 10,
    "business_type": 20,
    "goals": 30,
    "subscription": 40,
    "payment": 50,
    "create_store": 55,
    "products": 60,
    # "delivery_settings": 70,  # Skipped for now
    "payment_methods": 75,
    "features": 85,
    "whatsapp": 95,
    "completed": 100
}

# START store setup - creates session only, no store yet
@store_router.post("/setup/start", response_model=StoreSetupSessionResponse)
async def start_store_setup(
    start_data: StoreSetupStart,
    db: Session = Depends(get_db)
):
    """Start or RESTART a store setup session - overwrites existing session"""
    try:
        user_id = start_data.user_id
        
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if user already has a COMPLETED store
        existing_store = db.query(Store).filter(Store.owner_id == user_id).first()
        if existing_store and existing_store.is_setup_completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already has a completed store"
            )

        # Check for existing active session - OVERWRITE IT
        existing_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user_id,
            StoreSetupSession.is_active == True
        ).first()
        
        if existing_session:
            # RESET existing session instead of creating new one
            existing_session.session_data = {}
            existing_session.current_step = StoreSetupStep.BASIC_INFO
            existing_session.completed_steps = []
            existing_session.setup_progress = 0
            existing_session.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(existing_session)
            return existing_session
        
        # Create new setup session
        setup_session = StoreSetupSession(
            user_id=user_id,
            session_data={},
            current_step=StoreSetupStep.BASIC_INFO,
            setup_progress=0
        )
        
        db.add(setup_session)
        db.commit()
        db.refresh(setup_session)
        return setup_session
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting store setup: {str(e)}"
        )

# UPDATE setup step - still no store created
# UPDATE setup step - FIXED VERSION
@store_router.post("/setup/{session_id}/step", response_model=StoreSetupSessionResponse)
async def update_setup_step(
    session_id: uuid.UUID,
    step_data: StoreSetupStepData,
    db: Session = Depends(get_db)
):
    """Update setup step data - OVERWRITES existing step data"""
    try:
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.id == session_id,
            StoreSetupSession.is_active == True
        ).first()
        
        if not setup_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Setup session not found or inactive"
            )
        
        print(f"[UPDATE] BEFORE UPDATE - session_data: {setup_session.session_data}")
        print(f"[UPDATE] RECEIVED DATA: {step_data.data}")
        
        # FIX: Create a NEW dictionary to force SQLAlchemy to detect changes
        current_data = setup_session.session_data or {}
        new_session_data = current_data.copy()
        
        # Update with new data
        for key, value in step_data.data.items():
            new_session_data[key] = value
        
        # FIX: Force assignment to trigger SQLAlchemy change detection
        setup_session.session_data = new_session_data
        
        # Update current step
        setup_session.current_step = step_data.step
        
        # Track completed steps
        step_value = step_data.step.value
        current_completed = setup_session.completed_steps or []
        if step_value not in current_completed:
            new_completed = current_completed + [step_value]
            setup_session.completed_steps = new_completed
        
        # Remove duplicates
        setup_session.completed_steps = list(dict.fromkeys(setup_session.completed_steps))
        
        # Calculate progress
        total_steps = len(SETUP_STEPS) - 1
        completed_count = len(setup_session.completed_steps)
        setup_session.setup_progress = min(95, int((completed_count / total_steps) * 100))
        
        # Force update timestamp
        setup_session.updated_at = datetime.utcnow()
        
        print(f"[UPDATE] AFTER UPDATE - session_data: {setup_session.session_data}")
        print(f"[UPDATE] Completed steps: {setup_session.completed_steps}")
        print(f"[UPDATE] Progress: {setup_session.setup_progress}%")
        
        # FIX: Use explicit commit and refresh
        db.commit()
        db.refresh(setup_session)
        
        print(f"[SUCCESS] AFTER COMMIT - session_data: {setup_session.session_data}")
        return setup_session
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error updating setup step: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating setup step: {str(e)}"
        )
    
# COMPLETE setup - NOW create the actual store
@store_router.post("/setup/{session_id}/complete", response_model=StoreResponse)
async def complete_store_setup(
    session_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Complete store setup and CREATE the actual store"""
    try:
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.id == session_id,
            StoreSetupSession.is_active == True
        ).first()
        
        if not setup_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Setup session not found or inactive"
            )
        
        # Verify user exists and doesn't already have a store
        user = db.query(User).filter(User.id == setup_session.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Note: Users can have multiple stores - no single-store constraint

        # Validate required data
        session_data = setup_session.session_data
        required_fields = ['store_name', 'store_phone']
        for field in required_fields:
            if field not in session_data or not session_data[field]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required field: {field}"
                )

        # Get or create agency for the user
        agency = db.query(Agency).filter(Agency.owner_id == user.id).first()

        if not agency:
            # Create a new agency for the user based on store info
            store_name = session_data['store_name']
            # Create a URL-friendly slug from store name
            slug_base = re.sub(r'[^a-z0-9]+', '-', store_name.lower()).strip('-')
            slug = slug_base[:50]  # Limit length

            # Ensure slug is unique
            slug_counter = 1
            original_slug = slug
            while db.query(Agency).filter(Agency.slug == slug).first():
                slug = f"{original_slug}-{slug_counter}"
                slug_counter += 1

            agency = Agency(
                owner_id=user.id,
                name=store_name,  # Use store name as agency name
                slug=slug,
                email=user.email,
                phone=session_data.get('store_phone'),
                description=f"Agency for {store_name}"
            )
            db.add(agency)
            db.flush()  # Get the agency ID
            print(f"[Agency] Created agency {agency.id} ({agency.name}) for user {user.id}")
        else:
            print(f"[Agency] Using existing agency {agency.id} ({agency.name}) for user {user.id}")

        # CREATE the actual store with all collected data
        store_data = {
            'owner_id': user.id,
            'agency_id': agency.id,  # Link store to agency
            'store_name': session_data['store_name'],
            'store_phone': session_data['store_phone'],
            'store_email': session_data.get('store_email'),  # ADDED
            'store_link': session_data.get('store_link'),
            'color_theme': session_data.get('color_theme'),
            'logo_url': session_data.get('logo_url'),  # ADDED
            'screenshot_url': session_data.get('screenshot_url'),  # Homepage screenshot for campaigns
            'business_type': session_data.get('business_type'),
            'store_voice': session_data.get('store_voice'),  # ADDED
            'store_tone': session_data.get('store_tone'),  # ADDED
            'products_or_services': session_data.get('products_or_services', []),  # ADDED
            'delivery_enabled': session_data.get('delivery_enabled', True),
            'pickup_enabled': session_data.get('pickup_enabled', False),
            'dine_in_enabled': session_data.get('dine_in_enabled', False),
            'delivery_fee': session_data.get('delivery_fee', '0'),
            'free_delivery_minimum': session_data.get('free_delivery_minimum', False),
            'domain': session_data.get('domain'),
            'enabled_features': session_data.get('enabled_features', {}),
            'business_goals': session_data.get('business_goals', []),
            'payment_methods': session_data.get('payment_methods', {}),
            'current_step': StoreSetupStep.COMPLETED,
            'is_setup_completed': True
        }
        
        # Create the store
        db_store = Store(**store_data)
        db.add(db_store)
        db.flush()  # Get the store ID without committing

        # Create FAQs from scraped data if available
        scraped_faqs = session_data.get('scraped_faqs', [])
        if scraped_faqs:
            print(f"[FAQ] Creating {len(scraped_faqs)} FAQs for store {db_store.id}")
            for i, faq_data in enumerate(scraped_faqs):
                try:
                    faq = FAQ(
                        store_id=db_store.id,
                        question=faq_data.get('question', ''),
                        answer=faq_data.get('answer', ''),
                        category=faq_data.get('category', 'general'),
                        display_order=i,
                        is_active=True,
                        is_featured=i < 5  # Feature first 5 FAQs
                    )
                    db.add(faq)
                except Exception as faq_err:
                    print(f"[FAQ] Error creating FAQ {i}: {faq_err}")
                    # Continue with other FAQs if one fails

        # Create Assets from scraped images
        extracted_images = session_data.get('extracted_images', [])
        if extracted_images:
            print(f"[Assets] Creating {len(extracted_images)} assets for store {db_store.id}")
            for i, img_data in enumerate(extracted_images):
                try:
                    img_url = img_data.get('url') if isinstance(img_data, dict) else img_data
                    img_alt = img_data.get('alt', '') if isinstance(img_data, dict) else ''
                    is_logo = img_data.get('is_logo', False) if isinstance(img_data, dict) else False

                    # Generate a name for the asset
                    if is_logo:
                        asset_name = f"{db_store.store_name} Logo"
                    elif img_alt:
                        asset_name = img_alt[:255]  # Limit to 255 chars
                    else:
                        asset_name = f"Scraped Image {i + 1}"

                    asset = Asset(
                        store_id=db_store.id,
                        name=asset_name,
                        cloudinary_url=img_url,
                        cloudinary_secure_url=img_url if img_url.startswith('https') else None,
                        file_type=AssetType.IMAGE,
                        source="scraped",
                        is_active=True,
                        is_generated=False,
                        tags=["scraped", "logo" if is_logo else "website-image"],
                        description=f"Image scraped from {session_data.get('store_link', 'website')}"
                    )
                    db.add(asset)
                except Exception as asset_err:
                    print(f"[Assets] Error creating asset {i}: {asset_err}")
                    # Continue with other assets if one fails
            print(f"[Assets] Successfully queued {len(extracted_images)} assets for creation")

        # Deactivate the setup session
        setup_session.is_active = False
        setup_session.setup_progress = 100

        db.commit()
        db.refresh(db_store)

        print(f"[Store] Created store {db_store.id} with {len(scraped_faqs)} FAQs and {len(extracted_images)} assets")
        return db_store

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error completing store setup: {str(e)}"
        )

# CANCEL setup - no store created, session deactivated
@store_router.post("/setup/{session_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_store_setup(
    session_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Cancel store setup - NO store is created"""
    try:
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.id == session_id,
            StoreSetupSession.is_active == True
        ).first()
        
        if not setup_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Setup session not found or already inactive"
            )
        
        # Simply deactivate the session - NO store is created
        setup_session.is_active = False
        db.commit()
        
        return {"message": "Store setup cancelled successfully - no store was created"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cancelling store setup: {str(e)}"
        )

# GET active setup session
@store_router.get("/setup/session/{session_id}", response_model=StoreSetupSessionResponse)
async def get_setup_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get active setup session data"""
    try:
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.id == session_id,
            StoreSetupSession.is_active == True
        ).first()
        
        if not setup_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Setup session not found or inactive"
            )
        
        return setup_session
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching setup session: {str(e)}"
        )

# GET or CREATE setup session
@store_router.post("/setup/get-or-create", response_model=StoreSetupSessionResponse)
async def get_or_create_setup_session(
    start_data: StoreSetupStart,
    db: Session = Depends(get_db)
):
    """Get existing active session or create new one"""
    try:
        user_id = start_data.user_id

        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if user already has a COMPLETED store
        existing_store = db.query(Store).filter(Store.owner_id == user_id).first()
        if existing_store and existing_store.is_setup_completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already has a completed store"
            )

        # Try to get existing active session
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user_id,
            StoreSetupSession.is_active == True
        ).first()
        
        if setup_session:
            return setup_session
        else:
            # Create new session
            setup_session = StoreSetupSession(
                user_id=user_id,
                session_data={},
                current_step=StoreSetupStep.BASIC_INFO,
                setup_progress=0
            )
            db.add(setup_session)
            db.commit()
            db.refresh(setup_session)
            return setup_session
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting or creating setup session: {str(e)}"
        )

# FORCE RESTART setup
@store_router.post("/setup/force-restart", response_model=StoreSetupSessionResponse)
async def force_restart_setup(
    start_data: StoreSetupStart,
    db: Session = Depends(get_db)
):
    """Force restart store setup - deactivates all existing sessions"""
    try:
        user_id = start_data.user_id

        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if user already has a COMPLETED store
        existing_store = db.query(Store).filter(Store.owner_id == user_id).first()
        if existing_store and existing_store.is_setup_completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already has a completed store"
            )

        # Deactivate ALL existing sessions for this user
        existing_sessions = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user_id,
            StoreSetupSession.is_active == True
        ).all()
        
        for session in existing_sessions:
            session.is_active = False
        
        # Create brand new setup session
        setup_session = StoreSetupSession(
            user_id=user_id,
            session_data={},
            current_step=StoreSetupStep.BASIC_INFO,
            setup_progress=0
        )
        
        db.add(setup_session)
        db.commit()
        db.refresh(setup_session)
        return setup_session
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error force restarting store setup: {str(e)}"
        )


# ============================================
# SCRAPING ENDPOINTS - Must be before /{store_id} routes
# ============================================

@store_router.post("/scrape-website", status_code=status.HTTP_200_OK)
async def scrape_website(request: ScrapeRequest, db: Session = Depends(get_db)):
    """
    Scrape a website using Tavily and extract store information using AI Agent.
    Also extracts FAQs from the website content.

    Uses:
    - Tavily for multi-page web content extraction
    - LangChain + OpenRouter/OpenAI for AI-powered extraction
    - Extracts: store info, brand details, products/services, FAQs

    If sessionId is provided, saves scraped data to the setup session.
    """
    import os
    from modules.stores.store_scraping_agent import StoreScrapingAgent

    url = request.url.strip()

    # Ensure URL has protocol
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    # Check if Tavily API key is configured
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        print("[Scrape] WARNING: TAVILY_API_KEY not configured!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Website scraping is not available. TAVILY_API_KEY is not configured."
        )

    try:
        print(f"[Scrape] Starting scrape for: {url}")
        print(f"[Scrape] Tavily API key configured: {bool(tavily_key)}")

        # Initialize the AI scraping agent
        agent = StoreScrapingAgent()

        # Check if Tavily was initialized
        if not agent.tavily:
            print("[Scrape] ERROR: Tavily client failed to initialize")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tavily client failed to initialize. Check your API key."
            )

        print(f"[Scrape] Tavily client initialized: {agent.tavily is not None}")

        # Extract store info using Tavily + LangChain AI agent
        store_data = await agent.extract_store_info(url)

        # Check if we got actual scraped data or fallback
        pages_scraped = store_data.get('pages_scraped', 0)
        faqs_count = len(store_data.get('faqs', []))
        images_count = len(store_data.get('extracted_images', []))

        print(f"[Scrape] Successfully extracted data for: {url}")
        print(f"[Scrape] Store: {store_data.get('store_name')}")
        print(f"[Scrape] Pages scraped: {pages_scraped}")
        print(f"[Scrape] FAQs extracted: {faqs_count}")
        print(f"[Scrape] Images extracted: {images_count}")

        # Warn if fallback was used
        if pages_scraped == 0:
            print(f"[Scrape] WARNING: No pages were scraped - using fallback data")

        # If session ID provided, save to session
        if request.sessionId:
            try:
                session = db.query(StoreSetupSession).filter(
                    StoreSetupSession.id == request.sessionId
                ).first()

                if session:
                    from sqlalchemy.orm.attributes import flag_modified

                    # Update session data with scraped info
                    current_data = dict(session.session_data) if session.session_data else {}

                    # Merge scraped data into session
                    current_data["store_name"] = store_data.get("store_name") or current_data.get("store_name")
                    current_data["store_email"] = store_data.get("store_email") or current_data.get("store_email")
                    current_data["store_phone"] = store_data.get("store_phone") or current_data.get("store_phone")
                    current_data["store_voice"] = store_data.get("store_voice") or current_data.get("store_voice")
                    current_data["store_tone"] = store_data.get("store_tone") or current_data.get("store_tone")
                    current_data["store_website"] = url
                    current_data["services_products"] = store_data.get("services_products") or current_data.get("services_products")
                    current_data["color_theme"] = store_data.get("color_theme") or current_data.get("color_theme")
                    current_data["business_type"] = store_data.get("business_type") or current_data.get("business_type")
                    current_data["logo_url"] = store_data.get("logo_url") or current_data.get("logo_url")
                    current_data["screenshot_url"] = store_data.get("screenshot_url") or current_data.get("screenshot_url")
                    current_data["brand_style"] = store_data.get("brand_style") or current_data.get("brand_style")
                    current_data["store_link"] = store_data.get("store_link") or current_data.get("store_link")

                    # Save brand analysis and screenshot for campaign creation
                    current_data["brand_analysis"] = store_data.get("brand_analysis") or current_data.get("brand_analysis")
                    current_data["homepage_screenshot"] = store_data.get("homepage_screenshot") or current_data.get("homepage_screenshot")

                    # Save FAQs to session for later insertion
                    current_data["scraped_faqs"] = store_data.get("faqs", [])

                    # Save extracted images for asset creation
                    current_data["extracted_images"] = store_data.get("extracted_images", [])

                    # Assign new dict to ensure SQLAlchemy detects the change
                    session.session_data = current_data
                    flag_modified(session, "session_data")
                    db.commit()

                    print(f"[Scrape] Saved scraped data to session {request.sessionId}")
                    print(f"[Scrape] Session now has {len(current_data.get('scraped_faqs', []))} FAQs")

            except Exception as session_err:
                print(f"[Scrape] Warning: Failed to save to session: {session_err}")
                # Continue - don't fail the request if session save fails

        return store_data

    except ValueError as e:
        # API key not configured
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        print(f"[Scrape] Error scraping {url}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scrape website: {str(e)}"
        )


@store_router.get("/scrape-status", status_code=status.HTTP_200_OK)
async def check_scrape_status():
    """
    Debug endpoint to check if scraping services are properly configured.
    Returns the status of Tavily and OpenRouter/OpenAI configuration.
    """
    import os

    tavily_key = os.getenv("TAVILY_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    # Try to initialize the agent
    agent_status = "unknown"
    tavily_client_status = "unknown"
    try:
        from modules.stores.store_scraping_agent import StoreScrapingAgent, TAVILY_AVAILABLE, OPENROUTER_AVAILABLE
        agent = StoreScrapingAgent()
        agent_status = "initialized"
        tavily_client_status = "initialized" if agent.tavily else "failed"
    except Exception as e:
        agent_status = f"error: {str(e)}"

    return {
        "tavily_api_key_configured": bool(tavily_key),
        "tavily_api_key_preview": f"{tavily_key[:8]}..." if tavily_key else None,
        "tavily_module_available": TAVILY_AVAILABLE if 'TAVILY_AVAILABLE' in dir() else "unknown",
        "tavily_client_status": tavily_client_status,
        "openrouter_api_key_configured": bool(openrouter_key),
        "openai_api_key_configured": bool(openai_key),
        "openrouter_available": OPENROUTER_AVAILABLE if 'OPENROUTER_AVAILABLE' in dir() else "unknown",
        "agent_status": agent_status,
        "message": "Scraping is ready" if tavily_key and tavily_client_status == "initialized" else "Scraping is NOT configured properly"
    }


@store_router.post("/scrape-products", status_code=status.HTTP_200_OK)
async def scrape_products_from_website(
    request: ScrapeRequest,
    db: Session = Depends(get_db)
):
    """
    Scrape products/services from a website URL using AI.
    Returns a list of products with name, description, price, and category.
    """
    from modules.stores.store_scraping_agent import StoreScrapingAgent

    url = request.url
    print(f"[ScrapeProducts] Starting products scrape for: {url}")

    try:
        agent = StoreScrapingAgent()
        products_data = await agent.extract_products(url)

        print(f"[ScrapeProducts] Successfully extracted {len(products_data.get('products', []))} products from: {url}")

        return products_data

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        print(f"[ScrapeProducts] Error scraping products from {url}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scrape products: {str(e)}"
        )


# ============================================
# STORE CRUD ENDPOINTS
# ============================================

# CREATE store directly (without setup wizard)
@store_router.post("/", response_model=StoreResponse)
async def create_store(
    store_data: StoreCreate,
    db: Session = Depends(get_db)
):
    """Create a new store directly (for adding additional stores).
    Also creates FAQs if scraped_faqs is provided."""
    try:
        # Verify owner exists
        owner = db.query(User).filter(User.id == store_data.owner_id).first()
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Owner not found"
            )

        # Sanitize phone: keep only first number if comma-separated, limit to 50 chars
        phone = store_data.store_phone
        if phone:
            if ',' in phone:
                phone = phone.split(',')[0].strip()
            phone = phone[:50] if len(phone) > 50 else phone

        # Create the store
        db_store = Store(
            owner_id=store_data.owner_id,
            agency_id=store_data.agency_id,
            store_name=store_data.store_name,
            store_phone=phone,
            store_email=store_data.store_email,
            store_link=store_data.store_link,
            color_theme=store_data.color_theme,
            logo_url=store_data.logo_url,
            screenshot_url=store_data.screenshot_url,
            business_type=store_data.business_type,
            store_voice=store_data.store_voice,
            products_or_services=store_data.products_or_services or [],
            delivery_enabled=store_data.delivery_enabled,
            pickup_enabled=store_data.pickup_enabled,
            dine_in_enabled=store_data.dine_in_enabled,
            delivery_fee=store_data.delivery_fee,
            free_delivery_minimum=store_data.free_delivery_minimum,
            domain=store_data.domain,
            enabled_features=store_data.enabled_features or {},
            business_goals=store_data.business_goals or [],
            payment_methods=store_data.payment_methods or {},
            current_step=StoreSetupStep.COMPLETED,
            is_setup_completed=True
        )

        db.add(db_store)
        db.flush()  # Get the store ID without committing

        # Create FAQs from scraped data if available
        scraped_faqs = store_data.scraped_faqs or []
        if scraped_faqs:
            print(f"[FAQ] Creating {len(scraped_faqs)} FAQs for store {db_store.id}")
            for i, faq_data in enumerate(scraped_faqs):
                try:
                    faq = FAQ(
                        store_id=db_store.id,
                        question=faq_data.get('question', ''),
                        answer=faq_data.get('answer', ''),
                        category=faq_data.get('category', 'general'),
                        display_order=i,
                        is_active=True,
                        is_featured=i < 5  # Feature first 5 FAQs
                    )
                    db.add(faq)
                except Exception as faq_err:
                    print(f"[FAQ] Error creating FAQ {i}: {faq_err}")
                    # Continue with other FAQs if one fails

        # Create Assets from scraped images
        extracted_images = store_data.extracted_images or []
        if extracted_images:
            print(f"[Assets] Creating {len(extracted_images)} assets for store {db_store.id}")
            for i, img_data in enumerate(extracted_images):
                try:
                    img_url = img_data.get('url') if isinstance(img_data, dict) else img_data
                    img_alt = img_data.get('alt', '') if isinstance(img_data, dict) else ''
                    is_logo = img_data.get('is_logo', False) if isinstance(img_data, dict) else False

                    # Generate a name for the asset
                    if is_logo:
                        asset_name = f"{db_store.store_name} Logo"
                    elif img_alt:
                        asset_name = img_alt[:255]
                    else:
                        asset_name = f"Scraped Image {i + 1}"

                    asset = Asset(
                        store_id=db_store.id,
                        name=asset_name,
                        cloudinary_url=img_url,
                        cloudinary_secure_url=img_url if img_url.startswith('https') else None,
                        file_type=AssetType.IMAGE,
                        source="scraped",
                        is_active=True,
                        is_generated=False,
                        tags=["scraped", "logo" if is_logo else "website-image"],
                        description=f"Image scraped from {store_data.store_link or 'website'}"
                    )
                    db.add(asset)
                except Exception as asset_err:
                    print(f"[Assets] Error creating asset {i}: {asset_err}")

        db.commit()
        db.refresh(db_store)

        print(f"[Store] Created store {db_store.id} with {len(scraped_faqs)} FAQs and {len(extracted_images)} assets")
        return db_store

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating store: {str(e)}"
        )

# Existing store management endpoints (only work after store is created)
@store_router.get("/{store_id}", response_model=StoreResponse)
async def get_store(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get store details - only works if store exists"""
    try:
        store = db.query(Store).filter(Store.id == store_id).first()
        
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
            
        return store
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching store: {str(e)}"
        )

# GET all stores for user
@store_router.get("/owner/{owner_id}", response_model=StoreListResponse)
async def get_stores_by_owner(
    owner_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    try:
        # Verify owner exists
        owner = db.query(User).filter(User.id == owner_id).first()
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Owner not found"
            )
        
        # Get stores for owner, ordered by created_at (first created = default)
        query = db.query(Store).filter(Store.owner_id == owner_id).order_by(Store.created_at.asc())
        total = query.count()
        stores = query.offset(skip).limit(limit).all()
        
        return StoreListResponse(
            stores=stores,
            total=total,
            page=skip // limit + 1,
            size=len(stores)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching stores: {str(e)}"
        )

# UPDATE store
@store_router.patch("/{store_id}", response_model=StoreResponse)
async def update_store(
    store_id: uuid.UUID,
    store_data: StoreUpdate,
    db: Session = Depends(get_db)
):
    try:
        db_store = db.query(Store).filter(Store.id == store_id).first()

        if not db_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        update_data = store_data.model_dump(exclude_unset=True)
        print(f"[Store Update] Store ID: {store_id}")
        print(f"[Store Update] Fields to update: {list(update_data.keys())}")
        if 'logo_url' in update_data:
            print(f"[Store Update] logo_url value: {update_data['logo_url'][:100] if update_data['logo_url'] else 'None'}...")

        for field, value in update_data.items():
            setattr(db_store, field, value)

        db.commit()
        db.refresh(db_store)

        print(f"[Store Update] After save - logo_url: {db_store.logo_url[:100] if db_store.logo_url else 'None'}...")
        return db_store
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating store: {str(e)}"
        )

# DELETE store
@store_router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store(store_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        db_store = db.query(Store).filter(Store.id == store_id).first()

        if not db_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        # Delete related FAQs first (they have store_id foreign key)
        from modules.whatsapp.models import FAQ
        db.query(FAQ).filter(FAQ.store_id == store_id).delete(synchronize_session=False)

        # Delete the store
        db.delete(db_store)
        db.commit()
        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting store: {str(e)}"
        )
    
def send_message_externally(message_body: str) -> Dict[str, Any]:
    """
    Simulates sending a message using an external service API.
    In a real app, this would involve HTTP requests to a provider (Twilio, etc.).
    """
    try:

        return {
            "success": True,
            "message": f"Message successfully sent."
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Failed to connect to external messaging service.",
            "task_id": None
        }
    
@store_router.post(
    "/business/send-message",
    status_code=status.HTTP_202_ACCEPTED  # 202 Accepted indicates processing has begun
)
def send_message_endpoint(
    message_data: MessageSend,
):
    """
    Send a message to a recipient using a specified platform.
    This simulates triggering an external message service.
    """
    try:
        send_result = send_message_externally(
            message_body=message_data.message_body,
        )

        # Return a structured dictionary response
        return {
            "status": "success",
            "message": "Message processing has started successfully",
            "data": {
                "message_id": send_result.get("message_id"),
                "status": "queued",
                "timestamp": datetime.utcnow().isoformat()
            },
            "code": "MESSAGE_ACCEPTED"
        }

    except HTTPException:
        # Reraise FastAPI's HTTP exceptions
        raise
    except Exception as e:
        # Log an error in your database if necessary
        # create_error_log(...)
        
        # Return error as dictionary
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Internal server error during message sending process",
                "error": str(e),
                "code": "INTERNAL_SERVER_ERROR",
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@store_router.post(
    "/n8n/webhook/message",
    status_code=status.HTTP_200_OK
)
def n8n_simple_message_receive(
    message_data: SimpleMessage
):
    """
    Ultra-simple webhook for n8n - just receives a message
    """
    return {
        "received": True,
        "message": message_data.message,
        "timestamp": datetime.utcnow().isoformat()
    }

# Add this import at the top if not already present
from typing import List

# Add these schemas to your existing schemas.py

# Add this endpoint to your store_router in api.py
@store_router.get("/{store_id}/hashtag-info", response_model=Dict[str, Any])
async def get_store_hashtag_info(
    store_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get store name and business type for generating social media hashtags
    """
    try:
        store = db.query(Store).filter(Store.id == store_id).first()
        
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        # Generate hashtag suggestions
        hashtag_suggestions = generate_hashtag_suggestions(store.store_name, store.business_type)
        
        return {
            "store_id": str(store.id),
            "store_name": store.store_name,
            "business_type": store.business_type,
            "hashtag_suggestions": hashtag_suggestions,
            "primary_hashtag": f"#{store.store_name.replace(' ', '').lower()}",
            "business_hashtag": f"#{store.business_type.replace(' ', '').lower() if store.business_type else 'business'}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching store hashtag info: {str(e)}"
        )

@store_router.get("/owner/{owner_id}/hashtag-info", response_model=List[Dict[str, Any]])
async def get_all_stores_hashtag_info(
    owner_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get hashtag info for all stores owned by a user
    """
    try:
        # Verify owner exists
        owner = db.query(User).filter(User.id == owner_id).first()
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Owner not found"
            )
        
        # Get all stores for owner
        stores = db.query(Store).filter(Store.owner_id == owner_id).all()
        
        result = []
        for store in stores:
            hashtag_suggestions = generate_hashtag_suggestions(store.store_name, store.business_type)
            
            result.append({
                "store_id": str(store.id),
                "store_name": store.store_name,
                "business_type": store.business_type,
                "hashtag_suggestions": hashtag_suggestions,
                "primary_hashtag": f"#{store.store_name.replace(' ', '').lower()}",
                "business_hashtag": f"#{store.business_type.replace(' ', '').lower() if store.business_type else 'business'}"
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching stores hashtag info: {str(e)}"
        )

# Helper function for generating hashtag suggestions
def generate_hashtag_suggestions(store_name: str, business_type: Optional[str] = None) -> Dict[str, List[str]]:
    """
    Generate relevant hashtag suggestions based on store name and business type
    """
    # Clean store name for hashtag
    clean_store_name = store_name.replace(' ', '').lower()
    
    # Common business type mappings to hashtags
    business_hashtags = {
        "restaurant": ["food", "restaurant", "dining", "eatlocal", "foodie"],
        "cafe": ["coffee", "cafe", "barista", "coffeelover", "cafeculture"],
        "clothing": ["fashion", "style", "clothing", "outfit", "shoplocal"],
        "electronics": ["tech", "electronics", "gadgets", "innovation", "technology"],
        "beauty": ["beauty", "skincare", "makeup", "selfcare", "glam"],
        "fitness": ["fitness", "workout", "health", "gym", "wellness"],
        "home decor": ["homedecor", "interiordesign", "decor", "home", "design"],
        "jewelry": ["jewelry", "accessories", "bling", "style", "fashion"],
        "bookstore": ["books", "reading", "literature", "bookstore", "booklover"],
        "art gallery": ["art", "gallery", "creative", "artist", "exhibition"],
        "bakery": ["bakery", "bread", "pastry", "baking", "sweet"],
        "pharmacy": ["pharmacy", "health", "wellness", "medicine", "care"],
        "grocery": ["grocery", "food", "fresh", "market", "shoplocal"],
        "flower shop": ["flowers", "florist", "bouquet", "blooms", "nature"]
    }
    
    # General business hashtags
    general_hashtags = [
        "smallbusiness",
        "supportlocal",
        "shoplocal",
        "entrepreneur",
        "business",
        "localbusiness",
        "smallbiz"
    ]
    
    # Platform-specific hashtags
    platform_hashtags = {
        "instagram": ["instagood", "instagram", "ig"],
        "facebook": ["facebook", "fb"],
        "twitter": ["twitter", "tweet"],
        "tiktok": ["tiktok", "fyp", "viral"]
    }
    
    # Get business-specific hashtags
    business_specific = []
    if business_type and business_type.lower() in business_hashtags:
        business_specific = business_hashtags[business_type.lower()]
    elif business_type:
        # If business type not in mapping, create basic ones
        business_keyword = business_type.replace(' ', '').lower()
        business_specific = [business_keyword, f"{business_keyword}life", business_type.lower().replace(' ', '')]
    
    # Generate store-specific hashtags
    store_specific = [
        f"{clean_store_name}",
        f"shop{clean_store_name}",
        f"visit{clean_store_name}",
        f"{clean_store_name}official"
    ]
    
    return {
        "store_specific": store_specific,
        "business_related": business_specific,
        "general_business": general_hashtags,
        "platform_specific": platform_hashtags,
        "combined_sets": {
            "minimal": store_specific[:2] + business_specific[:2] + general_hashtags[:2],
            "comprehensive": store_specific + business_specific + general_hashtags,
            "platform_optimized": {
                "instagram": store_specific[:3] + business_specific[:3] + ["instagood", "photooftheday"],
                "facebook": store_specific[:2] + business_specific[:2] + general_hashtags[:3],
                "twitter": store_specific[:1] + business_specific[:1] + general_hashtags[:2],
                "tiktok": store_specific[:2] + business_specific[:2] + ["fyp", "viral", "trending"]
            }
        }
    }


# Debug endpoint to check store logo_url (no auth required)
@store_router.get("/debug/logo/{store_id}")
async def debug_store_logo(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """Debug endpoint to check store logo_url value"""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return {"error": "Store not found"}
    return {
        "store_id": str(store.id),
        "store_name": store.store_name,
        "logo_url": store.logo_url,
        "logo_url_length": len(store.logo_url) if store.logo_url else 0,
        "color_theme": store.color_theme
    }
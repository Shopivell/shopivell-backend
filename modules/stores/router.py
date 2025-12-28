# modules/stores/api.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Any, Dict, Optional
import uuid
from datetime import datetime

from database import get_db
from modules.users.models import User
from modules.stores.models import Store, StoreSetupStep, StoreSetupSession
from modules.stores.schemas import (
    MessageSend, ScrapeRequest, SimpleMessage, StoreCreate, StoreResponse, StoreUpdate, StoreListResponse,
    StoreSetupStepData, StoreSetupSessionResponse, StoreSetupStart
)

store_router = APIRouter(prefix="/api/stores", tags=["stores"])

# Constants for setup progress
SETUP_STEPS = {
    "basic_info": 20,
    "business_type": 35,
    "delivery_settings": 50,
    "payment_methods": 65,
    "features": 80,
    "goals": 95,
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
        
        print(f"🔄 BEFORE UPDATE - session_data: {setup_session.session_data}")
        print(f"🔄 RECEIVED DATA: {step_data.data}")
        
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
        
        print(f"🔄 AFTER UPDATE - session_data: {setup_session.session_data}")
        print(f"🔄 Completed steps: {setup_session.completed_steps}")
        print(f"🔄 Progress: {setup_session.setup_progress}%")
        
        # FIX: Use explicit commit and refresh
        db.commit()
        db.refresh(setup_session)
        
        print(f"✅ AFTER COMMIT - session_data: {setup_session.session_data}")
        return setup_session
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error updating setup step: {str(e)}")
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
        
        existing_store = db.query(Store).filter(Store.owner_id == user.id).first()
        if existing_store:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already has a store"
            )
        
        # Validate required data
        session_data = setup_session.session_data
        required_fields = ['store_name', 'store_phone']
        for field in required_fields:
            if field not in session_data or not session_data[field]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required field: {field}"
                )
        
        # CREATE the actual store with all collected data
        # In the complete_store_setup function, update the store_data dictionary:
        store_data = {
            'owner_id': user.id,
            'store_name': session_data['store_name'],
            'store_phone': session_data['store_phone'],
            'store_email': session_data.get('store_email'),  # ADDED
            'store_link': session_data.get('store_link'),
            'color_theme': session_data.get('color_theme'),
            'logo_url': session_data.get('logo_url'),  # ADDED
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
        
        # Deactivate the setup session
        setup_session.is_active = False
        setup_session.setup_progress = 100
        
        db.commit()
        db.refresh(db_store)
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

# CREATE store directly (without setup wizard)
@store_router.post("/", response_model=StoreResponse)
async def create_store(
    store_data: StoreCreate,
    db: Session = Depends(get_db)
):
    """Create a new store directly (for adding additional stores)"""
    try:
        # Verify owner exists
        owner = db.query(User).filter(User.id == store_data.owner_id).first()
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Owner not found"
            )

        # Create the store
        db_store = Store(
            owner_id=store_data.owner_id,
            agency_id=store_data.agency_id,
            store_name=store_data.store_name,
            store_phone=store_data.store_phone,
            store_email=store_data.store_email,
            store_link=store_data.store_link,
            color_theme=store_data.color_theme,
            logo_url=store_data.logo_url,
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
        db.commit()
        db.refresh(db_store)
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
        
        # Get stores for owner
        query = db.query(Store).filter(Store.owner_id == owner_id)
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
        for field, value in update_data.items():
            setattr(db_store, field, value)
        
        db.commit()
        db.refresh(db_store)
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

@store_router.post("/scrape-website", status_code=status.HTTP_200_OK)
async def scrape_website(request: ScrapeRequest):
    """
    Scrape a website using Tavily and extract store information using AI.

    Uses:
    - Tavily for web content extraction
    - OpenAI for parsing content into structured store data
    """
    from modules.stores.scraping_service import extract_store_info_from_website

    url = request.url.strip()

    # Ensure URL has protocol
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    try:
        # Extract store info using Tavily + AI agent
        store_data = extract_store_info_from_website(url)

        print(f"[Scrape] Successfully extracted data for: {url}")
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
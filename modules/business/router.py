from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import uuid
import requests
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse
from pydantic import BaseModel

from database import get_db
from .models import FacebookBusinessAccount, FacebookPage
from .schemas import (
    FacebookBusinessAccountResponse, FacebookCallbackRequest, FacebookOAuthUrlRequest, FacebookOAuthUrlRequest, FacebookPageResponse,
    FacebookBusinessAccountCreate, FacebookPageCreate,
    FacebookBusinessAccountUpdate, FacebookPageUpdate,
    FacebookOAuthRequest, FacebookOAuthResponse,
    FacebookBusinessAccountListResponse, FacebookPageListResponse, FacebookPostInsightsResponse, FacebookPostsResponse,
    SuccessMessage, FacebookPostCreate, FacebookPostResponse
)

business_router = APIRouter(prefix="/api/business", tags=["business"])

# Facebook Graph API base URL
FB_GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

# Facebook App credentials from environment (with defaults for your app)
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "859974717008470")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "c523768871eef789b46a160c5d1d4ab1")

# OAuth Configuration
FACEBOOK_REDIRECT_URI = os.getenv(
    "FACEBOOK_BUSINESS_REDIRECT_URI",
    "http://localhost:8000/v1/api/business/facebook/callback",
)

FACEBOOK_OAUTH_SCOPE = (
    "public_profile,"
    "pages_show_list,"
    "pages_read_engagement"
)

def exchange_short_lived_token_for_long_lived(short_lived_token: str) -> dict:
    """Exchange a short-lived access token for a long-lived token (60 days)"""
    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
        # If no app secret, return the short-lived token as-is
        return {"access_token": short_lived_token, "expires_in": 3600}
    
    try:
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "fb_exchange_token": short_lived_token
            }
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        # If exchange fails, log and return short-lived token
        print(f"Warning: Failed to exchange token for long-lived token: {str(e)}")
        return {"access_token": short_lived_token, "expires_in": 3600}

def get_facebook_user_info(access_token: str):
    """Get Facebook user information from access token"""
    try:
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/me",
            params={"access_token": access_token, "fields": "id,name,email"}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get Facebook user info: {str(e)}"
        )

def get_facebook_business_accounts(access_token: str):
    """Get Facebook business accounts for the user"""
    try:
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/me/businesses",
            params={
                "access_token": access_token,
                "fields": "id,name,primary_page"
            }
        )
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get business accounts: {str(e)}"
        )

def get_facebook_user_pages(access_token: str):
    """Get Facebook pages directly via /me/accounts (only needs pages_show_list)"""
    try:
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/me/accounts",
            params={
                "access_token": access_token,
                "fields": "id,name,category,category_list,about,cover,picture,website,phone,emails,location,access_token,tasks"
            }
        )
        response.raise_for_status()
        result = response.json()
        print(f"[FB DEBUG] /me/accounts response: {json.dumps(result, indent=2)}")
        return result.get("data", [])
    except Exception as e:
        print(f"[FB DEBUG] /me/accounts error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get Facebook pages: {str(e)}"
        )

def get_facebook_pages(access_token: str, business_account_id: str):
    """Get Facebook pages for a business account"""
    try:
        # First, get a long-lived token for the business account
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/{business_account_id}",
            params={
                "access_token": access_token,
                "fields": "id,name"
            }
        )
        response.raise_for_status()
        business_info = response.json()

        # Get pages owned by this business account
        pages_response = requests.get(
            f"{FB_GRAPH_API_BASE}/{business_account_id}/owned_pages",
            params={
                "access_token": access_token,
                "fields": "id,name,category,category_list,about,cover,picture,website,phone,emails,location,access_token,tasks"
            }
        )
        pages_response.raise_for_status()
        pages_data = pages_response.json().get("data", [])

        return business_info, pages_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get Facebook pages: {str(e)}"
        )

# OAuth URL Generation
@business_router.post("/facebook/oauth-url")
def get_facebook_business_oauth_url(request_data: FacebookOAuthUrlRequest):
    """Generate Facebook OAuth URL for business account connection"""
    # Use custom state if provided (e.g., contains return URL), otherwise generate UUID
    state = request_data.state or str(uuid.uuid4())

    # Use the redirect_uri from frontend or default
    redirect_uri = request_data.redirect_uri or FACEBOOK_REDIRECT_URI

    # Validate the redirect URI
    parsed_uri = urlparse(redirect_uri)
    if not parsed_uri.scheme or not parsed_uri.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redirect URI"
        )

    params = {
        "client_id": FACEBOOK_APP_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": FACEBOOK_OAUTH_SCOPE,
    }
    auth_url = f"https://www.facebook.com/v18.0/dialog/oauth?{urlencode(params)}"
    return JSONResponse({"auth_url": auth_url, "state": state})

# Helper function to process Facebook authentication
def process_facebook_authentication(code: str, db: Session) -> dict:
    """Process Facebook authentication and return result"""
    try:
        # Use the FACEBOOK_REDIRECT_URI for token exchange
        redirect_uri = FACEBOOK_REDIRECT_URI
        
        # 1. Exchange code for short-lived user access token
        try:
            token_resp = requests.get(
                f"{FB_GRAPH_API_BASE}/oauth/access_token",
                params={
                    "client_id": FACEBOOK_APP_ID,
                    "client_secret": FACEBOOK_APP_SECRET,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            user_access_token = token_data["access_token"]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange code for token: {str(e)}",
            )

        # 2. Reuse your existing connect_facebook_account logic
        oauth_data = FacebookOAuthRequest(access_token=user_access_token)
        result = connect_facebook_account(oauth_data, db)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Facebook authentication failed: {str(e)}"
        )

# OAuth Callback - GET endpoint (for direct browser redirects)
@business_router.post("/facebook/callback", response_model=FacebookOAuthResponse)
def facebook_business_callback_post(
    request_data: FacebookCallbackRequest,
    db: Session = Depends(get_db),
):
    """OAuth callback for Facebook business account connection (POST from React)"""
    try:
        # Use the redirect_uri that was used in the initial OAuth request
        # This should be your React app URL
        redirect_uri = request_data.redirect_uri or FACEBOOK_REDIRECT_URI
        
        # 1. Exchange code for short-lived user access token
        token_resp = requests.get(
            f"{FB_GRAPH_API_BASE}/oauth/access_token",
            params={
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": request_data.code,
            },
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        user_access_token = token_data["access_token"]
        
        # 2. Connect account
        oauth_data = FacebookOAuthRequest(access_token=user_access_token)
        result = connect_facebook_account(oauth_data, db)
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Facebook authentication failed: {str(e)}"
        )

# Business Account Operations
@business_router.post("/connect", response_model=FacebookOAuthResponse)
def connect_facebook_account(
    oauth_data: FacebookOAuthRequest,
    db: Session = Depends(get_db)
):
    """Connect Facebook Business Account and fetch pages"""
    try:
        # Get user info to verify token
        user_info = get_facebook_user_info(oauth_data.access_token)
        user_id = user_info.get("id")
        
        # Exchange short-lived token for long-lived token (if app secret is configured)
        long_lived_token_data = exchange_short_lived_token_for_long_lived(oauth_data.access_token)
        long_lived_token = long_lived_token_data.get("access_token", oauth_data.access_token)
        expires_in = long_lived_token_data.get("expires_in", 5184000)  # Default 60 days
        
        # Calculate expiration date
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None
        
        # Try to get business accounts first, fall back to direct page access
        business_account_id = None
        business_name = "My Business"

        try:
            business_accounts = get_facebook_business_accounts(long_lived_token)
            if business_accounts:
                first_business = business_accounts[0]
                business_account_id = first_business.get("id")
                business_name = first_business.get("name", "My Business")
        except Exception:
            # business_management permission not available, skip
            pass

        if not business_account_id:
            # Use user ID as business account identifier
            business_account_id = user_id
            business_name = user_info.get("name", "My Business")

        # Check if business account already exists
        existing_business = db.query(FacebookBusinessAccount).filter(
            FacebookBusinessAccount.business_account_id == business_account_id
        ).first()

        if existing_business:
            existing_business.access_token = long_lived_token
            existing_business.business_name = business_name
            existing_business.user_id = user_id
            existing_business.is_connected = True
            existing_business.expires_at = expires_at
            existing_business.updated_at = datetime.utcnow()
            business_account = existing_business
        else:
            business_account = FacebookBusinessAccount(
                business_account_id=business_account_id,
                business_name=business_name,
                access_token=long_lived_token,
                user_id=user_id,
                expires_at=expires_at,
                is_connected=True
            )
            db.add(business_account)
            db.commit()
            db.refresh(business_account)

        # Get pages directly via /me/accounts (works without business_management)
        pages_data = get_facebook_user_pages(long_lived_token)

        if not pages_data:
            # Fall back to business account pages if available
            try:
                if business_account_id != user_id:
                    _, pages_data = get_facebook_pages(long_lived_token, business_account_id)
            except Exception:
                pass

        if not pages_data:
            # Check what permissions the token actually has
            try:
                perms_resp = requests.get(
                    f"{FB_GRAPH_API_BASE}/me/permissions",
                    params={"access_token": long_lived_token}
                )
                perms_data = perms_resp.json().get("data", [])
                granted = [p["permission"] for p in perms_data if p.get("status") == "granted"]
                declined = [p["permission"] for p in perms_data if p.get("status") == "declined"]
                print(f"[FB DEBUG] Granted permissions: {granted}")
                print(f"[FB DEBUG] Declined permissions: {declined}")
            except Exception as perm_err:
                print(f"[FB DEBUG] Could not check permissions: {perm_err}")

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Facebook pages found. Make sure your Facebook account manages at least one Facebook Page."
            )
        
        connected_pages = []
        
        # Process each page
        for page_data in pages_data:
            page_id = page_data.get("id")
            page_name = page_data.get("name", "Untitled Page")
            page_access_token = page_data.get("access_token", "")
            
            # Check if page already exists
            existing_page = db.query(FacebookPage).filter(
                FacebookPage.page_id == page_id
            ).first()
            
            # Extract additional page information
            cover = page_data.get("cover", {})
            picture = page_data.get("picture", {})
            category_list = page_data.get("category_list", [])
            location = page_data.get("location", {})
            emails = page_data.get("emails", [])
            
            page_info = {
                "page_id": page_id,
                "page_name": page_name,
                "page_access_token": page_access_token,
                "category": page_data.get("category"),
                "category_list": ",".join([cat.get("name", "") for cat in category_list]) if category_list else None,
                "about": page_data.get("about"),
                "cover_photo_url": cover.get("source") if cover else None,
                "profile_picture_url": picture.get("data", {}).get("url") if picture else None,
                "website": page_data.get("website"),
                "phone": page_data.get("phone"),
                "email": emails[0] if emails else None,
                "location": location.get("name") if location else None,
                "tasks": ",".join(page_data.get("tasks", [])) if page_data.get("tasks") else None,
                "is_connected": True,
                "last_synced_at": datetime.utcnow()
            }
            
            if existing_page:
                # Update existing page
                for key, value in page_info.items():
                    if value is not None:
                        setattr(existing_page, key, value)
                existing_page.updated_at = datetime.utcnow()
                page = existing_page
            else:
                # Create new page
                page = FacebookPage(
                    business_account_id=business_account.id,
                    **page_info
                )
                db.add(page)
            
            connected_pages.append(page)
        
        db.commit()
        
        # Refresh all pages
        for page in connected_pages:
            db.refresh(page)
        
        return FacebookOAuthResponse(
            success=True,
            message=f"Successfully connected {len(connected_pages)} Facebook pages",
            business_account_id=business_account.id,
            pages=[FacebookPageResponse.model_validate(page) for page in connected_pages]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect Facebook account: {str(e)}"
        )

@business_router.get("/accounts", response_model=FacebookBusinessAccountListResponse)
def get_business_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get all connected Facebook business accounts"""
    business_accounts = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.is_connected == True
    ).offset(skip).limit(limit).all()
    
    total_count = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.is_connected == True
    ).count()
    
    return FacebookBusinessAccountListResponse(
        business_accounts=[FacebookBusinessAccountResponse.model_validate(acc) for acc in business_accounts],
        total_count=total_count
    )

@business_router.get("/accounts/{account_id}", response_model=FacebookBusinessAccountResponse)
def get_business_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific business account by ID"""
    business_account = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.id == account_id
    ).first()
    
    if not business_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business account not found"
        )
    
    return FacebookBusinessAccountResponse.model_validate(business_account)

@business_router.get("/pages", response_model=FacebookPageListResponse)
def get_facebook_pages_list(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    business_account_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db)
):
    """Get all connected Facebook pages"""
    query = db.query(FacebookPage).filter(FacebookPage.is_connected == True)
    
    if business_account_id:
        query = query.filter(FacebookPage.business_account_id == business_account_id)
    
    pages = query.offset(skip).limit(limit).all()
    total_count = query.count()
    
    return FacebookPageListResponse(
        pages=[FacebookPageResponse.model_validate(page) for page in pages],
        total_count=total_count
    )

@business_router.get("/pages/{page_id}", response_model=FacebookPageResponse)
def get_facebook_page(page_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific Facebook page by ID"""
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    return FacebookPageResponse.model_validate(page)

@business_router.delete("/accounts/{account_id}", response_model=SuccessMessage)
def disconnect_business_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Disconnect a Facebook business account"""
    business_account = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.id == account_id
    ).first()
    
    if not business_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business account not found"
        )
    
    # Mark as disconnected
    business_account.is_connected = False
    business_account.is_active = False
    business_account.updated_at = datetime.utcnow()
    
    # Also disconnect all pages
    for page in business_account.pages:
        page.is_connected = False
        page.is_active = False
        page.updated_at = datetime.utcnow()
    
    db.commit()
    
    return SuccessMessage(message="Business account disconnected successfully")

@business_router.delete("/pages/{page_id}", response_model=SuccessMessage)
def disconnect_facebook_page(page_id: uuid.UUID, db: Session = Depends(get_db)):
    """Disconnect a Facebook page"""
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    page.is_connected = False
    page.is_active = False
    page.updated_at = datetime.utcnow()
    
    db.commit()
    
    return SuccessMessage(message="Facebook page disconnected successfully")

@business_router.post("/pages/{page_id}/sync", response_model=FacebookPageResponse)
def sync_facebook_page(page_id: uuid.UUID, db: Session = Depends(get_db)):
    """Sync Facebook page data from Facebook API"""
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    business_account = page.business_account
    if not business_account or not business_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business account is not connected"
        )
    
    try:
        # Get updated page data from Facebook
        _, pages_data = get_facebook_pages(
            business_account.access_token,
            business_account.business_account_id
        )
        
        # Find the page in the response
        page_data = next((p for p in pages_data if p.get("id") == page.page_id), None)
        
        if not page_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Page not found in Facebook account"
            )
        
        # Update page data
        cover = page_data.get("cover", {})
        picture = page_data.get("picture", {})
        category_list = page_data.get("category_list", [])
        location = page_data.get("location", {})
        emails = page_data.get("emails", [])
        
        page.page_name = page_data.get("name", page.page_name)
        page.page_access_token = page_data.get("access_token", page.page_access_token)
        page.category = page_data.get("category", page.category)
        page.category_list = ",".join([cat.get("name", "") for cat in category_list]) if category_list else page.category_list
        page.about = page_data.get("about", page.about)
        page.cover_photo_url = cover.get("source") if cover else page.cover_photo_url
        page.profile_picture_url = picture.get("data", {}).get("url") if picture else page.profile_picture_url
        page.website = page_data.get("website", page.website)
        page.phone = page_data.get("phone", page.phone)
        page.email = emails[0] if emails else page.email
        page.location = location.get("name") if location else page.location
        page.tasks = ",".join(page_data.get("tasks", [])) if page_data.get("tasks") else page.tasks
        page.last_synced_at = datetime.utcnow()
        page.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(page)
        
        return FacebookPageResponse.model_validate(page)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync page: {str(e)}"
        )

def post_to_facebook_page(page_id: str, page_access_token: str, post_data: FacebookPostCreate):
    """Post content to a Facebook page using the Graph API"""
    try:
        # Prepare the post parameters
        params = {
            "access_token": page_access_token,
            "message": post_data.message
        }
        
        # Add optional parameters
        if post_data.link:
            params["link"] = post_data.link
        
        if post_data.scheduled_publish_time:
            # Facebook expects Unix timestamp for scheduled posts
            params["published"] = False
            params["scheduled_publish_time"] = int(post_data.scheduled_publish_time.timestamp())
        else:
            params["published"] = post_data.published
        
        # Post to Facebook Graph API
        response = requests.post(
            f"{FB_GRAPH_API_BASE}/{page_id}/feed",
            data=params
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to post to Facebook page: {error_detail}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post to Facebook page: {str(e)}"
        )

@business_router.post("/pages/{page_id}/post", response_model=FacebookPostResponse)
def post_to_facebook_page_endpoint(
    page_id: uuid.UUID,
    post_data: FacebookPostCreate,
    db: Session = Depends(get_db)
):
    """Post content to a Facebook page"""
    # Get the page from database
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    # Check if page is connected
    if not page.is_connected or not page.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook page is not connected or inactive"
        )
    
    # Check if business account is connected
    business_account = page.business_account
    if not business_account or not business_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business account is not connected"
        )
    
    try:
        # Post to Facebook using page access token
        result = post_to_facebook_page(
            page.page_id,
            page.page_access_token,
            post_data
        )
        
        # Extract post ID from result
        post_id = result.get("id")
        post_url = None
        if post_id:
            # Construct post URL (format: https://facebook.com/{post_id})
            post_url = f"https://facebook.com/{post_id}"
        
        return FacebookPostResponse(
            success=True,
            message="Content posted to Facebook page successfully",
            post_id=post_id,
            post_url=post_url
        )
        
    except HTTPException:
        raise

# New Analytics and Posts APIs
def get_facebook_page_posts(page_id: str, page_access_token: str, limit: int = 25):
    """Get posts from a Facebook page using the Graph API"""
    try:
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/{page_id}/posts",
            params={
                "access_token": page_access_token,
                "fields": (
                    "id,message,created_time,updated_time,permalink_url,"
                    "type,status_type,is_published,is_hidden,is_expired,"
                    "reactions.summary(true).limit(0),"
                    "comments.summary(true).limit(0),"
                    "shares"
                ),
                "limit": limit
            }
        )
        response.raise_for_status()
        return response.json().get("data", [])
    except requests.exceptions.HTTPError as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get Facebook posts: {error_detail}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Facebook posts: {str(e)}"
        )

def get_facebook_post_insights(post_id: str, page_access_token: str):
    """Get analytics/insights for a specific Facebook post"""
    try:
        # Common metrics for post insights
        metrics = [
            "post_impressions", "post_impressions_unique", "post_impressions_paid", "post_impressions_paid_unique",
            "post_impressions_fan", "post_impressions_fan_unique", "post_impressions_fan_paid", "post_impressions_fan_paid_unique",
            "post_impressions_organic", "post_impressions_organic_unique", "post_impressions_viral", "post_impressions_viral_unique",
            "post_engaged_users", "post_engaged_fan", "post_clicks", "post_reactions_like_total",
            "post_reactions_love_total", "post_reactions_wow_total", "post_reactions_haha_total",
            "post_reactions_sorry_total", "post_reactions_anger_total", "post_reactions_by_type_total"
        ]
        
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/{post_id}/insights",
            params={
                "access_token": page_access_token,
                "metric": ",".join(metrics),
                "period": "lifetime"
            }
        )
        response.raise_for_status()
        insights_data = response.json().get("data", [])
        
        # Process insights into a more usable format
        insights = {}
        for insight in insights_data:
            metric_name = insight.get("name")
            values = insight.get("values", [])
            if values:
                insights[metric_name] = values[0].get("value", 0)
        
        return insights
    except requests.exceptions.HTTPError as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get post insights: {error_detail}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get post insights: {str(e)}"
        )


@business_router.get("/pages/{page_id}/posts", response_model=FacebookPostsResponse)
def get_facebook_posts_endpoint(
    page_id: uuid.UUID,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get posts from a Facebook page"""
    # Get the page from database
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    # Check if page is connected
    if not page.is_connected or not page.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook page is not connected or inactive"
        )
    
    try:
        # Get posts from Facebook API
        posts_data = get_facebook_page_posts(
            page.page_id,
            page.page_access_token,
            limit
        )
        
        return FacebookPostsResponse(
            posts=posts_data,
            total_count=len(posts_data)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Facebook posts: {str(e)}"
        )

@business_router.get("/posts/{post_id}/analytics", response_model=FacebookPostInsightsResponse)
def get_facebook_post_analytics(
    post_id: str,
    page_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get analytics/insights for a specific Facebook post"""
    # Get the page from database
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    # Check if page is connected
    if not page.is_connected or not page.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook page is not connected or inactive"
        )
    
    try:
        # Get post insights from Facebook API
        insights = get_facebook_post_insights(
            post_id,
            page.page_access_token
        )
        
        # Optionally get post details for additional context
        post_details = {}
        try:
            response = requests.get(
                f"{FB_GRAPH_API_BASE}/{post_id}",
                params={
                    "access_token": page.page_access_token,
                    "fields": "message,created_time,permalink_url"
                }
            )
            if response.status_code == 200:
                post_details = response.json()
        except:
            pass  # If we can't get post details, we'll just return insights
        
        return FacebookPostInsightsResponse(
            success=True,
            post_id=post_id,
            insights=insights,
            message=post_details.get("message"),
            permalink_url=post_details.get("permalink_url")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get post analytics: {str(e)}"
        )

@business_router.get("/pages/{page_id}/analytics")
def get_facebook_page_analytics(
    page_id: uuid.UUID,
    since: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    until: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """Get overall analytics for a Facebook page with simplified metrics"""
    # Get the page from database
    page = db.query(FacebookPage).filter(FacebookPage.id == page_id).first()
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facebook page not found"
        )
    
    # Check if page is connected
    if not page.is_connected or not page.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook page is not connected or inactive"
        )
    
    if not page.page_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Page access token is missing"
        )
    
    try:
        # Use simpler, more reliable metrics that work with most page access tokens
        basic_metrics = [
            "page_impressions",
            "page_engaged_users",
        ]
        
        params = {
            "access_token": page.page_access_token,
            "metric": ",".join(basic_metrics),
        }
        
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/{page.page_id}/insights",
            params=params
        )
        
        if response.status_code != 200:
            # Try without period if day is not allowed for some metrics
            params.pop("period", None)
            
            response = requests.get(
                f"{FB_GRAPH_API_BASE}/{page.page_id}/insights",
                params=params
            )
        
        response.raise_for_status()
        insights_data = response.json().get("data", [])
        
        # Process insights data into a cleaner format
        analytics = {}
        for insight in insights_data:
            metric_name = insight.get("name")
            title = insight.get("title", metric_name)
            values = insight.get("values", [])
            
            if values:
                # Get the most recent value for summary
                latest_value = values[-1].get("value", 0)
                analytics[metric_name] = {
                    "title": title,
                    "latest_value": latest_value,
                    "history": values
                }
        
        # Also get basic page stats
        try:
            page_info_response = requests.get(
                f"{FB_GRAPH_API_BASE}/{page.page_id}",
                params={
                    "access_token": page.page_access_token,
                    "fields": "fan_count,followers_count,link,name,username"
                }
            )
            if page_info_response.status_code == 200:
                page_info = page_info_response.json()
                analytics["page_info"] = {
                    "fan_count": page_info.get("fan_count", 0),
                    "followers_count": page_info.get("followers_count", 0),
                    "name": page_info.get("name"),
                    "username": page_info.get("username"),
                    "link": page_info.get("link")
                }
        except:
            pass  # If page info fails, we still return insights
        
        return {
            "success": True,
            "page_id": page.page_id,
            "page_name": page.page_name,
            "analytics": analytics,
            "period": {
                "since": since,
                "until": until
            }
        }
        
    except requests.exceptions.HTTPError as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
            error_code = error_data.get("error", {}).get("code")
        except:
            error_detail = str(e)
            error_code = None
        
        # Provide more specific error messages
        if error_code == 190:
            error_detail = "Page access token is expired or invalid. Please reconnect the page."
        elif error_code == 100:
            error_detail = "Invalid parameter or insufficient permissions for analytics."
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get page analytics: {error_detail}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get page analytics: {str(e)}"
        )
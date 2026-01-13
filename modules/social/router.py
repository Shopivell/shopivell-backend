# modules/social/api.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
import uuid
from datetime import datetime
import requests
from urllib.parse import urlencode
import os

from database import get_db
from modules.users.models import User
from modules.stores.models import Store
from modules.social.models import FacebookPageConnection, SocialPost, SocialPlatform, SocialConnectionStatus
from modules.social.schemas import (
    FacebookPageList,
    FacebookPageConnectionCreate,
    FacebookPageConnectionResponse,
    OAuthCallback,
    FacebookOAuthURL,
)

# Configuration for localhost development
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "882284284358539")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "http://localhost:8000/v1/api/social/facebook/callback")
FACEBOOK_API_VERSION = os.getenv("FACEBOOK_API_VERSION", "v24.0")

# Log warning if Facebook is not configured
if not FACEBOOK_APP_SECRET:
    import logging
    logging.warning("FACEBOOK_APP_SECRET not set - Facebook integration will be disabled")

social_router = APIRouter(prefix="/api/social", tags=["social"])

@social_router.get("/facebook/debug")
async def debug_facebook_config():
    """Debug endpoint to check Facebook configuration"""
    return {
        "app_id": FACEBOOK_APP_ID,
        "app_secret_set": bool(FACEBOOK_APP_SECRET),
        "redirect_uri": FACEBOOK_REDIRECT_URI,
        "api_version": FACEBOOK_API_VERSION,
        "status": "OK" if FACEBOOK_APP_ID and FACEBOOK_APP_SECRET else "MISSING_CONFIG"
    }

@social_router.get("/facebook/oauth-url", response_model=FacebookOAuthURL)
async def get_facebook_oauth_url(
    user_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    """Generate Facebook OAuth URL for frontend redirect"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Required permissions for pages
        scopes = [
            "pages_show_list",
            "pages_manage_posts", 
            "public_profile",
            "business_management"
        ]
        
        params = {
            "client_id": FACEBOOK_APP_ID,
            "redirect_uri": FACEBOOK_REDIRECT_URI,
            "scope": ",".join(scopes),
            "response_type": "code",
            "state": str(user_id)
        }
        
        auth_url = f"https://www.facebook.com/{FACEBOOK_API_VERSION}/dialog/oauth?{urlencode(params)}"
        
        print(f"🔗 Generated OAuth URL for user {user_id}")
        print(f"📋 Scopes: {scopes}")
        print(f"🔄 Redirect URI: {FACEBOOK_REDIRECT_URI}")
        
        return FacebookOAuthURL(auth_url=auth_url)
        
    except Exception as e:
        print(f"❌ Error generating OAuth URL: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating OAuth URL: {str(e)}"
        )

@social_router.post("/facebook/callback", response_model=FacebookPageList)
async def handle_facebook_callback(
    callback_data: OAuthCallback,
    db: Session = Depends(get_db)
):
    """Exchange code for access token and fetch user's pages"""
    try:
        print(f"🔄 Received Facebook callback with code")
        
        # Step 1: Exchange code for access token
        token_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token"
        token_params = {
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "redirect_uri": FACEBOOK_REDIRECT_URI,
            "code": callback_data.code
        }
        
        print("🔄 Exchanging code for access token...")
        token_response = requests.get(token_url, params=token_params)
        token_data = token_response.json()
        
        if "access_token" not in token_data:
            error_msg = token_data.get('error', {}).get('message', 'Unknown error')
            print(f"❌ Failed to get access token: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Facebook API error: {error_msg}"
            )
        
        user_access_token = token_data["access_token"]
        print(f"✅ Got user access token")
        
        # Step 2: Get Facebook user info FIRST
        user_info_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/me"
        user_info_params = {
            "access_token": user_access_token,
            "fields": "id,name"
        }
        
        print("🔄 Getting user info...")
        user_info_response = requests.get(user_info_url, params=user_info_params)
        user_info_data = user_info_response.json()
        
        facebook_user_id = user_info_data["id"]
        facebook_user_name = user_info_data.get("name", "Unknown")
        print(f"👤 Facebook user: {facebook_user_name} (ID: {facebook_user_id})")
        
        # Step 3: Get long-lived token (optional)
        long_lived_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/oauth/access_token"
        long_lived_params = {
            "grant_type": "fb_exchange_token",
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "fb_exchange_token": user_access_token
        }
        
        print("🔄 Getting long-lived token...")
        long_lived_response = requests.get(long_lived_url, params=long_lived_params)
        long_lived_data = long_lived_response.json()
        
        if "access_token" in long_lived_data:
            user_access_token = long_lived_data["access_token"]
            print(f"✅ Got long-lived token")
        
        # Step 4: Get user's Facebook pages - UPDATED FIELDS (FIXED)
        pages_url = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}/me/accounts"
        pages_params = {
            "access_token": user_access_token,
            "fields": "id,name,access_token,category,category_list,tasks,picture{url},instagram_business_account"
        }
        
        print(f"🔄 Fetching pages using /me/accounts endpoint...")
        pages_response = requests.get(pages_url, params=pages_params)
        pages_data = pages_response.json()
        
        print(f"📊 Facebook Pages API Response: {pages_data}")
        
        if "error" in pages_data:
            error_msg = pages_data["error"].get("message", "Unknown error")
            print(f"❌ Facebook Pages API error: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Facebook Pages API error: {error_msg}"
            )
        
        pages = pages_data.get("data", [])
        print(f"📄 Found {len(pages)} pages")
        
        # Build pages list response
        pages_list = []
        for page in pages:
            page_info = {
                "id": page["id"],
                "name": page["name"],
                "access_token": page["access_token"],
                "category": page.get("category", "Unknown"),
                "tasks": page.get("tasks", []),  # Use tasks instead of perms
                "picture_url": page.get("picture", {}).get("data", {}).get("url") if page.get("picture") else None,
                "instagram_business_account": page.get("instagram_business_account")
            }
            pages_list.append(page_info)
            print(f"   📝 Page: {page['name']} (ID: {page['id']}) - Tasks: {page.get('tasks', [])}")
        
        return FacebookPageList(
            pages=pages_list,
            user_id=facebook_user_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in Facebook callback: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling Facebook callback: {str(e)}"
        )
    
@social_router.post("/facebook/connect-page", response_model=FacebookPageConnectionResponse)
async def connect_facebook_page(
    connection_data: FacebookPageConnectionCreate,
    db: Session = Depends(get_db)
):
    """Store Facebook page connection in database"""
    try:
        print(f"🔗 Connecting Facebook page: {connection_data.facebook_page_name}")
        
        # Verify user exists
        user = db.query(User).filter(User.id == connection_data.shopivell_user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Check if page is already connected
        existing_connection = db.query(FacebookPageConnection).filter(
            FacebookPageConnection.facebook_page_id == connection_data.facebook_page_id,
            FacebookPageConnection.shopivell_user_id == connection_data.shopivell_user_id
        ).first()
        
        if existing_connection:
            # Update existing connection
            print(f"🔄 Updating existing connection")
            existing_connection.facebook_page_token = connection_data.facebook_page_token
            existing_connection.facebook_page_name = connection_data.facebook_page_name
            existing_connection.status = SocialConnectionStatus.CONNECTED
            existing_connection.is_token_valid = True
            existing_connection.updated_at = datetime.utcnow()
            db_connection = existing_connection
        else:
            # Create new connection
            print(f"🆕 Creating new connection")
            connection = FacebookPageConnection(
                shopivell_user_id=connection_data.shopivell_user_id,
                store_id=connection_data.store_id,
                facebook_page_id=connection_data.facebook_page_id,
                facebook_page_name=connection_data.facebook_page_name,
                facebook_page_token=connection_data.facebook_page_token,
                facebook_user_id=connection_data.facebook_user_id,
                granted_permissions=connection_data.granted_permissions
            )
            db.add(connection)
            db_connection = connection
        
        db.commit()
        db.refresh(db_connection)
        
        print(f"✅ Successfully connected page: {connection_data.facebook_page_name}")
        return db_connection
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error connecting Facebook page: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error connecting Facebook page: {str(e)}"
        )

@social_router.get("/facebook/connections", response_model=List[FacebookPageConnectionResponse])
async def get_facebook_connections(
    user_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    """Get all Facebook page connections for a user"""
    try:
        print(f"📋 Fetching Facebook connections for user: {user_id}")
        
        connections = db.query(FacebookPageConnection).filter(
            FacebookPageConnection.shopivell_user_id == user_id,
            FacebookPageConnection.status == SocialConnectionStatus.CONNECTED
        ).all()
        
        print(f"✅ Found {len(connections)} connections")
        return connections
        
    except Exception as e:
        print(f"❌ Error fetching connections: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching Facebook connections: {str(e)}"
        )

@social_router.delete("/facebook/connections/{connection_id}")
async def disconnect_facebook_page(
    connection_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Disconnect a Facebook page connection"""
    try:
        print(f"🗑️ Disconnecting Facebook connection: {connection_id}")
        
        connection = db.query(FacebookPageConnection).filter(
            FacebookPageConnection.id == connection_id
        ).first()
        
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Facebook connection not found"
            )
        
        # Soft delete by updating status
        connection.status = SocialConnectionStatus.DISCONNECTED
        connection.is_token_valid = False
        connection.updated_at = datetime.utcnow()
        
        db.commit()
        
        print(f"✅ Successfully disconnected page: {connection.facebook_page_name}")
        return {"message": "Facebook page disconnected successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error disconnecting Facebook page: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error disconnecting Facebook page: {str(e)}"
        )
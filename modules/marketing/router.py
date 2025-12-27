# routers/marketing.py
import traceback
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_, desc
from typing import List, Optional, Dict, Any
import uuid
import requests
import os
from datetime import datetime, timedelta, date
import json
import asyncio

from database import get_db
from .models import (
    MetaAdAccount, MetaCampaign, MetaAdSet, MetaAd,
    MetaAdCreative, MetaExperiment, MetaAutomatedRule, MetaAdInsight,
)
from modules.business.models import FacebookBusinessAccount
from modules.campaigns.models import UrlCampaign, CampaignStatus as UrlCampaignStatus
from .schemas import (
    MetaAdAccountCreate, MetaAdAccountUpdate, MetaAdAccountResponse, MetaAdAccountListResponse,
    MetaCampaignCreate, MetaCampaignUpdate, MetaCampaignResponse, MetaCampaignListResponse,
    MetaAdSetCreate, MetaAdSetUpdate, MetaAdSetResponse, MetaAdSetListResponse,
    MetaAdCreate, MetaAdUpdate, MetaAdResponse, MetaAdListResponse,
    MetaAdCreativeCreate, MetaAdCreativeResponse, MetaAdCreativeListResponse,
    MetaExperimentCreate, MetaExperimentResponse, MetaExperimentListResponse,
    MetaAutomatedRuleCreate, MetaAutomatedRuleResponse, MetaAutomatedRuleListResponse,
    MetaAdInsightResponse, MetaAdInsightListResponse,
    MetaSyncRequest, MetaInsightsRequest, MetaCreateCampaignRequest, MetaCreateAdSetRequest,
    MetaCreateAdRequest, MetaCreateCreativeRequest, MetaCreateExperimentRequest,
    MetaBulkUpdateRequest, SuccessMessage, ErrorMessage,
    CampaignObjective, CampaignStatus, AdSetStatus, AdStatus,
    MetaInsightsSummary, MetaPerformanceMetrics, MetaCampaignPerformance,
    DraftItem, DraftListResponse, PublishDraftRequest, PublishDraftResponse
)

marketing_router = APIRouter(prefix="/api/marketing", tags=["marketing"])

# Facebook Graph API base URL
FB_GRAPH_API_BASE = "https://graph.facebook.com/v24.0"

# Helper Functions
def get_meta_ad_accounts(access_token: str):
    """Get Meta ad accounts for the user"""
    try:
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/me",  # Queries the /me node
            params={
                "access_token": access_token,
                "fields": "adaccounts{id,name,account_status,currency,timezone_name,business,business_name,amount_spent,balance,disable_reason}"
            }
        )
        response.raise_for_status()
        # Path to the data: response.json() -> 'adaccounts' -> 'data'
        return response.json().get("adaccounts", {}).get("data", [])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get Meta ad accounts: {str(e)}"
        )

def create_meta_campaign(ad_account_id: str, access_token: str, campaign_data: dict):
    """Create a campaign in Meta Ads API"""
    try:
        url = f"{FB_GRAPH_API_BASE}/{ad_account_id}/campaigns"
        
        # Start with access_token as first parameter
        params = {'access_token': access_token}
        
        # Add all campaign data as form parameters
        for key, value in campaign_data.items():
            if value is not None:
                # Convert lists to JSON strings
                if isinstance(value, list):
                    params[key] = json.dumps(value)
                # Convert datetime to UNIX timestamp
                elif isinstance(value, datetime):
                    params[key] = str(int(value.timestamp()))
                # Convert integers to strings
                elif isinstance(value, int):
                    params[key] = str(value)
                # Keep strings as is
                else:
                    params[key] = value
        
        response = requests.post(url, data=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create campaign: {error_detail}"
        )

def create_meta_adset(ad_account_id: str, access_token: str, adset_data: dict):
    """Create an ad set in Meta Ads API"""
    try:
        # Meta API requires act_ prefix for ad account ID
        url = f"{FB_GRAPH_API_BASE}/{ad_account_id}/adsets"
        
        # Start with access_token
        params = {"access_token": access_token}
        
        # Add all ad set data as form parameters
        for key, value in adset_data.items():
            if value is not None:
                # Convert lists to JSON strings (for targeting)
                if key == "targeting" and isinstance(value, str):
                    params[key] = value
                elif isinstance(value, list):
                    params[key] = json.dumps(value)
                # Keep strings as is
                else:
                    params[key] = str(value) if value is not None else value
        
        # Debug logging
        print(f"\n=== DEBUG: Creating Ad Set ===")
        print(f"URL: {url}")
        print(f"Params: { {k: v for k, v in params.items() if k != 'access_token'} }")
        print("=============================\n")
        
        response = requests.post(url, data=params)
        
        # Better error handling
        if response.status_code != 200:
            print(f"Error Response: {response.text}")
        
        response.raise_for_status()
        return response.json()
    except Exception as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
            # Add more details if available
            if error_data.get("error", {}).get("error_user_title"):
                error_detail = f"{error_detail}. {error_data['error']['error_user_title']}"
            if error_data.get("error", {}).get("error_user_msg"):
                error_detail = f"{error_detail}. {error_data['error']['error_user_msg']}"
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create ad set: {error_detail}"
        )
    
def upload_image_alternative_method(ad_account: MetaAdAccount, image_url: str) -> str:
    """Alternative method to upload images to Facebook"""
    try:
        print(f"\n=== DEBUG: Trying alternative image upload ===")
        
        # Download the image
        response = requests.get(image_url, timeout=30)
        if response.status_code != 200:
            return image_url  # Fallback to URL
        
        # Use a simpler upload approach
        upload_url = f"{FB_GRAPH_API_BASE}/{ad_account.ad_account_id}/adimages"
        
        # Create multipart form data
        files = {
            'filename': ('image.jpg', response.content, 'image/jpeg')
        }
        
        data = {
            'access_token': ad_account.access_token
        }
        
        upload_response = requests.post(upload_url, files=files, data=data, timeout=60)
        
        print(f"Alternative upload response: {upload_response.status_code}")
        print(f"Alternative upload body: {upload_response.text}")
        
        if upload_response.status_code == 200:
            result = upload_response.json()
            
            # Try to extract hash from different response formats
            if isinstance(result, dict):
                # Try common response formats
                for key in ['hash', 'images', 'data']:
                    if key in result:
                        if isinstance(result[key], dict) and 'hash' in result[key]:
                            return result[key]['hash']
                        elif isinstance(result[key], list) and len(result[key]) > 0:
                            if 'hash' in result[key][0]:
                                return result[key][0]['hash']
                        elif isinstance(result[key], str):
                            return result[key]
            
            # If we can't parse it, return the original response
            print(f"Could not parse response, returning as is: {result}")
            return str(result)
        
        return image_url  # Fallback to original URL
        
    except Exception as e:
        print(f"Alternative upload failed: {str(e)}")
        return image_url

def create_meta_adcreative(ad_account_id: str, access_token: str, creative_data: dict):
    """Create an ad creative in Meta Ads API"""
    try:
        # Use act_ prefix for ad account ID
        url = f"{FB_GRAPH_API_BASE}/{ad_account_id}/adcreatives"
        
        print(f"\n=== DEBUG: Meta AdCreative API Call ===")
        print(f"URL: {url}")
        
        # Start with access_token
        params = {"access_token": access_token}
        
        # Add all creative data as form parameters
        for key, value in creative_data.items():
            if value is not None and key != "access_token":
                if isinstance(value, dict):
                    params[key] = json.dumps(value)
                else:
                    params[key] = str(value)
        
        # Hide access token in logs
        safe_params = {k: '***' if k == 'access_token' else v for k, v in params.items()}
        print(f"Params: {safe_params}")
        
        # Log object_story_spec structure for debugging
        if 'object_story_spec' in params:
            try:
                parsed_spec = json.loads(params['object_story_spec'])
                print(f"Parsed object_story_spec: {json.dumps(parsed_spec, indent=2)}")
            except:
                print(f"Could not parse object_story_spec: {params['object_story_spec'][:200]}...")
        
        response = requests.post(url, data=params, timeout=60)
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        print("========================================\n")
        
        if response.status_code != 200:
            error_msg = "Unknown error"
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", str(response.text))
                error_code = error_data.get("error", {}).get("code", "UNKNOWN")
                error_type = error_data.get("error", {}).get("type", "Unknown")
                
                print(f"Meta API Error Details:")
                print(f"  Code: {error_code}")
                print(f"  Type: {error_type}")
                print(f"  Message: {error_msg}")
                
                # Add user-friendly message if available
                if error_data.get("error", {}).get("error_user_title"):
                    print(f"  User Title: {error_data['error']['error_user_title']}")
                if error_data.get("error", {}).get("error_user_msg"):
                    print(f"  User Message: {error_data['error']['error_user_msg']}")
                    
            except:
                error_msg = response.text
            
            raise Exception(f"Meta API Error ({response.status_code}): {error_msg}")
        
        return response.json()
        
    except Exception as e:
        error_detail = str(e)
        print(f"create_meta_adcreative error: {error_detail}")
        raise

def create_meta_ad(ad_account_id: str, access_token: str, ad_data: dict):
    """Create an ad in Meta Ads API"""
    try:
        # Check for duplicate 'act_' prefix
        print(f"\n=== DEBUG: Creating Meta Ad ===")
        print(f"Original ad_account_id: {ad_account_id}")
        
        if ad_account_id.startswith('act_'):
            account_id_for_api = ad_account_id
        else:
            account_id_for_api = f"act_{ad_account_id}"
        
        url = f"{FB_GRAPH_API_BASE}/{account_id_for_api}/ads"
        print(f"Final URL: {url}")
        
        params = {"access_token": access_token}
        
        for key, value in ad_data.items():
            if value is not None and key != "access_token":
                if isinstance(value, dict):
                    params[key] = json.dumps(value)
                else:
                    params[key] = str(value)
        
        safe_params = {k: '***' if k == 'access_token' else v for k, v in params.items()}
        print(f"Params: {safe_params}")
        
        response = requests.post(url, data=params, timeout=60)
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code != 200:
            error_detail = "Unknown error"
            try:
                error_data = response.json()
                error_detail = error_data.get("error", {}).get("message", "Unknown error")
                
                # Add user-friendly message if available
                user_msg = ""
                if error_data.get("error", {}).get("error_user_msg"):
                    user_msg = f" - {error_data['error']['error_user_msg']}"
                elif error_data.get("error", {}).get("error_user_title"):
                    user_msg = f" - {error_data['error']['error_user_title']}"
                
                error_detail = f"{error_detail}{user_msg}"
                
            except:
                error_detail = response.text
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create ad: {error_detail}"
            )
        
        return response.json()
        
    except HTTPException:
        # Re-raise HTTPException so it's not caught by the generic Exception handler
        raise
    except Exception as e:
        error_detail = str(e)
        print(f"create_meta_ad unexpected error: {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create ad: {error_detail}"
        )

def get_meta_insights(ad_account_id: str, access_token: str, params: dict):
    """Get insights from Meta Ads API"""
    try:
        url = f"{FB_GRAPH_API_BASE}/{ad_account_id}/insights"
        
        query_params = {
            "access_token": access_token,
            **params
        }
        
        response = requests.get(url, params=query_params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        error_detail = "Unknown error"
        try:
            error_data = e.response.json()
            error_detail = error_data.get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get insights: {error_detail}"
        )

# Helper to get business account access token
def get_business_account_access_token(business_account_id: uuid.UUID, db: Session) -> str:
    """Get access token from business account"""
    business_account = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.id == business_account_id,
        FacebookBusinessAccount.is_connected == True,
        FacebookBusinessAccount.is_active == True
    ).first()
    
    if not business_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business account not found or not connected"
        )
    
    # Check if token is expired
    if business_account.expires_at and business_account.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access token has expired. Please reconnect the account."
        )
    
    return business_account.access_token
def fetch_ads_library(
    access_token: str,
    search_term: str = None,
    ad_type: str = "ALL",  # must be one of Meta's allowed values
    limit: int = 50,
    ad_reached_countries: list[str] = ["ZW"]
):
    try:
        url = f"{FB_GRAPH_API_BASE}/ads_archive"

        params = {
            "search_terms": search_term,
            "ad_type": ad_type,
            "ad_reached_countries": ad_reached_countries,  
            "limit": limit,
        }

        # Remove null params
        params = {k: v for k, v in params.items() if v is not None}

        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()

        # Filter out political/issue ads
        if "data" in data:
            data["data"] = [
                ad for ad in data["data"]
                if ad.get("ad_type") != "POLITICAL_AND_ISSUE_ADS"
            ]

        return data

    except Exception as e:
        try:
            err_data = e.response.json()
            message = err_data.get("error", {}).get("message")
        except:
            message = str(e)

        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch ads from library: {message}"
        )



# Ad Account Routes
@marketing_router.post("/business/{business_account_id}/sync-ad-accounts", response_model=SuccessMessage)
def sync_ad_accounts_from_business(
    business_account_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Sync Meta ad accounts from a connected business account"""
    try:
        # Get business account access token
        access_token = get_business_account_access_token(business_account_id, db)
        
        # Get ad accounts from Meta API
        ad_accounts_data = get_meta_ad_accounts(access_token)
        
        total_synced = 0
        
        for account_data in ad_accounts_data:
            account_id = account_data.get("id")
            account_name = account_data.get("name")
            account_status = account_data.get("account_status")
            currency = account_data.get("currency")
            timezone_name = account_data.get("timezone_name")
            business_info = account_data.get("business", {})
            
            # Check if ad account already exists
            existing_account = db.query(MetaAdAccount).filter(
                MetaAdAccount.ad_account_id == account_id
            ).first()
            
            if existing_account:
                # Update existing account
                existing_account.account_name = account_name
                existing_account.account_status = account_status
                existing_account.currency = currency
                existing_account.timezone_name = timezone_name
                existing_account.business_id = business_info.get("id")
                existing_account.business_name = business_info.get("name")
                existing_account.access_token = access_token
                existing_account.user_id = existing_account.user_id  # Keep existing
                existing_account.is_connected = True
                existing_account.last_synced_at = datetime.utcnow()
                existing_account.updated_at = datetime.utcnow()
            else:
                # Get user info to get user_id
                try:
                    user_response = requests.get(
                        f"{FB_GRAPH_API_BASE}/me",
                        params={"access_token": access_token}
                    )
                    user_info = user_response.json()
                    user_id = user_info.get("id", "unknown")
                except:
                    user_id = "unknown"
                
                # Create new account
                ad_account = MetaAdAccount(
                    ad_account_id=account_id,
                    account_name=account_name,
                    account_status=account_status,
                    currency=currency,
                    timezone_name=timezone_name,
                    business_id=business_info.get("id"),
                    business_name=business_info.get("name"),
                    access_token=access_token,
                    user_id=user_id,
                    business_account_id=business_account_id,
                    is_connected=True,
                    last_synced_at=datetime.utcnow()
                )
                db.add(ad_account)
            
            total_synced += 1
        
        db.commit()
        
        # Start background task to sync campaigns for new accounts
        background_tasks.add_task(sync_campaigns_background, db, business_account_id)
        
        return SuccessMessage(
            success=True,
            message=f"Synced {total_synced} ad accounts",
            data={"synced_count": total_synced}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync ad accounts: {str(e)}"
        )

def sync_campaigns_background(db: Session, business_account_id: uuid.UUID):
    """Background task to sync campaigns for ad accounts"""
    try:
        # Get ad accounts for this business account
        ad_accounts = db.query(MetaAdAccount).filter(
            MetaAdAccount.business_account_id == business_account_id,
            MetaAdAccount.is_connected == True,
            MetaAdAccount.is_active == True
        ).all()
        
        for ad_account in ad_accounts:
            try:
                sync_campaigns_for_account(ad_account, db)
            except Exception as e:
                print(f"Failed to sync campaigns for ad account {ad_account.id}: {str(e)}")
                continue
    except Exception as e:
        print(f"Background sync failed: {str(e)}")

def sync_campaigns_for_account(ad_account: MetaAdAccount, db: Session):
    """Sync campaigns for a specific ad account"""
    try:
        # Get campaigns from Meta API
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/{ad_account.ad_account_id}/campaigns",
            params={
                "access_token": ad_account.access_token,
                "fields": "id,name,objective,status,special_ad_categories,buying_type,daily_budget,lifetime_budget,start_time,stop_time,bid_strategy,created_time,updated_time,effective_status"
            }
        )
        
        if response.status_code != 200:
            return
        
        campaigns_data = response.json().get("data", [])
        
        for campaign_data in campaigns_data:
            campaign_id = campaign_data.get("id")
            
            # Check if campaign already exists
            existing_campaign = db.query(MetaCampaign).filter(
                MetaCampaign.campaign_id == campaign_id
            ).first()
            
            # Parse dates
            start_time = None
            stop_time = None
            created_time = None
            updated_time = None
            
            if campaign_data.get("start_time"):
                start_time = datetime.fromisoformat(campaign_data.get("start_time").replace("Z", "+00:00"))
            if campaign_data.get("stop_time"):
                stop_time = datetime.fromisoformat(campaign_data.get("stop_time").replace("Z", "+00:00"))
            if campaign_data.get("created_time"):
                created_time = datetime.fromisoformat(campaign_data.get("created_time").replace("Z", "+00:00"))
            if campaign_data.get("updated_time"):
                updated_time = datetime.fromisoformat(campaign_data.get("updated_time").replace("Z", "+00:00"))
            
            campaign_info = {
                "campaign_id": campaign_id,
                "ad_account_id": ad_account.id,
                "name": campaign_data.get("name", "Unnamed Campaign"),
                "objective": campaign_data.get("objective", "LINK_CLICKS"),
                "status": campaign_data.get("status", "PAUSED"),
                "special_ad_categories": campaign_data.get("special_ad_categories"),
                "buying_type": campaign_data.get("buying_type", "AUCTION"),
                "daily_budget": campaign_data.get("daily_budget"),
                "lifetime_budget": campaign_data.get("lifetime_budget"),
                "start_time": start_time,
                "stop_time": stop_time,
                "bid_strategy": campaign_data.get("bid_strategy"),
                "created_time": created_time,
                "updated_time": updated_time,
                "effective_status": campaign_data.get("effective_status"),
                "last_synced_at": datetime.utcnow(),
                "is_active": campaign_data.get("effective_status") not in ["DELETED", "ARCHIVED"]
            }
            
            if existing_campaign:
                # Update existing campaign
                for key, value in campaign_info.items():
                    if value is not None:
                        setattr(existing_campaign, key, value)
                existing_campaign.updated_at = datetime.utcnow()
            else:
                # Create new campaign
                campaign = MetaCampaign(**campaign_info)
                db.add(campaign)
        
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Failed to sync campaigns: {str(e)}")

@marketing_router.get("/ad-accounts", response_model=MetaAdAccountListResponse)
def get_ad_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    business_account_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db)
):
    """Get all Meta ad accounts"""
    query = db.query(MetaAdAccount).filter(MetaAdAccount.is_connected == True)
    
    if business_account_id:
        query = query.filter(MetaAdAccount.business_account_id == business_account_id)
    
    # Get count first
    total_count = query.count()
    
    # Get paginated results
    ad_accounts = query.offset(skip).limit(limit).all()
    
    # Add statistics to each account
    ad_accounts_with_stats = []
    for account in ad_accounts:
        campaign_count = db.query(MetaCampaign).filter(
            MetaCampaign.ad_account_id == account.id,
            MetaCampaign.is_active == True
        ).count()
        
        active_campaign_count = db.query(MetaCampaign).filter(
            MetaCampaign.ad_account_id == account.id,
            MetaCampaign.status == "ACTIVE",
            MetaCampaign.is_active == True
        ).count()
        
        account_dict = MetaAdAccountResponse.model_validate(account).model_dump()
        account_dict["campaign_count"] = campaign_count
        account_dict["active_campaign_count"] = active_campaign_count
        
        ad_accounts_with_stats.append(account_dict)
    
    return MetaAdAccountListResponse(
        ad_accounts=ad_accounts_with_stats,
        total_count=total_count
    )

@marketing_router.get("/ad-accounts/{account_id}", response_model=MetaAdAccountResponse)
def get_ad_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific Meta ad account"""
    ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == account_id).first()
    
    if not ad_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad account not found"
        )
    
    # Add statistics
    campaign_count = db.query(MetaCampaign).filter(
        MetaCampaign.ad_account_id == ad_account.id,
        MetaCampaign.is_active == True
    ).count()
    
    active_campaign_count = db.query(MetaCampaign).filter(
        MetaCampaign.ad_account_id == ad_account.id,
        MetaCampaign.status == "ACTIVE",
        MetaCampaign.is_active == True
    ).count()
    
    response = MetaAdAccountResponse.model_validate(ad_account)
    response.campaign_count = campaign_count
    response.active_campaign_count = active_campaign_count
    
    return response

# Campaign Routes
@marketing_router.post("/ad-accounts/{account_id}/campaigns", response_model=MetaCampaignResponse)
def create_campaign(
    account_id: uuid.UUID,
    campaign_data: MetaCreateCampaignRequest,
    db: Session = Depends(get_db)
):
    """Create a new Meta campaign or save as draft"""
    # Get the ad account
    ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == account_id).first()

    if not ad_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad account not found"
        )

    # If saving as draft, don't need to check connection
    if campaign_data.save_as_draft:
        # Save as draft without publishing to Meta
        campaign = MetaCampaign(
            campaign_id=f"DRAFT_{uuid.uuid4().hex[:12].upper()}",
            ad_account_id=ad_account.id,
            name=campaign_data.name,
            objective=campaign_data.objective.value,
            status="DRAFT",
            special_ad_categories=campaign_data.special_ad_categories or ["NONE"],
            buying_type=campaign_data.buying_type,
            daily_budget=campaign_data.daily_budget,
            lifetime_budget=campaign_data.lifetime_budget,
            start_time=campaign_data.start_time,
            stop_time=campaign_data.stop_time,
            bid_strategy=None,
            created_time=datetime.utcnow(),
            updated_time=datetime.utcnow(),
            effective_status="DRAFT",
            is_draft=True,
            draft_data={
                "original_request": campaign_data.model_dump(mode='json'),
                "created_at": datetime.utcnow().isoformat()
            },
            is_active=True
        )

        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        return campaign

    if not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )

    try:
        # Prepare campaign data for Meta API in curl -F format
        meta_campaign_data = {
            "name": campaign_data.name,
            "objective": campaign_data.objective.value,
            "status": campaign_data.status.value,
            "buying_type": campaign_data.buying_type,
        }

        # Add special_ad_categories - Meta API requires this field
        # If not provided, default to ["NONE"]
        if campaign_data.special_ad_categories:
            meta_campaign_data["special_ad_categories"] = json.dumps(campaign_data.special_ad_categories)
        else:
            meta_campaign_data["special_ad_categories"] = '["NONE"]'

        # Add optional fields if they exist
        if campaign_data.daily_budget:
            meta_campaign_data["daily_budget"] = str(campaign_data.daily_budget)

        if campaign_data.lifetime_budget:
            meta_campaign_data["lifetime_budget"] = str(campaign_data.lifetime_budget)

        if campaign_data.start_time:
            meta_campaign_data["start_time"] = str(int(campaign_data.start_time.timestamp()))

        if campaign_data.stop_time:
            meta_campaign_data["stop_time"] = str(int(campaign_data.stop_time.timestamp()))

        # Create campaign in Meta using form data
        result = create_meta_campaign(
            ad_account.ad_account_id,
            ad_account.access_token,
            meta_campaign_data
        )

        # Save to database
        campaign = MetaCampaign(
            campaign_id=result.get("id"),
            ad_account_id=ad_account.id,
            name=campaign_data.name,
            objective=campaign_data.objective.value,
            status=campaign_data.status.value,
            special_ad_categories=campaign_data.special_ad_categories or ["NONE"],
            buying_type=campaign_data.buying_type,
            daily_budget=campaign_data.daily_budget,
            lifetime_budget=campaign_data.lifetime_budget,
            start_time=campaign_data.start_time,
            stop_time=campaign_data.stop_time,
            bid_strategy=None,  # Will be synced later
            created_time=datetime.utcnow(),
            updated_time=datetime.utcnow(),
            effective_status=campaign_data.status.value,
            last_synced_at=datetime.utcnow(),
            is_draft=False,
            published_at=datetime.utcnow(),
            is_active=True
        )

        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        
        return MetaCampaignResponse.model_validate(campaign)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign: {str(e)}"
        )
    
@marketing_router.get("/campaigns", response_model=MetaCampaignListResponse)
def get_campaigns(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    account_id: Optional[uuid.UUID] = None,
    business_account_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    objective: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all Meta campaigns"""
    query = db.query(MetaCampaign).join(MetaAdAccount).filter(MetaCampaign.is_active == True)
    
    if account_id:
        query = query.filter(MetaCampaign.ad_account_id == account_id)
    
    if business_account_id:
        query = query.filter(MetaAdAccount.business_account_id == business_account_id)
    
    if status:
        query = query.filter(MetaCampaign.status == status)
    
    if objective:
        query = query.filter(MetaCampaign.objective == objective)
    
    # Get count first
    total_count = query.count()
    
    # Get paginated results
    campaigns = query.offset(skip).limit(limit).all()
    
    # Add statistics to each campaign
    campaigns_with_stats = []
    for campaign in campaigns:
        ad_set_count = db.query(MetaAdSet).filter(
            MetaAdSet.campaign_id == campaign.id,
            MetaAdSet.is_active == True
        ).count()
        
        ad_count = db.query(MetaAd).filter(
            MetaAd.campaign_id == campaign.id,
            MetaAd.is_active == True
        ).count()
        
        # Get insights summary
        insights_query = db.query(
            func.sum(MetaAdInsight.spend).label("spend"),
            func.sum(MetaAdInsight.impressions).label("impressions"),
            func.sum(MetaAdInsight.clicks).label("clicks")
        ).join(MetaAd, MetaAd.id == MetaAdInsight.ad_id).filter(
            MetaAd.campaign_id == campaign.id
        )
        
        insights = insights_query.first()
        
        campaign_dict = MetaCampaignResponse.model_validate(campaign).model_dump()
        campaign_dict["ad_set_count"] = ad_set_count
        campaign_dict["ad_count"] = ad_count
        campaign_dict["spend"] = insights.spend or 0.0
        campaign_dict["impressions"] = insights.impressions or 0
        campaign_dict["clicks"] = insights.clicks or 0
        
        campaigns_with_stats.append(campaign_dict)
    
    return MetaCampaignListResponse(
        campaigns=campaigns_with_stats,
        total_count=total_count
    )

@marketing_router.get("/campaigns/{campaign_id}", response_model=MetaCampaignResponse)
def get_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific Meta campaign"""
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
    
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    
    # Add statistics
    ad_set_count = db.query(MetaAdSet).filter(
        MetaAdSet.campaign_id == campaign.id,
        MetaAdSet.is_active == True
    ).count()
    
    ad_count = db.query(MetaAd).filter(
        MetaAd.campaign_id == campaign.id,
        MetaAd.is_active == True
    ).count()
    
    # Get insights summary
    insights_query = db.query(
        func.sum(MetaAdInsight.spend).label("spend"),
        func.sum(MetaAdInsight.impressions).label("impressions"),
        func.sum(MetaAdInsight.clicks).label("clicks")
    ).join(MetaAd, MetaAd.id == MetaAdInsight.ad_id).filter(
        MetaAd.campaign_id == campaign.id
    )
    
    insights = insights_query.first()
    
    response = MetaCampaignResponse.model_validate(campaign)
    response.ad_set_count = ad_set_count
    response.ad_count = ad_count
    response.spend = insights.spend or 0.0
    response.impressions = insights.impressions or 0
    response.clicks = insights.clicks or 0
    
    return response

@marketing_router.put("/campaigns/{campaign_id}", response_model=MetaCampaignResponse)
def update_campaign(
    campaign_id: uuid.UUID,
    update_data: MetaCampaignUpdate,
    db: Session = Depends(get_db)
):
    """Update a Meta campaign"""
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
    
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    
    # Get the ad account
    ad_account = campaign.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        # Prepare update data for Meta API
        meta_update_data = {}
        
        if update_data.name:
            meta_update_data["name"] = update_data.name
        
        if update_data.status:
            meta_update_data["status"] = update_data.status.value
        
        if update_data.daily_budget is not None:
            meta_update_data["daily_budget"] = str(update_data.daily_budget)
        
        if update_data.lifetime_budget is not None:
            meta_update_data["lifetime_budget"] = str(update_data.lifetime_budget)
        
        if update_data.start_time:
            meta_update_data["start_time"] = int(update_data.start_time.timestamp())
        
        if update_data.stop_time:
            meta_update_data["stop_time"] = int(update_data.stop_time.timestamp())
        
        # Update in Meta
        if meta_update_data:
            url = f"{FB_GRAPH_API_BASE}/{campaign.campaign_id}"
            meta_update_data["access_token"] = ad_account.access_token
            
            response = requests.post(url, data=meta_update_data)
            response.raise_for_status()
        
        # Update in database
        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(campaign, key, value)
        
        campaign.updated_at = datetime.utcnow()
        campaign.updated_time = datetime.utcnow()
        
        db.commit()
        db.refresh(campaign)
        
        return MetaCampaignResponse.model_validate(campaign)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update campaign: {str(e)}"
        )

@marketing_router.post("/campaigns/{campaign_id}/sync", response_model=SuccessMessage)
def sync_campaign_data(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Sync campaign data from Meta API"""
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
    
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    
    ad_account = campaign.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        # Get campaign data from Meta API
        response = requests.get(
            f"{FB_GRAPH_API_BASE}/{campaign.campaign_id}",
            params={
                "access_token": ad_account.access_token,
                "fields": "id,name,objective,status,special_ad_categories,buying_type,daily_budget,lifetime_budget,start_time,stop_time,bid_strategy,created_time,updated_time,effective_status"
            }
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch campaign data from Meta"
            )
        
        campaign_data = response.json()
        
        # Parse dates
        start_time = None
        stop_time = None
        created_time = None
        updated_time = None
        
        if campaign_data.get("start_time"):
            start_time = datetime.fromisoformat(campaign_data.get("start_time").replace("Z", "+00:00"))
        if campaign_data.get("stop_time"):
            stop_time = datetime.fromisoformat(campaign_data.get("stop_time").replace("Z", "+00:00"))
        if campaign_data.get("created_time"):
            created_time = datetime.fromisoformat(campaign_data.get("created_time").replace("Z", "+00:00"))
        if campaign_data.get("updated_time"):
            updated_time = datetime.fromisoformat(campaign_data.get("updated_time").replace("Z", "+00:00"))
        
        # Update campaign
        campaign.name = campaign_data.get("name", campaign.name)
        campaign.objective = campaign_data.get("objective", campaign.objective)
        campaign.status = campaign_data.get("status", campaign.status)
        campaign.special_ad_categories = campaign_data.get("special_ad_categories")
        campaign.daily_budget = campaign_data.get("daily_budget")
        campaign.lifetime_budget = campaign_data.get("lifetime_budget")
        campaign.start_time = start_time
        campaign.stop_time = stop_time
        campaign.bid_strategy = campaign_data.get("bid_strategy")
        campaign.effective_status = campaign_data.get("effective_status")
        campaign.updated_time = updated_time
        campaign.last_synced_at = datetime.utcnow()
        campaign.updated_at = datetime.utcnow()
        
        db.commit()
        
        return SuccessMessage(
            success=True,
            message="Campaign data synced successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync campaign: {str(e)}"
        )

# Ad Set Routes
@marketing_router.post("/campaigns/{campaign_id}/adsets", response_model=MetaAdSetResponse)
def create_ad_set(
    campaign_id: uuid.UUID,
    adset_data: MetaCreateAdSetRequest,
    db: Session = Depends(get_db)
):
    """Create a new ad set"""
    # Get the campaign
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
    
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    
    ad_account = campaign.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        # Prepare ad set data for Meta API - SIMPLIFIED VERSION
        meta_adset_data = {
            "name": adset_data.name,
            "campaign_id": campaign.campaign_id,
            "status": adset_data.status.value,
        }
        
        # REQUIRED FIELDS per Meta documentation
        # if adset_data.daily_budget:
        #     meta_adset_data["daily_budget"] = str(adset_data.daily_budget)
        # else:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail="daily_budget is required"
        #     )
        
        if adset_data.targeting:
            # Ensure targeting is properly formatted
            if isinstance(adset_data.targeting, dict):
                meta_adset_data["targeting"] = json.dumps(adset_data.targeting)
            else:
                meta_adset_data["targeting"] = str(adset_data.targeting)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="targeting is required"
            )
        
        # OPTIONAL FIELDS - only add if provided
        if adset_data.optimization_goal:
            meta_adset_data["optimization_goal"] = adset_data.optimization_goal.value
        
        if adset_data.billing_event:
            meta_adset_data["billing_event"] = adset_data.billing_event.value
        
        if adset_data.lifetime_budget:
            meta_adset_data["lifetime_budget"] = str(adset_data.lifetime_budget)
        
        if adset_data.bid_amount:
            meta_adset_data["bid_amount"] = str(adset_data.bid_amount)
        
        if adset_data.start_time:
            # Convert datetime to UNIX timestamp
            meta_adset_data["start_time"] = str(int(adset_data.start_time.timestamp()))
        
        if adset_data.end_time:
            # Convert datetime to UNIX timestamp
            meta_adset_data["end_time"] = str(int(adset_data.end_time.timestamp()))
        
        # Debug: Print what we're sending
        print(f"\n=== Sending to Meta API ===")
        print(f"Campaign ID from DB: {campaign.campaign_id}")
        print(f"Ad Account ID: {ad_account.ad_account_id}")
        print(f"Data being sent: {meta_adset_data}")
        print("==========================\n")
        
        # Create ad set in Meta
        result = create_meta_adset(
            ad_account.ad_account_id,  # This should be the numeric ad account ID
            ad_account.access_token,
            meta_adset_data
        )
        
        # Save to database
        ad_set = MetaAdSet(
            adset_id=result.get("id"),
            ad_account_id=ad_account.id,
            campaign_id=campaign.id,
            name=adset_data.name,
            status=adset_data.status.value,
            optimization_goal=adset_data.optimization_goal.value if adset_data.optimization_goal else None,
            billing_event=adset_data.billing_event.value if adset_data.billing_event else None,
            daily_budget=adset_data.daily_budget,
            lifetime_budget=adset_data.lifetime_budget,
            bid_amount=adset_data.bid_amount,
            start_time=adset_data.start_time,
            end_time=adset_data.end_time,
            targeting=adset_data.targeting,
            created_time=datetime.utcnow(),
            updated_time=datetime.utcnow(),
            effective_status=adset_data.status.value,
            last_synced_at=datetime.utcnow(),
            is_active=True
        )
        
        db.add(ad_set)
        db.commit()
        db.refresh(ad_set)
        
        return MetaAdSetResponse.model_validate(ad_set)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create ad set: {str(e)}"
        )

@marketing_router.get("/adsets", response_model=MetaAdSetListResponse)
def get_ad_sets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    campaign_id: Optional[uuid.UUID] = None,
    account_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all ad sets"""
    query = db.query(MetaAdSet).filter(MetaAdSet.is_active == True)
    
    if campaign_id:
        query = query.filter(MetaAdSet.campaign_id == campaign_id)
    
    if account_id:
        query = query.filter(MetaAdSet.ad_account_id == account_id)
    
    if status:
        query = query.filter(MetaAdSet.status == status)
    
    # Get count first
    total_count = query.count()
    
    # Get paginated results
    ad_sets = query.offset(skip).limit(limit).all()
    
    # Add statistics to each ad set
    ad_sets_with_stats = []
    for ad_set in ad_sets:
        ad_count = db.query(MetaAd).filter(
            MetaAd.adset_id == ad_set.id,
            MetaAd.is_active == True
        ).count()
        
        # Get insights summary
        insights_query = db.query(
            func.sum(MetaAdInsight.spend).label("spend"),
            func.sum(MetaAdInsight.impressions).label("impressions"),
            func.sum(MetaAdInsight.clicks).label("clicks")
        ).join(MetaAd, MetaAd.id == MetaAdInsight.ad_id).filter(
            MetaAd.adset_id == ad_set.id
        )
        
        insights = insights_query.first()
        
        ad_set_dict = MetaAdSetResponse.model_validate(ad_set).model_dump()
        ad_set_dict["ad_count"] = ad_count
        ad_set_dict["spend"] = insights.spend or 0.0
        ad_set_dict["impressions"] = insights.impressions or 0
        ad_set_dict["clicks"] = insights.clicks or 0
        
        ad_sets_with_stats.append(ad_set_dict)
    
    return MetaAdSetListResponse(
        ad_sets=ad_sets_with_stats,
        total_count=total_count
    )

# Ad Creative Routes
@marketing_router.post("/ad-accounts/{account_id}/creatives", response_model=MetaAdCreativeResponse)
def create_ad_creative(
    account_id: uuid.UUID,
    creative_data: MetaCreateCreativeRequest,
    db: Session = Depends(get_db)
):
    """Create a new ad creative"""
    # Get the ad account
    ad_account = db.query(MetaAdAccount).filter(MetaAdAccount.id == account_id).first()
    
    if not ad_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad account not found"
        )
    
    if not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        print(f"\n=== DEBUG: Starting Creative Creation ===")
        print(f"Ad Account ID: {ad_account.ad_account_id}")
        print(f"Creative Type: {creative_data.creative_type}")
        print(f"Image URL: {creative_data.image_url}")
        
        # First, check if we have a valid page_id
        page_id = ad_account.business_id
        if not page_id:
            # Try to get a page ID from the user's pages
            try:
                print("Attempting to fetch user pages...")
                pages_response = requests.get(
                    f"{FB_GRAPH_API_BASE}/me/accounts",
                    params={"access_token": ad_account.access_token},
                    timeout=30
                )
                print(f"Pages response status: {pages_response.status_code}")
                
                if pages_response.status_code == 200:
                    pages_data = pages_response.json()
                    print(f"Pages data: {pages_data}")
                    
                    if "data" in pages_data and pages_data["data"]:
                        page_id = pages_data["data"][0]["id"]
                        print(f"Found page ID: {page_id}")
                    else:
                        print("No pages found in response")
                else:
                    print(f"Failed to fetch pages: {pages_response.text}")
            except Exception as e:
                print(f"Error fetching pages: {str(e)}")
                pass
        
        if not page_id:
            # If no page_id found, try using the ad account ID as a fallback
            print(f"No page_id found, using ad account ID as fallback")
            page_id = ad_account.ad_account_id
        
        # For image creatives, handle image upload properly
        image_hash = None
        if creative_data.creative_type == "IMAGE" and creative_data.image_url:
            try:
                print(f"\n=== DEBUG: Image Upload Process ===")
                print(f"Downloading image from: {creative_data.image_url}")
                
                # Download the image
                image_response = requests.get(creative_data.image_url, timeout=30)
                print(f"Image download status: {image_response.status_code}")
                print(f"Image size: {len(image_response.content) if image_response.status_code == 200 else 'N/A'} bytes")
                
                if image_response.status_code == 200:
                    # Upload image to Facebook
                    upload_url = f"{FB_GRAPH_API_BASE}/{ad_account.ad_account_id}/adimages"
                    print(f"Upload URL: {upload_url}")
                    
                    # Prepare the file upload
                    files = {
                        'file': ('ad_image.jpg', image_response.content, 'image/jpeg')
                    }
                    
                    params = {
                        "access_token": ad_account.access_token,
                    }
                    
                    print(f"Sending upload request...")
                    upload_response = requests.post(
                        upload_url,
                        files=files,
                        params=params,
                        timeout=60
                    )
                    
                    print(f"Upload response status: {upload_response.status_code}")
                    print(f"Upload response: {upload_response.text}")
                    
                    if upload_response.status_code == 200:
                        upload_data = upload_response.json()
                        print(f"Upload data JSON: {upload_data}")
                        
                        # Parse different response formats
                        image_hash = extract_image_hash(upload_data)
                        
                        if image_hash:
                            print(f"✓ Successfully extracted image hash: {image_hash}")
                        else:
                            print(f"✗ Could not extract image hash from response")
                            print(f"Full response structure: {upload_data}")
                            
                            # For testing, create a dummy hash
                            image_hash = f"test_hash_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                            print(f"Using test hash: {image_hash}")
                    else:
                        print(f"✗ Image upload failed")
                        # Create a test hash for development
                        image_hash = f"dev_hash_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                else:
                    print(f"✗ Failed to download image: Status {image_response.status_code}")
                    # Create a test hash for development
                    image_hash = f"url_hash_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                    
            except Exception as e:
                print(f"✗ Image handling error: {str(e)}")
                print(f"Traceback: {traceback.format_exc()}")
                # Create a test hash for development
                image_hash = f"error_hash_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Prepare creative data for Meta API
        meta_creative_data = {
            "access_token": ad_account.access_token,
            "name": creative_data.title or f"Creative {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        }
        
        # Build the correct object_story_spec based on creative type
        if creative_data.creative_type == "IMAGE":
            print(f"\n=== DEBUG: Building IMAGE Creative ===")
            
            # For link ads with image
            link_data = {
                "link": creative_data.url or "https://example.com",
                "message": creative_data.body or "",
                "name": creative_data.title or "",
                "description": creative_data.body or "",
                "call_to_action": {
                    "type": creative_data.call_to_action_type or "LEARN_MORE"
                }
            }
            
            # FIX THIS: Use "image_hash" not "picture"
            if image_hash:
                link_data["image_hash"] = image_hash  # <-- CHANGE THIS LINE
                print(f"Adding image_hash: {image_hash}")  # <-- UPDATE THIS LOG TOO
            else:
                print(f"Warning: No image hash available")
            
            object_story_spec = {
                "page_id": page_id,
                "link_data": link_data
            }
            
            print(f"Object Story Spec: {object_story_spec}")
            meta_creative_data["object_story_spec"] = json.dumps(object_story_spec)
            
        elif creative_data.creative_type == "VIDEO":
            print(f"\n=== DEBUG: Building VIDEO Creative ===")
            # For video creatives (simplified - requires proper video upload)
            object_story_spec = {
                "page_id": page_id,
                "video_data": {
                    "video_id": creative_data.video_url or "123456789",  # Should be actual video ID
                    "title": creative_data.title or "",
                    "message": creative_data.body or "",
                    "call_to_action": {
                        "type": creative_data.call_to_action_type or "LEARN_MORE"
                    }
                }
            }
            meta_creative_data["object_story_spec"] = json.dumps(object_story_spec)
            
        else:
            print(f"\n=== DEBUG: Building DEFAULT Creative ===")
            # Default to simple link ad
            object_story_spec = {
                "page_id": page_id,
                "link_data": {
                    "link": creative_data.url or "https://example.com",
                    "message": creative_data.body or "",
                    "name": creative_data.title or "",
                    "description": creative_data.body or "",
                    "call_to_action": {
                        "type": creative_data.call_to_action_type or "LEARN_MORE"
                    }
                }
            }
            
            if image_hash:
                # Correct field name according to Meta API:
                object_story_spec["link_data"]["image_hash"] = image_hash
            
            meta_creative_data["object_story_spec"] = json.dumps(object_story_spec)
        
        # Debug: Print what we're sending
        print(f"\n=== DEBUG: Final Request Data ===")
        print(f"Page ID: {page_id}")
        print(f"Creative type: {creative_data.creative_type}")
        print(f"Object Story Spec JSON: {meta_creative_data.get('object_story_spec')}")
        print("===================================\n")
        
        # Create creative in Meta
        print("Calling create_meta_adcreative...")
        result = create_meta_adcreative(
            ad_account.ad_account_id,
            ad_account.access_token,
            meta_creative_data
        )
        
        print(f"✓ Meta API Response: {result}")
        
        # Save to database
        creative = MetaAdCreative(
            creative_id=result.get("id"),
            ad_account_id=ad_account.id,
            creative_type=creative_data.creative_type.value,
            title=creative_data.title,
            body=creative_data.body,
            image_url=creative_data.image_url,
            image_hash=image_hash,
            video_url=creative_data.video_url,
            video_id=creative_data.video_id,
            url=creative_data.url,
            call_to_action_type=creative_data.call_to_action_type,
            created_time=datetime.utcnow(),
            updated_time=datetime.utcnow(),
            last_synced_at=datetime.utcnow(),
            is_active=True
        )
        
        db.add(creative)
        db.commit()
        db.refresh(creative)
        
        print(f"✓ Creative saved to database with ID: {creative.id}")
        
        return MetaAdCreativeResponse.model_validate(creative)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"\n✗ ERROR in create_ad_creative: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create ad creative: {str(e)}"
        )


def extract_image_hash(upload_data: dict) -> Optional[str]:
    """Extract image hash from Facebook's upload response"""
    try:
        # Try different response formats
        
        # Format 1: {"images": {"<hash>": "image_hash_here"}}
        if "images" in upload_data:
            images = upload_data["images"]
            if isinstance(images, dict):
                # Get the first value which should contain the hash
                for key, value in images.items():
                    if isinstance(value, dict) and "hash" in value:
                        return value["hash"]
                    elif isinstance(value, str):
                        # The key might be the hash itself
                        return key
        
        # Format 2: {"hash": "image_hash_here"}
        if "hash" in upload_data:
            return upload_data["hash"]
        
        # Format 3: {"data": [{"hash": "image_hash_here"}]}
        if "data" in upload_data and isinstance(upload_data["data"], list):
            if upload_data["data"] and isinstance(upload_data["data"][0], dict):
                return upload_data["data"][0].get("hash")
        
        # Format 4: Nested structure with hash
        # Try to find hash anywhere in the nested structure
        def find_hash(obj):
            if isinstance(obj, dict):
                if "hash" in obj:
                    return obj["hash"]
                for value in obj.values():
                    result = find_hash(value)
                    if result:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = find_hash(item)
                    if result:
                        return result
            return None
        
        hash_value = find_hash(upload_data)
        if hash_value:
            return hash_value
        
        # Format 5: The entire response might be the hash
        if isinstance(upload_data, str) and len(upload_data) > 10:
            return upload_data
        
        return None
        
    except Exception as e:
        print(f"Error extracting image hash: {str(e)}")
        return None
    
@marketing_router.get("/creatives", response_model=MetaAdCreativeListResponse)
def get_ad_creatives(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    account_id: Optional[uuid.UUID] = None,
    creative_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all ad creatives"""
    query = db.query(MetaAdCreative).filter(MetaAdCreative.is_active == True)
    
    if account_id:
        query = query.filter(MetaAdCreative.ad_account_id == account_id)
    
    if creative_type:
        query = query.filter(MetaAdCreative.creative_type == creative_type)
    
    # Get count first
    total_count = query.count()
    
    # Get paginated results
    creatives = query.offset(skip).limit(limit).all()
    
    # Add usage statistics
    creatives_with_stats = []
    for creative in creatives:
        ad_count = db.query(MetaAd).filter(
            MetaAd.creative_id == creative.id,
            MetaAd.is_active == True
        ).count()
        
        creative_dict = MetaAdCreativeResponse.model_validate(creative).model_dump()
        creative_dict["ad_count"] = ad_count
        creatives_with_stats.append(creative_dict)
    
    return MetaAdCreativeListResponse(
        ad_creatives=creatives_with_stats,
        total_count=total_count
    )

# Ad Routes
@marketing_router.post("/adsets/{adset_id}/ads", response_model=MetaAdResponse)
def create_ad(
    adset_id: uuid.UUID,
    ad_data: MetaCreateAdRequest,
    db: Session = Depends(get_db)
):
    """Create a new ad, with or without a pre-existing creative ID."""
    
    # Get the ad set
    ad_set = db.query(MetaAdSet).filter(MetaAdSet.id == adset_id).first()
    
    if not ad_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad set not found"
        )
    
    campaign = ad_set.campaign
    ad_account = ad_set.ad_account
    
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        print(f"\n=== DEBUG: Creating Ad ===")
        print(f"Ad Set ID: {ad_set.adset_id}")
        print(f"Ad Name: {ad_data.name}")
        print(f"Ad Status: {ad_data.status}")
        
        # Prepare the base parameters for the Meta API
        meta_ad_data = {
            "name": ad_data.name,
            "adset_id": ad_set.adset_id,
            "status": ad_data.status.value,
        }
        
        # Add optional fields
        if ad_data.tracking_specs:
            meta_ad_data["tracking_specs"] = json.dumps(ad_data.tracking_specs)
        
        if ad_data.ad_format:
            meta_ad_data["ad_format"] = ad_data.ad_format
        
        # --- PATH A: Use a pre-existing creative from our DB ---
        if ad_data.creative_id:
            print(f"PATH A: Using existing creative ID: {ad_data.creative_id}")
            creative = db.query(MetaAdCreative).filter(MetaAdCreative.id == ad_data.creative_id).first()
            if not creative:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Creative not found"
                )
            meta_ad_data["creative"] = json.dumps({"creative_id": creative.creative_id})
            print(f"Using Meta creative ID: {creative.creative_id}")
        
        # --- PATH B: Promote an existing Facebook Post ---
        elif ad_data.existing_post_id:
            print(f"PATH B: Promoting existing post ID: {ad_data.existing_post_id}")
            # The 'creative' parameter uses 'object_story_id' for existing posts
            meta_ad_data["creative"] = json.dumps({"object_story_id": ad_data.existing_post_id})
        
        # --- PATH C: Create a simple link ad with basic creative details ---
        elif ad_data.creative_link:
            print(f"PATH C: Creating simple link ad with URL: {ad_data.creative_link}")
            
            # We need a Facebook Page ID. Use the one from the ad account or fetch the first available.
            page_id = ad_account.business_id
            if not page_id:
                try:
                    print("Fetching available pages...")
                    pages_resp = requests.get(
                        f"{FB_GRAPH_API_BASE}/me/accounts",
                        params={"access_token": ad_account.access_token},
                        timeout=30
                    )
                    
                    if pages_resp.status_code == 200:
                        pages_data = pages_resp.json()
                        print(f"Pages response: {pages_data}")
                        
                        if "data" in pages_data and pages_data["data"]:
                            page_id = pages_data["data"][0]["id"]
                            print(f"Found page ID: {page_id}")
                        else:
                            print("No pages found in response")
                    else:
                        print(f"Failed to fetch pages: {pages_resp.text}")
                except Exception as e:
                    print(f"Error fetching pages: {str(e)}")
            
            if not page_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not find a Facebook Page for this ad account. Please connect a Facebook Page first."
                )
            
            # Handle image upload if image_url is provided
            image_hash = None
            if ad_data.image_url:
                try:
                    print(f"Uploading image from URL: {ad_data.image_url}")
                    image_response = requests.get(ad_data.image_url, timeout=30)
                    if image_response.status_code == 200:
                        upload_url = f"{FB_GRAPH_API_BASE}/{ad_account.ad_account_id}/adimages"
                        files = {
                            'file': ('ad_image.jpg', image_response.content, 'image/jpeg')
                        }
                        params = {
                            "access_token": ad_account.access_token,
                        }
                        
                        upload_response = requests.post(upload_url, files=files, params=params, timeout=60)
                        
                        if upload_response.status_code == 200:
                            upload_data = upload_response.json()
                            image_hash = extract_image_hash(upload_data)
                            if image_hash:
                                print(f"✓ Image uploaded successfully, hash: {image_hash}")
                            else:
                                print("⚠ Could not extract image hash from upload response")
                        else:
                            print(f"⚠ Image upload failed: {upload_response.text}")
                    else:
                        print(f"⚠ Failed to download image: {image_response.status_code}")
                except Exception as e:
                    print(f"⚠ Image handling error: {str(e)}")
            
            # Build the creative specification inline
            link_data = {
                "link": ad_data.creative_link,
                "message": ad_data.creative_message or "",
                "name": ad_data.name or "New Ad",
                "description": ad_data.creative_description or "",
                "call_to_action": {
                    "type": ad_data.call_to_action_type or "LEARN_MORE"
                }
            }
            
            # Add image hash if available
            if image_hash:
                link_data["image_hash"] = image_hash
            
            story_spec = {
                "page_id": page_id,
                "link_data": link_data
            }
            
            meta_ad_data["creative"] = json.dumps({"object_story_spec": story_spec})
            print(f"Created object_story_spec with page_id: {page_id}")
        
        # --- If none of the above conditions were met ---
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="To create an ad, provide either: a 'creative_id', an 'existing_post_id', or a 'creative_link'."
            )
        
        # Debug logging of final request data
        print(f"Final Meta API data: {meta_ad_data}")
        
        # IMPORTANT: Try Meta API call separately from database transaction
        meta_response = None
        meta_error = None
        
        try:
            meta_response = create_meta_ad(
                ad_account.ad_account_id,
                ad_account.access_token,
                meta_ad_data
            )
            print(f"✓ Meta API Response: {meta_response}")
        except HTTPException as e:
            meta_error = e
            print(f"Meta API Error: {str(e.detail) if hasattr(e, 'detail') else str(e)}")
        
        # Now handle database save in a clean transaction
        if meta_response:
            # Success case: Meta API worked, save real ad
            ad = MetaAd(
                ad_id=meta_response.get("id"),
                ad_account_id=ad_account.id,
                campaign_id=campaign.id,
                adset_id=ad_set.id,
                creative_id=ad_data.creative_id,
                name=ad_data.name,
                status=ad_data.status.value,
                ad_format=ad_data.ad_format,
                tracking_specs=ad_data.tracking_specs,
                created_time=datetime.utcnow(),
                updated_time=datetime.utcnow(),
                effective_status=ad_data.status.value,
                last_synced_at=datetime.utcnow(),
                is_active=True,
                is_draft=False,
                notes=None,
                draft_data=None,
                published_at=None
            )
        else:
            # Error case: Meta API failed, save as draft
            error_detail = str(meta_error.detail) if hasattr(meta_error, 'detail') else str(meta_error)
            print("⚠ Facebook app is in development mode. Saving as draft ad.")
            
            ad = MetaAd(
                ad_id=f"DRAFT_{uuid.uuid4().hex[:8]}",
                ad_account_id=ad_account.id,
                campaign_id=campaign.id,
                adset_id=ad_set.id,
                creative_id=ad_data.creative_id,
                name=ad_data.name,
                status="PAUSED",
                ad_format=ad_data.ad_format,
                tracking_specs=ad_data.tracking_specs,
                created_time=datetime.utcnow(),
                updated_time=datetime.utcnow(),
                effective_status="DRAFT",
                last_synced_at=datetime.utcnow(),
                is_active=True,
                is_draft=True,
                notes=f"Facebook app development mode error: {error_detail}",
                draft_data={
                    "original_request": meta_ad_data,
                    "original_status": ad_data.status.value,
                    "error": error_detail[:500]  # Limit error length
                },
                published_at=None
            )
        
        db.add(ad)
        db.commit()
        db.refresh(ad)
        
        if ad.is_draft:
            print(f"✓ Ad saved as DRAFT in database with ID: {ad.id}")
            print(f"⚠ Note: This ad was not created on Facebook due to development mode restrictions.")
            print(f"⚠ Once your app is in Live mode, you can publish this draft.")
        else:
            print(f"✓ Ad saved to database with ID: {ad.id}")
            print(f"✓ Ad created on Facebook with ID: {ad.ad_id}")
        
        return MetaAdResponse.model_validate(ad)
        
    except HTTPException:
        # Make sure to rollback on HTTPException
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"\n✗ ERROR in create_ad: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create ad: {str(e)}"
        )
    
@marketing_router.post("/ads/{ad_id}/publish-draft", response_model=MetaAdResponse)
def publish_draft_ad(
    ad_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Publish a draft ad when app is in live mode"""
    ad = db.query(MetaAd).filter(MetaAd.id == ad_id, MetaAd.is_draft == True).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft ad not found"
        )
    
    ad_account = ad.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        # Get the original request data from draft_data
        if not ad.draft_data or "original_request" not in ad.draft_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No original request data found for this draft"
            )
        
        original_request = ad.draft_data["original_request"]
        
        # Create the ad on Facebook
        result = create_meta_ad(
            ad_account.ad_account_id,
            ad_account.access_token,
            original_request
        )
        
        # Update the ad with real Facebook ID
        ad.ad_id = result.get("id")
        ad.is_draft = False
        ad.notes = "Draft published successfully"
        ad.published_at = datetime.utcnow()
        ad.updated_at = datetime.utcnow()
        ad.updated_time = datetime.utcnow()
        
        db.commit()
        db.refresh(ad)
        
        return MetaAdResponse.model_validate(ad)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish draft ad: {str(e)}"
        )
    
@marketing_router.get("/ads", response_model=MetaAdListResponse)
def get_ads(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    campaign_id: Optional[uuid.UUID] = None,
    adset_id: Optional[uuid.UUID] = None,
    account_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all ads"""
    query = db.query(MetaAd).filter(MetaAd.is_active == True)
    
    if campaign_id:
        query = query.filter(MetaAd.campaign_id == campaign_id)
    
    if adset_id:
        query = query.filter(MetaAd.adset_id == adset_id)
    
    if account_id:
        query = query.filter(MetaAd.ad_account_id == account_id)
    
    if status:
        query = query.filter(MetaAd.status == status)
    
    # Get count first
    total_count = query.count()
    
    # Get paginated results
    ads = query.offset(skip).limit(limit).all()
    
    # Add insights to each ad
    ads_with_stats = []
    for ad in ads:
        # Get latest insights
        latest_insight = db.query(MetaAdInsight).filter(
            MetaAdInsight.ad_id == ad.id
        ).order_by(desc(MetaAdInsight.date)).first()
        
        ad_dict = MetaAdResponse.model_validate(ad).model_dump()
        
        if latest_insight:
            ad_dict["spend"] = latest_insight.spend
            ad_dict["impressions"] = latest_insight.impressions
            ad_dict["clicks"] = latest_insight.clicks
            ad_dict["ctr"] = latest_insight.ctr
        else:
            ad_dict["spend"] = 0.0
            ad_dict["impressions"] = 0
            ad_dict["clicks"] = 0
            ad_dict["ctr"] = 0.0
        
        ads_with_stats.append(ad_dict)
    
    return MetaAdListResponse(
        ads=ads_with_stats,
        total_count=total_count
    )

@marketing_router.put("/ads/{ad_id}", response_model=MetaAdResponse)
def update_ad(
    ad_id: uuid.UUID,
    update_data: MetaAdUpdate,
    db: Session = Depends(get_db)
):
    """Update an ad"""
    ad = db.query(MetaAd).filter(MetaAd.id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad not found"
        )
    
    ad_account = ad.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )
    
    try:
        # Prepare update data for Meta API
        meta_update_data = {}
        
        if update_data.name:
            meta_update_data["name"] = update_data.name
        
        if update_data.status:
            meta_update_data["status"] = update_data.status.value
        
        # Update in Meta
        if meta_update_data:
            url = f"{FB_GRAPH_API_BASE}/{ad.ad_id}"
            meta_update_data["access_token"] = ad_account.access_token
            
            response = requests.post(url, data=meta_update_data)
            response.raise_for_status()
        
        # Update in database
        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(ad, key, value)
        
        ad.updated_at = datetime.utcnow()
        ad.updated_time = datetime.utcnow()
        
        db.commit()
        db.refresh(ad)
        
        return MetaAdResponse.model_validate(ad)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update ad: {str(e)}"
        )

# Insights Routes
@marketing_router.post("/insights/sync", response_model=SuccessMessage)
def sync_insights(
    background_tasks: BackgroundTasks,
    days: int = Query(7, ge=1, le=90),
    account_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db)
):
    """Sync insights for all active ads"""
    background_tasks.add_task(sync_insights_background, db, days, account_id)
    
    return SuccessMessage(
        success=True,
        message="Insights sync started in background"
    )

def sync_insights_background(db: Session, days: int, account_id: Optional[uuid.UUID] = None):
    """Background task to sync insights"""
    try:
        # Get date range
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)
        
        # Build query for ads
        query = db.query(MetaAd).join(MetaAdAccount).filter(
            MetaAd.is_active == True,
            MetaAd.status == "ACTIVE",
            MetaAdAccount.is_connected == True
        )
        
        if account_id:
            query = query.filter(MetaAdAccount.id == account_id)
        
        ads = query.all()
        
        for ad in ads:
            try:
                sync_ad_insights(ad, start_date, end_date, db)
            except Exception as e:
                print(f"Failed to sync insights for ad {ad.id}: {str(e)}")
                continue
    except Exception as e:
        print(f"Background insights sync failed: {str(e)}")

def sync_ad_insights(ad: MetaAd, start_date: date, end_date: date, db: Session):
    """Sync insights for a specific ad"""
    try:
        # Get insights from Meta API
        params = {
            "level": "ad",
            "time_range": json.dumps({
                "since": start_date.strftime("%Y-%m-%d"),
                "until": end_date.strftime("%Y-%m-%d")
            }),
            "fields": "impressions,clicks,spend,cpm,cpc,ctr,frequency,reach,actions,conversions"
        }
        
        insights_data = get_meta_insights(
            ad.ad_account.ad_account_id,
            ad.ad_account.access_token,
            params
        )
        
        insights_list = insights_data.get("data", [])
        
        for insight in insights_list:
            if insight.get("ad_id") != ad.ad_id:
                continue
            
            date_str = insight.get("date_start")
            if not date_str:
                continue
            
            insight_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            
            # Check if insight already exists for this date
            existing_insight = db.query(MetaAdInsight).filter(
                MetaAdInsight.ad_id == ad.id,
                MetaAdInsight.date == insight_date
            ).first()
            
            # Parse metrics
            impressions = int(insight.get("impressions", 0))
            clicks = int(insight.get("clicks", 0))
            spend = float(insight.get("spend", 0))
            
            cpm = float(insight.get("cpm", 0))
            cpc = float(insight.get("cpc", 0))
            ctr = float(insight.get("ctr", 0))
            frequency = float(insight.get("frequency", 0))
            reach = int(insight.get("reach", 0))
            
            # Parse conversions from actions
            conversions = 0
            actions = insight.get("actions", [])
            for action in actions:
                if action.get("action_type") in ["offsite_conversion", "purchase", "lead"]:
                    conversions += int(action.get("value", 0))
            
            cost_per_conversion = spend / conversions if conversions > 0 else 0
            conversion_rate = (conversions / clicks * 100) if clicks > 0 else 0
            
            insight_info = {
                "ad_id": ad.id,
                "date": insight_date,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "cpm": cpm,
                "cpc": cpc,
                "ctr": ctr,
                "frequency": frequency,
                "reach": reach,
                "conversions": conversions,
                "cost_per_conversion": cost_per_conversion,
                "conversion_rate": conversion_rate,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "raw_data": insight
            }
            
            if existing_insight:
                # Update existing insight
                for key, value in insight_info.items():
                    setattr(existing_insight, key, value)
                existing_insight.updated_at = datetime.utcnow()
            else:
                # Create new insight
                new_insight = MetaAdInsight(**insight_info)
                db.add(new_insight)
        
        db.commit()
        
    except Exception as e:
        db.rollback()
        print(f"Failed to sync insights for ad {ad.id}: {str(e)}")

@marketing_router.get("/ads/{ad_id}/insights", response_model=MetaAdInsightListResponse)
def get_ad_insights(
    ad_id: uuid.UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get insights for a specific ad"""
    ad = db.query(MetaAd).filter(MetaAd.id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad not found"
        )
    
    query = db.query(MetaAdInsight).filter(MetaAdInsight.ad_id == ad.id)
    
    if start_date:
        query = query.filter(MetaAdInsight.date >= start_date)
    
    if end_date:
        query = query.filter(MetaAdInsight.date <= end_date)
    
    # Default to last 30 days
    if not start_date and not end_date:
        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
        query = query.filter(MetaAdInsight.date >= thirty_days_ago)
    
    # Order by date descending
    query = query.order_by(desc(MetaAdInsight.date))
    
    # Get count first
    total_count = query.count()
    
    # Get paginated results
    insights = query.limit(limit).all()
    
    return MetaAdInsightListResponse(
        insights=[MetaAdInsightResponse.model_validate(insight) for insight in insights],
        total_count=total_count
    )

@marketing_router.get("/campaigns/{campaign_id}/insights/summary", response_model=MetaInsightsSummary)
def get_campaign_insights_summary(
    campaign_id: uuid.UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Get insights summary for a campaign"""
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
    
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    
    # Build query for insights
    query = db.query(
        func.sum(MetaAdInsight.spend).label("spend"),
        func.sum(MetaAdInsight.impressions).label("impressions"),
        func.sum(MetaAdInsight.clicks).label("clicks"),
        func.sum(MetaAdInsight.conversions).label("conversions"),
        func.sum(MetaAdInsight.reach).label("reach"),
        func.avg(MetaAdInsight.ctr).label("ctr"),
        func.avg(MetaAdInsight.cpc).label("cpc"),
        func.avg(MetaAdInsight.cpm).label("cpm"),
        func.avg(MetaAdInsight.frequency).label("frequency"),
        func.avg(MetaAdInsight.cost_per_conversion).label("cost_per_conversion"),
        func.avg(MetaAdInsight.conversion_rate).label("conversion_rate")
    ).join(MetaAd, MetaAd.id == MetaAdInsight.ad_id).filter(
        MetaAd.campaign_id == campaign.id
    )
    
    if start_date:
        query = query.filter(MetaAdInsight.date >= start_date)
    
    if end_date:
        query = query.filter(MetaAdInsight.date <= end_date)
    
    result = query.first()
    
    if not result:
        return MetaInsightsSummary(
            spend=0,
            impressions=0,
            clicks=0,
            ctr=0,
            cpc=0,
            cpm=0,
            conversions=0,
            cost_per_conversion=0,
            conversion_rate=0,
            reach=0,
            frequency=0
        )
    
    return MetaInsightsSummary(
        spend=result.spend or 0.0,
        impressions=result.impressions or 0,
        clicks=result.clicks or 0,
        ctr=result.ctr or 0.0,
        cpc=result.cpc or 0.0,
        cpm=result.cpm or 0.0,
        conversions=result.conversions or 0,
        cost_per_conversion=result.cost_per_conversion or 0.0,
        conversion_rate=result.conversion_rate or 0.0,
        reach=result.reach or 0,
        frequency=result.frequency or 0.0
    )

# Performance Dashboard
@marketing_router.get("/dashboard/performance")
def get_performance_dashboard(
    business_account_id: Optional[uuid.UUID] = None,
    account_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Get performance dashboard data"""
    # Default to last 30 days
    if not start_date:
        start_date = datetime.utcnow().date() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow().date()
    
    # Build base query
    query = db.query(MetaAdInsight).join(MetaAd).join(MetaCampaign).join(MetaAdAccount)
    
    if business_account_id:
        query = query.filter(MetaAdAccount.business_account_id == business_account_id)
    
    if account_id:
        query = query.filter(MetaAdAccount.id == account_id)
    
    query = query.filter(
        MetaAdInsight.date >= start_date,
        MetaAdInsight.date <= end_date
    )
    
    # Get daily performance
    daily_query = db.query(
        MetaAdInsight.date,
        func.sum(MetaAdInsight.spend).label("spend"),
        func.sum(MetaAdInsight.impressions).label("impressions"),
        func.sum(MetaAdInsight.clicks).label("clicks"),
        func.sum(MetaAdInsight.conversions).label("conversions"),
        func.avg(MetaAdInsight.ctr).label("ctr"),
        func.avg(MetaAdInsight.cpc).label("cpc")
    ).join(MetaAd).join(MetaCampaign).join(MetaAdAccount)
    
    if business_account_id:
        daily_query = daily_query.filter(MetaAdAccount.business_account_id == business_account_id)
    
    if account_id:
        daily_query = daily_query.filter(MetaAdAccount.id == account_id)
    
    daily_results = daily_query.filter(
        MetaAdInsight.date >= start_date,
        MetaAdInsight.date <= end_date
    ).group_by(MetaAdInsight.date).order_by(MetaAdInsight.date).all()
    
    daily_metrics = [
        MetaPerformanceMetrics(
            date=row.date,
            spend=row.spend or 0.0,
            impressions=row.impressions or 0,
            clicks=row.clicks or 0,
            conversions=row.conversions or 0,
            ctr=row.ctr or 0.0,
            cpc=row.cpc or 0.0
        )
        for row in daily_results
    ]
    
    # Get campaign performance
    campaign_query = db.query(
        MetaCampaign.campaign_id,
        MetaCampaign.name,
        MetaCampaign.objective,
        MetaCampaign.status,
        func.sum(MetaAdInsight.spend).label("spend"),
        func.sum(MetaAdInsight.impressions).label("impressions"),
        func.sum(MetaAdInsight.clicks).label("clicks"),
        func.avg(MetaAdInsight.ctr).label("ctr"),
        func.sum(MetaAdInsight.conversions).label("conversions"),
        func.avg(MetaAdInsight.cost_per_conversion).label("cost_per_conversion")
    ).join(MetaAd, MetaAd.campaign_id == MetaCampaign.id).join(
        MetaAdInsight, MetaAdInsight.ad_id == MetaAd.id
    ).join(MetaAdAccount, MetaAdAccount.id == MetaCampaign.ad_account_id)
    
    if business_account_id:
        campaign_query = campaign_query.filter(MetaAdAccount.business_account_id == business_account_id)
    
    if account_id:
        campaign_query = campaign_query.filter(MetaAdAccount.id == account_id)
    
    campaign_results = campaign_query.filter(
        MetaAdInsight.date >= start_date,
        MetaAdInsight.date <= end_date
    ).group_by(
        MetaCampaign.campaign_id,
        MetaCampaign.name,
        MetaCampaign.objective,
        MetaCampaign.status
    ).order_by(desc("spend")).limit(10).all()
    
    campaign_performance = [
        MetaCampaignPerformance(
            campaign_id=row.campaign_id,
            campaign_name=row.name,
            objective=row.objective,
            status=row.status,
            spend=row.spend or 0.0,
            impressions=row.impressions or 0,
            clicks=row.clicks or 0,
            ctr=row.ctr or 0.0,
            conversions=row.conversions or 0,
            cost_per_conversion=row.cost_per_conversion or 0.0
        )
        for row in campaign_results
    ]
    
    # Get summary metrics
    summary_query = db.query(
        func.sum(MetaAdInsight.spend).label("spend"),
        func.sum(MetaAdInsight.impressions).label("impressions"),
        func.sum(MetaAdInsight.clicks).label("clicks"),
        func.sum(MetaAdInsight.conversions).label("conversions"),
        func.avg(MetaAdInsight.ctr).label("ctr"),
        func.avg(MetaAdInsight.cpc).label("cpc"),
        func.avg(MetaAdInsight.cpm).label("cpm")
    ).join(MetaAd).join(MetaCampaign).join(MetaAdAccount)
    
    if business_account_id:
        summary_query = summary_query.filter(MetaAdAccount.business_account_id == business_account_id)
    
    if account_id:
        summary_query = summary_query.filter(MetaAdAccount.id == account_id)
    
    summary_result = summary_query.filter(
        MetaAdInsight.date >= start_date,
        MetaAdInsight.date <= end_date
    ).first()
    
    summary = MetaInsightsSummary(
        spend=summary_result.spend or 0.0,
        impressions=summary_result.impressions or 0,
        clicks=summary_result.clicks or 0,
        ctr=summary_result.ctr or 0.0,
        cpc=summary_result.cpc or 0.0,
        cpm=summary_result.cpm or 0.0,
        conversions=summary_result.conversions or 0,
        cost_per_conversion=0,
        conversion_rate=0,
        reach=0,
        frequency=0
    )
    
    return {
        "summary": summary,
        "daily_metrics": daily_metrics,
        "campaign_performance": campaign_performance,
        "period": {
            "start_date": start_date,
            "end_date": end_date
        }
    }

# Bulk Operations
@marketing_router.post("/campaigns/bulk-update", response_model=SuccessMessage)
def bulk_update_campaigns(
    update_data: MetaBulkUpdateRequest,
    db: Session = Depends(get_db)
):
    """Bulk update campaigns"""
    if not update_data.ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No campaign IDs provided"
        )
    
    campaigns = db.query(MetaCampaign).filter(
        MetaCampaign.id.in_(update_data.ids)
    ).all()
    
    if not campaigns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No campaigns found"
        )
    
    updated_count = 0
    
    for campaign in campaigns:
        try:
            # Update in Meta if status changed
            if update_data.status and campaign.status != update_data.status:
                ad_account = campaign.ad_account
                if ad_account and ad_account.is_connected:
                    url = f"{FB_GRAPH_API_BASE}/{campaign.campaign_id}"
                    data = {
                        "access_token": ad_account.access_token,
                        "status": update_data.status
                    }
                    response = requests.post(url, data=data)
                    if response.status_code == 200:
                        campaign.status = update_data.status
            
            # Update budget if provided
            if update_data.budget is not None:
                campaign.daily_budget = update_data.budget
            
            updated_count += 1
            
        except Exception as e:
            print(f"Failed to update campaign {campaign.id}: {str(e)}")
            continue
    
    db.commit()
    
    return SuccessMessage(
        success=True,
        message=f"Updated {updated_count} campaigns",
        data={"updated_count": updated_count}
    )

# Health Check
@marketing_router.get("/health")
def health_check():
    """Check if marketing API is healthy"""
    return {"status": "healthy", "service": "meta-marketing-api"}

@marketing_router.get("/ads-library", response_model=Dict[str, Any])
def get_ads_from_library(
    business_id: str = Query(...),
    search_term: Optional[str] = None,
    ad_type: Optional[str] = "NON_POLITICAL",            # DEFAULT FIX
    ad_reached_countries: list[str] = Query(default=["ZW"]),  # REQUIRED
    limit: int = 50,
    db: Session = Depends(get_db)
):
    # Fetch business
    business = db.query(FacebookBusinessAccount).filter(
        FacebookBusinessAccount.id == business_id
    ).first()

    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    # Pull token from business model
    access_token = business.access_token

    # Call helper
    result = fetch_ads_library(
        access_token=access_token,
        search_term=search_term,
        ad_type=ad_type,
        ad_reached_countries=ad_reached_countries,
        limit=limit
    )

    return result


# ==================== DRAFT ENDPOINTS ====================

@marketing_router.get("/drafts", response_model=DraftListResponse)
def list_all_drafts(
    ad_account_id: Optional[uuid.UUID] = None,
    draft_type: Optional[str] = Query(None, description="Filter by type: campaign, adset, ad, url_campaign"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List all drafts (campaigns, ad sets, ads, and URL campaigns)"""
    drafts = []

    # Get URL campaigns that are not published (DRAFT, ANALYZING, READY status)
    if draft_type is None or draft_type == "campaign" or draft_type == "url_campaign":
        url_campaign_query = db.query(UrlCampaign).filter(
            UrlCampaign.status.in_([
                UrlCampaignStatus.DRAFT,
                UrlCampaignStatus.ANALYZING,
                UrlCampaignStatus.READY
            ])
        )

        for url_campaign in url_campaign_query.all():
            # Build draft_data with campaign details for resuming
            draft_data = {
                "source_url": url_campaign.source_url,
                "scraped_data": url_campaign.scraped_data,
                "goal": url_campaign.goal.value if url_campaign.goal else None,
                "daily_budget": url_campaign.daily_budget,
                "countries": url_campaign.countries,
                "ad_sets_count": len(url_campaign.ad_sets) if url_campaign.ad_sets else 0
            }

            drafts.append(DraftItem(
                id=url_campaign.id,
                type="campaign",
                name=url_campaign.name,
                status=url_campaign.status.value.upper() if url_campaign.status else "DRAFT",
                notes=f"URL: {url_campaign.source_url}" if url_campaign.source_url else None,
                draft_data=draft_data,
                created_at=url_campaign.created_at,
                updated_at=url_campaign.updated_at,
                ad_account_id=None
            ))

    # Get Meta draft campaigns
    if draft_type is None or draft_type == "campaign":
        campaign_query = db.query(MetaCampaign).filter(MetaCampaign.is_draft == True)
        if ad_account_id:
            campaign_query = campaign_query.filter(MetaCampaign.ad_account_id == ad_account_id)

        for campaign in campaign_query.all():
            drafts.append(DraftItem(
                id=campaign.id,
                type="campaign",
                name=campaign.name,
                status=campaign.status or "DRAFT",
                notes=campaign.notes,
                draft_data=campaign.draft_data,
                created_at=campaign.created_at,
                updated_at=campaign.updated_at,
                ad_account_id=campaign.ad_account_id
            ))

    # Get draft ad sets
    if draft_type is None or draft_type == "adset":
        adset_query = db.query(MetaAdSet).filter(MetaAdSet.is_draft == True)
        if ad_account_id:
            adset_query = adset_query.filter(MetaAdSet.ad_account_id == ad_account_id)

        for adset in adset_query.all():
            campaign_name = None
            if adset.campaign:
                campaign_name = adset.campaign.name

            drafts.append(DraftItem(
                id=adset.id,
                type="adset",
                name=adset.name,
                status=adset.status or "DRAFT",
                notes=adset.notes,
                draft_data=adset.draft_data,
                created_at=adset.created_at,
                updated_at=adset.updated_at,
                ad_account_id=adset.ad_account_id,
                campaign_id=adset.campaign_id,
                campaign_name=campaign_name
            ))

    # Get draft ads
    if draft_type is None or draft_type == "ad":
        ad_query = db.query(MetaAd).filter(MetaAd.is_draft == True)
        if ad_account_id:
            ad_query = ad_query.filter(MetaAd.ad_account_id == ad_account_id)

        for ad in ad_query.all():
            campaign_name = None
            adset_name = None
            if ad.campaign:
                campaign_name = ad.campaign.name
            if ad.ad_set:
                adset_name = ad.ad_set.name

            drafts.append(DraftItem(
                id=ad.id,
                type="ad",
                name=ad.name,
                status=ad.status or "DRAFT",
                notes=ad.notes,
                draft_data=ad.draft_data,
                created_at=ad.created_at,
                updated_at=ad.updated_at,
                ad_account_id=ad.ad_account_id,
                campaign_id=ad.campaign_id,
                campaign_name=campaign_name,
                adset_id=ad.adset_id,
                adset_name=adset_name
            ))

    # Sort by created_at descending
    drafts.sort(key=lambda x: x.created_at, reverse=True)

    # Apply pagination
    total_count = len(drafts)
    drafts = drafts[skip:skip + limit]

    return DraftListResponse(drafts=drafts, total_count=total_count)


@marketing_router.post("/campaigns/{campaign_id}/publish-draft", response_model=PublishDraftResponse)
def publish_campaign_draft(
    campaign_id: uuid.UUID,
    request: Optional[PublishDraftRequest] = None,
    db: Session = Depends(get_db)
):
    """Publish a draft campaign to Meta"""
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )

    if not campaign.is_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign is not a draft"
        )

    ad_account = campaign.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )

    try:
        # Get original request from draft_data
        original_request = campaign.draft_data.get("original_request", {}) if campaign.draft_data else {}

        # Prepare campaign data for Meta API
        meta_campaign_data = {
            "name": campaign.name,
            "objective": campaign.objective,
            "status": original_request.get("status", "PAUSED"),
            "buying_type": campaign.buying_type or "AUCTION",
        }

        if campaign.special_ad_categories:
            meta_campaign_data["special_ad_categories"] = json.dumps(campaign.special_ad_categories)
        else:
            meta_campaign_data["special_ad_categories"] = '["NONE"]'

        if campaign.daily_budget:
            meta_campaign_data["daily_budget"] = str(campaign.daily_budget)

        if campaign.lifetime_budget:
            meta_campaign_data["lifetime_budget"] = str(campaign.lifetime_budget)

        if campaign.start_time:
            meta_campaign_data["start_time"] = str(int(campaign.start_time.timestamp()))

        if campaign.stop_time:
            meta_campaign_data["stop_time"] = str(int(campaign.stop_time.timestamp()))

        # Create campaign in Meta
        result = create_meta_campaign(
            ad_account.ad_account_id,
            ad_account.access_token,
            meta_campaign_data
        )

        # Update campaign with Meta ID
        campaign.campaign_id = result.get("id")
        campaign.is_draft = False
        campaign.published_at = datetime.utcnow()
        campaign.status = original_request.get("status", "PAUSED")
        campaign.effective_status = original_request.get("status", "PAUSED")
        campaign.last_synced_at = datetime.utcnow()
        if request and request.notes:
            campaign.notes = request.notes

        db.commit()

        return PublishDraftResponse(
            success=True,
            message="Campaign published successfully",
            meta_id=result.get("id"),
            published_at=campaign.published_at
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to publish campaign: {str(e)}"
        )


@marketing_router.post("/adsets/{adset_id}/publish-draft", response_model=PublishDraftResponse)
def publish_adset_draft(
    adset_id: uuid.UUID,
    request: Optional[PublishDraftRequest] = None,
    db: Session = Depends(get_db)
):
    """Publish a draft ad set to Meta"""
    adset = db.query(MetaAdSet).filter(MetaAdSet.id == adset_id).first()

    if not adset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ad set not found"
        )

    if not adset.is_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad set is not a draft"
        )

    ad_account = adset.ad_account
    if not ad_account or not ad_account.is_connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ad account is not connected"
        )

    campaign = adset.campaign
    if not campaign or campaign.is_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent campaign must be published first"
        )

    try:
        # Get original request from draft_data
        original_request = adset.draft_data.get("original_request", {}) if adset.draft_data else {}

        # Prepare ad set data for Meta API
        meta_adset_data = {
            "name": adset.name,
            "campaign_id": campaign.campaign_id,
            "status": original_request.get("status", "PAUSED"),
        }

        if adset.optimization_goal:
            meta_adset_data["optimization_goal"] = adset.optimization_goal

        if adset.billing_event:
            meta_adset_data["billing_event"] = adset.billing_event

        if adset.targeting:
            meta_adset_data["targeting"] = json.dumps(adset.targeting)

        if adset.lifetime_budget:
            meta_adset_data["lifetime_budget"] = str(adset.lifetime_budget)

        if adset.bid_amount:
            meta_adset_data["bid_amount"] = str(adset.bid_amount)

        if adset.start_time:
            meta_adset_data["start_time"] = str(int(adset.start_time.timestamp()))

        if adset.end_time:
            meta_adset_data["end_time"] = str(int(adset.end_time.timestamp()))

        # Create ad set in Meta
        result = create_meta_adset(
            ad_account.ad_account_id,
            ad_account.access_token,
            meta_adset_data
        )

        # Update ad set with Meta ID
        adset.adset_id = result.get("id")
        adset.is_draft = False
        adset.published_at = datetime.utcnow()
        adset.status = original_request.get("status", "PAUSED")
        adset.effective_status = original_request.get("status", "PAUSED")
        adset.last_synced_at = datetime.utcnow()
        if request and request.notes:
            adset.notes = request.notes

        db.commit()

        return PublishDraftResponse(
            success=True,
            message="Ad set published successfully",
            meta_id=result.get("id"),
            published_at=adset.published_at
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to publish ad set: {str(e)}"
        )


@marketing_router.delete("/drafts/{draft_type}/{draft_id}", response_model=SuccessMessage)
def delete_draft(
    draft_type: str,
    draft_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete a draft (campaign, adset, or ad)"""
    if draft_type == "campaign":
        item = db.query(MetaCampaign).filter(
            MetaCampaign.id == draft_id,
            MetaCampaign.is_draft == True
        ).first()
    elif draft_type == "adset":
        item = db.query(MetaAdSet).filter(
            MetaAdSet.id == draft_id,
            MetaAdSet.is_draft == True
        ).first()
    elif draft_type == "ad":
        item = db.query(MetaAd).filter(
            MetaAd.id == draft_id,
            MetaAd.is_draft == True
        ).first()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid draft type. Must be 'campaign', 'adset', or 'ad'"
        )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft {draft_type} not found"
        )

    db.delete(item)
    db.commit()

    return SuccessMessage(
        success=True,
        message=f"Draft {draft_type} deleted successfully"
    )


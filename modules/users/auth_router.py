# modules/users/auth_api.py
import os
import traceback
from fastapi import APIRouter, Depends, HTTPException, status
import uuid
import os
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
from sqlalchemy.orm import Session

from database import get_db
from modules.users.models import User, UserRole
from modules.users.schemas import (
    GoogleAuthRequest, GoogleSignupRequest, LoginRequest, LoginVerifyRequest, LoginResponse
)
from modules.stores.models import Store, StoreSetupSession
from utils.Verification_Codes_Services import VerificationCodeService

auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")

# Google Signup/Login
@auth_router.post("/google", response_model=LoginResponse)
async def google_auth(google_data: GoogleSignupRequest, db: Session = Depends(get_db)):
    try:
        print(f"Received Google access token: {google_data.access_token[:20]}...")
        
        # Use access_token to get user info from Google
        userinfo_response = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {google_data.access_token}'}
        )
        
        if userinfo_response.status_code != 200:
            print(f"Google API returned error: {userinfo_response.status_code} - {userinfo_response.text}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google access token"
            )
        
        user_info = userinfo_response.json()
        print(f"Google user info: {user_info}")
        
        # Extract user information from Google API response
        google_id = user_info['sub']
        email = user_info['email']
        name = user_info.get('name', '')
        profile_picture = user_info.get('picture', '')
        
        print(f"🔍 Extracted from Google - ID: {google_id}, Email: {email}, Name: '{name}', Picture: '{profile_picture}'")
        
        # Check if user already exists by email or google_id
        user = db.query(User).filter(
            (User.email == email) | (User.google_id == google_id)
        ).first()
        
        if user:
            print(f"✅ Found existing user: {user.email}, Current name: '{user.name}'")
        else:
            print(f"🆕 Creating new user for: {email}")
        
        if not user:
            # Create new user with Google data
            user = User(
                name=name or "",  # Ensure name is not None
                email=email,
                phone_number=None,
                role=UserRole.OWNER,
                is_verified=True,
                is_active=True,
                google_id=google_id,
                profile_picture=profile_picture or None
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"✅ New user created: {user.email}")
        else:
            # FIX: Update existing user with Google data - always update name and profile if available
            print(f"🔄 Checking updates for existing user: {user.email}")
            updates = {}
            
            # Always update google_id if it's not set or different
            if not user.google_id or user.google_id != google_id:
                user.google_id = google_id
                updates['google_id'] = google_id
            
            # FIX: Always update profile picture if Google provides one
            if profile_picture and user.profile_picture != profile_picture:
                user.profile_picture = profile_picture
                updates['profile_picture'] = profile_picture
            
            # FIX: Always update name if Google provides one and it's different from current
            if name and user.name != name:
                user.name = name
                updates['name'] = name
            
            # Always mark as verified
            if not user.is_verified:
                user.is_verified = True
                updates['is_verified'] = True
            
            if updates:
                print(f"📝 Applying updates: {updates}")
                db.commit()
                db.refresh(user)
                print(f"✅ User updated in database")
            else:
                print(f"✅ No updates needed")
        
        # VERIFY: Query the user again to confirm what's in DB
        verified_user = db.query(User).filter(User.id == user.id).first()
        print(f"🔍 VERIFICATION - DB contains: Name: '{verified_user.name}', Google ID: '{verified_user.google_id}', Profile Pic: '{verified_user.profile_picture}'")
        
        # Check store and setup session status
        store = db.query(Store).filter(Store.owner_id == user.id).first()
        has_store = store is not None
        
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user.id,
            StoreSetupSession.is_active == True
        ).first()
        
        # Determine detailed user status
        if has_store:
            user_status = "has_store"
            redirect_to = "/dashboard"
        elif setup_session:
            user_status = "has_incomplete_setup"
            redirect_to = f"/setup/{setup_session.id}"
        else:
            user_status = "no_store"
            redirect_to = "/setup/start"
        
        # Generate access token
        access_token = f"jwt_{user.id}_{uuid.uuid4()}"
        
        # FIX: Convert UUID to string for proper serialization
        user_dict = {
            "id": str(verified_user.id),  # Convert UUID to string
            "name": verified_user.name,
            "email": verified_user.email,
            "phone_number": verified_user.phone_number,
            "role": verified_user.role.value if hasattr(verified_user.role, 'value') else verified_user.role,
            "is_verified": bool(verified_user.is_verified),
            "is_active": bool(verified_user.is_active),
            "google_id": verified_user.google_id,
            "profile_picture": verified_user.profile_picture,
            "created_at": verified_user.created_at.isoformat() if verified_user.created_at else None,
            "updated_at": verified_user.updated_at.isoformat() if verified_user.updated_at else None
        }
        
        print(f"🔍 Final user data being sent: {user_dict}")
        
        # Create response - ensure all UUIDs are converted to strings
        response_data = {
            "user": user_dict,
            "store_id": str(store.id) if store else None,
            "has_active_setup_session": setup_session is not None,
            "setup_session_id": str(setup_session.id) if setup_session else None,
            "setup_progress": setup_session.setup_progress if setup_session else 0,
            "current_setup_step": setup_session.current_step.value if setup_session else None,
            "has_store": has_store,
            "user_status": user_status,
            "redirect_to": redirect_to,
            "access_token": access_token,
            "token_type": "bearer"
        }
        
        print(f"🎉 Google auth completed successfully for: {verified_user.email}")
        print(f"📤 Response data: {response_data}")
        
        return LoginResponse(**response_data)
        
    except Exception as e:
        print(f"❌ Google authentication error: {str(e)}")
        print(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )
    
# Send login code
@auth_router.post("/login", status_code=status.HTTP_200_OK)
async def send_login_code(login_data: LoginRequest, db: Session = Depends(get_db)):
    try:
        # Find user by email
        user = db.query(User).filter(User.email == login_data.email).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Send verification code
        success = VerificationCodeService.send_verification_code(
            db=db,
            email=login_data.email,
            code_type="email_verification"
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send verification code"
            )
        
        return {"message": "Verification code sent successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during login: {str(e)}"
        )

# Verify login code
@auth_router.post("/verify-login", response_model=LoginResponse)
async def verify_login(verify_data: LoginVerifyRequest, db: Session = Depends(get_db)):
    try:
        # Verify code
        is_valid = VerificationCodeService.verify_code(
            db=db,
            email=verify_data.email,
            code=verify_data.code,
            code_type="email_verification"
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired verification code"
            )
        
        # Get user
        user = db.query(User).filter(User.email == verify_data.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Mark user as verified if not already
        if not user.is_verified:
            user.is_verified = True
            db.commit()
            db.refresh(user)
        
        # Check if user has a completed store
        store = db.query(Store).filter(Store.owner_id == user.id).first()
        has_store = store is not None
        
        # Check if user has an active setup session
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user.id,
            StoreSetupSession.is_active == True
        ).first()
        
        has_active_session = setup_session is not None
        
        # Determine user status
        if has_store:
            user_status = "has_store"
        elif has_active_session:
            user_status = "has_incomplete_setup"
        else:
            user_status = "no_store"
        
        return LoginResponse(
            user=user,
            store_id=store.id if store else None,
            has_active_setup_session=has_active_session,
            setup_session_id=setup_session.id if setup_session else None,
            setup_progress=setup_session.setup_progress if setup_session else 0,
            current_setup_step=setup_session.current_step.value if setup_session else None,
            has_store=has_store,
            user_status=user_status,
            access_token="jwt_token_here",
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during verification: {str(e)}"
        )
    
# modules/users/auth_api.py
@auth_router.post("/verify-and-login", response_model=LoginResponse)
async def verify_and_login(verify_data: LoginVerifyRequest, db: Session = Depends(get_db)):
    """Verify code and login - returns detailed user status"""
    try:
        # Verify code
        is_valid = VerificationCodeService.verify_code(
            db=db,
            email=verify_data.email,
            code=verify_data.code,
            code_type="email_verification"
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired verification code"
            )
        
        # Get user
        user = db.query(User).filter(User.email == verify_data.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Mark user as verified
        if not user.is_verified:
            user.is_verified = True
            db.commit()
            db.refresh(user)
        
        # Check store and setup session status
        store = db.query(Store).filter(Store.owner_id == user.id).first()
        has_store = store is not None
        
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user.id,
            StoreSetupSession.is_active == True
        ).first()
        
        # Determine detailed user status
        if has_store:
            user_status = "has_store"
            redirect_to = "/dashboard"
        elif setup_session:
            user_status = "has_incomplete_setup"
            redirect_to = f"/setup/{setup_session.id}"
        else:
            user_status = "no_store"
            redirect_to = "/setup/start"
        
        # Generate token
        access_token = f"jwt_{user.id}"
        
        return LoginResponse(
            user=user,
            store_id=store.id if store else None,
            has_active_setup_session=setup_session is not None,
            setup_session_id=setup_session.id if setup_session else None,
            setup_progress=setup_session.setup_progress if setup_session else 0,
            current_setup_step=setup_session.current_step.value if setup_session else None,
            has_store=has_store,
            user_status=user_status,
            redirect_to=redirect_to,  # NEW: Tell frontend where to go
            access_token=access_token,
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during verification: {str(e)}"
        )
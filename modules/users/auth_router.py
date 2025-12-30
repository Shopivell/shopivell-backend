# modules/users/auth_api.py
import os
import traceback
import re
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
from modules.referral.service import ReferralService
from modules.referral.models import ReferralSource
from utils.jwt_auth import jwt_auth, token_blacklist, get_current_user, CurrentUser


def generate_unique_slug(db: Session, base_name: str) -> str:
    """Generate a unique slug for agency using raw SQL"""
    from sqlalchemy import text
    import uuid as uuid_module

    base_slug = re.sub(r'[^a-z0-9]+', '-', base_name.lower()).strip('-')
    if not base_slug:
        base_slug = 'agency'

    slug = base_slug
    counter = 1
    max_attempts = 100  # Safety limit

    while counter <= max_attempts:
        result = db.execute(text("SELECT 1 FROM agencies WHERE slug = :slug"), {"slug": slug}).fetchone()
        if not result:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Fallback: use UUID suffix if too many attempts
    return f"{base_slug}-{uuid_module.uuid4().hex[:8]}"

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
        
        print(f"[INFO] Extracted from Google - ID: {google_id}, Email: {email}, Name: '{name}', Picture: '{profile_picture}'")
        
        # Check if user already exists by email or google_id
        user = db.query(User).filter(
            (User.email == email) | (User.google_id == google_id)
        ).first()
        
        if user:
            print(f"[OK] Found existing user: {user.email}, Current name: '{user.name}'")
        else:
            print(f"[NEW] Creating new user for: {email}")
        
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
            print(f"[OK] New user created: {user.email}")
            
            # Process referral if code was provided
            if google_data.referral_code:
                try:
                    from modules.referral.models import UserReferralCode, Referral, UserTokenBalance, TokenTransaction, ReferralStatus, TokenTransactionType
                    from modules.referral.constants import TOKENS_PER_REFERRAL
                    from datetime import datetime
                    
                    # Validate referral code
                    referrer_code = db.query(UserReferralCode).filter(
                        UserReferralCode.referral_code == google_data.referral_code.upper()
                    ).first()
                    
                    if referrer_code and referrer_code.is_active and referrer_code.user_id != user.id:
                        # Create referral record
                        referral = Referral(
                            referrer_code_id=referrer_code.id,
                            referred_user_id=user.id,
                            status=ReferralStatus.REWARDED,
                            source=ReferralSource.OTHER,
                            referred_email=user.email,
                            tokens_awarded=TOKENS_PER_REFERRAL,
                            signed_up_at=datetime.utcnow(),
                            rewarded_at=datetime.utcnow()
                        )
                        db.add(referral)
                        
                        # Update referrer code stats
                        referrer_code.total_referrals += 1
                        referrer_code.successful_referrals += 1
                        referrer_code.total_tokens_earned += TOKENS_PER_REFERRAL
                        
                        # Get or create token balance for referrer
                        token_balance = db.query(UserTokenBalance).filter(
                            UserTokenBalance.user_id == referrer_code.user_id
                        ).first()
                        
                        if not token_balance:
                            token_balance = UserTokenBalance(
                                user_id=referrer_code.user_id,
                                available_tokens=0,
                                total_earned=0,
                                total_redeemed=0
                            )
                            db.add(token_balance)
                            db.commit()
                            db.refresh(token_balance)
                        
                        # Award tokens
                        token_balance.available_tokens += TOKENS_PER_REFERRAL
                        token_balance.total_earned += TOKENS_PER_REFERRAL
                        
                        # Create token transaction
                        token_tx = TokenTransaction(
                            token_balance_id=token_balance.id,
                            transaction_type=TokenTransactionType.EARNED,
                            amount=TOKENS_PER_REFERRAL,
                            balance_after=token_balance.available_tokens,
                            reference_type="referral",
                            reference_id=referral.id,
                            description=f"Earned for referring a new user"
                        )
                        db.add(token_tx)
                        db.commit()
                        
                        print(f"[OK] Referral processed: {user.email} via code {google_data.referral_code}")
                except Exception as ref_error:
                    print(f"[WARN] Referral processing failed: {ref_error}")
                    # Don't fail signup if referral fails
        else:
            # FIX: Update existing user with Google data - always update name and profile if available
            print(f"[UPDATE] Checking updates for existing user: {user.email}")
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
                print(f"[UPDATE] Applying updates: {updates}")
                db.commit()
                db.refresh(user)
                print(f"[OK] User updated in database")
            else:
                print(f"[OK] No updates needed")
        
        # VERIFY: Query the user again to confirm what's in DB
        verified_user = db.query(User).filter(User.id == user.id).first()
        print(f"[OK] VERIFICATION - DB contains: Name: '{verified_user.name}', Google ID: '{verified_user.google_id}', Profile Pic: '{verified_user.profile_picture}'")

        # Check store and setup session status
        store = db.query(Store).filter(Store.owner_id == user.id).first()
        # Only consider has_store=True if setup is actually completed
        has_store = store is not None and store.is_setup_completed

        # Get or create user's agency using raw SQL to avoid mapper issues
        from sqlalchemy import text
        import uuid as uuid_module

        agency_result = db.execute(
            text("SELECT id, name FROM agencies WHERE owner_id = :owner_id"),
            {"owner_id": str(verified_user.id)}
        ).fetchone()

        if not agency_result:
            agency_name = f"{verified_user.name}'s Agency" if verified_user.name else "My Agency"
            agency_slug = generate_unique_slug(db, agency_name)
            agency_id = str(uuid_module.uuid4())

            db.execute(
                text("""
                    INSERT INTO agencies (id, owner_id, name, slug, email, status, settings, created_at, updated_at)
                    VALUES (:id, :owner_id, :name, :slug, :email, 'ACTIVE', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "id": agency_id,
                    "owner_id": str(verified_user.id),
                    "name": agency_name,
                    "slug": agency_slug,
                    "email": verified_user.email
                }
            )
            db.commit()
            print(f"[OK] Agency created: {agency_name}")
            agency_result = (agency_id, agency_name)

        agency_id = agency_result[0] if agency_result else None

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
        # Generate proper JWT tokens
        tokens = jwt_auth.create_tokens(
            user_id=str(verified_user.id),
            email=verified_user.email,
            role=verified_user.role.value if hasattr(verified_user.role, 'value') else verified_user.role,
            store_id=str(store.id) if store else None,
            agency_id=str(agency_id) if agency_id else None
        )
        access_token = tokens.access_token
        refresh_token = tokens.refresh_token
        
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
        
        print(f"[INFO] Final user data being sent: {user_dict}")
        
        # Create response - ensure all UUIDs are converted to strings
        response_data = {
            "user": user_dict,
            "store_id": str(store.id) if store else None,
            "agency_id": str(agency_id) if agency_id else None,
            "has_active_setup_session": setup_session is not None,
            "setup_session_id": str(setup_session.id) if setup_session else None,
            "setup_progress": setup_session.setup_progress if setup_session else 0,
            "current_setup_step": setup_session.current_step.value if setup_session else None,
            "has_store": has_store,
            "user_status": user_status,
            "redirect_to": redirect_to,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

        print(f"[OK] Google auth completed successfully for: {verified_user.email}")
        print(f"[RESPONSE] Response data: {response_data}")
        
        return LoginResponse(**response_data)
        
    except Exception as e:
        print(f"[ERROR] Google authentication error: {str(e)}")
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
        # Only consider has_store=True if setup is actually completed
        has_store = store is not None and store.is_setup_completed

        # Get or create agency for user using raw SQL
        from sqlalchemy import text
        import uuid as uuid_module

        agency_result = db.execute(
            text("SELECT id FROM agencies WHERE owner_id = :owner_id"),
            {"owner_id": str(user.id)}
        ).fetchone()

        if not agency_result:
            agency_name = f"{user.name}'s Agency" if user.name else "My Agency"
            agency_slug = generate_unique_slug(db, agency_name)
            agency_id = str(uuid_module.uuid4())

            db.execute(
                text("""
                    INSERT INTO agencies (id, owner_id, name, slug, email, status, settings, created_at, updated_at)
                    VALUES (:id, :owner_id, :name, :slug, :email, 'ACTIVE', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "id": agency_id,
                    "owner_id": str(user.id),
                    "name": agency_name,
                    "slug": agency_slug,
                    "email": user.email
                }
            )
            db.commit()
            print(f"[OK] Agency created: {agency_name}")
        else:
            agency_id = agency_result[0]

        # Check if user has an active setup session
        setup_session = db.query(StoreSetupSession).filter(
            StoreSetupSession.user_id == user.id,
            StoreSetupSession.is_active == True
        ).first()

        has_active_session = setup_session is not None

        # Determine user status
        if has_store:
            user_status = "has_store"
            redirect_to = "/dashboard"
        elif has_active_session:
            user_status = "has_incomplete_setup"
            redirect_to = f"/setup/{setup_session.id}"
        else:
            user_status = "no_store"
            redirect_to = "/setup/start"

        # Generate proper JWT tokens
        tokens = jwt_auth.create_tokens(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value if hasattr(user.role, 'value') else user.role,
            store_id=str(store.id) if store else None,
            agency_id=str(agency_id) if agency_id else None
        )

        return LoginResponse(
            user=user,
            store_id=store.id if store else None,
            agency_id=agency_id if agency_id else None,
            has_active_setup_session=has_active_session,
            setup_session_id=setup_session.id if setup_session else None,
            setup_progress=setup_session.setup_progress if setup_session else 0,
            current_setup_step=setup_session.current_step.value if setup_session else None,
            has_store=has_store,
            user_status=user_status,
            redirect_to=redirect_to,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
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
        # Only consider has_store=True if setup is actually completed
        has_store = store is not None and store.is_setup_completed

        # Get or create agency for user using raw SQL
        from sqlalchemy import text
        import uuid as uuid_module

        agency_result = db.execute(
            text("SELECT id FROM agencies WHERE owner_id = :owner_id"),
            {"owner_id": str(user.id)}
        ).fetchone()

        if not agency_result:
            agency_name = f"{user.name}'s Agency" if user.name else "My Agency"
            agency_slug = generate_unique_slug(db, agency_name)
            agency_id = str(uuid_module.uuid4())

            db.execute(
                text("""
                    INSERT INTO agencies (id, owner_id, name, slug, email, status, settings, created_at, updated_at)
                    VALUES (:id, :owner_id, :name, :slug, :email, 'ACTIVE', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "id": agency_id,
                    "owner_id": str(user.id),
                    "name": agency_name,
                    "slug": agency_slug,
                    "email": user.email
                }
            )
            db.commit()
            print(f"[OK] Agency created: {agency_name}")
        else:
            agency_id = agency_result[0]

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
        # Generate proper JWT tokens
        tokens = jwt_auth.create_tokens(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value if hasattr(user.role, 'value') else user.role,
            store_id=str(store.id) if store else None,
            agency_id=str(agency_id) if agency_id else None
        )
        access_token = tokens.access_token
        refresh_token = tokens.refresh_token

        return LoginResponse(
            user=user,
            store_id=store.id if store else None,
            agency_id=agency_id if agency_id else None,
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

# Token refresh endpoint
@auth_router.post("/refresh")
async def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    """Get a new access token using a refresh token"""
    try:
        # Verify refresh token
        payload = jwt_auth.verify_token(refresh_token, token_type="refresh")
        
        # Get user from database
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        # Get store and agency
        store = db.query(Store).filter(Store.owner_id == user.id).first()
        
        from sqlalchemy import text
        agency_result = db.execute(
            text("SELECT id FROM agencies WHERE owner_id = :owner_id"),
            {"owner_id": str(user.id)}
        ).fetchone()
        agency_id = agency_result[0] if agency_result else None
        
        # Create new tokens
        tokens = jwt_auth.create_tokens(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value if hasattr(user.role, 'value') else user.role,
            store_id=str(store.id) if store else None,
            agency_id=str(agency_id) if agency_id else None
        )
        
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": "bearer",
            "expires_in": tokens.expires_in
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not refresh token: {str(e)}"
        )


# Logout endpoint
@auth_router.post("/logout")
async def logout(current_user: CurrentUser = Depends(get_current_user)):
    """Logout and blacklist the current token"""
    try:
        # In a real implementation, you would blacklist the token here
        # token_blacklist.blacklist_token(token, ttl=3600)
        return {"message": "Successfully logged out"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


# Get current user endpoint
@auth_router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current authenticated user details"""
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    store = db.query(Store).filter(Store.owner_id == user.id).first()

    # Check for active setup session
    setup_session = db.query(StoreSetupSession).filter(
        StoreSetupSession.user_id == user.id,
        StoreSetupSession.is_active == True
    ).first()

    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, 'value') else user.role,
        "is_verified": user.is_verified,
        "profile_picture": user.profile_picture,
        "store_id": str(store.id) if store else None,
        "agency_id": current_user.agency_id,
        "has_store": store is not None and store.is_setup_completed,
        "is_setup_completed": store.is_setup_completed if store else False,
        "has_active_setup_session": setup_session is not None,
        "setup_session_id": str(setup_session.id) if setup_session else None
    }

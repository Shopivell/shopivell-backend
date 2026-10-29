# modules/users/auth_api.py
import os
import traceback
import re
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
import uuid
import os
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from modules.users.models import User, UserRole, StoreMember
from modules.users.schemas import (
    GoogleAuthRequest, GoogleSignupRequest, LoginRequest, LoginVerifyRequest, LoginResponse, UserResponse
)
from modules.stores.models import Store, StoreSetupSession
from utils.Verification_Codes_Services import VerificationCodeService
from modules.referral.service import ReferralService
from modules.referral.models import ReferralSource
from utils.jwt_auth import jwt_auth, token_blacklist, get_current_user, CurrentUser, verify_password


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

    try:
        while counter <= max_attempts:
            result = db.execute(text("SELECT 1 FROM agencies WHERE slug = :slug"), {"slug": slug}).fetchone()
            if not result:
                return slug
            slug = f"{base_slug}-{counter}"
            counter += 1
    except Exception:
        # If agencies table doesn't exist, just use UUID-based slug
        pass

    # Fallback: use UUID suffix
    return f"{base_slug}-{uuid_module.uuid4().hex[:8]}"

auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])

class PasswordLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


@auth_router.post('/password-login', response_model=LoginResponse)
def password_login(data: PasswordLogin, db: Session = Depends(get_db)):
    """Optional password sign-in; email-code sign-in remains available."""
    import hashlib
    from sqlalchemy import text
    from utils.cache import cache
    # A shared Redis counter prevents unlimited guessing across workers. Fail
    # closed if the limiter is unavailable rather than disabling protection.
    try:
        if not cache.is_connected:
            raise RuntimeError('rate limiter unavailable')
        key = 'auth:password:' + hashlib.sha256(str(data.email).lower().encode()).hexdigest()
        attempts = cache._client.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]); end; return n",
            1, key, 900)
    except Exception:
        raise HTTPException(status_code=503, detail='Password sign-in is temporarily unavailable. Use an email code.')
    if attempts > 10:
        raise HTTPException(status_code=429, detail='Too many attempts. Try again later or use an email code.')
    user = db.query(User).filter(func.lower(User.email) == str(data.email).lower()).first()
    dummy = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxdS8ZngCbHqI/t8wA9Zh7lr0qO'
    matches = verify_password(data.password, user.password_hash if user and user.password_hash else dummy)
    if not user or not user.password_hash or not user.is_active or not user.is_verified or not matches:
        raise HTTPException(status_code=401, detail='Invalid email or password')
    store = _active_store_for_user(db, user)
    if user.role == UserRole.STAFF and not store:
        raise HTTPException(status_code=403, detail='No active store access')
    has_store = bool(store and store.is_setup_completed)
    setup = db.query(StoreSetupSession).filter(StoreSetupSession.user_id == user.id,
                                               StoreSetupSession.is_active.is_(True)).first()
    agency = db.execute(text('SELECT id FROM agencies WHERE owner_id = :owner_id'),
                        {'owner_id': str(user.id)}).fetchone()
    agency_id = str(agency[0]) if agency else None
    tokens = jwt_auth.create_tokens(user_id=str(user.id), email=user.email,
        role=_store_role(user, store), store_id=str(store.id) if store else None, agency_id=agency_id)
    return LoginResponse(user=UserResponse.model_validate(user).model_copy(update={'role': _store_role(user, store)}),
        permissions=_member_permissions(db, user, store), store_id=store.id if store else None,
        agency_id=agency_id, has_store=has_store, has_active_setup_session=bool(setup),
        setup_session_id=setup.id if setup else None, setup_progress=setup.setup_progress if setup else 0,
        current_setup_step=setup.current_step.value if setup else None,
        user_status='has_store' if has_store else 'has_incomplete_setup' if setup else 'no_store',
        redirect_to='/dashboard' if has_store else f'/setup/{setup.id}' if setup else '/setup/start',
        access_token=tokens.access_token, refresh_token=tokens.refresh_token, token_type='bearer')


def _accessible_stores(db: Session, user_id):
    memberships = db.query(StoreMember.store_id).filter(
        StoreMember.user_id == user_id, StoreMember.is_active.is_(True))
    return db.query(Store).filter((Store.owner_id == user_id) | Store.id.in_(memberships))


def _active_store_for_user(db: Session, user):
    query = _accessible_stores(db, user.id)
    if user.last_active_store_id:
        store = query.filter(Store.id == user.last_active_store_id).first()
        if store:
            return store
    return query.order_by(Store.created_at.asc()).first()


def _store_role(user, store):
    if store and store.owner_id != user.id:
        return UserRole.STAFF.value
    return user.role.value if hasattr(user.role, 'value') else user.role


def _member_permissions(db, user, store):
    if not store or store.owner_id == user.id:
        return []
    member = db.query(StoreMember).filter(StoreMember.store_id == store.id,
        StoreMember.user_id == user.id, StoreMember.is_active.is_(True)).first()
    return member.permissions if member else []

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "664377144183-g2si02jr6d7ulhc101sd9e037dkkji0u.apps.googleusercontent.com")

# Google Signup/Login
@auth_router.post("/google", response_model=LoginResponse)
async def google_auth(google_data: GoogleSignupRequest, db: Session = Depends(get_db)):
    try:
        user_info = None
        print(f"[GOOGLE AUTH] Received request - access_token: {bool(google_data.access_token)}, credential: {bool(google_data.credential)}")

        # Handle JWT credential (from Google One Tap)
        if google_data.credential:
            print(f"[GOOGLE AUTH] Processing JWT credential...")
            try:
                # Verify the JWT credential
                user_info = id_token.verify_oauth2_token(
                    google_data.credential,
                    google_requests.Request(),
                    GOOGLE_CLIENT_ID
                )
                print(f"[GOOGLE AUTH] JWT verified successfully: {user_info.get('email', 'N/A')}")
            except ValueError as e:
                print(f"[GOOGLE AUTH] JWT verification failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid Google credential: {str(e)}"
                )
            except Exception as e:
                print(f"[GOOGLE AUTH] Unexpected error during JWT verification: {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Google authentication error: {str(e)}"
                )

        # Handle access_token (from Google Login button)
        elif google_data.access_token:
            print(f"[GOOGLE AUTH] Processing access token: {google_data.access_token[:20]}...")

            # Use access_token to get user info from Google
            userinfo_response = requests.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {google_data.access_token}'}
            )

            if userinfo_response.status_code != 200:
                print(f"[GOOGLE AUTH] Google API error: {userinfo_response.status_code} - {userinfo_response.text}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid Google access token: {userinfo_response.text}"
                )

            user_info = userinfo_response.json()
            print(f"[GOOGLE AUTH] Access token verified: {user_info.get('email', 'N/A')}")

        else:
            print("[GOOGLE AUTH] No token provided")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either access_token or credential must be provided"
            )
        
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
            
            # Only set Google profile picture if user has no custom picture
            # (don't overwrite MinIO-uploaded pictures with Google avatar)
            if profile_picture and not user.profile_picture:
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
        # Get all stores ordered by created_at (first created = default)
        stores = _accessible_stores(db, user.id).order_by(Store.created_at.asc()).all()
        stores_count = len(stores)
        # Prefer whichever store the user was last working in (so it's restored
        # across logout/login here too, same as /verify-login, /refresh and /me)
        # over the oldest-created one, falling back to that when unset/stale.
        store = None
        if verified_user.last_active_store_id:
            store = next(
                (s for s in stores
                 if s.id == verified_user.last_active_store_id and s.is_setup_completed),
                None,
            )
        if not store:
            store = next((s for s in stores if s.is_setup_completed), None)
        # Only consider has_store=True if there's at least one completed store
        has_store = store is not None

        # Get or create user's agency using raw SQL to avoid mapper issues
        from sqlalchemy import text
        import uuid as uuid_module

        agency_id = None
        try:
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
                        VALUES (:id, :owner_id, :name, :slug, :email, 'active', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
            else:
                agency_id = agency_result[0]
        except Exception as agency_error:
            print(f"[WARN] Agency creation/lookup failed (table may not exist): {agency_error}")
            db.rollback()
            agency_id = None

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
            role=_store_role(verified_user, store),
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
            "role": _store_role(verified_user, store),
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
            "permissions": _member_permissions(db, verified_user, store),
            "store_id": str(store.id) if store else None,
            "agency_id": str(agency_id) if agency_id else None,
            "stores_count": stores_count,  # Number of stores user owns
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
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] Google authentication error: {error_msg}")
        print(f"Full traceback: {traceback.format_exc()}")
        # Include full error details for debugging
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {type(e).__name__}: {str(e)[:200]}"
        )
    
# Send login code (also handles signup for new users)
@auth_router.post("/login", status_code=status.HTTP_200_OK)
async def send_login_code(login_data: LoginRequest, db: Session = Depends(get_db)):
    try:
        # Find user by email
        user = db.query(User).filter(User.email == login_data.email).first()

        if user and not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled")

        is_new_user = False
        if not user:
            # Create new user for email signup
            user = User(
                name="",  # Will be updated during onboarding
                email=login_data.email,
                phone_number=None,
                role=UserRole.OWNER,
                is_verified=False,
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            is_new_user = True
            print(f"[OK] New user created via email: {login_data.email}")

        # Send verification code
        try:
            success = VerificationCodeService.send_verification_code(
                db=db,
                email=login_data.email,
                code_type="email_verification"
            )
            print(f"[DEBUG] send_verification_code result: {success}")
        except Exception as send_err:
            print(f"[DEBUG] send_verification_code EXCEPTION: {type(send_err).__name__}: {send_err}")
            # Dev fallback: create code manually and log it
            try:
                code = VerificationCodeService.create_verification_code(
                    db=db, email=login_data.email, code_type="email_verification"
                )
                print(f"[DEV FALLBACK] Verification code for {login_data.email}: {code.code}")
            except Exception:
                print(f"[DEV FALLBACK] Could not create code, any code will work")
            success = True  # Allow dev login even if email fails

        return {
            "message": "Verification code sent successfully",
            "is_new_user": is_new_user
        }

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
        if not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled")
        
        # Mark user as verified if not already
        if not user.is_verified:
            user.is_verified = True
            db.commit()
            db.refresh(user)
        
        # Check if user has a completed store - prefer whichever store they were last
        # working in (so it's restored across logout/login) over an arbitrary .first()
        # match, falling back to .first() if last_active_store_id is unset, stale
        # (store deleted), or belongs to a different owner.
        store = _active_store_for_user(db, user)
        if user.role == UserRole.STAFF and not store:
            raise HTTPException(status_code=403, detail="No active store access")
        # Only consider has_store=True if setup is actually completed
        has_store = store is not None and store.is_setup_completed

        # Get or create agency for user using raw SQL
        from sqlalchemy import text
        import uuid as uuid_module

        agency_id = None
        try:
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
                        VALUES (:id, :owner_id, :name, :slug, :email, 'active', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
        except Exception as agency_error:
            print(f"[WARN] Agency creation/lookup failed: {agency_error}")
            db.rollback()
            agency_id = None

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
            role=_store_role(user, store),
            store_id=str(store.id) if store else None,
            agency_id=str(agency_id) if agency_id else None
        )

        return LoginResponse(
            user=UserResponse.model_validate(user).model_copy(update={'role': _store_role(user, store)}),
            permissions=_member_permissions(db, user, store),
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
        # Get all stores ordered by created_at (first created = default)
        stores = _accessible_stores(db, user.id).order_by(Store.created_at.asc()).all()
        stores_count = len(stores)
        # Prefer whichever store the user was last working in (so it's restored
        # across logout/login here too, same as /verify-login, /refresh and /me)
        # over the oldest-created one, falling back to that when unset/stale.
        store = None
        if user.last_active_store_id:
            store = next(
                (s for s in stores
                 if s.id == user.last_active_store_id and s.is_setup_completed),
                None,
            )
        if not store:
            store = next((s for s in stores if s.is_setup_completed), None)
        # Only consider has_store=True if there's at least one completed store
        has_store = store is not None

        # Get or create agency for user using raw SQL
        from sqlalchemy import text
        import uuid as uuid_module

        agency_id = None
        try:
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
                        VALUES (:id, :owner_id, :name, :slug, :email, 'active', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
        except Exception as agency_error:
            print(f"[WARN] Agency creation/lookup failed: {agency_error}")
            db.rollback()
            agency_id = None

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
            role=_store_role(user, store),
            store_id=str(store.id) if store else None,
            agency_id=str(agency_id) if agency_id else None
        )
        access_token = tokens.access_token
        refresh_token = tokens.refresh_token

        return LoginResponse(
            user=UserResponse.model_validate(user).model_copy(update={'role': _store_role(user, store)}),
            permissions=_member_permissions(db, user, store),
            store_id=store.id if store else None,
            agency_id=agency_id if agency_id else None,
            stores_count=stores_count,  # Number of stores user owns
            has_active_setup_session=setup_session is not None,
            setup_session_id=setup_session.id if setup_session else None,
            setup_progress=setup_session.setup_progress if setup_session else 0,
            current_setup_step=setup_session.current_step.value if setup_session else None,
            has_store=has_store,
            user_status=user_status,
            redirect_to=redirect_to,  # NEW: Tell frontend where to go
            access_token=access_token,
            refresh_token=refresh_token,
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
async def refresh_token(request: Request, refresh_token: str = None, db: Session = Depends(get_db)):
    """Get a new access token using a refresh token"""
    try:
        if not refresh_token:
            try:
                refresh_token = (await request.json()).get('refresh_token')
            except (ValueError, AttributeError):
                refresh_token = None
        if not refresh_token:
            raise HTTPException(status_code=401, detail="Refresh token required")
        # Verify refresh token
        payload = jwt_auth.verify_token(refresh_token, token_type="refresh")
        
        # Get user from database
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        if not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled")
        
        # Get store and agency - same last-active-store preference as /verify-login.
        store = _active_store_for_user(db, user)
        if user.role == UserRole.STAFF and not store:
            raise HTTPException(status_code=403, detail="No active store access")

        from sqlalchemy import text
        agency_id = None
        try:
            agency_result = db.execute(
                text("SELECT id FROM agencies WHERE owner_id = :owner_id"),
                {"owner_id": str(user.id)}
            ).fetchone()
            agency_id = agency_result[0] if agency_result else None
        except Exception:
            agency_id = None

        # Create new tokens
        tokens = jwt_auth.create_tokens(
            user_id=str(user.id),
            email=user.email,
            role=_store_role(user, store),
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

    store = _active_store_for_user(db, user)
    member = (db.query(StoreMember).filter(StoreMember.store_id == store.id,
               StoreMember.user_id == user.id, StoreMember.is_active.is_(True)).first()
              if store and store.owner_id != user.id else None)

    # Check for active setup session
    setup_session = db.query(StoreSetupSession).filter(
        StoreSetupSession.user_id == user.id,
        StoreSetupSession.is_active == True
    ).first()

    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": _store_role(user, store),
        "permissions": member.permissions if member else [],
        "is_verified": user.is_verified,
        "profile_picture": user.profile_picture,
        "store_id": str(store.id) if store else None,
        "agency_id": current_user.agency_id,
        "has_store": store is not None and store.is_setup_completed,
        "is_setup_completed": store.is_setup_completed if store else False,
        "has_active_setup_session": setup_session is not None,
        "setup_session_id": str(setup_session.id) if setup_session else None
    }


class SetActiveStoreRequest(BaseModel):
    store_id: str


@auth_router.patch("/active-store")
async def set_active_store(
    payload: SetActiveStoreRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist which store the user is currently working in, so /verify-login,
    /refresh and /me restore it on their next login instead of defaulting to an
    arbitrary store. Called from the frontend whenever the store switcher changes
    (see authService.setStoreId)."""
    store = _accessible_stores(db, uuid.UUID(str(current_user.id))).filter(Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found for this user.")

    user = db.query(User).filter(User.id == current_user.id).first()
    user.last_active_store_id = store.id
    db.commit()
    # Issue the selected store's role in the same response so the UI does not
    # depend on a second refresh request racing with another token refresh.
    role = _store_role(user, store)
    tokens = jwt_auth.create_tokens(user_id=str(user.id), email=user.email, role=role,
                                    store_id=str(store.id), agency_id=current_user.agency_id)
    return {"success": True, "store_id": str(store.id), "role": role,
            "permissions": _member_permissions(db, user, store),
            "access_token": tokens.access_token, "refresh_token": tokens.refresh_token,
            "token_type": "bearer"}


class StoreMemberInput(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    role: str
    permissions: list[str] = Field(default_factory=list)
    branch_names: Optional[list[str]] = None


@auth_router.get('/stores')
def get_accessible_stores(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    from modules.stores.schemas import StoreResponse
    stores = _accessible_stores(db, uuid.UUID(str(current_user.id))).order_by(Store.created_at).all()
    return {'stores': [StoreResponse.model_validate(store) for store in stores],
            'total': len(stores), 'page': 1, 'size': len(stores)}


MEMBER_PERMISSIONS = frozenset({'messages', 'deliveries', 'ads', 'orders', 'products', 'customers'})


def _require_store_owner(db: Session, store_id: uuid.UUID, user: CurrentUser):
    store = db.query(Store).filter(Store.id == store_id, Store.owner_id == uuid.UUID(str(user.id))).first()
    if not store:
        raise HTTPException(status_code=403, detail='Only the store owner can manage its users')
    return store


def _member_payload(member, user):
    return {'id': str(member.id), 'user_id': str(user.id), 'name': user.name,
            'email': user.email, 'role': member.role,
            'permissions': member.permissions, 'branch_names': member.branch_names,
            'is_active': member.is_active}


@auth_router.get('/stores/{store_id}/members')
def list_store_members(store_id: uuid.UUID, db: Session = Depends(get_db),
                       current_user: CurrentUser = Depends(get_current_user)):
    _require_store_owner(db, store_id, current_user)
    rows = db.query(StoreMember, User).join(User, User.id == StoreMember.user_id).filter(
        StoreMember.store_id == store_id).order_by(StoreMember.created_at).all()
    return [_member_payload(member, user) for member, user in rows]


@auth_router.post('/stores/{store_id}/members', status_code=201)
def create_store_member(store_id: uuid.UUID, data: StoreMemberInput, db: Session = Depends(get_db),
                        current_user: CurrentUser = Depends(get_current_user)):
    _require_store_owner(db, store_id, current_user)
    if data.role not in ('staff', 'manager') or not set(data.permissions).issubset(MEMBER_PERMISSIONS):
        raise HTTPException(status_code=400, detail='Invalid role or permissions')
    email = str(data.email).strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user and user.id == uuid.UUID(str(current_user.id)):
        raise HTTPException(status_code=400, detail='The owner already has access to this store')
    if user and not user.is_active:
        raise HTTPException(status_code=409, detail='This user account is disabled')
    if not user:
        user = User(name=data.name.strip(), email=email, role=UserRole.STAFF,
                    is_active=True, is_verified=False)
        db.add(user)
        db.flush()
    member = db.query(StoreMember).filter(StoreMember.store_id == store_id,
                                           StoreMember.user_id == user.id).first()
    if member:
        raise HTTPException(status_code=409, detail='This user is already assigned to the store')
    member = StoreMember(store_id=store_id, user_id=user.id, role=data.role,
                         permissions=sorted(set(data.permissions)),
                         branch_names=sorted(set(data.branch_names)) if data.branch_names is not None else None,
                         is_active=True)
    db.add(member)
    db.commit()
    db.refresh(member)
    return _member_payload(member, user)


class StoreMemberUpdate(BaseModel):
    role: str
    permissions: list[str] = Field(default_factory=list)
    is_active: bool = True
    branch_names: Optional[list[str]] = None


@auth_router.put('/stores/{store_id}/members/{member_id}')
def update_store_member(store_id: uuid.UUID, member_id: uuid.UUID, data: StoreMemberUpdate,
                        db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    _require_store_owner(db, store_id, current_user)
    if data.role not in ('staff', 'manager') or not set(data.permissions).issubset(MEMBER_PERMISSIONS):
        raise HTTPException(status_code=400, detail='Invalid role or permissions')
    member = db.query(StoreMember).filter(StoreMember.store_id == store_id, StoreMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail='Store user not found')
    member.role, member.permissions, member.is_active = data.role, sorted(set(data.permissions)), data.is_active
    if data.branch_names is not None:
        member.branch_names = sorted(set(data.branch_names))
    db.commit()
    user = db.query(User).filter(User.id == member.user_id).first()
    return _member_payload(member, user)

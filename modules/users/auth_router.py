# modules/users/auth_api.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from modules.users.models import User
from modules.users.schemas import (
    LoginRequest, LoginVerifyRequest, LoginResponse
)
from modules.stores.models import Store, StoreSetupSession
from utils.Verification_Codes_Services import VerificationCodeService

auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])

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
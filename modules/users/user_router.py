# modules/users/api.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from database import get_db
from modules.users.models import User, UserRole
from utils.jwt_auth import get_current_user, CurrentUser
from modules.users.schemas import (
    UserCreate, UserResponse, UserUpdate, UserListResponse
)
from utils.Verification_Codes_Services import VerificationCodeService

user_router = APIRouter(prefix="/api/users", tags=["users"])

# GET all users with pagination
@user_router.get("/", response_model=UserListResponse)
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    role: Optional[str] = None,
    is_verified: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    # This legacy endpoint is global, not store-scoped.
    raise HTTPException(status_code=403, detail="Use store user settings")
    try:
        # Build query with filters
        query = db.query(User)
        
        if role:
            query = query.filter(User.role == role)
        if is_verified is not None:
            query = query.filter(User.is_verified == is_verified)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        users = query.offset(skip).limit(limit).all()
        
        return UserListResponse(
            users=users,
            total=total,
            page=skip // limit + 1,
            size=len(users)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching users: {str(e)}"
        )

# GET user by ID
@user_router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: uuid.UUID, db: Session = Depends(get_db),
                   current_user: CurrentUser = Depends(get_current_user)):
    if str(user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
            
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching user: {str(e)}"
        )

# CREATE user
@user_router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_data: UserCreate, db: Session = Depends(get_db)):
    if user_data.role != UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Staff must be added by a store owner")
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        
        if existing_user:
            # If user exists, just send verification code and return the existing user
            success = VerificationCodeService.send_verification_code(
                db=db,
                email=user_data.email,
                code_type="email_verification"
            )
            
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to send verification code"
                )
            
            return existing_user
        
        # Create new user if doesn't exist
        db_user = User(**user_data.model_dump())
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # Send verification code for new user
        success = VerificationCodeService.send_verification_code(
            db=db,
            email=user_data.email,
            code_type="email_verification"
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send verification code"
            )
        
        return db_user
  
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating user: {str(e)}"
        )
    
# UPDATE user
@user_router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID, 
    user_data: UserUpdate, 
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    if str(user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        # Get existing user
        db_user = db.query(User).filter(User.id == user_id).first()
        
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Update only provided fields
        update_data = user_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_user, field, value)
        
        db.commit()
        db.refresh(db_user)
        
        return db_user
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating user: {str(e)}"
        )

# DELETE user
@user_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db),
                      current_user: CurrentUser = Depends(get_current_user)):
    if str(user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        db_user = db.query(User).filter(User.id == user_id).first()
        
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        db.delete(db_user)
        db.commit()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting user: {str(e)}"
        )

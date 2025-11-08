from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from uuid import UUID # Import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response # Import Response for 204
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User # Ensure User model is correctly imported
from schemas import UserOut, UserUpdate, StatsResponse # Ensure UserOut, UserUpdate, StatsResponse are correctly imported
from auth import get_current_user # Ensure get_current_user is correctly imported

# --- Dependency to check admin role ---
# This dependency is applied to the router itself, meaning all endpoints
# within this router will automatically require an authenticated admin user.
def require_admin(current_user: User = Depends(get_current_user)):
    """
    Dependency that checks if the current authenticated user has 'admin' role.
    Raises HTTPException(403 Forbidden) if not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required."
        )
    return current_user

# --- Router for admin-only operations ---
admin_router = APIRouter(
    prefix="/admin",
    tags=["Admin Operations"], # Capitalized tag for consistency
    dependencies=[Depends(require_admin)] # Apply the admin dependency to the entire router
)

@admin_router.get("/users", response_model=List[UserOut], status_code=status.HTTP_200_OK)
def list_users(
    skip: int = Query(0, ge=0, description="Number of items to skip"), # Added Query descriptions and validation
    limit: int = Query(100, gt=0, le=1000, description="Maximum number of items to return"),
    role: Optional[str] = Query(None, description="Filter users by role (e.g., 'customer', 'supplier', 'admin')"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter users by status (e.g., 'active', 'disabled', 'pending')"), # Renamed 'status' to 'status_filter' to avoid conflict with Python's built-in status
    db: Session = Depends(get_db)
):
    """
    Retrieves a list of users, with optional filtering by role and status.
    Requires admin privileges.
    """
    query = db.query(User)

    if role:
        # Validate role to be one of the allowed enum values from your User model
        # You might want to import the Enum directly from models or define allowed roles
        allowed_roles = ["customer", "supplier", "admin"] # Assuming these are your defined roles
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role provided. Allowed roles are: {', '.join(allowed_roles)}.")
        query = query.filter(User.role == role)
    
    if status_filter: # Use the renamed variable
        # Validate status to be one of the allowed enum values from your User model
        allowed_statuses = ["active", "disabled", "pending"] # Assuming these are your defined statuses
        if status_filter not in allowed_statuses:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status provided. Allowed statuses are: {', '.join(allowed_statuses)}.")
        query = query.filter(User.status == status_filter)
        
    users = query.offset(skip).limit(limit).all()
    return users

@admin_router.get("/users/{user_id}", response_model=UserOut, status_code=status.HTTP_200_OK)
def get_user(
    user_id: UUID, # Use UUID type for path parameter
    db: Session = Depends(get_db)
):
    """
    Retrieves a single user's details by ID.
    Requires admin privileges.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user

@admin_router.patch("/users/{user_id}", response_model=UserOut, status_code=status.HTTP_200_OK)
def update_user(
    user_id: UUID, # Use UUID type for path parameter
    data: UserUpdate,
    db: Session = Depends(get_db)
):
    """
    Updates specific fields of a user's profile, such as status or role.
    Requires admin privileges.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    # Update only the fields that are provided in the request
    update_data = data.model_dump(exclude_unset=True) # Use model_dump for Pydantic V2
    for field, value in update_data.items():
        # Optional: Add validation for role and status changes if needed,
        # ensuring they are valid enum values from your User model.
        if field == "role":
            allowed_roles = ["customer", "supplier", "admin"]
            if value not in allowed_roles:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role value: '{value}'. Allowed roles are: {', '.join(allowed_roles)}.")
        if field == "status":
            allowed_statuses = ["active", "disabled", "pending"]
            if value not in allowed_statuses:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status value: '{value}'. Allowed statuses are: {', '.join(allowed_statuses)}.")
        
        setattr(user, field, value)
    
    # Update the 'updated_at' timestamp if your User model has one
    if hasattr(user, 'updated_at'):
        user.updated_at = datetime.now(timezone.utc)

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update user: {e}")

    return user

@admin_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID, # Use UUID type for path parameter
    db: Session = Depends(get_db)
):
    """
    Deletes a user permanently from the database.
    Requires admin privileges.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    try:
        db.delete(user)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete user: {e}")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT) # Return an empty response for 204

@admin_router.get("/stats/users", response_model=StatsResponse, status_code=status.HTTP_200_OK)
def user_stats(
    period_days: int = Query(30, gt=0, description="Number of days back from the current date to calculate statistics."),
    db: Session = Depends(get_db)
) -> StatsResponse:
    """
    Returns user statistics including total, active, disabled, and new users
    within a specified period. Requires admin privileges.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=period_days)

    total = db.query(func.count(User.id)).scalar()
    active = db.query(func.count(User.id)).filter(User.status == 'active').scalar()
    disabled = db.query(func.count(User.id)).filter(User.status == 'disabled').scalar()
    pending = db.query(func.count(User.id)).filter(User.status == 'pending').scalar() # Added pending users stat
    new_users = db.query(func.count(User.id)).filter(User.created_at >= since).scalar()

    return StatsResponse(
        total_users=total,
        active_users=active,
        disabled_users=disabled,
        pending_users=pending, # Include in response
        new_users=new_users,
        period_days=period_days
    )
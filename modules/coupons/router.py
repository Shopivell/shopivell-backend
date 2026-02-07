# modules/coupons/router.py
"""
API endpoints for coupons and promotions.
"""

import logging
from typing import Optional
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from modules.users.models import User
from utils.jwt_auth import get_current_user

from .models import Coupon, CouponUsage
from .schemas import (
    CouponCreate, CouponUpdate, CouponResponse, CouponListResponse,
    CouponValidateRequest, CouponValidateResponse,
    CouponApplyRequest, CouponUsageResponse
)

logger = logging.getLogger(__name__)

coupon_router = APIRouter(prefix="/api/coupons", tags=["Coupons"])


# ============ Helper Functions ============

def get_coupon_response(coupon: Coupon) -> CouponResponse:
    """Convert Coupon model to response schema."""
    return CouponResponse(
        id=coupon.id,
        store_id=coupon.store_id,
        code=coupon.code,
        description=coupon.description,
        type=coupon.type,
        value=coupon.value,
        min_order_amount=coupon.min_order_amount,
        max_discount=coupon.max_discount,
        usage_limit=coupon.usage_limit,
        used_count=coupon.used_count,
        per_user_limit=coupon.per_user_limit,
        applicable_products=coupon.applicable_products or [],
        applicable_categories=coupon.applicable_categories or [],
        starts_at=coupon.starts_at,
        expires_at=coupon.expires_at,
        is_active=coupon.is_active,
        created_at=coupon.created_at,
        updated_at=coupon.updated_at
    )


def calculate_discount(coupon: Coupon, order_amount: float) -> float:
    """Calculate the discount amount for a coupon."""
    if coupon.type == "percentage":
        discount = order_amount * (coupon.value / 100)
        if coupon.max_discount:
            discount = min(discount, coupon.max_discount)
        return round(discount, 2)
    elif coupon.type == "fixed":
        return min(coupon.value, order_amount)
    elif coupon.type == "free_shipping":
        return 0  # Shipping discount handled separately
    return 0


def validate_coupon_logic(coupon: Coupon, order_amount: float, user_id: UUID, db: Session) -> tuple[bool, str]:
    """Validate if a coupon can be used. Returns (is_valid, message)."""
    if not coupon:
        return False, "Coupon not found"

    if not coupon.is_active:
        return False, "Coupon is inactive"

    now = datetime.utcnow()
    if coupon.starts_at and now < coupon.starts_at:
        return False, "Coupon is not yet active"

    if coupon.expires_at and now > coupon.expires_at:
        return False, "Coupon has expired"

    if coupon.usage_limit and coupon.used_count >= coupon.usage_limit:
        return False, "Coupon usage limit reached"

    if coupon.min_order_amount and order_amount < coupon.min_order_amount:
        return False, f"Minimum order amount is {coupon.min_order_amount}"

    # Check per-user limit
    user_usage_count = db.query(CouponUsage).filter(
        CouponUsage.coupon_id == coupon.id,
        CouponUsage.user_id == user_id
    ).count()

    if user_usage_count >= coupon.per_user_limit:
        return False, "You have already used this coupon the maximum number of times"

    return True, "Coupon is valid"


# ============ Store Owner Endpoints ============

@coupon_router.post("", response_model=CouponResponse, status_code=status.HTTP_201_CREATED)
async def create_coupon(
    coupon_data: CouponCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new coupon for a store.
    """
    try:
        # Check if code already exists
        existing = db.query(Coupon).filter(Coupon.code == coupon_data.code.upper()).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Coupon code already exists"
            )

        coupon = Coupon(
            store_id=coupon_data.store_id,
            code=coupon_data.code.upper(),
            description=coupon_data.description,
            type=coupon_data.type.value,
            value=coupon_data.value,
            min_order_amount=coupon_data.min_order_amount,
            max_discount=coupon_data.max_discount,
            usage_limit=coupon_data.usage_limit,
            per_user_limit=coupon_data.per_user_limit,
            applicable_products=coupon_data.applicable_products or [],
            applicable_categories=coupon_data.applicable_categories or [],
            starts_at=coupon_data.starts_at,
            expires_at=coupon_data.expires_at,
            is_active=coupon_data.is_active
        )

        db.add(coupon)
        db.commit()
        db.refresh(coupon)

        logger.info(f"Coupon created: {coupon.code} for store {coupon.store_id}")
        return get_coupon_response(coupon)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating coupon: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create coupon: {str(e)}"
        )


@coupon_router.get("/store/{store_id}", response_model=CouponListResponse)
async def get_store_coupons(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all coupons for a store.
    """
    query = db.query(Coupon).filter(Coupon.store_id == store_id)

    if is_active is not None:
        query = query.filter(Coupon.is_active == is_active)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    coupons = query.order_by(desc(Coupon.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return CouponListResponse(
        coupons=[get_coupon_response(c) for c in coupons],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@coupon_router.put("/{coupon_id}", response_model=CouponResponse)
async def update_coupon(
    coupon_id: UUID,
    update_data: CouponUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a coupon.
    """
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coupon not found"
        )

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(coupon, key, value)

    db.commit()
    db.refresh(coupon)

    return get_coupon_response(coupon)


@coupon_router.delete("/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_coupon(
    coupon_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a coupon.
    """
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()

    if not coupon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coupon not found"
        )

    db.delete(coupon)
    db.commit()
    return None


# ============ Shopper Endpoints ============

@coupon_router.post("/validate", response_model=CouponValidateResponse)
async def validate_coupon(
    request: CouponValidateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Validate a coupon code for an order.
    """
    coupon = db.query(Coupon).filter(
        Coupon.code == request.code.upper(),
        Coupon.store_id == request.store_id
    ).first()

    is_valid, message = validate_coupon_logic(coupon, request.order_amount, current_user.id, db)

    discount = 0
    if is_valid and coupon:
        discount = calculate_discount(coupon, request.order_amount)
        message = f"Coupon applied! You save ${discount:.2f}"

    return CouponValidateResponse(
        valid=is_valid,
        discount_amount=discount,
        message=message
    )


@coupon_router.post("/apply", response_model=CouponUsageResponse)
async def apply_coupon(
    request: CouponApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Apply a coupon to an order (records usage).
    """
    coupon = db.query(Coupon).filter(
        Coupon.code == request.code.upper(),
        Coupon.store_id == request.store_id
    ).first()

    is_valid, message = validate_coupon_logic(coupon, request.order_amount, current_user.id, db)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    discount = calculate_discount(coupon, request.order_amount)

    usage = CouponUsage(
        coupon_id=coupon.id,
        user_id=current_user.id,
        order_id=request.order_id,
        discount_amount=discount
    )
    db.add(usage)

    coupon.used_count += 1

    db.commit()
    db.refresh(usage)

    return CouponUsageResponse(
        id=usage.id,
        coupon_id=usage.coupon_id,
        user_id=usage.user_id,
        order_id=usage.order_id,
        discount_amount=usage.discount_amount,
        used_at=usage.used_at
    )


# ============ Admin Endpoints ============

@coupon_router.get("/admin/all", response_model=CouponListResponse)
async def admin_get_all_coupons(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Get all coupons across all stores.
    """
    query = db.query(Coupon)

    if store_id:
        query = query.filter(Coupon.store_id == store_id)
    if is_active is not None:
        query = query.filter(Coupon.is_active == is_active)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    coupons = query.order_by(desc(Coupon.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return CouponListResponse(
        coupons=[get_coupon_response(c) for c in coupons],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )

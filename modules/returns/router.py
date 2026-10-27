# modules/returns/router.py
"""
API endpoints for returns and refunds.
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

from .models import ReturnRequest
from .schemas import (
    ReturnCreate, ReturnStatusUpdate, ReturnResponse,
    ReturnListResponse, ReturnStatus
)

logger = logging.getLogger(__name__)

return_router = APIRouter(prefix="/api/returns", tags=["Returns"])


# ============ Helper Functions ============

def get_return_response(ret: ReturnRequest) -> ReturnResponse:
    """Convert ReturnRequest model to response schema."""
    return ReturnResponse(
        id=ret.id,
        store_id=ret.store_id,
        order_id=ret.order_id,
        customer_id=ret.customer_id,
        reason=ret.reason,
        description=ret.description,
        images=ret.images or [],
        status=ret.status,
        refund_amount=ret.refund_amount,
        refund_method=ret.refund_method,
        admin_notes=ret.admin_notes,
        created_at=ret.created_at,
        updated_at=ret.updated_at,
        resolved_at=ret.resolved_at
    )


# ============ Shopper Endpoints ============

@return_router.post("", response_model=ReturnResponse, status_code=status.HTTP_201_CREATED)
async def create_return_request(
    return_data: ReturnCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new return request for an order.
    """
    try:
        # Check if a return request already exists for this order
        existing = db.query(ReturnRequest).filter(
            ReturnRequest.order_id == return_data.order_id,
            ReturnRequest.customer_id == current_user.id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A return request already exists for this order"
            )

        ret = ReturnRequest(
            store_id=return_data.store_id,
            order_id=return_data.order_id,
            customer_id=current_user.id,
            reason=return_data.reason.value,
            description=return_data.description,
            images=return_data.images or [],
            status=ReturnStatus.PENDING.value
        )

        db.add(ret)
        db.commit()
        db.refresh(ret)

        logger.info(f"Return request created: {ret.id} for order {ret.order_id}")
        return get_return_response(ret)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating return request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create return request: {str(e)}"
        )


@return_router.get("/customer/{user_id}", response_model=ReturnListResponse)
async def get_customer_returns(
    user_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all return requests for a customer.
    """
    query = db.query(ReturnRequest).filter(ReturnRequest.customer_id == user_id)

    if status_filter:
        query = query.filter(ReturnRequest.status == status_filter)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    returns = query.order_by(desc(ReturnRequest.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ReturnListResponse(
        returns=[get_return_response(r) for r in returns],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# ============ Store Owner Endpoints ============

@return_router.get("/store/{store_id}", response_model=ReturnListResponse)
async def get_store_returns(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all return requests for a store.
    """
    query = db.query(ReturnRequest).filter(ReturnRequest.store_id == store_id)

    if status_filter:
        query = query.filter(ReturnRequest.status == status_filter)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    returns = query.order_by(desc(ReturnRequest.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ReturnListResponse(
        returns=[get_return_response(r) for r in returns],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@return_router.put("/{return_id}/status", response_model=ReturnResponse)
async def update_return_status(
    return_id: UUID,
    update_data: ReturnStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update the status of a return request (store owner or admin).
    """
    ret = db.query(ReturnRequest).filter(ReturnRequest.id == return_id).first()

    if not ret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found"
        )

    ret.status = update_data.status.value

    if update_data.refund_amount is not None:
        ret.refund_amount = update_data.refund_amount
    if update_data.refund_method is not None:
        ret.refund_method = update_data.refund_method.value
    if update_data.admin_notes is not None:
        ret.admin_notes = update_data.admin_notes

    if update_data.status in [ReturnStatus.COMPLETED, ReturnStatus.REFUNDED, ReturnStatus.REJECTED]:
        ret.resolved_at = datetime.utcnow()

    db.commit()
    db.refresh(ret)

    return get_return_response(ret)


# ============ Admin Endpoints ============

@return_router.get("/admin/all", response_model=ReturnListResponse)
async def admin_get_all_returns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Get all return requests across all stores.
    """
    query = db.query(ReturnRequest)

    if store_id:
        query = query.filter(ReturnRequest.store_id == store_id)
    if status_filter:
        query = query.filter(ReturnRequest.status == status_filter)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    returns = query.order_by(desc(ReturnRequest.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ReturnListResponse(
        returns=[get_return_response(r) for r in returns],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )

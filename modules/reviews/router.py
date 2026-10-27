# modules/reviews/router.py
"""
API endpoints for product and store reviews.
"""

import logging
from typing import Optional
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from database import get_db
from modules.users.models import User
from utils.jwt_auth import get_current_user

from .models import Review, ReviewVote
from .schemas import (
    ReviewCreate, ReviewUpdate, ReviewResponse, ReviewListResponse,
    ReviewSummary, ReviewVoteCreate, SellerResponseCreate,
    AdminReviewUpdate, UserInfo
)

logger = logging.getLogger(__name__)

review_router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


# ============ Helper Functions ============

def get_review_response(review: Review) -> ReviewResponse:
    """Convert Review model to response schema."""
    customer_info = None
    if review.customer:
        customer_info = UserInfo(
            id=review.customer.id,
            email=review.customer.email,
            first_name=getattr(review.customer, 'first_name', None),
            last_name=getattr(review.customer, 'last_name', None)
        )

    return ReviewResponse(
        id=review.id,
        store_id=review.store_id,
        product_id=review.product_id,
        customer_id=review.customer_id,
        order_id=review.order_id,
        rating=review.rating,
        title=review.title,
        comment=review.comment,
        images=review.images or [],
        is_verified_purchase=review.is_verified_purchase,
        is_approved=review.is_approved,
        helpful_count=review.helpful_count,
        reported_count=review.reported_count,
        seller_response=review.seller_response,
        seller_response_at=review.seller_response_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        customer=customer_info
    )


# ============ Shopper Endpoints ============

@review_router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review_data: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new review for a product or store.
    """
    try:
        # Check if user already reviewed this product/store
        existing = db.query(Review).filter(
            Review.customer_id == current_user.id,
            Review.store_id == review_data.store_id,
            Review.product_id == review_data.product_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already reviewed this item"
            )

        is_verified = False
        if review_data.order_id:
            is_verified = True

        review = Review(
            store_id=review_data.store_id,
            product_id=review_data.product_id,
            customer_id=current_user.id,
            order_id=review_data.order_id,
            rating=review_data.rating,
            title=review_data.title,
            comment=review_data.comment,
            images=review_data.images or [],
            is_verified_purchase=is_verified
        )

        db.add(review)
        db.commit()
        db.refresh(review)

        logger.info(f"New review created: {review.id} by user {current_user.id}")
        return get_review_response(review)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating review: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create review: {str(e)}"
        )


@review_router.get("/product/{product_id}", response_model=ReviewListResponse)
async def get_product_reviews(
    product_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("recent", description="Sort by: recent, rating_high, rating_low, helpful"),
    db: Session = Depends(get_db)
):
    """
    Get all approved reviews for a product. No authentication required.
    """
    query = db.query(Review).filter(
        Review.product_id == product_id,
        Review.is_approved == True
    )

    if sort_by == "rating_high":
        query = query.order_by(desc(Review.rating), desc(Review.created_at))
    elif sort_by == "rating_low":
        query = query.order_by(Review.rating, desc(Review.created_at))
    elif sort_by == "helpful":
        query = query.order_by(desc(Review.helpful_count), desc(Review.created_at))
    else:
        query = query.order_by(desc(Review.created_at))

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    reviews = query.offset((page - 1) * page_size).limit(page_size).all()

    return ReviewListResponse(
        reviews=[get_review_response(r) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@review_router.get("/store/{store_id}", response_model=ReviewListResponse)
async def get_store_reviews(
    store_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    rating: Optional[int] = Query(None, ge=1, le=5),
    db: Session = Depends(get_db)
):
    """
    Get all approved reviews for a store. No authentication required.
    """
    query = db.query(Review).filter(
        Review.store_id == store_id,
        Review.is_approved == True
    )

    if rating:
        query = query.filter(Review.rating == rating)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    reviews = query.order_by(desc(Review.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ReviewListResponse(
        reviews=[get_review_response(r) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@review_router.get("/store/{store_id}/summary", response_model=ReviewSummary)
async def get_store_review_summary(
    store_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get review summary for a store (avg rating, distribution).
    """
    reviews = db.query(Review).filter(
        Review.store_id == store_id,
        Review.is_approved == True
    )

    total = reviews.count()
    avg = db.query(func.avg(Review.rating)).filter(
        Review.store_id == store_id,
        Review.is_approved == True
    ).scalar() or 0.0

    distribution = {}
    for i in range(1, 6):
        count = reviews.filter(Review.rating == i).count()
        distribution[str(i)] = count

    return ReviewSummary(
        avg_rating=round(float(avg), 1),
        total_reviews=total,
        rating_distribution=distribution
    )


@review_router.put("/{review_id}", response_model=ReviewResponse)
async def update_review(
    review_id: UUID,
    update_data: ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update your own review.
    """
    review = db.query(Review).filter(
        Review.id == review_id,
        Review.customer_id == current_user.id
    ).first()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found or you don't have permission to edit it"
        )

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(review, key, value)

    db.commit()
    db.refresh(review)

    return get_review_response(review)


@review_router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a review: the original reviewer, or the store owner moderating reviews
    on their own store.
    """
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    is_author = review.customer_id == current_user.id
    is_store_owner = False
    if not is_author:
        from modules.stores.models import Store
        is_store_owner = db.query(Store).filter(
            Store.id == review.store_id, Store.owner_id == current_user.id
        ).first() is not None

    if not (is_author or is_store_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this review"
        )

    db.delete(review)
    db.commit()
    return None


# ============ Voting ============

@review_router.post("/{review_id}/vote", response_model=ReviewResponse)
async def vote_review(
    review_id: UUID,
    vote_data: ReviewVoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Vote a review as helpful or not helpful.
    """
    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )

    existing_vote = db.query(ReviewVote).filter(
        ReviewVote.review_id == review_id,
        ReviewVote.user_id == current_user.id
    ).first()

    if existing_vote:
        existing_vote.is_helpful = vote_data.is_helpful
    else:
        vote = ReviewVote(
            review_id=review_id,
            user_id=current_user.id,
            is_helpful=vote_data.is_helpful
        )
        db.add(vote)

    # Recalculate helpful count
    helpful_count = db.query(ReviewVote).filter(
        ReviewVote.review_id == review_id,
        ReviewVote.is_helpful == True
    ).count()
    review.helpful_count = helpful_count

    db.commit()
    db.refresh(review)

    return get_review_response(review)


# ============ Seller Endpoints ============

@review_router.put("/{review_id}/respond", response_model=ReviewResponse)
async def respond_to_review(
    review_id: UUID,
    response_data: SellerResponseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Seller responds to a review on their store.
    """
    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )

    review.seller_response = response_data.seller_response
    review.seller_response_at = datetime.utcnow()

    db.commit()
    db.refresh(review)

    return get_review_response(review)


# ============ Admin Endpoints ============

@review_router.get("/admin/pending", response_model=ReviewListResponse)
async def admin_get_pending_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Get all pending/unapproved reviews.
    """
    query = db.query(Review).filter(Review.is_approved == False)

    if store_id:
        query = query.filter(Review.store_id == store_id)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    reviews = query.order_by(desc(Review.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ReviewListResponse(
        reviews=[get_review_response(r) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@review_router.get("/admin/all", response_model=ReviewListResponse)
async def admin_get_all_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    store_id: Optional[UUID] = None,
    rating: Optional[int] = Query(None, ge=1, le=5),
    is_approved: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Get all reviews with filters.
    """
    query = db.query(Review)

    if store_id:
        query = query.filter(Review.store_id == store_id)
    if rating:
        query = query.filter(Review.rating == rating)
    if is_approved is not None:
        query = query.filter(Review.is_approved == is_approved)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    reviews = query.order_by(desc(Review.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return ReviewListResponse(
        reviews=[get_review_response(r) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@review_router.patch("/admin/{review_id}", response_model=ReviewResponse)
async def admin_update_review(
    review_id: UUID,
    update_data: AdminReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Approve or reject a review.
    """
    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(review, key, value)

    db.commit()
    db.refresh(review)

    return get_review_response(review)

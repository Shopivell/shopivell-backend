# modules/feedback/router.py
"""
API endpoints for feedback, bug reports, and feature requests.
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from database import get_db
from modules.users.models import User
from utils.jwt_auth import get_current_user, CurrentUser

from .models import Feedback, FeedbackComment, FeedbackVote
from .schemas import (
    FeedbackCreate, FeedbackUpdate, FeedbackAdminUpdate,
    FeedbackResponse, FeedbackListResponse, FeedbackStatsResponse,
    CommentCreate, CommentUpdate, FeedbackCommentResponse, UserInfo,
    FeedbackType, FeedbackStatus, FeedbackPriority
)

logger = logging.getLogger(__name__)

feedback_router = APIRouter(prefix="/feedback", tags=["Feedback"])


# ============ Helper Functions ============

def get_feedback_response(feedback: Feedback, db: Session) -> FeedbackResponse:
    """Convert Feedback model to response schema"""
    comments_count = db.query(FeedbackComment).filter(
        FeedbackComment.feedback_id == feedback.id
    ).count()

    user_info = None
    if feedback.user:
        user_info = UserInfo(
            id=feedback.user.id,
            email=feedback.user.email,
            first_name=getattr(feedback.user, 'first_name', None),
            last_name=getattr(feedback.user, 'last_name', None)
        )

    return FeedbackResponse(
        id=feedback.id,
        type=feedback.type,
        title=feedback.title,
        description=feedback.description,
        page_url=feedback.page_url,
        browser_info=feedback.browser_info,
        screenshot_url=feedback.screenshot_url,
        error_message=feedback.error_message,
        steps_to_reproduce=feedback.steps_to_reproduce,
        status=feedback.status,
        priority=feedback.priority,
        admin_response=feedback.admin_response,
        responded_at=feedback.responded_at,
        upvotes=feedback.upvotes,
        is_public=feedback.is_public,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
        resolved_at=feedback.resolved_at,
        user=user_info,
        comments_count=comments_count
    )


# ============ User Endpoints ============

@feedback_router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    feedback_data: FeedbackCreate,
    store_id: Optional[UUID] = Query(None, description="Store ID if applicable"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Submit new feedback, bug report, or feature request.

    Users can submit:
    - Bug reports with steps to reproduce
    - Feature requests
    - General feedback or questions
    - Improvement suggestions

    Optional: Include screenshot URL, browser info, and error messages.
    """
    try:
        feedback = Feedback(
            user_id=current_user.id,
            store_id=store_id,
            type=feedback_data.type.value,
            title=feedback_data.title,
            description=feedback_data.description,
            page_url=feedback_data.page_url,
            browser_info=feedback_data.browser_info,
            screenshot_url=feedback_data.screenshot_url,
            error_message=feedback_data.error_message,
            steps_to_reproduce=feedback_data.steps_to_reproduce,
            priority=feedback_data.priority.value,
            is_public=feedback_data.is_public,
            rating=feedback_data.rating,
            status=FeedbackStatus.NEW.value
        )

        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        logger.info(f"New feedback submitted: {feedback.id} by user {current_user.id}")

        return get_feedback_response(feedback, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit feedback: {str(e)}"
        )


@feedback_router.get("", response_model=FeedbackListResponse)
async def list_my_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[FeedbackType] = None,
    status: Optional[FeedbackStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all feedback submitted by the current user.

    Supports filtering by type and status.
    """
    query = db.query(Feedback).filter(Feedback.user_id == current_user.id)

    if type:
        query = query.filter(Feedback.type == type.value)
    if status:
        query = query.filter(Feedback.status == status.value)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    feedback_list = query.order_by(desc(Feedback.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return FeedbackListResponse(
        feedback=[get_feedback_response(f, db) for f in feedback_list],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@feedback_router.get("/public", response_model=FeedbackListResponse)
async def list_public_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[FeedbackType] = None,
    status: Optional[FeedbackStatus] = None,
    sort_by: str = Query("recent", description="Sort by: recent, popular, status"),
    db: Session = Depends(get_db)
):
    """
    List all public feedback (feature requests, etc.) that users can vote on.

    No authentication required.
    """
    query = db.query(Feedback).filter(Feedback.is_public == True)

    if type:
        query = query.filter(Feedback.type == type.value)
    if status:
        query = query.filter(Feedback.status == status.value)

    # Sorting
    if sort_by == "popular":
        query = query.order_by(desc(Feedback.upvotes), desc(Feedback.created_at))
    elif sort_by == "status":
        query = query.order_by(Feedback.status, desc(Feedback.created_at))
    else:  # recent
        query = query.order_by(desc(Feedback.created_at))

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    feedback_list = query.offset((page - 1) * page_size).limit(page_size).all()

    return FeedbackListResponse(
        feedback=[get_feedback_response(f, db) for f in feedback_list],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@feedback_router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get statistics about user's submitted feedback.
    """
    base_query = db.query(Feedback).filter(Feedback.user_id == current_user.id)

    total = base_query.count()

    # Count by type
    by_type = {}
    for t in FeedbackType:
        count = base_query.filter(Feedback.type == t.value).count()
        if count > 0:
            by_type[t.value] = count

    # Count by status
    by_status = {}
    for s in FeedbackStatus:
        count = base_query.filter(Feedback.status == s.value).count()
        if count > 0:
            by_status[s.value] = count

    # Count by priority
    by_priority = {}
    for p in FeedbackPriority:
        count = base_query.filter(Feedback.priority == p.value).count()
        if count > 0:
            by_priority[p.value] = count

    # Recent count (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_count = base_query.filter(Feedback.created_at >= week_ago).count()

    return FeedbackStatsResponse(
        total=total,
        by_type=by_type,
        by_status=by_status,
        by_priority=by_priority,
        recent_count=recent_count
    )


@feedback_router.get("/{feedback_id}", response_model=FeedbackResponse)
async def get_feedback(
    feedback_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get details of a specific feedback item.

    Users can view their own feedback or public feedback.
    """
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )

    # Check access
    if feedback.user_id != current_user.id and not feedback.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this feedback"
        )

    return get_feedback_response(feedback, db)


@feedback_router.patch("/{feedback_id}", response_model=FeedbackResponse)
async def update_feedback(
    feedback_id: UUID,
    update_data: FeedbackUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update your own feedback.

    Only the original submitter can update feedback.
    """
    feedback = db.query(Feedback).filter(
        Feedback.id == feedback_id,
        Feedback.user_id == current_user.id
    ).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found or you don't have permission to edit it"
        )

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(feedback, key, value)

    db.commit()
    db.refresh(feedback)

    return get_feedback_response(feedback, db)


@feedback_router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    feedback_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete your own feedback.

    Only the original submitter can delete feedback.
    """
    feedback = db.query(Feedback).filter(
        Feedback.id == feedback_id,
        Feedback.user_id == current_user.id
    ).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found or you don't have permission to delete it"
        )

    db.delete(feedback)
    db.commit()

    return None


# ============ Voting ============

@feedback_router.post("/{feedback_id}/vote", response_model=FeedbackResponse)
async def vote_feedback(
    feedback_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upvote a public feedback item.

    Users can only vote once per feedback item.
    """
    feedback = db.query(Feedback).filter(
        Feedback.id == feedback_id,
        Feedback.is_public == True
    ).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public feedback not found"
        )

    # Check if already voted
    existing_vote = db.query(FeedbackVote).filter(
        FeedbackVote.feedback_id == feedback_id,
        FeedbackVote.user_id == current_user.id
    ).first()

    if existing_vote:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already voted for this feedback"
        )

    # Create vote
    vote = FeedbackVote(
        feedback_id=feedback_id,
        user_id=current_user.id
    )
    db.add(vote)

    # Increment upvotes
    feedback.upvotes += 1

    db.commit()
    db.refresh(feedback)

    return get_feedback_response(feedback, db)


@feedback_router.delete("/{feedback_id}/vote", response_model=FeedbackResponse)
async def remove_vote(
    feedback_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Remove your vote from a feedback item.
    """
    vote = db.query(FeedbackVote).filter(
        FeedbackVote.feedback_id == feedback_id,
        FeedbackVote.user_id == current_user.id
    ).first()

    if not vote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You haven't voted for this feedback"
        )

    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if feedback:
        feedback.upvotes = max(0, feedback.upvotes - 1)

    db.delete(vote)
    db.commit()

    if feedback:
        db.refresh(feedback)
        return get_feedback_response(feedback, db)

    raise HTTPException(status_code=404, detail="Feedback not found")


# ============ Comments ============

@feedback_router.post("/{feedback_id}/comments", response_model=FeedbackCommentResponse)
async def add_comment(
    feedback_id: UUID,
    comment_data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a comment to a feedback item.

    Users can comment on their own feedback or public feedback.
    """
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )

    # Check access
    if feedback.user_id != current_user.id and not feedback.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can't comment on this feedback"
        )

    comment = FeedbackComment(
        feedback_id=feedback_id,
        user_id=current_user.id,
        comment=comment_data.comment,
        is_admin=False  # Will be set by admin endpoint
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    user_info = UserInfo(
        id=current_user.id,
        email=current_user.email,
        first_name=getattr(current_user, 'first_name', None),
        last_name=getattr(current_user, 'last_name', None)
    )

    return FeedbackCommentResponse(
        id=comment.id,
        comment=comment.comment,
        is_admin=comment.is_admin,
        created_at=comment.created_at,
        user=user_info
    )


@feedback_router.get("/{feedback_id}/comments", response_model=List[FeedbackCommentResponse])
async def get_comments(
    feedback_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all comments for a feedback item.
    """
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )

    # Check access
    if feedback.user_id != current_user.id and not feedback.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this feedback"
        )

    comments = db.query(FeedbackComment).filter(
        FeedbackComment.feedback_id == feedback_id
    ).order_by(FeedbackComment.created_at).all()

    result = []
    for comment in comments:
        user_info = None
        if comment.user:
            user_info = UserInfo(
                id=comment.user.id,
                email=comment.user.email,
                first_name=getattr(comment.user, 'first_name', None),
                last_name=getattr(comment.user, 'last_name', None)
            )

        result.append(FeedbackCommentResponse(
            id=comment.id,
            comment=comment.comment,
            is_admin=comment.is_admin,
            created_at=comment.created_at,
            user=user_info
        ))

    return result


# ============ Admin Endpoints ============

@feedback_router.get("/admin/all", response_model=FeedbackListResponse)
async def admin_list_all_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[FeedbackType] = None,
    status: Optional[FeedbackStatus] = None,
    priority: Optional[FeedbackPriority] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] List all feedback from all users.

    Supports filtering by type, status, and priority.
    """
    # TODO: Add proper admin check
    # if not current_user.is_admin:
    #     raise HTTPException(status_code=403, detail="Admin access required")

    query = db.query(Feedback)

    if type:
        query = query.filter(Feedback.type == type.value)
    if status:
        query = query.filter(Feedback.status == status.value)
    if priority:
        query = query.filter(Feedback.priority == priority.value)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    feedback_list = query.order_by(desc(Feedback.created_at)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return FeedbackListResponse(
        feedback=[get_feedback_response(f, db) for f in feedback_list],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@feedback_router.patch("/admin/{feedback_id}", response_model=FeedbackResponse)
async def admin_update_feedback(
    feedback_id: UUID,
    update_data: FeedbackAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Update feedback status, priority, or add admin response.
    """
    # TODO: Add proper admin check

    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()

    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)

    if 'admin_response' in update_dict and update_dict['admin_response']:
        feedback.responded_at = datetime.utcnow()
        feedback.responded_by = current_user.id

    if 'status' in update_dict:
        update_dict['status'] = update_dict['status'].value
        if update_dict['status'] == FeedbackStatus.COMPLETED.value:
            feedback.resolved_at = datetime.utcnow()

    if 'priority' in update_dict:
        update_dict['priority'] = update_dict['priority'].value

    for key, value in update_dict.items():
        setattr(feedback, key, value)

    db.commit()
    db.refresh(feedback)

    return get_feedback_response(feedback, db)


@feedback_router.get("/admin/stats", response_model=FeedbackStatsResponse)
async def admin_get_all_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    [Admin] Get statistics about all feedback.
    """
    # TODO: Add proper admin check

    total = db.query(Feedback).count()

    # Count by type
    by_type = {}
    for t in FeedbackType:
        count = db.query(Feedback).filter(Feedback.type == t.value).count()
        if count > 0:
            by_type[t.value] = count

    # Count by status
    by_status = {}
    for s in FeedbackStatus:
        count = db.query(Feedback).filter(Feedback.status == s.value).count()
        if count > 0:
            by_status[s.value] = count

    # Count by priority
    by_priority = {}
    for p in FeedbackPriority:
        count = db.query(Feedback).filter(Feedback.priority == p.value).count()
        if count > 0:
            by_priority[p.value] = count

    # Recent count (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_count = db.query(Feedback).filter(Feedback.created_at >= week_ago).count()

    return FeedbackStatsResponse(
        total=total,
        by_type=by_type,
        by_status=by_status,
        by_priority=by_priority,
        recent_count=recent_count
    )

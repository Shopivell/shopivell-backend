from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from database import get_db
from utils.jwt_auth import get_current_user, CurrentUser
from modules.fashion.models import TryOnSession, MeasurementStatus
from modules.fashion.schemas import TryOnResponse, TryOnListResponse

fashion_router = APIRouter(prefix="/api/fashion", tags=["fashion-tryon"])


@fashion_router.post("/try-on", response_model=TryOnResponse, status_code=201)
async def create_tryon_session(
    front_image: UploadFile = File(..., description="Full-body front photo (JPEG/PNG)"),
    side_image: Optional[UploadFile] = File(None, description="Side-view photo (optional)"),
    height_cm: float = Form(152.0, description="User height in cm for calibration"),
    store_id: Optional[str] = Form(None, description="Optional store UUID"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Extract body measurements from photos using computer vision.

    Upload a front-facing full-body photo (required) and optionally a side-view photo.
    Provide your real height in cm for accurate calibration.

    **Photo guidelines:**
    - Full body visible (head to feet)
    - Arms slightly apart from body
    - Tight-fitting clothes for best accuracy
    - Good lighting, plain background preferred
    - Accuracy: +/- 2-3 cm

    **Returns** measurements: shoulder_width, chest_width, chest_circumference,
    waist_width, waist, hip_width, hip, neck, arm_length, shirt_length,
    thigh, thigh_circumference, trouser_length (all in cm).
    """
    # Read image bytes
    front_bytes = await front_image.read()
    side_bytes = await side_image.read() if side_image else None

    # Parse store_id
    parsed_store_id = None
    if store_id:
        try:
            parsed_store_id = uuid.UUID(store_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid store_id format")

    # Create DB record
    session = TryOnSession(
        user_id=uuid.UUID(current_user.id),
        store_id=parsed_store_id,
        height_cm=height_cm,
        status=MeasurementStatus.FAILED.value,
    )
    db.add(session)
    db.flush()

    try:
        from modules.fashion.service import process_images

        result = process_images(
            front_image_bytes=front_bytes,
            side_image_bytes=side_bytes,
            user_height_cm=height_cm,
        )

        session.measurements = result["measurements"]
        session.debug_info = result["debug_info"]
        session.status = MeasurementStatus.COMPLETED.value
        db.commit()
        db.refresh(session)
        return session

    except ValueError as e:
        session.error_message = str(e)
        db.commit()
        db.refresh(session)
        raise HTTPException(status_code=400, detail={
            "message": str(e),
            "code": "INVALID_POSE",
            "session_id": str(session.id),
        })
    except Exception as e:
        session.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Measurement processing error: {str(e)}")


@fashion_router.get("/try-on/{session_id}", response_model=TryOnResponse)
async def get_tryon_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get a try-on session by ID."""
    session = db.query(TryOnSession).filter(
        TryOnSession.id == session_id,
        TryOnSession.user_id == uuid.UUID(current_user.id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Try-on session not found")
    return session


@fashion_router.get("/try-on/{session_id}/measurements")
async def get_tryon_measurements(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get just the measurements for a completed session."""
    session = db.query(TryOnSession).filter(
        TryOnSession.id == session_id,
        TryOnSession.user_id == uuid.UUID(current_user.id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Try-on session not found")
    if session.status != MeasurementStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail=f"Session status: {session.status}")
    return {"measurements": session.measurements, "debug_info": session.debug_info}


@fashion_router.get("/try-on", response_model=TryOnListResponse)
async def list_tryon_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all try-on sessions for the current user."""
    query = db.query(TryOnSession).filter(
        TryOnSession.user_id == uuid.UUID(current_user.id),
    )
    if status_filter:
        query = query.filter(TryOnSession.status == status_filter)

    total = query.count()
    sessions = query.order_by(TryOnSession.created_at.desc()).offset(skip).limit(limit).all()

    return TryOnListResponse(
        sessions=sessions,
        total=total,
        page=skip // limit + 1 if limit else 1,
        size=len(sessions),
    )


@fashion_router.delete("/try-on/{session_id}", status_code=204)
async def delete_tryon_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete a try-on session."""
    session = db.query(TryOnSession).filter(
        TryOnSession.id == session_id,
        TryOnSession.user_id == uuid.UUID(current_user.id),
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Try-on session not found")
    db.delete(session)
    db.commit()
    return None

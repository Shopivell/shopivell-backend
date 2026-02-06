from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
import uuid


class MeasurementsResult(BaseModel):
    """Body measurements extracted from images."""
    shoulder_width: Optional[float] = None
    chest_width: Optional[float] = None
    chest_circumference: Optional[float] = None
    waist_width: Optional[float] = None
    waist: Optional[float] = None
    hip_width: Optional[float] = None
    hip: Optional[float] = None
    neck: Optional[float] = None
    neck_width: Optional[float] = None
    arm_length: Optional[float] = None
    shirt_length: Optional[float] = None
    thigh: Optional[float] = None
    thigh_circumference: Optional[float] = None
    trouser_length: Optional[float] = None


class DebugInfo(BaseModel):
    scale_factor: Optional[float] = None
    focal_length: Optional[float] = None
    user_height_cm: Optional[float] = None


class TryOnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    height_cm: float
    status: str
    error_message: Optional[str] = None
    measurements: Optional[dict] = None
    debug_info: Optional[dict] = None
    created_at: datetime


class TryOnListResponse(BaseModel):
    sessions: List[TryOnResponse]
    total: int
    page: int
    size: int

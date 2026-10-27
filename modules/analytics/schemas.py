from pydantic import BaseModel, ConfigDict
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import uuid

# Platform Schemas
class PlatformBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    platform_type: str
    is_active: bool = False
    sync_status: str = 'inactive'

class PlatformCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    platform_type: str
    api_config: Dict[str, Any]

class PlatformResponse(PlatformBase):
    id: uuid.UUID
    last_sync: Optional[datetime]
    created_at: datetime
    updated_at: datetime

class PlatformListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    platforms: List[PlatformResponse]
    total: int

# Platform Data Schemas
class PlatformDataBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    platform_id: uuid.UUID
    data_type: str
    date: date
    metrics: Dict[str, Any]
    dimensions: Optional[Dict[str, Any]] = None

class PlatformDataCreate(PlatformDataBase):
    pass

class PlatformDataResponse(PlatformDataBase):
    id: uuid.UUID
    created_at: datetime

class PlatformDataListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    data: List[PlatformDataResponse]
    total: int
    page: int
    size: int

# Analytics Report Schemas
class ReportBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    category: str
    description: Optional[str] = None
    created_by: str = 'Shopify'
    report_type: str = 'standard'
    data_source: str = 'internal'
    has_info: bool = False
    is_active: bool = True
    is_favorite: bool = False

class ReportCreate(ReportBase):
    configuration: Optional[Dict[str, Any]] = None

class ReportUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    configuration: Optional[Dict[str, Any]] = None
    has_info: Optional[bool] = None
    is_active: Optional[bool] = None
    is_favorite: Optional[bool] = None

class ReportResponse(ReportBase):
    id: uuid.UUID
    configuration: Optional[Dict[str, Any]] = None
    last_viewed: Optional[datetime]
    created_at: datetime
    updated_at: datetime

class ReportListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    reports: List[ReportResponse]
    total: int
    page: int
    size: int

# Data Sync Log Schemas
class SyncLogBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    platform_id: uuid.UUID
    sync_type: str
    status: str
    records_processed: int = 0

class SyncLogResponse(SyncLogBase):
    id: uuid.UUID
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime]

class SyncLogListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    logs: List[SyncLogResponse]
    total: int
    page: int
    size: int

# Data Ingestion Schemas
class DataIngestionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    platform: str  # google_analytics, facebook, instagram, etc.
    data_type: str  # sessions, conversions, impressions, etc.
    date: date
    metrics: Dict[str, Any]
    dimensions: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None  # For authentication

class BulkDataIngestionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    platform: str
    data: List[Dict[str, Any]]  # List of data points

class DataIngestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    success: bool
    records_processed: int
    message: str

# Report View Schemas
class ReportViewBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    report_id: uuid.UUID
    viewed_by: Optional[str] = None

class ReportViewResponse(ReportViewBase):
    id: uuid.UUID
    viewed_at: datetime

# Search and Filter Schemas
class ReportFilter(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    search: Optional[str] = None
    category: Optional[str] = None
    created_by: Optional[str] = None
    data_source: Optional[str] = None
    is_favorite: Optional[bool] = None
    is_active: Optional[bool] = None

# Add this to your schemas.py file

class ExplorationCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: str
    description: Optional[str] = None
    category: str = "Exploration"
    metrics: List[str] = []
    dimensions: List[str] = []
    filters: Dict[str, Any] = {}
    visualization_type: str = "line"  # line, bar, pie, table, etc.
    date_range: Dict[str, Any] = {}
    created_by: str = "user"
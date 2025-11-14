from fastapi import APIRouter, Depends, HTTPException, Query, status, Header
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Optional, List
from datetime import datetime, date, timedelta
import uuid
import json

from database import get_db
from modules.analytics.models import (
    AnalyticsPlatform, PlatformData, AnalyticsReport, 
    ReportView, DataSyncLog
)
from modules.analytics.schemas import (
    # Platform schemas
    ExplorationCreate, PlatformCreate, PlatformResponse, PlatformListResponse,
    # Platform Data schemas
    PlatformDataCreate, PlatformDataResponse, PlatformDataListResponse,
    # Report schemas
    ReportCreate, ReportResponse, ReportListResponse, ReportUpdate,
    # Sync Log schemas
    SyncLogResponse, SyncLogListResponse,
    # Data Ingestion schemas
    DataIngestionRequest, BulkDataIngestionRequest, DataIngestionResponse,
    # Report View schemas
    ReportViewResponse,
    # Filter schemas
    ReportFilter
)

analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# =============================================================================
# PLATFORM MANAGEMENT ENDPOINTS
# =============================================================================

# GET all analytics platforms
@analytics_router.get("/platforms", response_model=PlatformListResponse)
async def get_platforms(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(AnalyticsPlatform)
        
        if is_active is not None:
            query = query.filter(AnalyticsPlatform.is_active == is_active)
        
        total = query.count()
        platforms = query.offset(skip).limit(limit).all()
        
        return PlatformListResponse(
            platforms=platforms,
            total=total
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching platforms: {str(e)}"
        )

# CREATE analytics platform
@analytics_router.post("/platforms", response_model=PlatformResponse, status_code=status.HTTP_201_CREATED)
async def create_platform(platform_data: PlatformCreate, db: Session = Depends(get_db)):
    try:
        # Check if platform already exists
        existing_platform = db.query(AnalyticsPlatform).filter(
            AnalyticsPlatform.name == platform_data.name
        ).first()
        
        if existing_platform:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Platform with this name already exists"
            )
        
        db_platform = AnalyticsPlatform(**platform_data.model_dump())
        db.add(db_platform)
        db.commit()
        db.refresh(db_platform)
        
        return db_platform
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating platform: {str(e)}"
        )

# UPDATE platform activation
@analytics_router.patch("/platforms/{platform_id}/activate")
async def activate_platform(platform_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        platform = db.query(AnalyticsPlatform).filter(AnalyticsPlatform.id == platform_id).first()
        
        if not platform:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Platform not found"
            )
        
        platform.is_active = True
        platform.sync_status = 'active'
        platform.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {"message": "Platform activated successfully"}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error activating platform: {str(e)}"
        )

# =============================================================================
# DATA INGESTION ENDPOINTS (For external platforms)
# =============================================================================

# POST data from external platforms (Google Analytics, Facebook, etc.)
@analytics_router.post("/data/ingest", response_model=DataIngestionResponse)
async def ingest_platform_data(
    data_request: DataIngestionRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    try:
        # Find the platform
        platform = db.query(AnalyticsPlatform).filter(
            AnalyticsPlatform.name == data_request.platform,
            AnalyticsPlatform.is_active == True
        ).first()
        
        if not platform:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Platform '{data_request.platform}' not found or not active"
            )
        
        # Validate API key if required (simplified validation)
        if authorization and platform.api_config:
            # In real implementation, validate the API key/token
            pass
        
        # Create platform data record
        platform_data = PlatformData(
            platform_id=platform.id,
            data_type=data_request.data_type,
            date=data_request.date,
            metrics=data_request.metrics,
            dimensions=data_request.dimensions or {}
        )
        
        db.add(platform_data)
        
        # Update platform sync info
        platform.last_sync = datetime.utcnow()
        platform.sync_status = 'synced'
        
        # Create sync log
        sync_log = DataSyncLog(
            platform_id=platform.id,
            sync_type='incremental',
            status='success',
            records_processed=1,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        db.add(sync_log)
        
        db.commit()
        
        return DataIngestionResponse(
            success=True,
            records_processed=1,
            message=f"Data ingested successfully for {data_request.platform}"
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error ingesting data: {str(e)}"
        )

# POST bulk data ingestion
@analytics_router.post("/data/ingest/bulk", response_model=DataIngestionResponse)
async def bulk_ingest_platform_data(
    bulk_request: BulkDataIngestionRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    try:
        platform = db.query(AnalyticsPlatform).filter(
            AnalyticsPlatform.name == bulk_request.platform,
            AnalyticsPlatform.is_active == True
        ).first()
        
        if not platform:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Platform '{bulk_request.platform}' not found or not active"
            )
        
        records_processed = 0
        for data_point in bulk_request.data:
            platform_data = PlatformData(
                platform_id=platform.id,
                data_type=data_point.get('data_type', 'unknown'),
                date=data_point.get('date', datetime.utcnow().date()),
                metrics=data_point.get('metrics', {}),
                dimensions=data_point.get('dimensions', {})
            )
            db.add(platform_data)
            records_processed += 1
        
        # Update platform sync info
        platform.last_sync = datetime.utcnow()
        platform.sync_status = 'synced'
        
        # Create sync log
        sync_log = DataSyncLog(
            platform_id=platform.id,
            sync_type='bulk',
            status='success',
            records_processed=records_processed,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        db.add(sync_log)
        
        db.commit()
        
        return DataIngestionResponse(
            success=True,
            records_processed=records_processed,
            message=f"Bulk data ingested successfully for {bulk_request.platform}"
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error ingesting bulk data: {str(e)}"
        )

# =============================================================================
# REPORTS MANAGEMENT ENDPOINTS
# =============================================================================

# GET all analytics reports with filtering
@analytics_router.get("/reports", response_model=ReportListResponse)
async def get_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    created_by: Optional[str] = None,
    data_source: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(AnalyticsReport)
        
        # Apply filters
        if search:
            query = query.filter(AnalyticsReport.name.ilike(f"%{search}%"))
        if category and category != 'all':
            query = query.filter(AnalyticsReport.category == category)
        if created_by and created_by != 'all':
            query = query.filter(AnalyticsReport.created_by == created_by)
        if data_source and data_source != 'all':
            query = query.filter(AnalyticsReport.data_source == data_source)
        if is_favorite is not None:
            query = query.filter(AnalyticsReport.is_favorite == is_favorite)
        if is_active is not None:
            query = query.filter(AnalyticsReport.is_active == is_active)
        
        total = query.count()
        reports = query.offset(skip).limit(limit).all()
        
        return ReportListResponse(
            reports=reports,
            total=total,
            page=skip // limit + 1,
            size=len(reports)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching reports: {str(e)}"
        )

# GET single report by ID
@analytics_router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(report_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        report = db.query(AnalyticsReport).filter(AnalyticsReport.id == report_id).first()
        
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
            
        return report
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching report: {str(e)}"
        )

# CREATE analytics report
@analytics_router.post("/reports", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(report_data: ReportCreate, db: Session = Depends(get_db)):
    try:
        # Check if report name already exists
        existing_report = db.query(AnalyticsReport).filter(
            AnalyticsReport.name == report_data.name
        ).first()
        
        if existing_report:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Report with this name already exists"
            )
        
        db_report = AnalyticsReport(**report_data.model_dump())
        db.add(db_report)
        db.commit()
        db.refresh(db_report)
        
        return db_report
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating report: {str(e)}"
        )

# UPDATE report
@analytics_router.put("/reports/{report_id}", response_model=ReportResponse)
async def update_report(
    report_id: uuid.UUID, 
    report_data: ReportUpdate, 
    db: Session = Depends(get_db)
):
    try:
        report = db.query(AnalyticsReport).filter(AnalyticsReport.id == report_id).first()
        
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        # Update fields
        update_data = report_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(report, field, value)
        
        report.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(report)
        
        return report
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating report: {str(e)}"
        )

# DELETE report (soft delete)
@analytics_router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        report = db.query(AnalyticsReport).filter(AnalyticsReport.id == report_id).first()
        
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        # Soft delete by setting is_active to False
        report.is_active = False
        report.updated_at = datetime.utcnow()
        
        db.commit()
        
        return None
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting report: {str(e)}"
        )

# TOGGLE report favorite status
@analytics_router.patch("/reports/{report_id}/favorite")
async def toggle_report_favorite(report_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        report = db.query(AnalyticsReport).filter(AnalyticsReport.id == report_id).first()
        
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        report.is_favorite = not report.is_favorite
        report.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {"is_favorite": report.is_favorite}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling favorite: {str(e)}"
        )

# RECORD report view
@analytics_router.post("/reports/{report_id}/view")
async def record_report_view(
    report_id: uuid.UUID, 
    viewed_by: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        report = db.query(AnalyticsReport).filter(AnalyticsReport.id == report_id).first()
        
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report not found"
            )
        
        # Create view record
        view = ReportView(
            report_id=report_id,
            viewed_by=viewed_by
        )
        db.add(view)
        
        # Update report's last_viewed timestamp
        report.last_viewed = datetime.utcnow()
        report.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {"message": "View recorded successfully"}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error recording view: {str(e)}"
        )

# =============================================================================
# DATA QUERY ENDPOINTS
# =============================================================================

# GET platform data
@analytics_router.get("/data/platform/{platform_id}", response_model=PlatformDataListResponse)
async def get_platform_data(
    platform_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    data_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(PlatformData).filter(PlatformData.platform_id == platform_id)
        
        if start_date:
            query = query.filter(PlatformData.date >= start_date)
        if end_date:
            query = query.filter(PlatformData.date <= end_date)
        if data_type:
            query = query.filter(PlatformData.data_type == data_type)
        
        total = query.count()
        data = query.order_by(PlatformData.date.desc()).offset(skip).limit(limit).all()
        
        return PlatformDataListResponse(
            data=data,
            total=total,
            page=skip // limit + 1,
            size=len(data)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching platform data: {str(e)}"
        )

# GET sync logs
@analytics_router.get("/sync-logs", response_model=SyncLogListResponse)
async def get_sync_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    platform_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(DataSyncLog)
        
        if platform_id:
            query = query.filter(DataSyncLog.platform_id == platform_id)
        if status:
            query = query.filter(DataSyncLog.status == status)
        
        total = query.count()
        logs = query.order_by(DataSyncLog.started_at.desc()).offset(skip).limit(limit).all()
        
        return SyncLogListResponse(
            logs=logs,
            total=total,
            page=skip // limit + 1,
            size=len(logs)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching sync logs: {str(e)}"
        )
    
# Add this to your analytics_router in the REPORTS MANAGEMENT ENDPOINTS section

# CREATE exploration report
@analytics_router.post("/explorations", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_exploration(
    exploration_data: ExplorationCreate,
    db: Session = Depends(get_db)
):
    try:
        # Check if exploration name already exists
        existing_report = db.query(AnalyticsReport).filter(
            AnalyticsReport.name == exploration_data.name
        ).first()
        
        if existing_report:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exploration with this name already exists"
            )
        
        # Prepare configuration for the exploration
        configuration = {
            "metrics": exploration_data.metrics,
            "dimensions": exploration_data.dimensions,
            "filters": exploration_data.filters,
            "visualization_type": exploration_data.visualization_type,
            "date_range": exploration_data.date_range,
            "is_exploration": True
        }
        
        # Create the exploration report
        db_report = AnalyticsReport(
            name=exploration_data.name,
            description=exploration_data.description,
            category=exploration_data.category,
            created_by=exploration_data.created_by,
            report_type="exploration",
            data_source="internal",
            configuration=configuration,
            is_active=True,
            is_favorite=False
        )
        
        db.add(db_report)
        db.commit()
        db.refresh(db_report)
        
        return db_report
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating exploration: {str(e)}"
        )
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


# =============================================================================
# PRODUCT ANALYTICS ENDPOINTS
# =============================================================================

@analytics_router.post("/products/events")
def track_product_event(
    product_id: uuid.UUID,
    event_type: str = Query(..., description="Event type: view, click, add_to_cart, purchase, wishlist"),
    store_id: uuid.UUID = Query(...),
    customer_id: uuid.UUID = Query(None),
    session_id: str = Query(None),
    source: str = Query("storefront"),
    db: Session = Depends(get_db)
):
    """Track a product event (view, click, add_to_cart, purchase)."""
    from .models import ProductEvent

    event = ProductEvent(
        store_id=store_id,
        product_id=product_id,
        event_type=event_type,
        customer_id=customer_id,
        session_id=session_id,
        source=source,
    )
    db.add(event)
    db.commit()

    # Also update daily metrics
    _update_daily_metrics(db, store_id, product_id, event_type)

    return {"success": True, "event_id": str(event.id)}


@analytics_router.post("/products/events/batch")
def track_product_events_batch(
    events: list,
    db: Session = Depends(get_db)
):
    """Track multiple product events at once."""
    from .models import ProductEvent

    created = []
    for ev in events:
        event = ProductEvent(
            store_id=ev.get("store_id"),
            product_id=ev.get("product_id"),
            event_type=ev.get("event_type"),
            customer_id=ev.get("customer_id"),
            session_id=ev.get("session_id"),
            source=ev.get("source", "storefront"),
        )
        db.add(event)
        created.append(event)

    db.commit()

    # Update daily metrics for each unique product
    seen = set()
    for ev in events:
        key = (str(ev.get("store_id")), str(ev.get("product_id")), ev.get("event_type"))
        if key not in seen:
            _update_daily_metrics(db, ev.get("store_id"), ev.get("product_id"), ev.get("event_type"))
            seen.add(key)

    return {"success": True, "tracked": len(created)}


@analytics_router.get("/products/{store_id}/overview")
def get_product_analytics_overview(
    store_id: uuid.UUID,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    Get product analytics overview for a store.
    Returns top products, totals, and trends.
    """
    from .models import ProductMetricsDaily
    from modules.products.models import Product

    start_date = (datetime.utcnow() - timedelta(days=days)).date()

    # Get aggregated metrics per product
    product_metrics = db.query(
        ProductMetricsDaily.product_id,
        func.sum(ProductMetricsDaily.views).label("total_views"),
        func.sum(ProductMetricsDaily.clicks).label("total_clicks"),
        func.sum(ProductMetricsDaily.add_to_cart).label("total_add_to_cart"),
        func.sum(ProductMetricsDaily.purchases).label("total_purchases"),
        func.sum(ProductMetricsDaily.revenue).label("total_revenue"),
        func.sum(ProductMetricsDaily.units_sold).label("total_units_sold"),
    ).filter(
        ProductMetricsDaily.store_id == store_id,
        ProductMetricsDaily.date >= start_date,
    ).group_by(
        ProductMetricsDaily.product_id
    ).all()

    # Get store totals
    total_views = sum(m.total_views or 0 for m in product_metrics)
    total_clicks = sum(m.total_clicks or 0 for m in product_metrics)
    total_add_to_cart = sum(m.total_add_to_cart or 0 for m in product_metrics)
    total_purchases = sum(m.total_purchases or 0 for m in product_metrics)
    total_revenue = sum(float(m.total_revenue or 0) for m in product_metrics)

    # Get product details for top products
    product_ids = [m.product_id for m in product_metrics]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {str(p.id): p for p in products}

    # Build top products list (sorted by revenue)
    top_products = []
    for m in sorted(product_metrics, key=lambda x: float(x.total_revenue or 0), reverse=True)[:20]:
        product = products_map.get(str(m.product_id))
        if product:
            conversion_rate = (float(m.total_purchases or 0) / float(m.total_views or 1)) * 100
            top_products.append({
                "product_id": str(m.product_id),
                "title": product.title,
                "image_url": product.image_url,
                "category": product.category,
                "price": float(product.price) if product.price else 0,
                "views": int(m.total_views or 0),
                "clicks": int(m.total_clicks or 0),
                "add_to_cart": int(m.total_add_to_cart or 0),
                "purchases": int(m.total_purchases or 0),
                "revenue": float(m.total_revenue or 0),
                "units_sold": int(m.total_units_sold or 0),
                "conversion_rate": round(conversion_rate, 2),
            })

    return {
        "store_id": str(store_id),
        "period_days": days,
        "totals": {
            "views": total_views,
            "clicks": total_clicks,
            "add_to_cart": total_add_to_cart,
            "purchases": total_purchases,
            "revenue": round(total_revenue, 2),
            "conversion_rate": round((total_purchases / max(total_views, 1)) * 100, 2),
        },
        "top_products": top_products,
    }


@analytics_router.get("/products/{store_id}/trends")
def get_product_trends(
    store_id: uuid.UUID,
    days: int = Query(30, ge=1, le=365),
    product_id: uuid.UUID = Query(None, description="Filter by specific product"),
    db: Session = Depends(get_db)
):
    """Get daily trends for product metrics (views, purchases, revenue over time)."""
    from .models import ProductMetricsDaily

    start_date = (datetime.utcnow() - timedelta(days=days)).date()

    query = db.query(
        ProductMetricsDaily.date,
        func.sum(ProductMetricsDaily.views).label("views"),
        func.sum(ProductMetricsDaily.clicks).label("clicks"),
        func.sum(ProductMetricsDaily.add_to_cart).label("add_to_cart"),
        func.sum(ProductMetricsDaily.purchases).label("purchases"),
        func.sum(ProductMetricsDaily.revenue).label("revenue"),
        func.sum(ProductMetricsDaily.units_sold).label("units_sold"),
    ).filter(
        ProductMetricsDaily.store_id == store_id,
        ProductMetricsDaily.date >= start_date,
    )

    if product_id:
        query = query.filter(ProductMetricsDaily.product_id == product_id)

    daily_data = query.group_by(ProductMetricsDaily.date).order_by(ProductMetricsDaily.date).all()

    trends = []
    for row in daily_data:
        trends.append({
            "date": row.date.isoformat(),
            "views": int(row.views or 0),
            "clicks": int(row.clicks or 0),
            "add_to_cart": int(row.add_to_cart or 0),
            "purchases": int(row.purchases or 0),
            "revenue": float(row.revenue or 0),
            "units_sold": int(row.units_sold or 0),
        })

    return {
        "store_id": str(store_id),
        "period_days": days,
        "product_id": str(product_id) if product_id else None,
        "trends": trends,
    }


@analytics_router.get("/products/{store_id}/product/{product_id}")
def get_single_product_analytics(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get detailed analytics for a single product."""
    from .models import ProductMetricsDaily, ProductEvent
    from modules.products.models import Product

    product = db.query(Product).filter(Product.id == product_id, Product.store_id == store_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    start_date = (datetime.utcnow() - timedelta(days=days)).date()

    # Daily metrics
    daily_data = db.query(ProductMetricsDaily).filter(
        ProductMetricsDaily.product_id == product_id,
        ProductMetricsDaily.store_id == store_id,
        ProductMetricsDaily.date >= start_date,
    ).order_by(ProductMetricsDaily.date).all()

    # Totals
    total_views = sum(d.views or 0 for d in daily_data)
    total_clicks = sum(d.clicks or 0 for d in daily_data)
    total_add_to_cart = sum(d.add_to_cart or 0 for d in daily_data)
    total_purchases = sum(d.purchases or 0 for d in daily_data)
    total_revenue = sum(float(d.revenue or 0) for d in daily_data)
    total_units = sum(d.units_sold or 0 for d in daily_data)

    # Source breakdown
    source_breakdown = db.query(
        ProductEvent.source,
        func.count(ProductEvent.id).label("count"),
    ).filter(
        ProductEvent.product_id == product_id,
        ProductEvent.store_id == store_id,
        ProductEvent.created_at >= datetime.utcnow() - timedelta(days=days),
    ).group_by(ProductEvent.source).all()

    return {
        "product": {
            "id": str(product.id),
            "title": product.title,
            "image_url": product.image_url,
            "category": product.category,
            "price": float(product.price) if product.price else 0,
            "status": product.status,
        },
        "period_days": days,
        "totals": {
            "views": total_views,
            "clicks": total_clicks,
            "add_to_cart": total_add_to_cart,
            "purchases": total_purchases,
            "revenue": round(total_revenue, 2),
            "units_sold": total_units,
            "conversion_rate": round((total_purchases / max(total_views, 1)) * 100, 2),
            "cart_rate": round((total_add_to_cart / max(total_views, 1)) * 100, 2),
        },
        "daily": [
            {
                "date": d.date.isoformat(),
                "views": d.views or 0,
                "clicks": d.clicks or 0,
                "add_to_cart": d.add_to_cart or 0,
                "purchases": d.purchases or 0,
                "revenue": float(d.revenue or 0),
                "units_sold": d.units_sold or 0,
            }
            for d in daily_data
        ],
        "sources": [
            {"source": s.source or "unknown", "count": s.count}
            for s in source_breakdown
        ],
    }


def _update_daily_metrics(db: Session, store_id, product_id, event_type: str, revenue: float = 0, units: int = 0):
    """Update or create daily metrics for a product."""
    from .models import ProductMetricsDaily

    today = datetime.utcnow().date()

    metrics = db.query(ProductMetricsDaily).filter(
        ProductMetricsDaily.store_id == store_id,
        ProductMetricsDaily.product_id == product_id,
        ProductMetricsDaily.date == today,
    ).first()

    if not metrics:
        metrics = ProductMetricsDaily(
            store_id=store_id,
            product_id=product_id,
            date=today,
        )
        db.add(metrics)

    if event_type == "view":
        metrics.views = (metrics.views or 0) + 1
    elif event_type == "click":
        metrics.clicks = (metrics.clicks or 0) + 1
    elif event_type == "add_to_cart":
        metrics.add_to_cart = (metrics.add_to_cart or 0) + 1
    elif event_type == "purchase":
        metrics.purchases = (metrics.purchases or 0) + 1
        metrics.revenue = (metrics.revenue or 0) + revenue
        metrics.units_sold = (metrics.units_sold or 0) + (units or 1)

    db.commit()
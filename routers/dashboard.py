import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from database import get_db
from models import Order, Product, RequestPost, User
from schemas.dashboard_schema import (
    DashboardOverviewResponseSchema,
    DashboardStatsSchema,
    LowStockItemSchema,
    PerformanceMetricsSchema,
    RecentOrderSchema,
)


logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _generate_order_number(order_id: UUID) -> str:
    return str(order_id).split("-")[0].upper()


@dashboard_router.get("/overview", response_model=DashboardOverviewResponseSchema)
def get_dashboard_overview(db: Session = Depends(get_db)) -> DashboardOverviewResponseSchema:
    total_orders = db.query(func.count(Order.id)).scalar() or 0
    total_revenue_raw = db.query(func.coalesce(func.sum(Order.total_price), 0)).scalar() or 0
    total_revenue = float(total_revenue_raw)

    total_customers = db.query(func.count(User.id)).filter(User.role.in_(["customer", "both"])).scalar() or 0
    inventory_items = db.query(func.count(Product.id)).scalar() or 0
    total_requests = db.query(func.count(RequestPost.id)).scalar() or 0
    open_requests = (
        db.query(func.count(RequestPost.id))
        .filter(RequestPost.status.in_(["open", "counter_offered", "supplier_accepted"]))
        .scalar()
        or 0
    )

    fulfilled_orders = (
        db.query(func.count(Order.id)).filter(Order.status.in_(["delivered", "completed"])).scalar() or 0
    )

    conversion_rate = (
        (total_orders / total_requests) * 100 if total_requests else 0.0
    )
    average_order_value = (total_revenue / total_orders) if total_orders else 0.0
    fulfillment_rate = (
        (fulfilled_orders / total_orders) * 100 if total_orders else 0.0
    )

    Customer = aliased(User)
    recent_orders_raw: List[Order] = (
        db.query(Order, Customer.name.label("customer_name"))
        .join(Customer, Order.customer_id == Customer.id, isouter=True)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )

    recent_orders = [
        RecentOrderSchema(
            order_id=order.id,
            order_number=_generate_order_number(order.id),
            customer_name=customer_name,
            total_amount=float(order.total_price),
            status=order.status,
            created_at=order.created_at,
        )
        for order, customer_name in recent_orders_raw
    ]

    low_stock_candidates = (
        db.query(Product)
        .filter(Product.image_path.is_(None))
        .order_by(Product.updated_at.desc().nullslast(), Product.created_at.desc())
        .limit(5)
        .all()
    )

    low_stock_alerts = [
        LowStockItemSchema(
            product_id=product.id,
            name=product.name,
            price=float(product.price),
            updated_at=product.updated_at or product.created_at,
        )
        for product in low_stock_candidates
    ]

    stats = DashboardStatsSchema(
        total_revenue=round(total_revenue, 2),
        total_orders=total_orders,
        total_customers=total_customers,
        inventory_items=inventory_items,
        open_requests=open_requests,
    )

    performance = PerformanceMetricsSchema(
        conversion_rate=round(conversion_rate, 2),
        average_order_value=round(average_order_value, 2),
        fulfillment_rate=round(fulfillment_rate, 2),
    )

    return DashboardOverviewResponseSchema(
        stats=stats,
        performance=performance,
        recent_orders=recent_orders,
        low_stock_alerts=low_stock_alerts,
    )


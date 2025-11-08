from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DashboardStatsSchema(BaseModel):
    total_revenue: float
    total_orders: int
    total_customers: int
    inventory_items: int
    open_requests: int


class PerformanceMetricsSchema(BaseModel):
    conversion_rate: float
    average_order_value: float
    fulfillment_rate: float


class RecentOrderSchema(BaseModel):
    order_id: UUID
    order_number: str
    customer_name: Optional[str]
    total_amount: float
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LowStockItemSchema(BaseModel):
    product_id: UUID
    name: str
    price: float
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DashboardOverviewResponseSchema(BaseModel):
    stats: DashboardStatsSchema
    performance: PerformanceMetricsSchema
    recent_orders: List[RecentOrderSchema]
    low_stock_alerts: List[LowStockItemSchema]


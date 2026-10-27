from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract
from typing import Optional
from datetime import datetime, timedelta
import uuid

from database import get_db
from modules.procurement.models import (
    Supplier, CatalogProduct, PurchaseOrder, PurchaseOrderItem,
    GoodsReceipt, GoodsReceiptItem, ConsumptionRecord, ProcurementAlert,
    POStatus, PaymentStatus, GoodsReceiptStatus
)
from modules.procurement.schemas import (
    SupplierCreate, SupplierUpdate, SupplierResponse,
    CatalogProductCreate, CatalogProductUpdate, CatalogProductResponse, CatalogProductListResponse,
    PurchaseOrderCreate, PurchaseOrderUpdate, PurchaseOrderResponse, PurchaseOrderListResponse,
    POStatusUpdate, GoodsReceiptCreate, GoodsReceiptResponse,
    ProcurementAnalyticsResponse, ConsumptionTrendResponse, AdminAnalyticsResponse,
    ConsumptionRecordResponse, ProcurementAlertResponse,
)
from modules.products.models import Product

procurement_router = APIRouter(prefix="/api/procurement", tags=["procurement"])


# =====================
# CATALOG ENDPOINTS
# =====================

@procurement_router.get("/catalog", response_model=CatalogProductListResponse)
async def browse_catalog(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    supplier_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
):
    try:
        query = db.query(CatalogProduct).filter(CatalogProduct.is_available == True)

        if supplier_id:
            query = query.filter(CatalogProduct.supplier_id == supplier_id)
        if category:
            query = query.filter(CatalogProduct.category == category)
        if search:
            query = query.filter(CatalogProduct.name.ilike(f"%{search}%"))

        total = query.count()
        products = query.order_by(CatalogProduct.name).offset(skip).limit(limit).all()

        return CatalogProductListResponse(
            products=products,
            total=total,
            page=skip // limit + 1 if limit else 1,
            size=len(products),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching catalog: {str(e)}")


@procurement_router.get("/catalog/{product_id}", response_model=CatalogProductResponse)
async def get_catalog_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    product = db.query(CatalogProduct).filter(CatalogProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Catalog product not found")
    return product


# =====================
# PURCHASE ORDER ENDPOINTS
# =====================

@procurement_router.post("/orders", response_model=PurchaseOrderResponse, status_code=201)
async def create_purchase_order(
    order_data: PurchaseOrderCreate,
    db: Session = Depends(get_db),
):
    try:
        # Calculate totals from items
        subtotal = sum(item.total_price for item in order_data.items)
        total = subtotal + order_data.tax + order_data.shipping_cost

        po = PurchaseOrder(
            store_id=order_data.store_id,
            supplier_id=order_data.supplier_id,
            payment_terms=order_data.payment_terms,
            currency=order_data.currency,
            estimated_arrival=order_data.estimated_arrival,
            shipping_carrier=order_data.shipping_carrier,
            tracking_number=order_data.tracking_number,
            destination=order_data.destination,
            reference_number=order_data.reference_number,
            notes=order_data.notes,
            tags=order_data.tags,
            shipping_cost=order_data.shipping_cost,
            tax=order_data.tax,
            subtotal=subtotal,
            total=total,
        )
        db.add(po)
        db.flush()

        for item_data in order_data.items:
            po_item = PurchaseOrderItem(
                purchase_order_id=po.id,
                catalog_product_id=item_data.catalog_product_id,
                product_name=item_data.product_name,
                sku=item_data.sku,
                quantity_ordered=item_data.quantity_ordered,
                unit_price=item_data.unit_price,
                total_price=item_data.total_price,
                quantity_pending=item_data.quantity_ordered,
            )
            db.add(po_item)

        db.commit()
        db.refresh(po)
        return po
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating purchase order: {str(e)}")


@procurement_router.get("/orders/store/{store_id}", response_model=PurchaseOrderListResponse)
async def list_store_orders(
    store_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        query = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items)
        ).filter(PurchaseOrder.store_id == store_id)

        if status:
            query = query.filter(PurchaseOrder.status == status)
        if date_from:
            query = query.filter(PurchaseOrder.created_at >= date_from)
        if date_to:
            query = query.filter(PurchaseOrder.created_at <= date_to)

        total = query.count()
        orders = query.order_by(PurchaseOrder.created_at.desc()).offset(skip).limit(limit).all()

        return PurchaseOrderListResponse(
            orders=orders,
            total=total,
            page=skip // limit + 1 if limit else 1,
            size=len(orders),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing orders: {str(e)}")


@procurement_router.get("/orders/{order_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    po = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.items)
    ).filter(PurchaseOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


@procurement_router.put("/orders/{order_id}", response_model=PurchaseOrderResponse)
async def update_purchase_order(
    order_id: uuid.UUID,
    order_data: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
):
    try:
        po = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        if po.status != POStatus.DRAFT.value:
            raise HTTPException(status_code=400, detail="Only draft orders can be updated")

        update_data = order_data.model_dump(exclude_unset=True, exclude={"items"})
        for field, value in update_data.items():
            setattr(po, field, value)

        # Update items if provided
        if order_data.items is not None:
            # Remove existing items
            db.query(PurchaseOrderItem).filter(
                PurchaseOrderItem.purchase_order_id == order_id
            ).delete()

            for item_data in order_data.items:
                po_item = PurchaseOrderItem(
                    purchase_order_id=order_id,
                    catalog_product_id=item_data.catalog_product_id,
                    product_name=item_data.product_name,
                    sku=item_data.sku,
                    quantity_ordered=item_data.quantity_ordered,
                    unit_price=item_data.unit_price,
                    total_price=item_data.total_price,
                    quantity_pending=item_data.quantity_ordered,
                )
                db.add(po_item)

        # Recalculate totals
        items = db.query(PurchaseOrderItem).filter(
            PurchaseOrderItem.purchase_order_id == order_id
        ).all()
        po.subtotal = sum(item.total_price for item in items)
        po.total = po.subtotal + po.tax + po.shipping_cost

        db.commit()
        db.refresh(po)
        return po
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating order: {str(e)}")


@procurement_router.post("/orders/{order_id}/submit", response_model=PurchaseOrderResponse)
async def submit_purchase_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items)
        ).filter(PurchaseOrder.id == order_id).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        if po.status != POStatus.DRAFT.value:
            raise HTTPException(status_code=400, detail="Only draft orders can be submitted")
        if not po.items:
            raise HTTPException(status_code=400, detail="Cannot submit an order with no items")

        po.status = POStatus.SUBMITTED.value
        po.submitted_at = datetime.utcnow()
        db.commit()
        db.refresh(po)
        return po
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error submitting order: {str(e)}")


@procurement_router.post("/orders/{order_id}/cancel", response_model=PurchaseOrderResponse)
async def cancel_purchase_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items)
        ).filter(PurchaseOrder.id == order_id).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        if po.status in [POStatus.DELIVERED.value, POStatus.CANCELLED.value]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel a {po.status} order")

        po.status = POStatus.CANCELLED.value
        db.commit()
        db.refresh(po)
        return po
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error cancelling order: {str(e)}")


@procurement_router.post("/orders/{order_id}/receive", response_model=GoodsReceiptResponse)
async def receive_goods(
    order_id: uuid.UUID,
    receipt_data: GoodsReceiptCreate,
    db: Session = Depends(get_db),
):
    """Record goods receipt and update store inventory."""
    try:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items)
        ).filter(PurchaseOrder.id == order_id).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        if po.status in [POStatus.DRAFT.value, POStatus.CANCELLED.value]:
            raise HTTPException(status_code=400, detail=f"Cannot receive goods for a {po.status} order")

        # Create goods receipt
        gr = GoodsReceipt(
            purchase_order_id=order_id,
            store_id=po.store_id,
            received_by=receipt_data.received_by,
            notes=receipt_data.notes,
        )
        db.add(gr)
        db.flush()

        all_fully_received = True

        for item_data in receipt_data.items:
            # Validate PO item exists
            po_item = db.query(PurchaseOrderItem).filter(
                PurchaseOrderItem.id == item_data.purchase_order_item_id,
                PurchaseOrderItem.purchase_order_id == order_id,
            ).first()
            if not po_item:
                raise HTTPException(
                    status_code=400,
                    detail=f"PO item {item_data.purchase_order_item_id} not found in this order"
                )

            # Create receipt item
            gr_item = GoodsReceiptItem(
                goods_receipt_id=gr.id,
                purchase_order_item_id=item_data.purchase_order_item_id,
                quantity_received=item_data.quantity_received,
                quantity_rejected=item_data.quantity_rejected,
                notes=item_data.notes,
            )
            db.add(gr_item)

            # Update PO item quantities
            po_item.quantity_received += item_data.quantity_received
            po_item.quantity_pending = po_item.quantity_ordered - po_item.quantity_received

            if po_item.quantity_pending > 0:
                all_fully_received = False

            # Update store product inventory by matching SKU
            store_product = db.query(Product).filter(
                Product.store_id == po.store_id,
                Product.sku == po_item.sku,
            ).first()

            if store_product:
                store_product.available += item_data.quantity_received
                store_product.on_hand += item_data.quantity_received
                store_product.quantity += item_data.quantity_received

        # Set receipt status
        gr.status = GoodsReceiptStatus.COMPLETE.value if all_fully_received else GoodsReceiptStatus.PARTIAL.value

        # Update PO status if all items fully received
        if all_fully_received:
            po.status = POStatus.DELIVERED.value
            po.delivered_at = datetime.utcnow()
        elif po.status == POStatus.SUBMITTED.value or po.status == POStatus.CONFIRMED.value:
            po.status = POStatus.PROCESSING.value

        db.commit()
        db.refresh(gr)
        return gr
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error receiving goods: {str(e)}")


# =====================
# ANALYTICS ENDPOINTS
# =====================

@procurement_router.get("/analytics/store/{store_id}", response_model=ProcurementAnalyticsResponse)
async def get_store_analytics(store_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        # Total orders
        total_orders = db.query(func.count(PurchaseOrder.id)).filter(
            PurchaseOrder.store_id == store_id
        ).scalar() or 0

        # Total spending
        total_spending = db.query(func.sum(PurchaseOrder.total)).filter(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status != POStatus.CANCELLED.value,
        ).scalar() or 0.0

        # Pending orders
        pending_orders = db.query(func.count(PurchaseOrder.id)).filter(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status.in_([
                POStatus.SUBMITTED.value, POStatus.CONFIRMED.value,
                POStatus.PROCESSING.value, POStatus.SHIPPED.value,
            ]),
        ).scalar() or 0

        # Delivered orders
        delivered_orders = db.query(func.count(PurchaseOrder.id)).filter(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status == POStatus.DELIVERED.value,
        ).scalar() or 0

        avg_order_value = total_spending / total_orders if total_orders > 0 else 0.0

        # Monthly spending (last 12 months)
        twelve_months_ago = datetime.utcnow() - timedelta(days=365)
        monthly_results = db.query(
            extract('year', PurchaseOrder.created_at).label('year'),
            extract('month', PurchaseOrder.created_at).label('month'),
            func.sum(PurchaseOrder.total).label('total'),
        ).filter(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status != POStatus.CANCELLED.value,
            PurchaseOrder.created_at >= twelve_months_ago,
        ).group_by('year', 'month').order_by('year', 'month').all()

        spending_by_month = [
            {"year": int(r.year), "month": int(r.month), "total": float(r.total or 0)}
            for r in monthly_results
        ]

        # Spending by category
        category_results = db.query(
            CatalogProduct.category,
            func.sum(PurchaseOrderItem.total_price).label('total'),
        ).join(
            PurchaseOrderItem, PurchaseOrderItem.catalog_product_id == CatalogProduct.id
        ).join(
            PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id
        ).filter(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status != POStatus.CANCELLED.value,
        ).group_by(CatalogProduct.category).all()

        spending_by_category = [
            {"category": r.category or "Uncategorized", "total": float(r.total or 0)}
            for r in category_results
        ]

        # Top products by order volume
        top_results = db.query(
            PurchaseOrderItem.product_name,
            PurchaseOrderItem.sku,
            func.sum(PurchaseOrderItem.quantity_ordered).label('total_qty'),
            func.sum(PurchaseOrderItem.total_price).label('total_spend'),
        ).join(
            PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id
        ).filter(
            PurchaseOrder.store_id == store_id,
            PurchaseOrder.status != POStatus.CANCELLED.value,
        ).group_by(
            PurchaseOrderItem.product_name, PurchaseOrderItem.sku
        ).order_by(func.sum(PurchaseOrderItem.total_price).desc()).limit(10).all()

        top_products = [
            {
                "name": r.product_name,
                "sku": r.sku,
                "total_quantity": int(r.total_qty or 0),
                "total_spend": float(r.total_spend or 0),
            }
            for r in top_results
        ]

        return ProcurementAnalyticsResponse(
            total_orders=total_orders,
            total_spending=float(total_spending),
            pending_orders=pending_orders,
            delivered_orders=delivered_orders,
            avg_order_value=float(avg_order_value),
            spending_by_month=spending_by_month,
            spending_by_category=spending_by_category,
            top_products=top_products,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching analytics: {str(e)}")


@procurement_router.get("/analytics/store/{store_id}/consumption", response_model=list[ConsumptionTrendResponse])
async def get_consumption_trends(store_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        # Get products with consumption data
        products = db.query(Product).filter(
            Product.store_id == store_id,
            Product.inventory_tracked == True,
        ).all()

        trends = []
        for product in products:
            records = db.query(ConsumptionRecord).filter(
                ConsumptionRecord.store_id == store_id,
                ConsumptionRecord.product_id == product.id,
            ).order_by(ConsumptionRecord.period_end.desc()).limit(30).all()

            if records:
                total_consumed = sum(r.quantity_consumed for r in records)
                total_days = sum(
                    (r.period_end - r.period_start).days or 1 for r in records
                )
                avg_daily = total_consumed / total_days if total_days > 0 else 0
                days_remaining = product.available / avg_daily if avg_daily > 0 else None
            else:
                avg_daily = 0
                days_remaining = None

            consumption_history = [
                {
                    "period_start": r.period_start.isoformat(),
                    "period_end": r.period_end.isoformat(),
                    "quantity": r.quantity_consumed,
                }
                for r in records
            ]

            trends.append(ConsumptionTrendResponse(
                product_id=product.id,
                product_name=product.title,
                avg_daily_consumption=avg_daily,
                current_stock=product.available,
                estimated_days_remaining=days_remaining,
                consumption_history=consumption_history,
            ))

        return trends
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching consumption: {str(e)}")


# =====================
# ADMIN ENDPOINTS
# =====================

@procurement_router.post("/admin/catalog", response_model=CatalogProductResponse, status_code=201)
async def admin_add_catalog_product(
    product_data: CatalogProductCreate,
    db: Session = Depends(get_db),
):
    try:
        product = CatalogProduct(**product_data.model_dump())
        db.add(product)
        db.commit()
        db.refresh(product)
        return product
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error adding catalog product: {str(e)}")


@procurement_router.put("/admin/catalog/{product_id}", response_model=CatalogProductResponse)
async def admin_update_catalog_product(
    product_id: uuid.UUID,
    product_data: CatalogProductUpdate,
    db: Session = Depends(get_db),
):
    try:
        product = db.query(CatalogProduct).filter(CatalogProduct.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Catalog product not found")

        update_data = product_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(product, field, value)

        db.commit()
        db.refresh(product)
        return product
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating catalog product: {str(e)}")


@procurement_router.delete("/admin/catalog/{product_id}", status_code=204)
async def admin_delete_catalog_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        product = db.query(CatalogProduct).filter(CatalogProduct.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Catalog product not found")
        db.delete(product)
        db.commit()
        return None
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting catalog product: {str(e)}")


@procurement_router.get("/admin/orders", response_model=PurchaseOrderListResponse)
async def admin_list_all_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    store_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
):
    try:
        query = db.query(PurchaseOrder).options(joinedload(PurchaseOrder.items))

        if status:
            query = query.filter(PurchaseOrder.status == status)
        if store_id:
            query = query.filter(PurchaseOrder.store_id == store_id)

        total = query.count()
        orders = query.order_by(PurchaseOrder.created_at.desc()).offset(skip).limit(limit).all()

        return PurchaseOrderListResponse(
            orders=orders,
            total=total,
            page=skip // limit + 1 if limit else 1,
            size=len(orders),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing orders: {str(e)}")


@procurement_router.patch("/admin/orders/{order_id}/status", response_model=PurchaseOrderResponse)
async def admin_update_order_status(
    order_id: uuid.UUID,
    status_data: POStatusUpdate,
    db: Session = Depends(get_db),
):
    try:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.items)
        ).filter(PurchaseOrder.id == order_id).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")

        valid_transitions = {
            POStatus.SUBMITTED.value: [POStatus.CONFIRMED.value, POStatus.CANCELLED.value],
            POStatus.CONFIRMED.value: [POStatus.PROCESSING.value, POStatus.CANCELLED.value],
            POStatus.PROCESSING.value: [POStatus.SHIPPED.value, POStatus.CANCELLED.value],
            POStatus.SHIPPED.value: [POStatus.DELIVERED.value],
        }

        allowed = valid_transitions.get(po.status, [])
        if status_data.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{po.status}' to '{status_data.status}'"
            )

        po.status = status_data.status

        now = datetime.utcnow()
        if status_data.status == POStatus.CONFIRMED.value:
            po.confirmed_at = now
        elif status_data.status == POStatus.SHIPPED.value:
            po.shipped_at = now
            if status_data.tracking_number:
                po.tracking_number = status_data.tracking_number
            if status_data.shipping_carrier:
                po.shipping_carrier = status_data.shipping_carrier
        elif status_data.status == POStatus.DELIVERED.value:
            po.delivered_at = now

        if status_data.notes:
            po.notes = status_data.notes

        db.commit()
        db.refresh(po)
        return po
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating status: {str(e)}")


@procurement_router.get("/admin/analytics", response_model=AdminAnalyticsResponse)
async def admin_analytics(db: Session = Depends(get_db)):
    try:
        total_orders = db.query(func.count(PurchaseOrder.id)).scalar() or 0
        total_revenue = db.query(func.sum(PurchaseOrder.total)).filter(
            PurchaseOrder.status != POStatus.CANCELLED.value
        ).scalar() or 0.0
        active_stores = db.query(func.count(func.distinct(PurchaseOrder.store_id))).scalar() or 0

        # Orders by status
        status_counts = db.query(
            PurchaseOrder.status,
            func.count(PurchaseOrder.id),
        ).group_by(PurchaseOrder.status).all()
        orders_by_status = {s: c for s, c in status_counts}

        # Monthly trends (last 12 months)
        twelve_months_ago = datetime.utcnow() - timedelta(days=365)
        monthly = db.query(
            extract('year', PurchaseOrder.created_at).label('year'),
            extract('month', PurchaseOrder.created_at).label('month'),
            func.count(PurchaseOrder.id).label('count'),
            func.sum(PurchaseOrder.total).label('total'),
        ).filter(
            PurchaseOrder.created_at >= twelve_months_ago,
        ).group_by('year', 'month').order_by('year', 'month').all()

        monthly_trends = [
            {"year": int(r.year), "month": int(r.month), "count": r.count, "total": float(r.total or 0)}
            for r in monthly
        ]

        return AdminAnalyticsResponse(
            total_orders_all=total_orders,
            total_revenue=float(total_revenue),
            active_stores=active_stores,
            orders_by_status=orders_by_status,
            monthly_trends=monthly_trends,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching admin analytics: {str(e)}")


# =====================
# SEED ENDPOINT
# =====================

@procurement_router.post("/seed-supplier", response_model=SupplierResponse)
async def seed_default_supplier(db: Session = Depends(get_db)):
    """Create or return the default Shopivell supplier."""
    try:
        existing = db.query(Supplier).filter(Supplier.name == "Shopivell").first()
        if existing:
            return existing

        supplier = Supplier(
            name="Shopivell",
            contact_email="procurement@shopivell.com",
            contact_phone="+1-800-SHOPIVELL",
            address="Shopivell HQ",
            is_active=True,
        )
        db.add(supplier)
        db.commit()
        db.refresh(supplier)
        return supplier
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error seeding supplier: {str(e)}")


# =====================
# SUPPLIER ENDPOINTS
# =====================

@procurement_router.get("/suppliers", response_model=list[SupplierResponse])
async def list_suppliers(db: Session = Depends(get_db)):
    suppliers = db.query(Supplier).filter(Supplier.is_active == True).all()
    return suppliers


@procurement_router.post("/suppliers", response_model=SupplierResponse, status_code=201)
async def create_supplier(data: SupplierCreate, db: Session = Depends(get_db)):
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@procurement_router.put("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(supplier_id: uuid.UUID, data: SupplierUpdate, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(supplier, k, v)
    db.commit()
    db.refresh(supplier)
    return supplier


@procurement_router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    db.delete(supplier)
    db.commit()
    return {"detail": "Supplier deleted"}

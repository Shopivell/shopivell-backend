import uuid
import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_

from database import get_db
from modules.delivery.models import Delivery, DeliveryTracking, DeliveryZone, DeliveryStatus, Vehicle, Driver, VehicleStatus, DriverStatus
from modules.delivery.schemas import (
    DeliveryCreate, DeliveryUpdate, DeliveryResponse, DeliveryListResponse,
    DeliveryStatusUpdate, DeliveryAssign,
    DeliveryZoneCreate, DeliveryZoneUpdate, DeliveryZoneResponse,
    DeliveryTrackingResponse,
    CostEstimateRequest, CostEstimateResponse,
    DeliveryAnalytics,
    VehicleCreate, VehicleUpdate, VehicleResponse,
    DriverCreate, DriverUpdate, DriverResponse,
)
from modules.orders.models import CustomerOrder
from modules.users.access import require_store_capability
from utils.jwt_auth import get_current_user


async def _authorize_delivery_request(request: Request, db: Session = Depends(get_db),
                                      current_user=Depends(get_current_user)):
    """Resolve the affected store from the route or resource, never from a JWT claim."""
    params = request.path_params
    store_id = params.get('store_id')
    resources = {'delivery_id': Delivery, 'zone_id': DeliveryZone,
                 'vehicle_id': Vehicle, 'driver_id': Driver}
    for key, model in resources.items():
        if key in params:
            try:
                obj = db.query(model).filter(model.id == uuid.UUID(str(params[key]))).first()
            except ValueError:
                raise HTTPException(status_code=404, detail='Delivery resource not found')
            if not obj:
                raise HTTPException(status_code=404, detail='Delivery resource not found')
            store_id = obj.store_id
            break
    if 'tracking_number' in params:
        obj = db.query(Delivery).filter(Delivery.tracking_number == params['tracking_number']).first()
        if not obj:
            raise HTTPException(status_code=404, detail='Delivery not found')
        store_id = obj.store_id
    payload = {}
    if request.method in ('POST', 'PUT', 'PATCH'):
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if not store_id:
            store_id = payload.get('store_id')
    if not store_id:
        raise HTTPException(status_code=403, detail='Store could not be determined')
    store = require_store_capability(db, current_user, store_id, 'deliveries')
    # Linked objects must belong to the same store as the delivery.
    for field, model in [('order_id', CustomerOrder), ('delivery_zone_id', DeliveryZone),
                         ('zone_id', DeliveryZone), ('vehicle_id', Vehicle), ('driver_id', Driver)]:
        if payload.get(field):
            try:
                related = db.query(model).filter(model.id == uuid.UUID(str(payload[field]))).first()
            except ValueError:
                related = None
            if not related or related.store_id != store.id:
                raise HTTPException(status_code=403, detail='Linked resource belongs to another store')


delivery_router = APIRouter(prefix="/api/delivery", tags=["Delivery"],
                            dependencies=[Depends(_authorize_delivery_request)])


# ──────────────────────────────── Delivery Zones ────────────────────────────────

@delivery_router.post("/zones", response_model=DeliveryZoneResponse)
def create_zone(zone: DeliveryZoneCreate, db: Session = Depends(get_db)):
    db_zone = DeliveryZone(**zone.model_dump())
    db.add(db_zone)
    db.commit()
    db.refresh(db_zone)
    return db_zone


@delivery_router.get("/zones/store/{store_id}", response_model=list[DeliveryZoneResponse])
def list_zones(store_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(DeliveryZone).filter(
        DeliveryZone.store_id == store_id
    ).order_by(DeliveryZone.min_distance_km).all()


@delivery_router.put("/zones/{zone_id}", response_model=DeliveryZoneResponse)
def update_zone(zone_id: uuid.UUID, payload: DeliveryZoneUpdate, db: Session = Depends(get_db)):
    zone = db.query(DeliveryZone).filter(DeliveryZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Delivery zone not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(zone, k, v)
    db.commit()
    db.refresh(zone)
    return zone


@delivery_router.delete("/zones/{zone_id}")
def delete_zone(zone_id: uuid.UUID, db: Session = Depends(get_db)):
    zone = db.query(DeliveryZone).filter(DeliveryZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Delivery zone not found")
    db.delete(zone)
    db.commit()
    return {"detail": "Zone deleted"}


# ──────────────────────────────── Cost Calculation ────────────────────────────────

def _calculate_cost(distance_km: float, zone: DeliveryZone) -> dict:
    """Calculate delivery cost based on distance and zone pricing."""
    cost = zone.base_fee + (distance_km * zone.per_km_rate)
    duration = distance_km * zone.estimated_time_per_km_min
    return {
        "distance_km": round(distance_km, 2),
        "base_fee": zone.base_fee,
        "per_km_rate": zone.per_km_rate,
        "delivery_cost": round(cost, 2),
        "estimated_duration_min": round(duration, 1),
        "currency": zone.currency,
        "zone_name": zone.name,
    }


@delivery_router.post("/estimate-cost", response_model=CostEstimateResponse)
def estimate_cost(req: CostEstimateRequest, db: Session = Depends(get_db)):
    """Estimate delivery cost for a given distance. Finds the matching zone automatically."""
    if req.zone_id:
        zone = db.query(DeliveryZone).filter(DeliveryZone.id == req.zone_id).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")
    else:
        zone = db.query(DeliveryZone).filter(
            DeliveryZone.store_id == req.store_id,
            DeliveryZone.is_active == True,
            DeliveryZone.min_distance_km <= req.distance_km,
            (DeliveryZone.max_distance_km >= req.distance_km) | (DeliveryZone.max_distance_km.is_(None)),
        ).first()
        if not zone:
            # Fallback: use the zone with the highest max_distance
            zone = db.query(DeliveryZone).filter(
                DeliveryZone.store_id == req.store_id,
                DeliveryZone.is_active == True,
            ).order_by(DeliveryZone.max_distance_km.desc().nullslast()).first()
        if not zone:
            raise HTTPException(status_code=404, detail="No delivery zones configured for this store")

    return _calculate_cost(req.distance_km, zone)


# ──────────────────────────────── Deliveries CRUD ────────────────────────────────

@delivery_router.post("", response_model=DeliveryResponse)
def create_delivery(payload: DeliveryCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()

    # Auto-calculate cost if distance and zone are provided
    if payload.distance_km and payload.distance_km > 0:
        zone = None
        if payload.delivery_zone_id:
            zone = db.query(DeliveryZone).filter(DeliveryZone.id == payload.delivery_zone_id).first()
        else:
            zone = db.query(DeliveryZone).filter(
                DeliveryZone.store_id == payload.store_id,
                DeliveryZone.is_active == True,
                DeliveryZone.min_distance_km <= payload.distance_km,
                (DeliveryZone.max_distance_km >= payload.distance_km) | (DeliveryZone.max_distance_km.is_(None)),
            ).first()
            if not zone:
                zone = db.query(DeliveryZone).filter(
                    DeliveryZone.store_id == payload.store_id,
                    DeliveryZone.is_active == True,
                ).order_by(DeliveryZone.max_distance_km.desc().nullslast()).first()

        if zone:
            cost_info = _calculate_cost(payload.distance_km, zone)
            data["base_fee"] = cost_info["base_fee"]
            data["per_km_rate"] = cost_info["per_km_rate"]
            data["delivery_cost"] = cost_info["delivery_cost"]
            data["estimated_duration_min"] = cost_info["estimated_duration_min"]
            data["currency"] = cost_info["currency"]
            if not data.get("delivery_zone_id"):
                data["delivery_zone_id"] = zone.id

    delivery = Delivery(**data)
    db.add(delivery)
    db.flush()

    # Create initial tracking event
    tracking = DeliveryTracking(
        delivery_id=delivery.id,
        status=DeliveryStatus.PENDING,
        notes="Delivery created",
    )
    db.add(tracking)
    db.commit()
    db.refresh(delivery)

    # Update the linked order's delivery_status
    if delivery.order_id:
        order = db.query(CustomerOrder).filter(CustomerOrder.id == delivery.order_id).first()
        if order:
            order.delivery_status = DeliveryStatus.PENDING.value
            db.commit()

    return delivery


@delivery_router.get("/store/{store_id}", response_model=DeliveryListResponse)
def list_deliveries(
    store_id: uuid.UUID,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(Delivery.store_id == store_id)

    if status:
        q = q.filter(Delivery.status == status)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            (Delivery.customer_name.ilike(pattern)) |
            (Delivery.tracking_number.ilike(pattern)) |
            (Delivery.delivery_address.ilike(pattern))
        )

    total = q.count()
    deliveries = q.order_by(Delivery.created_at.desc()).offset(skip).limit(limit).all()

    return DeliveryListResponse(
        deliveries=deliveries,
        total=total,
        skip=skip,
        limit=limit,
    )


@delivery_router.get("/store/{store_id}/order/{order_id}", response_model=Optional[DeliveryResponse])
def get_order_delivery(store_id: uuid.UUID, order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return the delivery linked to an order in the selected store, if any."""
    return db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(
        Delivery.store_id == store_id,
        Delivery.order_id == order_id,
    ).order_by(Delivery.created_at.desc()).first()


@delivery_router.get("/{delivery_id}", response_model=DeliveryResponse)
def get_delivery(delivery_id: uuid.UUID, db: Session = Depends(get_db)):
    delivery = db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return delivery


@delivery_router.get("/track/{tracking_number}", response_model=DeliveryResponse)
def track_delivery(tracking_number: str, db: Session = Depends(get_db)):
    """Public tracking endpoint by tracking number."""
    delivery = db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(Delivery.tracking_number == tracking_number).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return delivery


@delivery_router.put("/{delivery_id}", response_model=DeliveryResponse)
def update_delivery(delivery_id: uuid.UUID, payload: DeliveryUpdate, db: Session = Depends(get_db)):
    delivery = db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Recalculate cost if distance changed
    new_distance = update_data.get("distance_km")
    new_zone_id = update_data.get("delivery_zone_id")

    if new_distance is not None or new_zone_id is not None:
        dist = new_distance if new_distance is not None else delivery.distance_km
        z_id = new_zone_id if new_zone_id is not None else delivery.delivery_zone_id

        if dist and dist > 0:
            zone = None
            if z_id:
                zone = db.query(DeliveryZone).filter(DeliveryZone.id == z_id).first()
            else:
                zone = db.query(DeliveryZone).filter(
                    DeliveryZone.store_id == delivery.store_id,
                    DeliveryZone.is_active == True,
                    DeliveryZone.min_distance_km <= dist,
                    (DeliveryZone.max_distance_km >= dist) | (DeliveryZone.max_distance_km.is_(None)),
                ).first()

            if zone:
                cost_info = _calculate_cost(dist, zone)
                update_data["base_fee"] = cost_info["base_fee"]
                update_data["per_km_rate"] = cost_info["per_km_rate"]
                update_data["delivery_cost"] = cost_info["delivery_cost"]
                update_data["estimated_duration_min"] = cost_info["estimated_duration_min"]

    for k, v in update_data.items():
        setattr(delivery, k, v)

    db.commit()
    db.refresh(delivery)
    return delivery


@delivery_router.delete("/{delivery_id}")
def delete_delivery(delivery_id: uuid.UUID, db: Session = Depends(get_db)):
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")
    db.delete(delivery)
    db.commit()
    return {"detail": "Delivery deleted"}


# ──────────────────────────────── Status Updates & Tracking ────────────────────────────────

@delivery_router.patch("/{delivery_id}/status", response_model=DeliveryResponse)
def update_delivery_status(
    delivery_id: uuid.UUID,
    payload: DeliveryStatusUpdate,
    db: Session = Depends(get_db),
):
    delivery = db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    now = datetime.utcnow()
    delivery.status = payload.status

    if payload.status == DeliveryStatus.PICKED_UP.value:
        delivery.picked_up_at = now
    elif payload.status == DeliveryStatus.DELIVERED.value:
        delivery.delivered_at = now
    elif payload.status == DeliveryStatus.FAILED.value:
        delivery.failed_at = now
        if payload.failure_reason:
            delivery.failure_reason = payload.failure_reason

    # Create tracking event
    tracking = DeliveryTracking(
        delivery_id=delivery.id,
        status=payload.status,
        location=payload.location,
        latitude=payload.latitude,
        longitude=payload.longitude,
        notes=payload.notes,
    )
    db.add(tracking)

    # Sync status to the linked order
    if delivery.order_id:
        order = db.query(CustomerOrder).filter(CustomerOrder.id == delivery.order_id).first()
        if order:
            order.delivery_status = payload.status

    db.commit()
    db.refresh(delivery)
    return delivery


@delivery_router.get("/{delivery_id}/tracking", response_model=list[DeliveryTrackingResponse])
def get_tracking_history(delivery_id: uuid.UUID, db: Session = Depends(get_db)):
    events = db.query(DeliveryTracking).filter(
        DeliveryTracking.delivery_id == delivery_id
    ).order_by(DeliveryTracking.created_at.asc()).all()
    return events


# ──────────────────────────────── Analytics ────────────────────────────────

@delivery_router.get("/analytics/store/{store_id}", response_model=DeliveryAnalytics)
def get_delivery_analytics(store_id: uuid.UUID, db: Session = Depends(get_db)):
    base = db.query(Delivery).filter(Delivery.store_id == store_id)

    total = base.count()
    delivered = base.filter(Delivery.status == DeliveryStatus.DELIVERED).count()
    in_transit = base.filter(Delivery.status.in_([
        DeliveryStatus.IN_TRANSIT, DeliveryStatus.OUT_FOR_DELIVERY, DeliveryStatus.PICKED_UP,
    ])).count()
    pending = base.filter(Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.ASSIGNED])).count()
    failed = base.filter(Delivery.status == DeliveryStatus.FAILED).count()

    cost_agg = db.query(
        func.coalesce(func.sum(Delivery.delivery_cost), 0),
        func.coalesce(func.avg(Delivery.delivery_cost), 0),
        func.coalesce(func.avg(Delivery.distance_km), 0),
    ).filter(Delivery.store_id == store_id).first()

    total_cost = float(cost_agg[0])
    avg_cost = float(cost_agg[1])
    avg_dist = float(cost_agg[2])

    # Average delivery time for completed deliveries
    completed = base.filter(
        Delivery.delivered_at.isnot(None),
        Delivery.created_at.isnot(None),
    ).all()
    avg_time = 0.0
    if completed:
        times = [(d.delivered_at - d.created_at).total_seconds() / 60 for d in completed]
        avg_time = sum(times) / len(times)

    success_rate = (delivered / total * 100) if total > 0 else 0.0

    return DeliveryAnalytics(
        total_deliveries=total,
        delivered_count=delivered,
        in_transit_count=in_transit,
        pending_count=pending,
        failed_count=failed,
        total_delivery_cost=round(total_cost, 2),
        avg_delivery_cost=round(avg_cost, 2),
        avg_distance_km=round(avg_dist, 2),
        avg_delivery_time_min=round(avg_time, 1),
        delivery_success_rate=round(success_rate, 1),
    )


# ──────────────────────────────── Vehicles CRUD ────────────────────────────────

@delivery_router.post("/vehicles", response_model=VehicleResponse, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db)):
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@delivery_router.get("/vehicles/store/{store_id}", response_model=list[VehicleResponse])
def list_vehicles(store_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(Vehicle).filter(Vehicle.store_id == store_id).order_by(Vehicle.created_at.desc()).all()


@delivery_router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(vehicle_id: uuid.UUID, db: Session = Depends(get_db)):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@delivery_router.put("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(vehicle_id: uuid.UUID, payload: VehicleUpdate, db: Session = Depends(get_db)):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, k, v)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@delivery_router.delete("/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: uuid.UUID, db: Session = Depends(get_db)):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    db.delete(vehicle)
    db.commit()
    return {"detail": "Vehicle deleted"}


# ──────────────────────────────── Drivers CRUD ────────────────────────────────

@delivery_router.post("/drivers", response_model=DriverResponse, status_code=201)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db)):
    driver = Driver(**payload.model_dump())
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@delivery_router.get("/drivers/store/{store_id}", response_model=list[DriverResponse])
def list_drivers(store_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(Driver).filter(Driver.store_id == store_id).order_by(Driver.created_at.desc()).all()


@delivery_router.get("/drivers/{driver_id}", response_model=DriverResponse)
def get_driver(driver_id: uuid.UUID, db: Session = Depends(get_db)):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@delivery_router.put("/drivers/{driver_id}", response_model=DriverResponse)
def update_driver(driver_id: uuid.UUID, payload: DriverUpdate, db: Session = Depends(get_db)):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(driver, k, v)
    db.commit()
    db.refresh(driver)
    return driver


@delivery_router.delete("/drivers/{driver_id}")
def delete_driver(driver_id: uuid.UUID, db: Session = Depends(get_db)):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    db.delete(driver)
    db.commit()
    return {"detail": "Driver deleted"}


# ──────────────────────────────── Assign Driver/Vehicle ────────────────────────────────

@delivery_router.patch("/{delivery_id}/assign", response_model=DeliveryResponse)
def assign_driver_vehicle(
    delivery_id: uuid.UUID,
    payload: DeliveryAssign,
    db: Session = Depends(get_db),
):
    """Assign a driver and optionally a vehicle to a delivery."""
    delivery = db.query(Delivery).options(
        joinedload(Delivery.tracking_events)
    ).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery not found")

    driver = db.query(Driver).filter(Driver.id == payload.driver_id, Driver.store_id == delivery.store_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    delivery.driver_id = driver.id
    delivery.delivery_person = driver.name
    delivery.delivery_person_phone = driver.phone

    # Use the vehicle from payload, or fallback to driver's assigned vehicle
    vid = payload.vehicle_id or driver.vehicle_id
    if vid:
        vehicle = db.query(Vehicle).filter(Vehicle.id == vid, Vehicle.store_id == delivery.store_id).first()
        if vehicle:
            delivery.vehicle_id = vehicle.id
            vehicle.status = VehicleStatus.IN_USE

    driver.status = DriverStatus.ON_DELIVERY
    delivery.status = DeliveryStatus.ASSIGNED

    # Create tracking event
    tracking = DeliveryTracking(
        delivery_id=delivery.id,
        status=DeliveryStatus.ASSIGNED,
        notes=f"Assigned to driver {driver.name}",
    )
    db.add(tracking)

    db.commit()
    db.refresh(delivery)
    return delivery

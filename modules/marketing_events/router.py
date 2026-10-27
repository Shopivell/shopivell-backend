"""
Marketing Events API

Three sources of "events that affect ad performance", merged into one
upcoming-events feed used by the campaign-generation agents:
  1. Custom events - the tenant's own (sale, launch, etc.)
  2. Retail calendar - a built-in set of well-known shopping events
     (Black Friday, Back to School, Christmas, ...), overridable per store
  3. Public holidays - fetched live from the free Nager.Date API, keyed by
     the store's country_code

Nothing here forces campaign generation to reference an event - agents that
want event context call get_relevant_upcoming_events() and decide for
themselves whether anything is close/relevant enough to mention.
"""
import calendar
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from utils.jwt_auth import get_current_user
from modules.users.models import User
from modules.stores.models import Store
from .models import StoreMarketingEvent, StoreRetailEventOverride

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["Marketing Events"])


# =============================================================================
# Built-in retail calendar
# =============================================================================
# Fixed-date events use (month, day). Floating events (Black Friday / Cyber
# Monday) are computed per year. Dates are deliberately generic/global rather
# than per-country - the Southern Hemisphere "Back to School" window (Jan) is
# used as the default since Shopivell's primary market is Zimbabwe; a tenant
# in a Northern Hemisphere market can adjust it via the Retail Calendar
# override UI (custom_start_month/day).
RETAIL_EVENTS: List[Dict[str, Any]] = [
    {"key": "new_year", "name": "New Year", "month": 1, "day": 1, "duration_days": 3, "impact": "low", "budget_multiplier": 1.1},
    {"key": "back_to_school", "name": "Back to School", "month": 1, "day": 8, "duration_days": 21, "impact": "medium", "budget_multiplier": 1.15},
    {"key": "valentines_day", "name": "Valentine's Day", "month": 2, "day": 14, "duration_days": 10, "impact": "medium", "budget_multiplier": 1.2},
    {"key": "africa_day", "name": "Africa Day", "month": 5, "day": 25, "duration_days": 3, "impact": "low", "budget_multiplier": 1.05},
    {"key": "mid_year_sale", "name": "Mid-Year Sale Season", "month": 7, "day": 1, "duration_days": 14, "impact": "low", "budget_multiplier": 1.1},
    {"key": "black_friday", "name": "Black Friday", "month": None, "day": None, "duration_days": 4, "impact": "high", "budget_multiplier": 1.5, "floating": "black_friday"},
    {"key": "cyber_monday", "name": "Cyber Monday", "month": None, "day": None, "duration_days": 1, "impact": "high", "budget_multiplier": 1.4, "floating": "cyber_monday"},
    {"key": "christmas_shopping", "name": "Christmas Shopping Season", "month": 12, "day": 1, "duration_days": 24, "impact": "high", "budget_multiplier": 1.4},
    {"key": "boxing_day", "name": "Boxing Day / Year-End Sale", "month": 12, "day": 26, "duration_days": 6, "impact": "medium", "budget_multiplier": 1.2},
]
RETAIL_EVENTS_BY_KEY = {e["key"]: e for e in RETAIL_EVENTS}


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    """The nth occurrence of a weekday in a month (weekday: Mon=0..Sun=6)."""
    first_day, days_in_month = calendar.monthrange(year, month)
    offset = (weekday - first_day) % 7
    day = 1 + offset + (n - 1) * 7
    return datetime(year, month, day)


def _floating_event_date(key: str, year: int) -> datetime:
    if key == "black_friday":
        # 4th Thursday of November + 1 day
        thanksgiving = _nth_weekday_of_month(year, 11, 3, 4)  # Thursday=3
        return thanksgiving + timedelta(days=1)
    if key == "cyber_monday":
        thanksgiving = _nth_weekday_of_month(year, 11, 3, 4)
        return thanksgiving + timedelta(days=4)  # following Monday
    raise ValueError(f"Unknown floating event: {key}")


def _retail_event_instance(event: Dict[str, Any], year: int, override: Optional[StoreRetailEventOverride] = None) -> Optional[Dict[str, Any]]:
    """Resolve one built-in retail event to a concrete instance for a given
    year, applying a store's override (if any). Returns None if disabled."""
    if override and override.is_enabled is False:
        return None

    month = event.get("month")
    day = event.get("day")
    duration_days = event["duration_days"]
    impact = event["impact"]
    budget_multiplier = event["budget_multiplier"]
    name = event["name"]

    if override:
        if override.custom_start_month is not None:
            month = override.custom_start_month
        if override.custom_start_day is not None:
            day = override.custom_start_day
        if override.custom_duration_days is not None:
            duration_days = override.custom_duration_days
        if override.custom_impact:
            impact = override.custom_impact
        if override.custom_budget_multiplier is not None:
            budget_multiplier = override.custom_budget_multiplier
        if override.custom_name:
            name = override.custom_name

    if event.get("floating") and not (override and override.custom_start_month is not None):
        start = _floating_event_date(event["floating"], year)
    else:
        try:
            start = datetime(year, month, day)
        except ValueError:
            # e.g. Feb 30 from a bad override - skip rather than 500
            return None

    end = start + timedelta(days=max(duration_days - 1, 0))

    return {
        "key": event["key"],
        "name": name,
        "start_date": start,
        "end_date": end,
        "source": "retail_calendar",
        "impact": impact,
        "budget_multiplier": budget_multiplier,
        "duration_days": duration_days,
        "has_override": override is not None,
    }


async def _fetch_public_holidays(country_code: str, year: int) -> List[Dict[str, Any]]:
    """Public holidays from the free Nager.Date API. Returns [] (never raises)
    when the country isn't covered or the service is unreachable - holidays
    are a nice-to-have, not something that should break the page."""
    if not country_code:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://date.nager.at/api/v3/publicholidays/{year}/{country_code.upper()}")
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as e:
        logger.info("Public holiday lookup failed for %s/%s: %s", country_code, year, e)
        return []

    holidays = []
    for h in data or []:
        try:
            d = datetime.fromisoformat(h["date"])
        except Exception:
            continue
        holidays.append({
            "name": h.get("localName") or h.get("name") or "Public Holiday",
            "start_date": d,
            "end_date": d,
            "source": "public_holiday",
            "impact": "medium",
            "budget_multiplier": 1.1,
        })
    return holidays


def _get_overrides(db: Session, store_id: uuid.UUID) -> Dict[str, StoreRetailEventOverride]:
    rows = db.query(StoreRetailEventOverride).filter(StoreRetailEventOverride.store_id == store_id).all()
    return {r.event_key: r for r in rows}


def _resolve_retail_events(db: Session, store_id: uuid.UUID, years: List[int]) -> List[Dict[str, Any]]:
    overrides = _get_overrides(db, store_id)
    out = []
    for year in years:
        for event in RETAIL_EVENTS:
            instance = _retail_event_instance(event, year, overrides.get(event["key"]))
            if instance:
                out.append(instance)
    return out


# =============================================================================
# Custom events CRUD
# =============================================================================

@router.get("/marketing-events/{store_id}")
async def list_store_events(
    store_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    events = (
        db.query(StoreMarketingEvent)
        .filter(StoreMarketingEvent.store_id == store_id)
        .order_by(StoreMarketingEvent.start_date.desc())
        .all()
    )
    return {
        "success": True,
        "total": len(events),
        "events": [
            {
                "id": str(e.id),
                "name": e.name,
                "event_type": e.event_type,
                "start_date": e.start_date.isoformat(),
                "end_date": e.end_date.isoformat(),
                "budget_multiplier": e.budget_multiplier,
                "is_active": e.is_active,
                "notes": e.notes,
            }
            for e in events
        ],
    }


@router.post("/marketing-events/{store_id}")
async def create_store_event(
    store_id: uuid.UUID,
    name: str = Query(...),
    event_type: str = Query("custom"),
    start_date: str = Query(...),
    end_date: str = Query(...),
    budget_multiplier: float = Query(1.0),
    notes: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    try:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    event = StoreMarketingEvent(
        store_id=store_id,
        name=name,
        event_type=event_type,
        start_date=start_dt,
        end_date=end_dt,
        budget_multiplier=budget_multiplier,
        notes=notes,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"success": True, "event_id": str(event.id)}


@router.put("/marketing-events/{event_id}")
async def update_store_event(
    event_id: uuid.UUID,
    name: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    budget_multiplier: Optional[float] = Query(None),
    is_active: Optional[bool] = Query(None),
    notes: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = db.query(StoreMarketingEvent).filter(StoreMarketingEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if name is not None:
        event.name = name
    if event_type is not None:
        event.event_type = event_type
    if start_date is not None:
        try:
            event.start_date = datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date is not None:
        try:
            event.end_date = datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    if budget_multiplier is not None:
        event.budget_multiplier = budget_multiplier
    if is_active is not None:
        event.is_active = is_active
    if notes is not None:
        event.notes = notes

    event.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.delete("/marketing-events/{event_id}")
async def delete_store_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = db.query(StoreMarketingEvent).filter(StoreMarketingEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.commit()
    return {"success": True}


# =============================================================================
# Upcoming events (merged feed)
# =============================================================================

@router.get("/marketing-events/{store_id}/upcoming")
async def get_upcoming_events(
    store_id: uuid.UUID,
    days_ahead: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    country_code = (store.country_code or "ZW").upper()
    now = datetime.utcnow()
    window_end = now + timedelta(days=days_ahead)
    years = sorted({now.year, window_end.year})

    combined: List[Dict[str, Any]] = []

    # Custom events
    custom_events = (
        db.query(StoreMarketingEvent)
        .filter(StoreMarketingEvent.store_id == store_id, StoreMarketingEvent.is_active == True)
        .all()
    )
    for e in custom_events:
        combined.append({
            "name": e.name,
            "start_date": e.start_date,
            "end_date": e.end_date,
            "source": "custom",
            "impact": "medium",
            "budget_multiplier": e.budget_multiplier,
            "event_type": e.event_type,
        })

    # Retail calendar
    for instance in _resolve_retail_events(db, store_id, years):
        combined.append({
            "name": instance["name"],
            "start_date": instance["start_date"],
            "end_date": instance["end_date"],
            "source": "retail_calendar",
            "impact": instance["impact"],
            "budget_multiplier": instance["budget_multiplier"],
        })

    # Public holidays
    for year in years:
        combined.extend(await _fetch_public_holidays(country_code, year))

    # Filter to the window and sort
    upcoming = []
    for item in combined:
        end_date = item["end_date"]
        if end_date < now or item["start_date"] > window_end:
            continue
        days_until = max((item["start_date"].date() - now.date()).days, 0)
        upcoming.append({
            "name": item["name"],
            "start_date": item["start_date"].date().isoformat(),
            "end_date": item["end_date"].date().isoformat(),
            "source": item["source"],
            "impact": item["impact"],
            "budget_multiplier": item["budget_multiplier"],
            "days_until": days_until,
            **({"event_type": item["event_type"]} if "event_type" in item else {}),
        })
    upcoming.sort(key=lambda x: x["days_until"])

    return {
        "success": True,
        "country_code": country_code,
        "total": len(upcoming),
        "events": upcoming,
    }


async def get_relevant_upcoming_events(db: Session, store, within_days: int = 14) -> List[Dict[str, Any]]:
    """For campaign-generation agents: events close enough to genuinely matter
    right now. Deliberately narrow (default 14 days) and impact-filtered so
    a distant or low-impact event never gets forced into ad copy - callers
    should treat this as optional context, not a mandatory theme."""
    if not store:
        return []
    country_code = (store.country_code or "ZW").upper()
    now = datetime.utcnow()
    window_end = now + timedelta(days=within_days)
    years = sorted({now.year, window_end.year})

    combined: List[Dict[str, Any]] = []
    for instance in _resolve_retail_events(db, store.id, years):
        combined.append(instance)
    for year in years:
        combined.extend(await _fetch_public_holidays(country_code, year))
    custom_events = (
        db.query(StoreMarketingEvent)
        .filter(StoreMarketingEvent.store_id == store.id, StoreMarketingEvent.is_active == True)
        .all()
    )
    for e in custom_events:
        combined.append({"name": e.name, "start_date": e.start_date, "end_date": e.end_date, "impact": "medium"})

    relevant = []
    for item in combined:
        if item["end_date"] < now or item["start_date"] > window_end:
            continue
        if item.get("impact") == "low":
            continue
        relevant.append({
            "name": item["name"],
            "start_date": item["start_date"].date().isoformat(),
            "days_until": max((item["start_date"].date() - now.date()).days, 0),
        })
    relevant.sort(key=lambda x: x["days_until"])
    return relevant[:3]


# =============================================================================
# Public holidays (direct lookup)
# =============================================================================

@router.get("/calendar/holidays/{country_code}")
async def get_public_holidays(
    country_code: str,
    year: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
):
    holidays = await _fetch_public_holidays(country_code, year or datetime.utcnow().year)
    return {
        "success": True,
        "holidays": [
            {"name": h["name"], "date": h["start_date"].date().isoformat()}
            for h in holidays
        ],
    }


# =============================================================================
# Retail calendar (with store overrides)
# =============================================================================

@router.get("/calendar/retail-events/{country_code}")
async def get_retail_events(
    country_code: str,
    year: Optional[int] = Query(None),
    store_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    yr = year or datetime.utcnow().year
    overrides = _get_overrides(db, store_id) if store_id else {}
    events = []
    for event in RETAIL_EVENTS:
        instance = _retail_event_instance(event, yr, overrides.get(event["key"]))
        if instance:
            events.append({
                "name": instance["name"],
                "key": instance["key"],
                "start_date": instance["start_date"].date().isoformat(),
                "end_date": instance["end_date"].date().isoformat(),
                "source": "retail_calendar",
                "impact": instance["impact"],
                "budget_multiplier": instance["budget_multiplier"],
                "duration_days": instance["duration_days"],
                "has_override": instance["has_override"],
            })
    return {"success": True, "events": events}


@router.put("/calendar/retail-events/{store_id}/{event_key}")
async def update_retail_event_override(
    store_id: uuid.UUID,
    event_key: str,
    is_enabled: Optional[bool] = Query(None),
    custom_name: Optional[str] = Query(None),
    custom_budget_multiplier: Optional[float] = Query(None),
    custom_impact: Optional[str] = Query(None),
    custom_start_month: Optional[int] = Query(None),
    custom_start_day: Optional[int] = Query(None),
    custom_duration_days: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if event_key not in RETAIL_EVENTS_BY_KEY:
        raise HTTPException(status_code=404, detail="Unknown retail event")

    override = db.query(StoreRetailEventOverride).filter(
        StoreRetailEventOverride.store_id == store_id,
        StoreRetailEventOverride.event_key == event_key,
    ).first()
    if not override:
        override = StoreRetailEventOverride(store_id=store_id, event_key=event_key)
        db.add(override)

    if is_enabled is not None:
        override.is_enabled = is_enabled
    if custom_name is not None:
        override.custom_name = custom_name
    if custom_budget_multiplier is not None:
        override.custom_budget_multiplier = custom_budget_multiplier
    if custom_impact is not None:
        override.custom_impact = custom_impact
    if custom_start_month is not None:
        override.custom_start_month = custom_start_month
    if custom_start_day is not None:
        override.custom_start_day = custom_start_day
    if custom_duration_days is not None:
        override.custom_duration_days = custom_duration_days

    override.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


marketing_events_router = router

# calendar_engine.py - External Events & Calendar Engine
"""
Three event sources for ad optimization context:
1. Public holidays via Nager.Date API (free, no key needed)
2. Built-in retail calendar with region-aware date computation
3. User-configured marketing events from DB

Usage:
    from modules.agents.calendar_engine import get_upcoming_events
    events = get_upcoming_events("ZW", store_id="...", days_ahead=14)
"""

import logging
import requests
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from database import SessionLocal
from utils.cache import RedisCache, CacheConfig

logger = logging.getLogger(__name__)
cache = RedisCache()


# ============ 1. Public Holidays (Nager.Date API) ============

def fetch_public_holidays(country_code: str, year: int = None) -> List[Dict[str, Any]]:
    """
    Fetch public holidays from Nager.Date API.
    Free, no API key required. Cached for 7 days.
    """
    if not year:
        year = datetime.utcnow().year

    cache_key = f"holidays:{country_code}:{year}"
    cached = cache.get(cache_key) if cache.is_connected else None
    if cached:
        return cached

    try:
        response = requests.get(
            f"https://date.nager.at/api/v3/publicholidays/{year}/{country_code}",
            timeout=10
        )
        if response.status_code == 200:
            holidays = []
            for h in response.json():
                holidays.append({
                    "name": h.get("localName") or h.get("name", "Holiday"),
                    "date": h.get("date"),
                    "start_date": h.get("date"),
                    "end_date": h.get("date"),
                    "country_code": country_code,
                    "source": "public_holiday",
                    "impact": "medium",
                    "budget_multiplier": 1.1,
                    "fixed": h.get("fixed", True)
                })

            if holidays and cache.is_connected:
                cache.set(cache_key, holidays, ttl=CacheConfig.TTL_DAY * 7)

            logger.info(f"[CalendarEngine] Fetched {len(holidays)} holidays for {country_code}/{year}")
            return holidays
        else:
            logger.warning(f"[CalendarEngine] Nager.Date API returned {response.status_code} for {country_code}")
            return []
    except Exception as e:
        logger.error(f"[CalendarEngine] Failed to fetch holidays: {e}")
        return []


# ============ 2. Built-in Retail Calendar ============

def _compute_nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Compute the nth occurrence of a weekday in a given month.
    weekday: 0=Monday, 4=Friday, 6=Sunday
    n: 1-based (1st, 2nd, 3rd, 4th)
    """
    first_day = date(year, month, 1)
    # Find first occurrence of the weekday
    days_until = (weekday - first_day.weekday()) % 7
    first_occurrence = first_day + timedelta(days=days_until)
    return first_occurrence + timedelta(weeks=n - 1)


def _compute_easter(year: int) -> date:
    """Compute Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


RETAIL_CALENDAR = {
    # === Global Events ===
    "black_friday": {
        "name": "Black Friday",
        "compute": "4th_friday_november",
        "duration_days": 4,
        "regions": ["all"],
        "impact": "high",
        "budget_multiplier": 1.5
    },
    "cyber_monday": {
        "name": "Cyber Monday",
        "compute": "monday_after_black_friday",
        "duration_days": 1,
        "regions": ["all"],
        "impact": "high",
        "budget_multiplier": 1.4
    },
    "christmas_season": {
        "name": "Christmas Shopping Season",
        "month": 12, "day": 1,
        "duration_days": 25,
        "regions": ["all"],
        "impact": "high",
        "budget_multiplier": 1.4
    },
    "new_year_sales": {
        "name": "New Year Sales",
        "month": 1, "day": 1,
        "duration_days": 7,
        "regions": ["all"],
        "impact": "medium",
        "budget_multiplier": 1.2
    },
    "valentines_day": {
        "name": "Valentine's Day",
        "month": 2, "day": 7,
        "duration_days": 8,
        "regions": ["all"],
        "impact": "medium",
        "budget_multiplier": 1.3
    },
    "easter_season": {
        "name": "Easter Season",
        "compute": "easter_minus_7",
        "duration_days": 14,
        "regions": ["all"],
        "impact": "medium",
        "budget_multiplier": 1.2
    },
    "mid_year_sales": {
        "name": "Mid-Year Sales",
        "month": 6, "day": 15,
        "duration_days": 15,
        "regions": ["all"],
        "impact": "medium",
        "budget_multiplier": 1.2
    },

    # === Back to School (Southern Hemisphere) ===
    "back_to_school_southern": {
        "name": "Back to School",
        "month": 1, "day": 8,
        "duration_days": 21,
        "regions": ["ZW", "ZA", "BW", "NA", "MZ", "ZM", "MW"],
        "impact": "medium",
        "budget_multiplier": 1.3
    },
    "back_to_school_southern_term2": {
        "name": "Back to School (Term 2)",
        "month": 5, "day": 1,
        "duration_days": 14,
        "regions": ["ZW", "ZA", "BW", "NA"],
        "impact": "low",
        "budget_multiplier": 1.15
    },
    "back_to_school_southern_term3": {
        "name": "Back to School (Term 3)",
        "month": 9, "day": 1,
        "duration_days": 14,
        "regions": ["ZW", "ZA", "BW", "NA"],
        "impact": "low",
        "budget_multiplier": 1.15
    },

    # === Back to School (Northern Hemisphere) ===
    "back_to_school_northern": {
        "name": "Back to School",
        "month": 8, "day": 15,
        "duration_days": 30,
        "regions": ["US", "CA", "GB", "DE", "FR"],
        "impact": "medium",
        "budget_multiplier": 1.3
    },

    # === Back to School (Australia) ===
    "back_to_school_australia": {
        "name": "Back to School",
        "month": 1, "day": 20,
        "duration_days": 21,
        "regions": ["AU"],
        "impact": "medium",
        "budget_multiplier": 1.3
    },

    # === Mother's Day ===
    "mothers_day_us": {
        "name": "Mother's Day",
        "compute": "2nd_sunday_may",
        "duration_days": 7,
        "regions": ["US", "CA", "AU", "IN", "ZA", "ZW", "NG", "KE", "GH"],
        "impact": "medium",
        "budget_multiplier": 1.25
    },
    "mothers_day_uk": {
        "name": "Mother's Day (Mothering Sunday)",
        "compute": "mothering_sunday",
        "duration_days": 7,
        "regions": ["GB"],
        "impact": "medium",
        "budget_multiplier": 1.25
    },

    # === Father's Day ===
    "fathers_day": {
        "name": "Father's Day",
        "compute": "3rd_sunday_june",
        "duration_days": 7,
        "regions": ["US", "CA", "GB", "ZA", "ZW", "IN", "NG"],
        "impact": "low",
        "budget_multiplier": 1.2
    },

    # === Regional Events ===
    "festive_season_southern_africa": {
        "name": "Festive Season",
        "month": 12, "day": 15,
        "duration_days": 17,
        "regions": ["ZW", "ZA", "BW", "NA", "MZ", "ZM"],
        "impact": "high",
        "budget_multiplier": 1.4
    },
    "independence_day_zw": {
        "name": "Zimbabwe Independence Day",
        "month": 4, "day": 18,
        "duration_days": 3,
        "regions": ["ZW"],
        "impact": "medium",
        "budget_multiplier": 1.2
    },
    "heritage_day_za": {
        "name": "Heritage Day",
        "month": 9, "day": 24,
        "duration_days": 3,
        "regions": ["ZA"],
        "impact": "low",
        "budget_multiplier": 1.1
    },
    "independence_day_us": {
        "name": "Independence Day (4th of July)",
        "month": 7, "day": 1,
        "duration_days": 5,
        "regions": ["US"],
        "impact": "medium",
        "budget_multiplier": 1.3
    },
}


def _compute_event_date(event: Dict, year: int) -> Optional[date]:
    """Compute the start date for a retail event in a given year."""
    if "month" in event and "day" in event:
        try:
            return date(year, event["month"], event["day"])
        except ValueError:
            return None

    compute = event.get("compute", "")

    if compute == "4th_friday_november":
        return _compute_nth_weekday(year, 11, 4, 4)  # 4th Friday of Nov

    elif compute == "monday_after_black_friday":
        bf = _compute_nth_weekday(year, 11, 4, 4)
        return bf + timedelta(days=3)  # Friday + 3 = Monday

    elif compute == "2nd_sunday_may":
        return _compute_nth_weekday(year, 5, 6, 2)  # 2nd Sunday of May

    elif compute == "3rd_sunday_june":
        return _compute_nth_weekday(year, 6, 6, 3)  # 3rd Sunday of June

    elif compute == "mothering_sunday":
        # 4th Sunday of Lent = Easter - 21 days
        easter = _compute_easter(year)
        return easter - timedelta(days=21)

    elif compute == "easter_minus_7":
        easter = _compute_easter(year)
        return easter - timedelta(days=7)

    return None


def compute_retail_events(
    country_code: str,
    year: int = None,
    store_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Compute all built-in retail events applicable to a country for a given year.
    Handles dynamic date computation (Black Friday, Easter, etc.).
    Applies per-store overrides if store_id is provided.
    """
    if not year:
        year = datetime.utcnow().year

    country_upper = country_code.upper()

    # Load store overrides if available
    overrides = {}
    if store_id:
        db = SessionLocal()
        try:
            from modules.agents.models import StoreCalendarOverride
            import uuid as uuid_mod
            sid = uuid_mod.UUID(store_id) if isinstance(store_id, str) else store_id
            store_overrides = db.query(StoreCalendarOverride).filter(
                StoreCalendarOverride.store_id == sid
            ).all()
            overrides = {o.event_key: o for o in store_overrides}
        except Exception as e:
            logger.warning(f"[CalendarEngine] Failed to load overrides: {e}")
        finally:
            db.close()

    events = []

    for key, event in RETAIL_CALENDAR.items():
        regions = event.get("regions", [])
        if "all" not in regions and country_upper not in regions:
            continue

        # Apply override if exists
        override = overrides.get(key)
        if override and not override.is_enabled:
            continue  # User disabled this event

        # Use override values or defaults
        name = (override.custom_name if override and override.custom_name else event["name"])
        impact = (override.custom_impact if override and override.custom_impact else event.get("impact", "medium"))
        budget_mult = (override.custom_budget_multiplier if override and override.custom_budget_multiplier else event.get("budget_multiplier", 1.0))
        duration = (override.custom_duration_days if override and override.custom_duration_days else event.get("duration_days", 1))

        # Compute start date (use override month/day if set, else original)
        if override and override.custom_start_month and override.custom_start_day:
            try:
                start = date(year, override.custom_start_month, override.custom_start_day)
            except ValueError:
                start = _compute_event_date(event, year)
        else:
            start = _compute_event_date(event, year)

        if not start:
            continue

        end = start + timedelta(days=duration - 1)

        events.append({
            "name": name,
            "key": key,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": "retail_calendar",
            "impact": impact,
            "budget_multiplier": budget_mult,
            "duration_days": duration,
            "has_override": bool(override),
            "editable": True
        })

    # Sort by start date
    events.sort(key=lambda x: x["start_date"])
    return events


# ============ 3. Aggregated Upcoming Events ============

def get_upcoming_events(
    country_code: str,
    store_id: Optional[str] = None,
    days_ahead: int = 14
) -> List[Dict[str, Any]]:
    """
    Get all upcoming events from all three sources, merged and sorted.

    Args:
        country_code: ISO country code (e.g., "ZW")
        store_id: Optional store ID for custom events
        days_ahead: How many days to look ahead

    Returns:
        List of event dicts sorted by days_until
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    events = []

    # Source 1: Public holidays
    try:
        holidays = fetch_public_holidays(country_code)
        for h in holidays:
            h_date = date.fromisoformat(h["date"]) if isinstance(h["date"], str) else h["date"]
            if today <= h_date <= cutoff:
                events.append({
                    "name": h["name"],
                    "start_date": h_date.isoformat(),
                    "end_date": h_date.isoformat(),
                    "source": "public_holiday",
                    "impact": "medium",
                    "budget_multiplier": 1.1,
                    "days_until": (h_date - today).days
                })
    except Exception as e:
        logger.warning(f"[CalendarEngine] Holiday fetch failed: {e}")

    # Also fetch next year's holidays if we're near year end
    if today.month == 12:
        try:
            next_year_holidays = fetch_public_holidays(country_code, today.year + 1)
            for h in next_year_holidays:
                h_date = date.fromisoformat(h["date"]) if isinstance(h["date"], str) else h["date"]
                if today <= h_date <= cutoff:
                    events.append({
                        "name": h["name"],
                        "start_date": h_date.isoformat(),
                        "end_date": h_date.isoformat(),
                        "source": "public_holiday",
                        "impact": "medium",
                        "budget_multiplier": 1.1,
                        "days_until": (h_date - today).days
                    })
        except Exception:
            pass

    # Source 2: Built-in retail calendar (with store overrides)
    try:
        retail_events = compute_retail_events(country_code, store_id=store_id)
        # Also compute for next year if near year end
        if today.month >= 11:
            retail_events.extend(compute_retail_events(country_code, today.year + 1, store_id=store_id))

        for re in retail_events:
            r_start = date.fromisoformat(re["start_date"])
            r_end = date.fromisoformat(re["end_date"])

            # Include if event overlaps with our window
            if r_end >= today and r_start <= cutoff:
                days_until = max((r_start - today).days, 0)
                events.append({
                    "name": re["name"],
                    "start_date": re["start_date"],
                    "end_date": re["end_date"],
                    "source": "retail_calendar",
                    "impact": re["impact"],
                    "budget_multiplier": re["budget_multiplier"],
                    "days_until": days_until
                })
    except Exception as e:
        logger.warning(f"[CalendarEngine] Retail calendar error: {e}")

    # Source 3: User-configured events
    if store_id:
        db = SessionLocal()
        try:
            from modules.agents.models import MarketingEvent
            import uuid as uuid_mod

            sid = uuid_mod.UUID(store_id) if isinstance(store_id, str) else store_id
            custom_events = db.query(MarketingEvent).filter(
                MarketingEvent.store_id == sid,
                MarketingEvent.is_active == True,
                MarketingEvent.end_date >= datetime.utcnow(),
                MarketingEvent.start_date <= datetime.utcnow() + timedelta(days=days_ahead)
            ).all()

            for ce in custom_events:
                ce_start = ce.start_date.date() if isinstance(ce.start_date, datetime) else ce.start_date
                days_until = max((ce_start - today).days, 0)
                events.append({
                    "name": ce.name,
                    "start_date": ce_start.isoformat(),
                    "end_date": (ce.end_date.date() if isinstance(ce.end_date, datetime) else ce.end_date).isoformat(),
                    "source": "custom",
                    "impact": "medium",
                    "budget_multiplier": ce.budget_multiplier or 1.0,
                    "days_until": days_until,
                    "event_type": ce.event_type
                })
        except Exception as e:
            logger.warning(f"[CalendarEngine] Custom events error: {e}")
        finally:
            db.close()

    # Sort by days_until (soonest first)
    events.sort(key=lambda x: x["days_until"])

    return events


def get_current_event_context(country_code: str, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a summary of the current event context for the rules engine.

    Returns:
        Dict with days_to_next_event, event_budget_multiplier, is_event_active, events
    """
    events = get_upcoming_events(country_code, store_id, days_ahead=14)
    today = date.today()

    # Find active events (happening right now)
    active_events = [e for e in events if e["days_until"] == 0]

    # Find next upcoming event
    upcoming = [e for e in events if e["days_until"] > 0]

    # Compute metrics
    days_to_next = upcoming[0]["days_until"] if upcoming else 999
    is_active = 1.0 if active_events else 0.0

    # Budget multiplier: use the highest among active events, or the next upcoming one
    if active_events:
        budget_mult = max(e["budget_multiplier"] for e in active_events)
    elif upcoming and upcoming[0]["days_until"] <= 3:
        budget_mult = upcoming[0]["budget_multiplier"]
    else:
        budget_mult = 1.0

    return {
        "days_to_next_event": days_to_next,
        "event_budget_multiplier": budget_mult,
        "is_event_active": is_active,
        "active_events": active_events,
        "upcoming_events": upcoming[:5],
        "total_events": len(events)
    }

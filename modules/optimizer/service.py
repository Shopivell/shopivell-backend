"""
Ad optimizer — the 24/7 rules engine over Zernio ad data.

Replaces the OpenClaw optimizer plugin, which was never deployed. Every
OPTIMIZER_INTERVAL_MINUTES a daemon thread in the web process (same pattern as
modules.jobs.queue):
  1. takes a Postgres advisory lock, so overlapping containers during a
     start-first rolling update never double-run,
  2. for each store with a Zernio profile, fetches its Meta ads tree (last 7
     days + yesterday) and evaluates modules.optimizer.rules per ad set,
  3. records a daily snapshot and every decision and — only when allowed —
     applies the change through Zernio and notifies the store owner.

Dry run is the default: nothing changes on Meta unless OPTIMIZER_DRY_RUN=false,
the store's optimizer config has dry_run=False, and store.ads_enabled is True.
"""

import asyncio
import logging
import os
import threading
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, text

from database import SessionLocal, USE_SQLITE, engine
from modules.optimizer import rules as R
from modules.optimizer.models import OptimizerConfig, OptimizerDecision, OptimizerSnapshot

logger = logging.getLogger(__name__)

INTERVAL_MINUTES = int(os.getenv("OPTIMIZER_INTERVAL_MINUTES", "15"))
GLOBAL_DRY_RUN = os.getenv("OPTIMIZER_DRY_RUN", "true").strip().lower() not in ("0", "false", "no")
_LOCK_KEY = 7203314159  # arbitrary bigint for pg_try_advisory_lock

_thread = None
_stop = threading.Event()
_state: Dict[str, Any] = {"last_check": None, "next_check": None, "last_error": None}


# ---------------- Zernio data ----------------

async def _tree(account_id: str, preset: str) -> List[Dict[str, Any]]:
    from modules.openclaw.router import _zernio
    campaigns, page = [], 1
    while True:
        res = await _zernio("GET", "/ads/tree", params={"accountId": account_id, "datePreset": preset, "page": page})
        res = res if isinstance(res, dict) else {}
        campaigns += res.get("campaigns") or []
        if page >= min(int((res.get("pagination") or {}).get("pages") or 1), 20):
            return campaigns
        page += 1


async def _fetch_ad_sets(profile_id: str) -> List[Tuple[Dict, Dict, Optional[Dict]]]:
    """[(campaign, ad_set, yesterday's copy of the ad set or None)] for the profile's Meta accounts."""
    from modules.openclaw.router import _zernio
    listing = await _zernio("GET", "/accounts")
    accounts = listing.get("accounts", []) if isinstance(listing, dict) else (listing or [])
    rows = []
    for acct in accounts:
        pid = acct.get("profileId")
        pid = pid.get("_id") if isinstance(pid, dict) else pid
        if acct.get("platform") != "facebook" or str(pid) != str(profile_id):
            continue
        account_id = acct.get("_id") or acct.get("id")
        week = await _tree(account_id, "last_7d")
        yesterday = {s.get("platformAdSetId"): s
                     for c in await _tree(account_id, "yesterday") for s in c.get("adSets") or []}
        for camp in week:
            for ad_set in camp.get("adSets") or []:
                rows.append((camp, ad_set, yesterday.get(ad_set.get("platformAdSetId"))))
    return rows


async def _apply(ad_set_id: str, proposal: Dict[str, Any]) -> None:
    from modules.openclaw.router import _dispatch_zernio
    if proposal["action"] == "pause":
        await _dispatch_zernio("pause_ad", {"ad_id": ad_set_id})
    else:
        await _dispatch_zernio("scale_budget", {"campaign_id": ad_set_id, "new_budget": proposal["new_budget"]})


# ---------------- per-store run ----------------

def effective_dry_run(store, cfg: Optional[OptimizerConfig]) -> bool:
    return GLOBAL_DRY_RUN or not store.ads_enabled or cfg is None or bool(cfg.dry_run)


def _history(db, ad_set_id: str, today: date) -> Dict[date, Dict[str, Any]]:
    rows = (db.query(OptimizerSnapshot)
            .filter(OptimizerSnapshot.ad_set_id == ad_set_id,
                    OptimizerSnapshot.day < today,
                    OptimizerSnapshot.day >= today - timedelta(days=7))
            .all())
    return {r.day: r.metrics or {} for r in rows}


def _save_snapshot(db, store_id, campaign_id: str, ad_set_id: str, active: bool, today: date, metrics) -> None:
    snap = db.query(OptimizerSnapshot).filter_by(ad_set_id=ad_set_id, day=today).first()
    if not snap:
        snap = OptimizerSnapshot(store_id=store_id, ad_set_id=ad_set_id, day=today)
        db.add(snap)
    snap.campaign_id, snap.active, snap.metrics = campaign_id, active, metrics


def _last_fired(db, ad_set_id: str, now: datetime) -> Dict[str, datetime]:
    rows = (db.query(OptimizerDecision.rule, func.max(OptimizerDecision.created_at))
            .filter(OptimizerDecision.ad_set_id == ad_set_id,
                    OptimizerDecision.created_at >= now - timedelta(days=7))
            .group_by(OptimizerDecision.rule)
            .all())
    return {rule: ts for rule, ts in rows}


def _notify(db, store, camp, ad_set, p) -> None:
    try:
        from modules.notifications.router import NotificationService
        from modules.notifications.schemas import NotificationType, NotificationPriority
        name = ad_set.get("adSetName") or camp.get("campaignName") or "ad set"
        if p["action"] == "pause":
            title, priority = f"Ad paused: {name}", NotificationPriority.HIGH
        else:
            verb = "increased" if p["action"] == "budget_increase" else "reduced"
            title, priority = f"Ad budget {verb}: {name}", NotificationPriority.NORMAL
        message = p["reason"] + (f". Daily budget ${p['old_budget']:.2f} -> ${p['new_budget']:.2f}."
                                 if "new_budget" in p else ".")
        asyncio.run(NotificationService(store.id).create_notification(
            db=db, title=title, message=message,
            notification_type=NotificationType.SYSTEM, priority=priority))
    except Exception as e:
        logger.warning(f"[optimizer] notification failed for store {store.id}: {e}")


def _decide(db, store, camp, ad_set, p, metrics, dry_run: bool) -> None:
    ad_set_id = str(ad_set.get("platformAdSetId"))
    status, error = "dry_run", None
    if not dry_run:
        try:
            asyncio.run(_apply(ad_set_id, p))
            status = "applied"
        except Exception as e:
            status, error = "failed", str(e)[:1000]
    db.add(OptimizerDecision(
        store_id=store.id, campaign_id=str(camp.get("platformCampaignId") or ""),
        campaign_name=camp.get("campaignName"), ad_set_id=ad_set_id, ad_set_name=ad_set.get("adSetName"),
        rule=p["rule"], action=p["action"], status=status, metrics=metrics,
        details={k: p[k] for k in ("old_budget", "new_budget", "reason") if k in p}, error=error))
    logger.info(f"[optimizer] {status}: {p['rule']} -> {p['action']} on ad set {ad_set_id} ({p['reason']})")
    if status == "applied":
        _notify(db, store, camp, ad_set, p)


def _run_store(db, store) -> int:
    cfg = db.get(OptimizerConfig, store.id)
    rules = R.merged_rules(cfg.rules if cfg else None)
    dry_run = effective_dry_run(store, cfg)
    now = datetime.utcnow()
    today = now.date()
    fired = 0
    for camp, ad_set, yday in asyncio.run(_fetch_ad_sets(store.zernio_profile_id)):
        ad_set_id = str(ad_set.get("platformAdSetId") or "")
        if not ad_set_id:
            continue
        metrics = R.ad_set_metrics(ad_set)
        active = (str(camp.get("status", "")).lower() == "active"
                  and str(ad_set.get("status", "")).lower() == "active")
        history = _history(db, ad_set_id, today)
        _save_snapshot(db, store.id, str(camp.get("platformCampaignId") or ""), ad_set_id, active, today, metrics)
        if not active:
            continue
        proposals = R.evaluate(
            ad_set, metrics, rules=rules, history=history,
            yesterday_spend=R.ad_set_metrics(yday)["spend"] if yday else None,
            last_fired=_last_fired(db, ad_set_id, now), now=now,
            target_roas=cfg.target_roas if cfg else None, target_cpa=cfg.target_cpa if cfg else None)
        for p in proposals:
            _decide(db, store, camp, ad_set, p, metrics, dry_run)
            fired += 1
    db.commit()
    return fired


def run_once() -> Dict[str, Any]:
    """One optimizer pass over every store with a Zernio profile."""
    from modules.stores.models import Store
    summary: Dict[str, Any] = {"stores": 0, "decisions": 0, "errors": []}
    with engine.connect() as lock_conn:
        if not USE_SQLITE and not lock_conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar():
            logger.info("[optimizer] another instance is mid-run; skipping")
            return {**summary, "skipped": "locked"}
        try:
            db = SessionLocal()
            try:
                # A "-" means a placeholder UUID, not a real Zernio profile id.
                stores = [s for s in db.query(Store).filter(Store.zernio_profile_id.isnot(None)).all()
                          if "-" not in str(s.zernio_profile_id)]
                for store in stores:
                    try:
                        summary["decisions"] += _run_store(db, store)
                        summary["stores"] += 1
                    except Exception as e:
                        db.rollback()
                        summary["errors"].append(f"{store.id}: {e}"[:300])
                        logger.warning(f"[optimizer] store {store.id} failed: {e}")
            finally:
                db.close()
        finally:
            if not USE_SQLITE:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
    _state["last_check"] = datetime.utcnow()
    return summary


# ---------------- background thread ----------------

def _loop() -> None:
    logger.info(f"[optimizer] started (every {INTERVAL_MINUTES} min, global dry_run={GLOBAL_DRY_RUN})")
    _stop.wait(60)  # let the app finish booting
    while not _stop.is_set():
        try:
            logger.info(f"[optimizer] run: {run_once()}")
            _state["last_error"] = None
        except Exception as e:
            _state["last_error"] = str(e)[:300]
            logger.error(f"[optimizer] run failed: {e}\n{traceback.format_exc()}")
        _state["next_check"] = datetime.utcnow() + timedelta(minutes=INTERVAL_MINUTES)
        _stop.wait(INTERVAL_MINUTES * 60)
    logger.info("[optimizer] stopped")


def start_optimizer() -> None:
    """Start the optimizer thread (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="ad-optimizer")
    _thread.start()


def stop_optimizer() -> None:
    _stop.set()


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())


# ---------------- API helpers (used by /openclaw/stores/{id}/optimizer/*) ----------------

def _iso(ts: Optional[datetime]) -> Optional[str]:
    return ts.isoformat() + "Z" if ts else None


def get_status(db, store) -> Dict[str, Any]:
    cfg = db.get(OptimizerConfig, store.id)
    now = datetime.utcnow()
    snaps = (db.query(OptimizerSnapshot)
             .filter(OptimizerSnapshot.store_id == store.id, OptimizerSnapshot.day == now.date())
             .all())
    todays = (db.query(OptimizerDecision)
              .filter(OptimizerDecision.store_id == store.id,
                      OptimizerDecision.created_at >= datetime.combine(now.date(), datetime.min.time()))
              .order_by(OptimizerDecision.created_at.desc())
              .all())
    return {
        "store_id": str(store.id),
        "connected": bool(store.zernio_profile_id),
        "running": is_running(),
        "dry_run": effective_dry_run(store, cfg),
        "interval_minutes": INTERVAL_MINUTES,
        "last_check": _iso(_state["last_check"]),
        "next_check": _iso(_state["next_check"]),
        "last_error": _state["last_error"],
        "active_campaigns": len({s.campaign_id for s in snaps if s.active}),
        "active_ad_sets": sum(1 for s in snaps if s.active),
        "targets": {"roas": cfg.target_roas if cfg else None, "cpa": cfg.target_cpa if cfg else None},
        "rules": R.merged_rules(cfg.rules if cfg else None),
        "actions_today": [{"campaign": d.campaign_name, "ad_set": d.ad_set_name, "rule": d.rule,
                           "action": d.action, "status": d.status, "time": d.created_at.strftime("%H:%M")}
                          for d in todays],
    }


def get_history(db, store, limit: int = 20) -> Dict[str, Any]:
    rows = (db.query(OptimizerDecision)
            .filter(OptimizerDecision.store_id == store.id)
            .order_by(OptimizerDecision.created_at.desc())
            .limit(max(1, min(limit, 200)))
            .all())
    return {"decisions": [{"timestamp": _iso(d.created_at), "campaign_id": d.campaign_id,
                           "campaign_name": d.campaign_name, "ad_set_id": d.ad_set_id,
                           "ad_set_name": d.ad_set_name, "rule": d.rule, "action": d.action,
                           "status": d.status, "metrics": d.metrics, "details": d.details, "error": d.error}
                          for d in rows]}


def update_config(db, store, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Set targets / dry_run and merge per-rule overrides; returns the new status."""
    cfg = db.get(OptimizerConfig, store.id) or OptimizerConfig(store_id=store.id, dry_run=True, rules={})
    for key in ("target_roas", "target_cpa", "dry_run"):
        if key in updates:
            setattr(cfg, key, updates.pop(key))
    rules = dict(cfg.rules or {})
    for name, overrides in updates.items():
        if name in R.DEFAULT_RULES and isinstance(overrides, dict):
            rules[name] = {**rules.get(name, {}),
                           **{k: v for k, v in overrides.items() if k in R.DEFAULT_RULES[name]}}
    cfg.rules = rules
    db.add(cfg)
    db.commit()
    return get_status(db, store)

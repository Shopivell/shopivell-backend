"""
FastAPI router for Micro-Strategy (Lexi) and Pixel Readiness Tracker.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import uuid
import logging

from database import get_db
from .models import MicroStrategy, MicroStrategyPhase, PhaseVariation, PixelReadinessTracker
from .schemas import (
    CreateMicroStrategyRequest,
    UpdateMicroStrategyRequest,
    DeclareWinnerRequest,
    CreatePixelTrackerRequest,
    MicroStrategyResponse,
    MicroStrategyListResponse,
    PhaseResponse,
    PixelTrackerResponse,
    PixelTrackerListResponse,
    LearningsResponse,
)
from .service import MicroStrategyService

logger = logging.getLogger(__name__)

micro_strategy_router = APIRouter(
    prefix="/api/micro-strategy",
    tags=["micro-strategy"],
)


# ── Micro-Strategy CRUD ───────────────────────────────────


@micro_strategy_router.post("/", response_model=MicroStrategyResponse)
async def create_strategy(req: CreateMicroStrategyRequest, db: Session = Depends(get_db)):
    """Create a new micro-strategy with 4 pre-defined phases."""
    service = MicroStrategyService(db)
    strategy = service.create_strategy(
        ad_account_id=req.ad_account_id,
        store_id=req.store_id,
        name=req.name,
        source_url=req.source_url,
        destination_url=req.destination_url,
        winner_metric=req.winner_metric,
        daily_budget_cents=req.daily_budget_cents,
        max_spend_per_phase_cents=req.max_spend_per_phase_cents,
        min_days_per_phase=req.min_days_per_phase,
        max_days_per_phase=req.max_days_per_phase,
        variations_per_phase=req.variations_per_phase,
        product_context=req.product_context,
    )
    return strategy


@micro_strategy_router.get("/{strategy_id}", response_model=MicroStrategyResponse)
async def get_strategy(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get full strategy with phases and variations."""
    service = MicroStrategyService(db)
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@micro_strategy_router.get("/store/{store_id}", response_model=MicroStrategyListResponse)
async def list_strategies(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """List all strategies for a store."""
    service = MicroStrategyService(db)
    strategies = service.list_strategies(store_id)
    return MicroStrategyListResponse(strategies=strategies, total=len(strategies))


@micro_strategy_router.patch("/{strategy_id}", response_model=MicroStrategyResponse)
async def update_strategy(
    strategy_id: uuid.UUID,
    req: UpdateMicroStrategyRequest,
    db: Session = Depends(get_db),
):
    """Update strategy configuration."""
    service = MicroStrategyService(db)
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(strategy, key, value)
    db.commit()
    db.refresh(strategy)
    return strategy


@micro_strategy_router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a strategy and all its phases/variations."""
    service = MicroStrategyService(db)
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    service.delete_strategy(strategy_id)
    return {"message": "Strategy deleted"}


# ── Strategy Control ──────────────────────────────────────


@micro_strategy_router.post("/{strategy_id}/start", response_model=MicroStrategyResponse)
async def start_strategy(
    strategy_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start a strategy: scrapes product context, generates Phase 1 variations,
    publishes to Meta, and activates ads. Runs in background.
    """
    service = MicroStrategyService(db)
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    try:
        strategy = await service.start_strategy(strategy_id)
        return strategy
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start strategy: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")


@micro_strategy_router.post("/{strategy_id}/pause", response_model=MicroStrategyResponse)
async def pause_strategy(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Pause all active ads for this strategy."""
    service = MicroStrategyService(db)
    try:
        strategy = await service.pause_strategy(strategy_id)
        return strategy
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@micro_strategy_router.post("/{strategy_id}/resume", response_model=MicroStrategyResponse)
async def resume_strategy(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Resume a paused strategy."""
    service = MicroStrategyService(db)
    try:
        strategy = await service.resume_strategy(strategy_id)
        return strategy
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Phase Operations ──────────────────────────────────────


@micro_strategy_router.get("/{strategy_id}/phases", response_model=list[PhaseResponse])
async def list_phases(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    """List all phases for a strategy."""
    strategy = db.query(MicroStrategy).filter(MicroStrategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy.phases


@micro_strategy_router.get(
    "/{strategy_id}/phases/{phase_id}", response_model=PhaseResponse
)
async def get_phase(
    strategy_id: uuid.UUID, phase_id: uuid.UUID, db: Session = Depends(get_db)
):
    """Get full phase detail with variations and metrics."""
    phase = (
        db.query(MicroStrategyPhase)
        .filter(
            MicroStrategyPhase.id == phase_id,
            MicroStrategyPhase.strategy_id == strategy_id,
        )
        .first()
    )
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")
    return phase


@micro_strategy_router.post("/{strategy_id}/phases/{phase_id}/sync-metrics")
async def sync_metrics(
    strategy_id: uuid.UUID, phase_id: uuid.UUID, db: Session = Depends(get_db)
):
    """Force sync performance metrics from Meta for this phase."""
    service = MicroStrategyService(db)
    phase = (
        db.query(MicroStrategyPhase)
        .filter(
            MicroStrategyPhase.id == phase_id,
            MicroStrategyPhase.strategy_id == strategy_id,
        )
        .first()
    )
    if not phase:
        raise HTTPException(status_code=404, detail="Phase not found")

    await service.sync_phase_metrics(phase_id)
    db.refresh(phase)
    return {"message": "Metrics synced", "total_spend_cents": phase.total_spend_cents}


@micro_strategy_router.post("/{strategy_id}/phases/{phase_id}/declare-winner")
async def declare_winner(
    strategy_id: uuid.UUID,
    phase_id: uuid.UUID,
    req: DeclareWinnerRequest = DeclareWinnerRequest(),
    db: Session = Depends(get_db),
):
    """Declare a winner for a phase (auto-detect or manual override)."""
    service = MicroStrategyService(db)
    try:
        winner = await service.declare_winner(strategy_id, phase_id, req.variation_id)
        return {
            "message": "Winner declared",
            "winner_id": str(winner.id),
            "winner_name": winner.variation_name,
            "winner_value": winner.variable_value,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Learnings ─────────────────────────────────────────────


@micro_strategy_router.get("/{strategy_id}/learnings", response_model=LearningsResponse)
async def get_learnings(strategy_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get structured learnings for a strategy."""
    service = MicroStrategyService(db)
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    completed_phases = sum(1 for p in strategy.phases if p.status == "COMPLETED")

    return LearningsResponse(
        strategy_id=strategy.id,
        strategy_name=strategy.name,
        learnings=strategy.learnings,
        winning_headline=strategy.winning_headline,
        winning_image_url=strategy.winning_image_url,
        winning_audience=strategy.winning_audience,
        winning_offer=strategy.winning_offer,
        phases_completed=completed_phases,
        phases_total=4,
    )


@micro_strategy_router.get("/store/{store_id}/learnings")
async def get_store_learnings(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """Aggregate learnings across all strategies for a store."""
    service = MicroStrategyService(db)
    strategies = service.list_strategies(store_id)

    all_learnings = []
    for s in strategies:
        completed = sum(1 for p in s.phases if p.status == "COMPLETED")
        all_learnings.append({
            "strategy_id": str(s.id),
            "strategy_name": s.name,
            "learnings": s.learnings,
            "winning_headline": s.winning_headline,
            "winning_image_url": s.winning_image_url,
            "winning_audience": s.winning_audience,
            "winning_offer": s.winning_offer,
            "phases_completed": completed,
        })

    return {"store_id": str(store_id), "strategies": all_learnings, "total": len(all_learnings)}


# ── Pixel Readiness Tracker ──────────────────────────────


@micro_strategy_router.post("/pixel-tracker", response_model=PixelTrackerResponse)
async def create_pixel_tracker(req: CreatePixelTrackerRequest, db: Session = Depends(get_db)):
    """Create a pixel readiness tracker."""
    service = MicroStrategyService(db)
    tracker = service.create_pixel_tracker(
        ad_account_id=req.ad_account_id,
        store_id=req.store_id,
        pixel_id=req.pixel_id,
        pixel_name=req.pixel_name,
        micro_strategy_id=req.micro_strategy_id,
        required_events=req.required_events,
        required_days=req.required_days,
        event_window_days=req.event_window_days,
    )
    return tracker


@micro_strategy_router.get("/pixel-tracker/{tracker_id}", response_model=PixelTrackerResponse)
async def get_pixel_tracker(tracker_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get pixel tracker status."""
    service = MicroStrategyService(db)
    tracker = service.get_pixel_tracker(tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")
    return tracker


@micro_strategy_router.get("/pixel-tracker/store/{store_id}", response_model=PixelTrackerListResponse)
async def list_pixel_trackers(store_id: uuid.UUID, db: Session = Depends(get_db)):
    """List all pixel trackers for a store."""
    service = MicroStrategyService(db)
    trackers = service.list_pixel_trackers(store_id)
    return PixelTrackerListResponse(trackers=trackers, total=len(trackers))


@micro_strategy_router.post("/pixel-tracker/{tracker_id}/start-traffic")
async def start_traffic(tracker_id: uuid.UUID, db: Session = Depends(get_db)):
    """Start a traffic campaign to warm up the pixel."""
    service = MicroStrategyService(db)
    try:
        tracker = await service.start_traffic_campaign(tracker_id)
        return {
            "message": "Traffic campaign started",
            "campaign_id": tracker.traffic_campaign_id,
            "status": tracker.switch_status,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@micro_strategy_router.post("/pixel-tracker/{tracker_id}/check")
async def check_readiness(tracker_id: uuid.UUID, db: Session = Depends(get_db)):
    """Force check if pixel has enough data to switch to Lead Gen."""
    service = MicroStrategyService(db)
    tracker = service.get_pixel_tracker(tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    ready = await service.check_pixel_readiness(tracker_id)
    db.refresh(tracker)

    return {
        "ready": ready,
        "total_events": tracker.total_optimization_events,
        "required_events": tracker.required_events,
        "status": tracker.switch_status,
    }


@micro_strategy_router.post("/pixel-tracker/{tracker_id}/switch")
async def trigger_switch(tracker_id: uuid.UUID, db: Session = Depends(get_db)):
    """Manually trigger the switch from Traffic to Lead Gen."""
    service = MicroStrategyService(db)
    try:
        tracker = await service.execute_objective_switch(tracker_id)
        return {
            "message": "Switched to Lead Generation",
            "leadgen_campaign_id": tracker.leadgen_campaign_id,
            "status": tracker.switch_status,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@micro_strategy_router.get("/pixel-tracker/{tracker_id}/events")
async def get_pixel_events(tracker_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get detailed pixel event breakdown."""
    service = MicroStrategyService(db)
    tracker = service.get_pixel_tracker(tracker_id)
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found")

    return {
        "pixel_id": tracker.pixel_id,
        "events": {
            "PageView": tracker.page_view_count,
            "ViewContent": tracker.view_content_count,
            "Lead": tracker.lead_count,
            "AddToCart": tracker.add_to_cart_count,
            "Purchase": tracker.purchase_count,
        },
        "total_optimization_events": tracker.total_optimization_events,
        "required_events": tracker.required_events,
        "progress_percent": min(
            100.0,
            (tracker.total_optimization_events / max(tracker.required_events, 1)) * 100,
        ),
    }

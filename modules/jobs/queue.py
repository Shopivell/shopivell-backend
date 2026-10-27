"""
Durable background job queue (Postgres-backed) with an in-process worker.

Why: scraping, embedding sync, and publishing ran synchronously inside HTTP
handlers, so a slow or failing task blocked the response or was silently
dropped by a swallow-and-continue except. This queue moves such work off the
request path: jobs are persisted, retried with exponential backoff, and claimed
with FOR UPDATE SKIP LOCKED so multiple web workers / replicas never double-run
a job. No separate worker container is needed — a daemon thread in the web
process drains the queue (same pattern as the existing scheduler).

Usage:
    from modules.jobs.queue import enqueue
    enqueue("sync_store_knowledge", {"store_id": str(store_id)})

    from modules.jobs.queue import handler
    @handler("sync_store_knowledge")
    def _sync(payload): ...
"""

import asyncio
import inspect
import logging
import threading
import traceback
from datetime import datetime, timedelta

from database import SessionLocal
from modules.jobs.models import BackgroundJob

logger = logging.getLogger(__name__)

_HANDLERS = {}
_worker_thread = None
_stop = threading.Event()

# Retry backoff is min(_MAX_BACKOFF, _BASE_BACKOFF * 2**(attempts-1)) seconds.
_BASE_BACKOFF = 10
_MAX_BACKOFF = 300


def register_handler(job_type: str, fn) -> None:
    _HANDLERS[job_type] = fn


def handler(job_type: str):
    """Decorator to register a job handler. Handler signature: fn(payload: dict)."""
    def deco(fn):
        register_handler(job_type, fn)
        return fn
    return deco


def enqueue(job_type: str, payload: dict = None, max_attempts: int = 3, delay_seconds: int = 0):
    """Persist a job for the worker to pick up. Returns job id (str) or None.

    Never raises — enqueue failures must not break the caller's request."""
    try:
        db = SessionLocal()
        try:
            job = BackgroundJob(
                job_type=job_type,
                payload=payload or {},
                status="pending",
                max_attempts=max_attempts,
                run_at=datetime.utcnow() + timedelta(seconds=delay_seconds),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            logger.info(f"[jobs] enqueued {job_type} ({job.id})")
            return str(job.id)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[jobs] enqueue failed for {job_type}: {e}")
        return None


def _claim_one(db):
    """Atomically claim the next due job. Returns the row (status=running) or None."""
    job = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.status == "pending", BackgroundJob.run_at <= datetime.utcnow())
        .order_by(BackgroundJob.run_at)
        .with_for_update(skip_locked=True)  # Postgres: never contend with other workers
        .first()
    )
    if not job:
        return None
    job.status = "running"
    job.attempts += 1
    db.commit()
    return job


def _run_handler(job_type: str, payload: dict):
    fn = _HANDLERS.get(job_type)
    if not fn:
        raise RuntimeError(f"No handler registered for job_type '{job_type}'")
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(payload))
    return fn(payload)


def _process_once() -> bool:
    """Claim + run at most one job. Returns True if a job was handled."""
    db = SessionLocal()
    try:
        job = _claim_one(db)
        if not job:
            return False
        job_id, job_type, payload = job.id, job.job_type, dict(job.payload or {})
        attempts, max_attempts = job.attempts, job.max_attempts
        try:
            result = _run_handler(job_type, payload)
            job.status = "done"
            job.last_error = None
            job.result = result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result)
            db.commit()
            logger.info(f"[jobs] done {job_type} ({job_id})")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if attempts >= max_attempts:
                job.status = "failed"
                job.last_error = err[:2000]
                logger.error(f"[jobs] FAILED {job_type} ({job_id}) after {attempts} attempts: {err}")
            else:
                backoff = min(_MAX_BACKOFF, _BASE_BACKOFF * (2 ** (attempts - 1)))
                job.status = "pending"
                job.last_error = err[:2000]
                job.run_at = datetime.utcnow() + timedelta(seconds=backoff)
                logger.warning(f"[jobs] retry {job_type} ({job_id}) attempt {attempts}/{max_attempts} in {backoff}s: {err}")
            db.commit()
        return True
    finally:
        db.close()


def _loop(poll_interval: float):
    logger.info("[jobs] worker started")
    while not _stop.is_set():
        try:
            # Drain any ready jobs, then idle until the next poll.
            if not _process_once():
                _stop.wait(poll_interval)
        except Exception as e:
            logger.error(f"[jobs] worker loop error: {e}\n{traceback.format_exc()}")
            _stop.wait(poll_interval)
    logger.info("[jobs] worker stopped")


def start_worker(poll_interval: float = 5.0) -> None:
    """Start the background worker thread (idempotent)."""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    # Import handlers so they register before we start draining.
    try:
        import modules.jobs.handlers  # noqa: F401
    except Exception as e:
        logger.error(f"[jobs] failed to import handlers: {e}")
    _stop.clear()
    _worker_thread = threading.Thread(target=_loop, args=(poll_interval,), daemon=True, name="job-worker")
    _worker_thread.start()


def stop_worker() -> None:
    _stop.set()

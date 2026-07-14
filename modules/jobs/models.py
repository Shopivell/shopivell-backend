from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, UUID, Index
from datetime import datetime
import uuid
from database import Base


class BackgroundJob(Base):
    """A durable unit of background work.

    Slow / failure-prone tasks (embedding sync, etc.) are enqueued here and run
    by an in-process worker (modules.jobs.queue) instead of on the HTTP request
    thread, so a slow or failing task no longer blocks a response or gets
    silently dropped. Rows persist across restarts and are retried with backoff.
    """
    __tablename__ = "background_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(String(100), nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    # pending -> running -> done | failed  (failed = exhausted max_attempts)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    # Earliest time the job may run; pushed forward for retry backoff.
    run_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Fast claim query: pending jobs whose run_at has arrived, oldest first.
    __table_args__ = (
        Index("ix_background_jobs_claim", "status", "run_at"),
    )

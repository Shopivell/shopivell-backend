"""
Lightweight, dependency-free observability.

Before this, logging was unconfigured plain text with scattered print() calls and
no way to tie a log line to the request, tenant, or agent that produced it — which
is why failures like an embeddings 429 stayed invisible until someone dug through
raw output. This module gives:

  * One central logging config (consistent format, optional JSON) that takes over
    any ad-hoc logging.basicConfig calls.
  * A per-request correlation id (X-Request-ID) propagated via a contextvar and
    stamped onto every log record.
  * Automatic enrichment with the AI context (store_id, agent) already tracked in
    modules.openrouter.context, so agent decisions and their log lines correlate.

No external collector or API key required. Configure with env:
  LOG_LEVEL (default INFO), LOG_FORMAT=json|plain (default plain),
  LOG_LEVEL_THIRDPARTY (default WARNING).
"""

import json
import logging
import os
import sys
import time
import uuid
import contextvars

# Per-request correlation id, set by RequestContextMiddleware. "-" outside a request.
request_id_var: contextvars.ContextVar = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_var.get()


class ContextFilter(logging.Filter):
    """Stamp request_id + AI context (store_id, agent) onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        store_id, agent = "-", "-"
        try:
            from modules.openrouter.context import ai_context
            ctx = ai_context.get()
            store_id = getattr(ctx, "store_id", None) or "-"
            agent = getattr(ctx, "agent_name", None) or "-"
        except Exception:
            pass
        record.store_id = store_id
        record.agent = agent
        return True


class JsonFormatter(logging.Formatter):
    """Machine-readable one-line-per-record JSON (LOG_FORMAT=json)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "store_id": getattr(record, "store_id", "-"),
            "agent": getattr(record, "agent", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_PLAIN_FMT = (
    "%(asctime)s %(levelname)-7s "
    "[req:%(request_id)s store:%(store_id)s agent:%(agent)s] "
    "%(name)s: %(message)s"
)

_configured = False


def setup_logging() -> None:
    """Configure the root logger once, overriding any prior basicConfig."""
    global _configured
    if _configured:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    use_json = os.getenv("LOG_FORMAT", "plain").lower() == "json"

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if use_json else logging.Formatter(_PLAIN_FMT))

    root = logging.getLogger()
    root.handlers.clear()  # drop any handlers installed by stray basicConfig calls
    root.addHandler(handler)
    root.setLevel(level)

    # Tame noisy third-party loggers so real signal isn't buried.
    third = os.getenv("LOG_LEVEL_THIRDPARTY", "WARNING").upper()
    for noisy in ("httpx", "httpcore", "urllib3", "sqlalchemy.engine", "asyncio"):
        logging.getLogger(noisy).setLevel(third)
    # Our RequestContextMiddleware already logs one correlated access line per
    # request, so silence uvicorn's own (uncorrelated) access log to avoid dupes.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info(
        "Structured logging configured (format=%s, level=%s)",
        "json" if use_json else "plain", level,
    )


class RequestContextMiddleware:
    """Pure-ASGI middleware: assign a correlation id per request, expose it as a
    contextvar (so downstream logs carry it) and the X-Request-ID response header,
    and emit one access line with status + duration.

    Implemented as raw ASGI (not BaseHTTPMiddleware) so the contextvar reliably
    propagates into the endpoint — BaseHTTPMiddleware runs the endpoint in a
    separate context and would drop it.
    """

    # Skip access logging for these (health checks / static spam).
    _QUIET_PREFIXES = ("/health", "/static", "/favicon")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        rid = headers.get(b"x-request-id", b"").decode() or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status_holder = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if not path.startswith(self._QUIET_PREFIXES):
                dur_ms = (time.perf_counter() - start) * 1000
                logging.getLogger("access").info(
                    "%s %s -> %s (%.0fms)",
                    scope.get("method", "?"), path, status_holder["code"], dur_ms,
                )
            request_id_var.reset(token)

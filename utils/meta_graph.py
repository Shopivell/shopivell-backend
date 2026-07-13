"""Rate-limit-aware Meta Graph API client.

Meta throttles the Graph/Marketing API per app, per business-use-case, and per
ad account. Ignoring the usage headers and blindly retrying throttled calls
*extends* the throttle window and trips Meta's "inconsistent API request volume"
enforcement (a signal that contributes to account/portfolio restrictions).

This wrapper:
- reads the usage headers (X-App-Usage, X-Ad-Account-Usage, X-Business-Use-Case-Usage),
- proactively slows/pauses when usage is high,
- on a rate-limit error, honors estimated_time_to_regain_access and backs off
  exponentially before retrying.

Use graph_request() for any Meta Graph write/read that runs unattended or in bulk.
"""
import asyncio
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Meta rate-limit / throttling error codes (application, ads, and BUC throttles).
RATE_LIMIT_ERROR_CODES = {
    4, 17, 32, 613,
    80000, 80001, 80002, 80003, 80004, 80005, 80006, 80007, 80008, 80009, 80014,
}

# Proactively slow down once any usage metric crosses these percentages.
USAGE_SOFT_LIMIT = 75.0   # ease off
USAGE_HARD_LIMIT = 95.0   # pause until it recovers
MAX_BACKOFF_SECONDS = 300.0


def parse_usage(headers) -> tuple:
    """Return (max_usage_pct, max_regain_seconds) parsed from Meta's usage headers.

    Handles all three header shapes:
      X-App-Usage:              {"call_count":10,"total_cputime":5,"total_time":3}
      X-Ad-Account-Usage:       {"acc_id_util_pct":9.67, ...}
      X-Business-Use-Case-Usage:{"<id>":[{"call_count":..,"estimated_time_to_regain_access":..}]}
    """
    max_pct = 0.0
    max_regain = 0.0

    def _scan(obj):
        nonlocal max_pct, max_regain
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if kl in ("call_count", "total_cputime", "total_time", "acc_id_util_pct") \
                        and isinstance(v, (int, float)):
                    max_pct = max(max_pct, float(v))
                elif kl == "estimated_time_to_regain_access" and isinstance(v, (int, float)):
                    max_regain = max(max_regain, float(v))
                else:
                    _scan(v)
        elif isinstance(obj, list):
            for v in obj:
                _scan(v)

    for name in ("x-app-usage", "x-ad-account-usage", "x-business-use-case-usage"):
        raw = headers.get(name)
        if not raw:
            continue
        try:
            _scan(json.loads(raw))
        except Exception:
            continue
    return max_pct, max_regain


def _error_code(resp: httpx.Response) -> Optional[int]:
    try:
        return resp.json().get("error", {}).get("code")
    except Exception:
        return None


async def graph_request(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    timeout: float = 30.0,
    max_retries: int = 4,
) -> httpx.Response:
    """Perform a Meta Graph API request with usage-aware backoff.

    Returns the final httpx.Response (callers check status_code as before). On a
    rate-limit error it retries up to max_retries times, honoring the regain time.
    """
    backoff = 2.0
    resp: Optional[httpx.Response] = None

    for attempt in range(max_retries + 1):
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, data=data)

        usage_pct, regain = parse_usage(resp.headers)

        if resp.status_code == 200:
            # Proactively cool down so we never *reach* the hard cap.
            if usage_pct >= USAGE_HARD_LIMIT:
                sleep_for = min(MAX_BACKOFF_SECONDS, regain or 60.0)
                logger.warning(f"[MetaGraph] usage {usage_pct:.0f}% — pausing {sleep_for:.0f}s")
                await asyncio.sleep(sleep_for)
            elif usage_pct >= USAGE_SOFT_LIMIT:
                logger.info(f"[MetaGraph] usage {usage_pct:.0f}% — easing off")
                await asyncio.sleep(2.0)
            return resp

        code = _error_code(resp)
        if code in RATE_LIMIT_ERROR_CODES and attempt < max_retries:
            sleep_for = min(MAX_BACKOFF_SECONDS, regain or backoff)
            logger.warning(
                f"[MetaGraph] rate-limited (code {code}); backing off {sleep_for:.0f}s "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(sleep_for)
            backoff *= 2
            continue

        # Non-rate-limit error, or retries exhausted — hand back the response.
        return resp

    return resp

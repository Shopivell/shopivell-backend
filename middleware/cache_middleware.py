# middleware/cache_middleware.py
"""
FastAPI Caching Middleware

This middleware provides automatic response caching for GET requests.
It caches responses based on the request path and query parameters.
"""

import hashlib
import json
from typing import Optional, List, Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from utils.cache import cache, CacheConfig


class CacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware that caches GET request responses.

    Configuration:
        - exclude_paths: Paths that should never be cached
        - include_paths: If set, only these paths are cached
        - default_ttl: Default TTL for cached responses
        - ttl_rules: Dictionary mapping path patterns to TTLs

    Usage in main.py:
        from middleware.cache_middleware import CacheMiddleware

        app.add_middleware(
            CacheMiddleware,
            exclude_paths=["/v1/auth", "/v1/payment/webhook"],
            default_ttl=60
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        exclude_paths: Optional[List[str]] = None,
        include_paths: Optional[List[str]] = None,
        default_ttl: int = CacheConfig.TTL_SHORT,
        ttl_rules: Optional[dict] = None
    ):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/v1/auth",
            "/v1/payment/webhook",
            "/v1/whatsapp/webhook",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
        self.include_paths = include_paths
        self.default_ttl = default_ttl
        self.ttl_rules = ttl_rules or {
            "/v1/products": CacheConfig.TTL_MEDIUM,
            "/v1/stores": CacheConfig.TTL_MEDIUM,
            "/v1/analytics": CacheConfig.TTL_SHORT,
            "/v1/content": CacheConfig.TTL_LONG,
            "/v1/assets": CacheConfig.TTL_LONG,
        }

    def _should_cache(self, request: Request) -> bool:
        """Determine if request should be cached"""
        # Only cache GET requests
        if request.method != "GET":
            return False

        path = request.url.path

        # Check exclusions
        for excluded in self.exclude_paths:
            if path.startswith(excluded):
                return False

        # Check inclusions if specified
        if self.include_paths:
            return any(path.startswith(inc) for inc in self.include_paths)

        return True

    def _get_ttl(self, path: str) -> int:
        """Get TTL for a given path"""
        for pattern, ttl in self.ttl_rules.items():
            if path.startswith(pattern):
                return ttl
        return self.default_ttl

    def _generate_cache_key(self, request: Request) -> str:
        """Generate a unique cache key for the request"""
        # Include path and sorted query params
        key_parts = [request.url.path]

        if request.query_params:
            sorted_params = sorted(request.query_params.items())
            key_parts.append(str(sorted_params))

        # Include authorization header hash for user-specific caching
        auth_header = request.headers.get("authorization", "")
        if auth_header:
            auth_hash = hashlib.md5(auth_header.encode()).hexdigest()[:8]
            key_parts.append(f"user:{auth_hash}")

        key_string = "|".join(key_parts)
        return f"api:{hashlib.md5(key_string.encode()).hexdigest()}"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with caching"""
        # Skip caching if not applicable
        if not self._should_cache(request) or not cache.is_connected:
            return await call_next(request)

        cache_key = self._generate_cache_key(request)

        # Try to get cached response
        cached_response = cache.get(cache_key)
        if cached_response:
            return JSONResponse(
                content=cached_response.get("body"),
                status_code=cached_response.get("status_code", 200),
                headers={
                    "X-Cache": "HIT",
                    "Content-Type": "application/json"
                }
            )

        # Call the actual endpoint
        response = await call_next(request)

        # Only cache successful JSON responses
        if (
            response.status_code == 200
            and response.headers.get("content-type", "").startswith("application/json")
        ):
            # Read response body
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            try:
                body_json = json.loads(body.decode())
                ttl = self._get_ttl(request.url.path)

                # Cache the response
                cache.set(
                    cache_key,
                    {"body": body_json, "status_code": response.status_code},
                    ttl
                )

                # Return new response with cache header
                return JSONResponse(
                    content=body_json,
                    status_code=response.status_code,
                    headers={"X-Cache": "MISS"}
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Return original response if can't parse JSON
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type
                )

        return response


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds Cache-Control headers to responses.

    This helps with browser and CDN caching.
    """

    def __init__(
        self,
        app: ASGIApp,
        default_max_age: int = 0,
        path_rules: Optional[dict] = None
    ):
        super().__init__(app)
        self.default_max_age = default_max_age
        self.path_rules = path_rules or {
            "/uploads/": 86400,  # 1 day for uploaded assets
            "/v1/content/templates": 3600,  # 1 hour for templates
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only add cache headers to successful GET requests
        if request.method == "GET" and response.status_code == 200:
            path = request.url.path
            max_age = self.default_max_age

            for pattern, age in self.path_rules.items():
                if path.startswith(pattern):
                    max_age = age
                    break

            if max_age > 0:
                response.headers["Cache-Control"] = f"public, max-age={max_age}"
            else:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

        return response

# utils/cache.py
"""
Redis Caching Utility for Shopivell Backend

This module provides Redis-based caching functionality with:
- Connection management with fallback for when Redis is unavailable
- Decorator-based caching for functions and API endpoints
- Cache invalidation patterns for data consistency
- TTL management for different data types
"""

import os
import json
import hashlib
import functools
from typing import Optional, Any, Callable, Union, List
from datetime import timedelta
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Try to import redis, handle if not installed
try:
    import redis
    from redis.exceptions import ConnectionError, TimeoutError
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis package not installed. Caching will be disabled.")


class CacheConfig:
    """Cache configuration with TTL presets for different data types"""

    # TTL Presets (in seconds)
    TTL_SHORT = 60  # 1 minute - for rapidly changing data
    TTL_MEDIUM = 300  # 5 minutes - for moderately changing data
    TTL_LONG = 3600  # 1 hour - for slowly changing data
    TTL_DAY = 86400  # 24 hours - for rarely changing data

    # Cache key prefixes for different modules
    PREFIXES = {
        "products": "prod:",
        "stores": "store:",
        "orders": "order:",
        "users": "user:",
        "analytics": "analytics:",
        "campaigns": "campaign:",
        "assets": "asset:",
        "content": "content:",
        "settings": "settings:",
    }


class RedisCache:
    """
    Redis cache manager with connection pooling and fallback handling.

    Usage:
        cache = RedisCache()

        # Set a value
        cache.set("key", {"data": "value"}, ttl=300)

        # Get a value
        data = cache.get("key")

        # Delete a key
        cache.delete("key")

        # Invalidate by pattern
        cache.invalidate_pattern("prod:store_123:*")
    """

    _instance = None
    _client = None
    _connected = False

    def __new__(cls):
        """Singleton pattern to ensure single Redis connection pool"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize Redis connection if not already connected"""
        if not self._connected and REDIS_AVAILABLE:
            self._connect()

    def _connect(self):
        """Establish Redis connection with environment configuration"""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_db = int(os.getenv("REDIS_DB", "0"))
            redis_password = os.getenv("REDIS_PASSWORD", None)

            # Use URL if provided, otherwise use individual settings
            if redis_url and redis_url != "redis://localhost:6379/0":
                self._client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
            else:
                self._client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )

            # Test connection
            self._client.ping()
            self._connected = True
            logger.info(f"Redis connected successfully to {redis_host}:{redis_port}")

        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Caching disabled.")
            self._connected = False
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected and available"""
        if not self._connected or not self._client:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            self._connected = False
            return False

    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/error
        """
        if not self.is_connected:
            return None

        try:
            value = self._client.get(key)
            if value:
                return json.loads(value)
            return None
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis get error: {e}")
            return None
        except json.JSONDecodeError:
            return value  # Return raw value if not JSON

    def set(
        self,
        key: str,
        value: Any,
        ttl: int = CacheConfig.TTL_MEDIUM
    ) -> bool:
        """
        Set a value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected:
            return False

        try:
            serialized = json.dumps(value, default=str)
            self._client.setex(key, ttl, serialized)
            return True
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis set error: {e}")
            return False
        except (TypeError, json.JSONEncodeError) as e:
            logger.error(f"JSON serialization error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """
        Delete a key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if deleted, False otherwise
        """
        if not self.is_connected:
            return False

        try:
            self._client.delete(key)
            return True
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis delete error: {e}")
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., "prod:store_123:*")

        Returns:
            Number of keys deleted
        """
        if not self.is_connected:
            return 0

        try:
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis invalidate error: {e}")
            return 0

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: int = CacheConfig.TTL_MEDIUM
    ) -> Any:
        """
        Get from cache or compute and cache the value.

        Args:
            key: Cache key
            factory: Function to compute value if not cached
            ttl: Time to live in seconds

        Returns:
            Cached or computed value
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        value = factory()
        self.set(key, value, ttl)
        return value

    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """
        Increment a counter in cache.

        Args:
            key: Counter key
            amount: Amount to increment by

        Returns:
            New counter value or None if error
        """
        if not self.is_connected:
            return None

        try:
            return self._client.incrby(key, amount)
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis increment error: {e}")
            return None

    def get_many(self, keys: List[str]) -> dict:
        """
        Get multiple values at once.

        Args:
            keys: List of cache keys

        Returns:
            Dictionary of key -> value pairs
        """
        if not self.is_connected or not keys:
            return {}

        try:
            values = self._client.mget(keys)
            result = {}
            for key, value in zip(keys, values):
                if value:
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = value
            return result
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis mget error: {e}")
            return {}

    def clear_all(self) -> bool:
        """
        Clear all keys in the current database.
        WARNING: Use with caution!

        Returns:
            True if successful
        """
        if not self.is_connected:
            return False

        try:
            self._client.flushdb()
            return True
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis flush error: {e}")
            return False


# Global cache instance
cache = RedisCache()


def generate_cache_key(*args, prefix: str = "", **kwargs) -> str:
    """
    Generate a consistent cache key from arguments.

    Args:
        *args: Positional arguments to include in key
        prefix: Optional prefix for the key
        **kwargs: Keyword arguments to include in key

    Returns:
        MD5 hash-based cache key
    """
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_string = ":".join(key_parts)
    key_hash = hashlib.md5(key_string.encode()).hexdigest()[:12]

    if prefix:
        return f"{prefix}{key_hash}"
    return key_hash


def cached(
    ttl: int = CacheConfig.TTL_MEDIUM,
    prefix: str = "",
    key_builder: Optional[Callable] = None
):
    """
    Decorator to cache function results.

    Args:
        ttl: Time to live in seconds
        prefix: Cache key prefix
        key_builder: Custom function to build cache key from args/kwargs

    Example:
        @cached(ttl=300, prefix="prod:")
        def get_product(product_id: str):
            return db.query(Product).filter(Product.id == product_id).first()
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = generate_cache_key(
                    func.__name__, *args, prefix=prefix, **kwargs
                )

            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_value

            # Compute and cache
            logger.debug(f"Cache MISS: {cache_key}")
            result = func(*args, **kwargs)

            if result is not None:
                cache.set(cache_key, result, ttl)

            return result

        # Add cache control methods to the wrapper
        wrapper.cache_clear = lambda pattern=None: cache.invalidate_pattern(
            pattern or f"{prefix}*"
        )
        wrapper.cache_key = lambda *a, **kw: generate_cache_key(
            func.__name__, *a, prefix=prefix, **kw
        )

        return wrapper
    return decorator


def cached_async(
    ttl: int = CacheConfig.TTL_MEDIUM,
    prefix: str = "",
    key_builder: Optional[Callable] = None
):
    """
    Decorator to cache async function results.

    Args:
        ttl: Time to live in seconds
        prefix: Cache key prefix
        key_builder: Custom function to build cache key from args/kwargs

    Example:
        @cached_async(ttl=300, prefix="store:")
        async def get_store(store_id: str):
            return await db.get(Store, store_id)
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = generate_cache_key(
                    func.__name__, *args, prefix=prefix, **kwargs
                )

            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_value

            # Compute and cache
            logger.debug(f"Cache MISS: {cache_key}")
            result = await func(*args, **kwargs)

            if result is not None:
                cache.set(cache_key, result, ttl)

            return result

        # Add cache control methods
        wrapper.cache_clear = lambda pattern=None: cache.invalidate_pattern(
            pattern or f"{prefix}*"
        )

        return wrapper
    return decorator


class CacheInvalidator:
    """
    Helper class for cache invalidation patterns.

    Usage:
        invalidator = CacheInvalidator()

        # After updating a product
        invalidator.invalidate_product(product_id, store_id)

        # After updating store settings
        invalidator.invalidate_store(store_id)
    """

    def __init__(self, cache_instance: RedisCache = None):
        self._cache = cache_instance or cache

    def invalidate_product(self, product_id: str, store_id: str = None):
        """Invalidate product-related caches"""
        self._cache.delete(f"prod:{product_id}")
        self._cache.invalidate_pattern(f"prod:*{product_id}*")
        if store_id:
            self._cache.invalidate_pattern(f"prod:store_{store_id}:*")

    def invalidate_store(self, store_id: str):
        """Invalidate store-related caches"""
        self._cache.invalidate_pattern(f"store:{store_id}:*")
        self._cache.invalidate_pattern(f"prod:store_{store_id}:*")
        self._cache.invalidate_pattern(f"order:store_{store_id}:*")

    def invalidate_user(self, user_id: str):
        """Invalidate user-related caches"""
        self._cache.invalidate_pattern(f"user:{user_id}:*")

    def invalidate_order(self, order_id: str, store_id: str = None):
        """Invalidate order-related caches"""
        self._cache.delete(f"order:{order_id}")
        if store_id:
            self._cache.invalidate_pattern(f"order:store_{store_id}:*")
            self._cache.invalidate_pattern(f"analytics:store_{store_id}:*")

    def invalidate_analytics(self, store_id: str):
        """Invalidate analytics caches"""
        self._cache.invalidate_pattern(f"analytics:store_{store_id}:*")

    def invalidate_campaign(self, campaign_id: str, store_id: str = None):
        """Invalidate campaign-related caches"""
        self._cache.delete(f"campaign:{campaign_id}")
        if store_id:
            self._cache.invalidate_pattern(f"campaign:store_{store_id}:*")


# Global invalidator instance
cache_invalidator = CacheInvalidator()


# Health check function
def check_redis_health() -> dict:
    """
    Check Redis connection health.

    Returns:
        Health status dictionary
    """
    if not REDIS_AVAILABLE:
        return {
            "status": "unavailable",
            "message": "Redis package not installed",
            "connected": False
        }

    if cache.is_connected:
        try:
            info = cache._client.info("server")
            return {
                "status": "healthy",
                "connected": True,
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0)
            }
        except Exception as e:
            return {
                "status": "error",
                "connected": False,
                "message": str(e)
            }

    return {
        "status": "disconnected",
        "connected": False,
        "message": "Redis not connected"
    }

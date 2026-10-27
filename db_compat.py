"""
Cross-database compatibility layer for SQLAlchemy types.
Provides PG_UUID, Vector, and ARRAY that work on both PostgreSQL and SQLite.
"""
import uuid as _uuid
from sqlalchemy import String, Text, JSON, TypeDecorator

from database import USE_SQLITE

if USE_SQLITE:
    class _UUIDType(TypeDecorator):
        """UUID type that stores as String(36) on SQLite."""
        impl = String(36)
        cache_ok = True

        def __init__(self, as_uuid=True, *args, **kwargs):
            super().__init__()
            self.as_uuid = as_uuid

        def process_bind_param(self, value, dialect):
            if value is not None:
                return str(value)
            return value

        def process_result_value(self, value, dialect):
            if value is not None and self.as_uuid:
                return _uuid.UUID(value)
            return value

    PG_UUID = _UUIDType
    UUID = _UUIDType

    def Vector(dim):
        """Placeholder for pgvector Vector type - stores as Text on SQLite."""
        return Text()

    class _ArrayType(TypeDecorator):
        """ARRAY type that stores as JSON on SQLite."""
        impl = JSON
        cache_ok = True

        def __init__(self, item_type=None, *args, **kwargs):
            super().__init__()

    ARRAY = _ArrayType

else:
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    from sqlalchemy.dialects.postgresql import UUID
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import ARRAY

# dependencies.py
"""
FastAPI Dependencies for Shopivell Backend

This module provides common dependencies used across routers.
"""

from fastapi.security import OAuth2PasswordBearer
from utils.jwt_auth import (
    get_current_user,
    get_current_user_optional,
    get_current_user_with_blacklist,
    require_roles,
    require_store_access,
    CurrentUser,
    jwt_auth
)

# OAuth2 scheme for Swagger UI authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/api/auth/login", auto_error=False)

# Re-export commonly used dependencies
__all__ = [
    "get_current_user",
    "get_current_user_optional",
    "get_current_user_with_blacklist",
    "require_roles",
    "require_store_access",
    "CurrentUser",
    "jwt_auth",
    "oauth2_scheme"
]

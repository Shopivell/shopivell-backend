# utils/jwt_auth.py
"""
JWT Authentication Utility for Shopivell Backend

This module provides comprehensive JWT-based authentication with:
- Token generation and validation
- Refresh token support
- Role-based access control
- Token blacklisting (optional with Redis)
"""

import os
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()


class JWTConfig:
    """JWT Configuration"""
    SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-change-in-production")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))  # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))  # 7 days


if (os.getenv('USE_SQLITE', 'true').lower() != 'true'
        and JWTConfig.SECRET_KEY == 'your-super-secret-key-change-in-production'):
    raise RuntimeError('JWT_SECRET_KEY must be configured for PostgreSQL deployments')


class TokenPayload(BaseModel):
    """Token payload structure"""
    sub: str  # user_id
    email: str
    role: str
    store_id: Optional[str] = None
    agency_id: Optional[str] = None
    exp: datetime
    iat: datetime
    type: str = "access"  # "access" or "refresh"


class TokenResponse(BaseModel):
    """Token response structure"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class JWTAuth:
    """
    JWT Authentication Handler

    Usage:
        jwt_auth = JWTAuth()

        # Create tokens
        tokens = jwt_auth.create_tokens(user_id, email, role, store_id)

        # Verify token
        payload = jwt_auth.verify_token(token)

        # Decode without verification (for debugging)
        payload = jwt_auth.decode_token_unsafe(token)
    """

    def __init__(self):
        self.secret_key = JWTConfig.SECRET_KEY
        self.algorithm = JWTConfig.ALGORITHM
        self.access_token_expire = timedelta(minutes=JWTConfig.ACCESS_TOKEN_EXPIRE_MINUTES)
        self.refresh_token_expire = timedelta(days=JWTConfig.REFRESH_TOKEN_EXPIRE_DAYS)

        # Warn if using default secret key
        if self.secret_key == "your-super-secret-key-change-in-production":
            print("WARNING: Using default JWT secret key. Set JWT_SECRET_KEY in .env for production!")

    def create_access_token(
        self,
        user_id: str,
        email: str,
        role: str,
        store_id: Optional[str] = None,
        agency_id: Optional[str] = None,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a JWT access token.

        Args:
            user_id: User's unique identifier
            email: User's email
            role: User's role (e.g., "OWNER", "ADMIN", "STAFF")
            store_id: Optional store ID
            agency_id: Optional agency ID
            additional_claims: Optional additional claims to include

        Returns:
            JWT access token string
        """
        now = datetime.utcnow()
        expire = now + self.access_token_expire

        payload = {
            "sub": str(user_id),
            "email": email,
            "role": role,
            "store_id": str(store_id) if store_id else None,
            "agency_id": str(agency_id) if agency_id else None,
            "exp": expire,
            "iat": now,
            "type": "access"
        }

        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self,
        user_id: str,
        email: str
    ) -> str:
        """
        Create a JWT refresh token.

        Args:
            user_id: User's unique identifier
            email: User's email

        Returns:
            JWT refresh token string
        """
        now = datetime.utcnow()
        expire = now + self.refresh_token_expire

        payload = {
            "sub": str(user_id),
            "email": email,
            "exp": expire,
            "iat": now,
            "type": "refresh"
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_tokens(
        self,
        user_id: str,
        email: str,
        role: str,
        store_id: Optional[str] = None,
        agency_id: Optional[str] = None
    ) -> TokenResponse:
        """
        Create both access and refresh tokens.

        Args:
            user_id: User's unique identifier
            email: User's email
            role: User's role
            store_id: Optional store ID
            agency_id: Optional agency ID

        Returns:
            TokenResponse with both tokens
        """
        access_token = self.create_access_token(
            user_id=user_id,
            email=email,
            role=role,
            store_id=store_id,
            agency_id=agency_id
        )

        refresh_token = self.create_refresh_token(
            user_id=user_id,
            email=email
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=JWTConfig.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )

    def verify_token(self, token: str, token_type: str = "access") -> Dict[str, Any]:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token string
            token_type: Expected token type ("access" or "refresh")

        Returns:
            Decoded token payload

        Raises:
            HTTPException: If token is invalid, expired, or wrong type
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Check token type
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type. Expected {token_type}.",
                    headers={"WWW-Authenticate": "Bearer"}
                )

            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"}
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"}
            )

    def decode_token_unsafe(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode a token without verification (for debugging only).

        Args:
            token: JWT token string

        Returns:
            Decoded payload or None if invalid
        """
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            return None

    def refresh_access_token(self, refresh_token: str) -> str:
        """
        Create a new access token from a valid refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New access token

        Note: This requires fetching user data from DB to get current role/store
        """
        payload = self.verify_token(refresh_token, token_type="refresh")

        # Create new access token (caller should fetch user data for role/store)
        return self.create_access_token(
            user_id=payload["sub"],
            email=payload["email"],
            role="OWNER",  # Default - should be fetched from DB
            store_id=None,  # Should be fetched from DB
            agency_id=None  # Should be fetched from DB
        )


    def create_unsubscribe_token(self, user_id: str, email: str) -> str:
        """
        Create a long-lived signed token used in email unsubscribe links.

        The token is not tied to a login session, so recipients can unsubscribe
        without authenticating. It carries type="unsubscribe" so it can never be
        used as an access token.
        """
        now = datetime.utcnow()
        payload = {
            "sub": str(user_id),
            "email": email,
            "iat": now,
            "exp": now + timedelta(days=3650),  # effectively non-expiring
            "type": "unsubscribe",
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_unsubscribe_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify an unsubscribe token. Returns the payload, or None if invalid."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except jwt.InvalidTokenError:
            return None
        if payload.get("type") != "unsubscribe":
            return None
        return payload


# Global JWT auth instance
jwt_auth = JWTAuth()


# FastAPI Security
security = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """Current authenticated user model"""
    id: str
    email: str
    role: str
    store_id: Optional[str] = None
    agency_id: Optional[str] = None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> CurrentUser:
    """
    FastAPI dependency to get the current authenticated user.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(current_user: CurrentUser = Depends(get_current_user)):
            return {"user_id": current_user.id}
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    payload = jwt_auth.verify_token(token, token_type="access")

    # Store memberships are revocable; do not rely solely on a JWT that may
    # have been issued before the owner disabled access.
    if str(payload.get('role', '')).lower() == 'staff':
        from database import SessionLocal
        from modules.users.models import User, StoreMember
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == UUID(payload['sub']), User.is_active.is_(True)).first()
            member = (db.query(StoreMember).filter(
                StoreMember.user_id == UUID(payload['sub']),
                StoreMember.store_id == UUID(payload['store_id']),
                StoreMember.is_active.is_(True)).first() if payload.get('store_id') else None)
            if not user or not member:
                raise HTTPException(status_code=403, detail='Store access has been removed')
        finally:
            db.close()

    return CurrentUser(
        id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        store_id=payload.get("store_id"),
        agency_id=payload.get("agency_id")
    )


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[CurrentUser]:
    """
    FastAPI dependency to optionally get the current user.
    Returns None if not authenticated instead of raising an exception.

    Usage:
        @router.get("/public-or-private")
        async def endpoint(current_user: Optional[CurrentUser] = Depends(get_current_user_optional)):
            if current_user:
                return {"message": "Hello, authenticated user!"}
            return {"message": "Hello, guest!"}
    """
    if not credentials:
        return None

    try:
        token = credentials.credentials
        payload = jwt_auth.verify_token(token, token_type="access")
        return CurrentUser(
            id=payload["sub"],
            email=payload["email"],
            role=payload["role"],
            store_id=payload.get("store_id"),
            agency_id=payload.get("agency_id")
        )
    except HTTPException:
        return None


def require_roles(allowed_roles: List[str]):
    """
    Dependency factory for role-based access control.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            current_user: CurrentUser = Depends(require_roles(["ADMIN", "OWNER"]))
        ):
            return {"message": "Welcome, admin!"}
    """
    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user)
    ) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {allowed_roles}"
            )
        return current_user

    return role_checker


def require_store_access(
    current_user: CurrentUser = Depends(get_current_user)
) -> CurrentUser:
    """
    Dependency to ensure user has an associated store.

    Usage:
        @router.get("/store-endpoint")
        async def store_endpoint(
            current_user: CurrentUser = Depends(require_store_access)
        ):
            return {"store_id": current_user.store_id}
    """
    if not current_user.store_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Store access required. Please complete store setup."
        )
    return current_user


# Token blacklist (requires Redis)
class TokenBlacklist:
    """
    Token blacklist for logout functionality.
    Uses Redis for distributed blacklist.
    """

    def __init__(self):
        self._local_blacklist: set = set()  # Fallback if Redis unavailable
        self._redis_available = False

        try:
            from utils.cache import cache
            self._cache = cache
            self._redis_available = cache.is_connected
        except ImportError:
            self._cache = None

    def blacklist_token(self, token: str, ttl: int = 3600) -> bool:
        """
        Add a token to the blacklist.

        Args:
            token: JWT token to blacklist
            ttl: Time to live in seconds (should match token expiration)

        Returns:
            True if successful
        """
        if self._redis_available and self._cache:
            return self._cache.set(f"blacklist:{token}", "1", ttl)
        else:
            self._local_blacklist.add(token)
            return True

    def is_blacklisted(self, token: str) -> bool:
        """
        Check if a token is blacklisted.

        Args:
            token: JWT token to check

        Returns:
            True if blacklisted
        """
        if self._redis_available and self._cache:
            return self._cache.get(f"blacklist:{token}") is not None
        else:
            return token in self._local_blacklist

    def clear_local(self):
        """Clear the local blacklist (for testing)"""
        self._local_blacklist.clear()


# Global blacklist instance
token_blacklist = TokenBlacklist()


async def get_current_user_with_blacklist(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> CurrentUser:
    """
    Get current user with blacklist check.
    Use this for endpoints where logout should immediately invalidate tokens.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials

    # Check blacklist
    if token_blacklist.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = jwt_auth.verify_token(token, token_type="access")

    return CurrentUser(
        id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        store_id=payload.get("store_id"),
        agency_id=payload.get("agency_id")
    )


# ============ Convenience Functions ============
# These wrapper functions allow importing directly without using the class

import bcrypt


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    store_id: Optional[str] = None,
    agency_id: Optional[str] = None
) -> str:
    """Create an access token."""
    return jwt_auth.create_access_token(user_id, email, role, store_id, agency_id)


def create_refresh_token(user_id: str, email: str) -> str:
    """Create a refresh token."""
    return jwt_auth.create_refresh_token(user_id, email)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a token."""
    try:
        return jwt_auth.verify_token(token, token_type="access")
    except HTTPException:
        return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

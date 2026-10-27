# modules/admin/models.py
"""
Admin models for the admin dashboard.
"""

import uuid
from datetime import datetime, timedelta
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, JSON
from db_compat import UUID
from sqlalchemy.orm import relationship
import enum

from database import Base


class AdminRole(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"


class InvitationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AuditAction(str, enum.Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SUSPEND = "suspend"
    ACTIVATE = "activate"
    INVITE = "invite"
    VIEW = "view"


class AdminUser(Base):
    """
    Admin user model for platform administrators.
    Links to the main User model for authentication.
    """
    __tablename__ = "admin_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    role = Column(SQLEnum(AdminRole), default=AdminRole.ADMIN, nullable=False)
    permissions = Column(JSON, default=dict)
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", backref="admin_profile")
    invited_by = relationship("AdminUser", remote_side=[id], backref="invited_admins")


class AdminInvitation(Base):
    """
    Invitation model for inviting new admin users.
    """
    __tablename__ = "admin_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    role = Column(SQLEnum(AdminRole), default=AdminRole.ADMIN, nullable=False)
    invitation_code = Column(String(64), nullable=False, unique=True, index=True)
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    status = Column(SQLEnum(InvitationStatus), default=InvitationStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=7))
    accepted_at = Column(DateTime, nullable=True)

    # Relationships
    invited_by = relationship("AdminUser", backref="sent_invitations")

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class AuditLog(Base):
    """
    Audit log for tracking admin actions.
    """
    __tablename__ = "admin_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_user_id = Column(UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    action = Column(SQLEnum(AuditAction), nullable=False)
    resource_type = Column(String(50), nullable=False)  # agency, store, user, payment, etc.
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    details = Column(JSON, default=dict)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    admin_user = relationship("AdminUser", backref="audit_logs")

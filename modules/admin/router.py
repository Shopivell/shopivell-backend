# modules/admin/router.py
"""
Admin API router with all admin endpoints.
"""

import uuid
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, String

from database import get_db
from utils.Verification_Codes_Services import VerificationCodeService
from utils.jwt_auth import (
    create_access_token,
    create_refresh_token,
    verify_password,
    get_password_hash,
    decode_token,
)
from modules.users.models import User
from modules.stores.models import Store
from modules.agency.models import Agency
from modules.campaigns.models import UrlCampaign
from modules.assets.models import Asset
from modules.payment.models import PaymentTransaction
from modules.feedback.models import Feedback

from .models import AdminUser, AdminInvitation, AuditLog, AdminRole, InvitationStatus, AuditAction
from .schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    AdminUserResponse,
    AdminUserListResponse,
    InviteAdminRequest,
    InviteAdminResponse,
    AcceptInvitationRequest,
    InvitationVerifyResponse,
    DashboardOverview,
    RevenueDataPoint,
    AgencyListItem,
    AgencyListResponse,
    UpdateAgencyStatusRequest,
    StoreListItem,
    StoreListResponse,
    CampaignListItem,
    CampaignListResponse,
    AssetListItem,
    AssetListResponse,
    UserListItem,
    UserListResponse,
    PaymentListItem,
    PaymentListResponse,
    IncomeStats,
    FeedbackListItem,
    FeedbackListResponse,
    RespondToFeedbackRequest,
)

admin_router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ============ Helper Functions ============

def get_current_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    """Get the current authenticated admin user."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.split(" ")[1]
    payload = decode_token(token)

    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload["sub"]
    admin_user = db.query(AdminUser).filter(
        AdminUser.user_id == user_id,
        AdminUser.is_active == True
    ).first()

    if not admin_user:
        raise HTTPException(status_code=403, detail="Not an admin user")

    return admin_user


def log_action(
    db: Session,
    admin_user: AdminUser,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[uuid.UUID] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None
):
    """Log an admin action to the audit log."""
    log = AuditLog(
        admin_user_id=admin_user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        ip_address=ip_address
    )
    db.add(log)
    db.commit()


def send_admin_invitation_email(email: str, invitation_code: str, inviter_name: str = "Shopivell Admin") -> bool:
    """Send a beautiful admin invitation email."""
    invite_url = f"https://admin.shopivell.com/invite/{invitation_code}"

    subject = "You're Invited to Join Shopivell Admin Dashboard"
    body = f"""
Hello,

You have been invited by {inviter_name} to join the Shopivell Admin Dashboard as an administrator.

As an admin, you will be able to:
- Monitor all agencies and stores on the platform
- View and manage campaigns and advertisements
- Track platform revenue and payments
- Manage admin users and permissions
- Respond to user feedback

To accept this invitation and set up your admin account, please click the link below:

ACCEPT INVITATION: {invite_url}

This invitation will expire in 7 days.

If you did not expect this invitation, you can safely ignore this email.

Best regards,
The Shopivell Team
    """

    return VerificationCodeService.send_email(email, subject, body.strip())


# ============ Authentication Endpoints ============

@admin_router.post("/auth/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest, db: Session = Depends(get_db)):
    """Admin login endpoint."""
    import traceback
    try:
        # Find user by email
        user = db.query(User).filter(User.email == request.email).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Verify password
        if not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Check if user is an admin
        admin_user = db.query(AdminUser).filter(
            AdminUser.user_id == user.id,
            AdminUser.is_active == True
        ).first()

        if not admin_user:
            raise HTTPException(status_code=403, detail="Not authorized as admin")

        # Update last login
        admin_user.last_login_at = datetime.utcnow()
        db.commit()

        # Create tokens
        access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=admin_user.role.value
        )
        refresh_token = create_refresh_token(user_id=str(user.id), email=user.email)

        return AdminLoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=AdminUserResponse(
                id=admin_user.id,
                email=user.email,
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                role=admin_user.role.value,
                is_active=admin_user.is_active,
                created_at=admin_user.created_at,
                last_login_at=admin_user.last_login_at
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Admin login error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.post("/auth/refresh", response_model=RefreshTokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Refresh access token."""
    payload = decode_token(request.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload["sub"]
    user = db.query(User).filter(User.id == user_id).first()
    admin_user = db.query(AdminUser).filter(
        AdminUser.user_id == user_id,
        AdminUser.is_active == True
    ).first()

    if not user or not admin_user:
        raise HTTPException(status_code=401, detail="User not found")

    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=admin_user.role.value
    )

    return RefreshTokenResponse(access_token=access_token)


@admin_router.get("/auth/me", response_model=AdminUserResponse)
async def get_current_admin_user(
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get current admin user info."""
    user = db.query(User).filter(User.id == admin.user_id).first()
    return AdminUserResponse(
        id=admin.id,
        email=user.email,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        role=admin.role.value,
        is_active=admin.is_active,
        created_at=admin.created_at,
        last_login_at=admin.last_login_at
    )


# ============ Dashboard Endpoints ============

@admin_router.get("/dashboard/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get dashboard overview metrics."""
    # Count agencies (check both cases for status)
    total_agencies = db.query(func.count(Agency.id)).scalar() or 0
    active_agencies = db.query(func.count(Agency.id)).filter(
        func.upper(Agency.status) == "ACTIVE"
    ).scalar() or 0

    # Count stores
    total_stores = db.query(func.count(Store.id)).scalar() or 0

    # Count users
    total_users = db.query(func.count(User.id)).scalar() or 0

    # Count active campaigns (check both cases)
    active_campaigns = db.query(func.count(UrlCampaign.id)).filter(
        func.upper(UrlCampaign.status) == "ACTIVE"
    ).scalar() or 0

    # Calculate revenue (check both cases for status)
    total_revenue = db.query(func.sum(PaymentTransaction.amount)).filter(
        func.upper(func.cast(PaymentTransaction.status, String)) == "COMPLETED"
    ).scalar() or 0

    # New signups today
    today = datetime.utcnow().date()
    new_signups_today = db.query(func.count(User.id)).filter(
        func.date(User.created_at) == today
    ).scalar() or 0

    # Revenue growth (mock for now)
    revenue_growth = 12.5

    return DashboardOverview(
        total_agencies=total_agencies,
        total_stores=total_stores,
        total_users=total_users,
        total_revenue=float(total_revenue),
        active_campaigns=active_campaigns,
        active_agencies=active_agencies,
        new_signups_today=new_signups_today,
        revenue_growth=revenue_growth
    )


@admin_router.get("/dashboard/revenue")
async def get_revenue_data(
    days: int = Query(30, ge=7, le=365),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get revenue data for the last N days."""
    data = []
    today = datetime.utcnow().date()

    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)
        revenue = db.query(func.sum(PaymentTransaction.amount)).filter(
            func.date(PaymentTransaction.created_at) == date,
            func.upper(func.cast(PaymentTransaction.status, String)) == "COMPLETED"
        ).scalar() or 0

        data.append({
            "date": date.strftime("%b %d"),
            "revenue": float(revenue)
        })

    return data


# ============ Agency Endpoints ============

@admin_router.get("/agencies", response_model=AgencyListResponse)
async def list_agencies(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all agencies with pagination."""
    query = db.query(Agency)

    if status:
        query = query.filter(Agency.status == status)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    agencies = query.order_by(Agency.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for agency in agencies:
        owner = db.query(User).filter(User.id == agency.owner_id).first()
        stores_count = db.query(func.count(Store.id)).filter(Store.agency_id == agency.id).scalar() or 0

        items.append(AgencyListItem(
            id=agency.id,
            name=agency.name,
            owner_name=f"{owner.first_name or ''} {owner.last_name or ''}".strip() if owner else "Unknown",
            owner_email=owner.email if owner else "Unknown",
            stores_count=stores_count,
            status=agency.status,
            total_revenue=0,  # TODO: Calculate from payments
            created_at=agency.created_at
        ))

    return AgencyListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@admin_router.put("/agencies/{agency_id}/status")
async def update_agency_status(
    agency_id: uuid.UUID,
    request: UpdateAgencyStatusRequest,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update agency status (activate/suspend)."""
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    agency.status = request.status
    db.commit()

    log_action(db, admin, AuditAction.UPDATE, "agency", agency_id, {"status": request.status})

    return {"message": f"Agency status updated to {request.status}"}


# ============ Store Endpoints ============

@admin_router.get("/stores", response_model=StoreListResponse)
async def list_stores(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all stores with pagination."""
    query = db.query(Store)
    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    stores = query.order_by(Store.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for store in stores:
        owner = db.query(User).filter(User.id == store.owner_id).first()
        agency = db.query(Agency).filter(Agency.id == store.agency_id).first() if store.agency_id else None
        campaigns_count = db.query(func.count(UrlCampaign.id)).filter(UrlCampaign.store_id == store.id).scalar() or 0

        items.append(StoreListItem(
            id=store.id,
            store_name=store.store_name,
            agency_name=agency.name if agency else None,
            owner_email=owner.email if owner else "Unknown",
            products_count=0,  # TODO: Add products count
            campaigns_count=campaigns_count,
            status="active",
            created_at=store.created_at
        ))

    return StoreListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# ============ Campaign Endpoints ============

@admin_router.get("/campaigns", response_model=CampaignListResponse)
async def list_campaigns(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all campaigns with pagination."""
    query = db.query(UrlCampaign)

    if status:
        query = query.filter(UrlCampaign.status == status)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    campaigns = query.order_by(UrlCampaign.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for campaign in campaigns:
        store = db.query(Store).filter(Store.id == campaign.store_id).first()

        items.append(CampaignListItem(
            id=campaign.id,
            name=campaign.name,
            store_name=store.store_name if store else "Unknown",
            platform="facebook",  # TODO: Get from campaign
            status=campaign.status,
            budget=float(campaign.total_budget or 0),
            spent=0,  # TODO: Calculate from insights
            impressions=0,
            clicks=0,
            conversions=0,
            created_at=campaign.created_at
        ))

    return CampaignListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@admin_router.get("/campaigns/running")
async def get_running_campaigns(
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get currently running campaigns."""
    campaigns = db.query(UrlCampaign).filter(func.upper(UrlCampaign.status) == "ACTIVE").all()

    result = []
    for campaign in campaigns:
        store = db.query(Store).filter(Store.id == campaign.store_id).first()
        result.append({
            "id": str(campaign.id),
            "name": campaign.name,
            "store_name": store.store_name if store else "Unknown",
            "platform": "facebook",
            "budget": float(campaign.total_budget or 0),
            "spent": 0,
            "impressions": 0,
            "clicks": 0,
            "conversions": 0
        })

    return result


# ============ Asset Endpoints ============

@admin_router.get("/assets", response_model=AssetListResponse)
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all assets with pagination."""
    query = db.query(Asset)
    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    assets = query.order_by(Asset.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for asset in assets:
        store = db.query(Store).filter(Store.id == asset.store_id).first()

        items.append(AssetListItem(
            id=asset.id,
            name=asset.name,
            store_name=store.store_name if store else "Unknown",
            file_type=asset.file_type,
            url=asset.secure_url or asset.url or "",
            source=asset.source or "upload",
            created_at=asset.created_at
        ))

    return AssetListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# ============ User Endpoints ============

@admin_router.get("/users", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all users with pagination."""
    query = db.query(User)
    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = [
        UserListItem(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role.value if hasattr(user.role, 'value') else str(user.role),
            is_verified=user.is_verified,
            is_active=user.is_active,
            created_at=user.created_at
        )
        for user in users
    ]

    return UserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# ============ Admin Management Endpoints ============

@admin_router.get("/admins", response_model=AdminUserListResponse)
async def list_admins(
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all admin users."""
    admin_users = db.query(AdminUser).filter(AdminUser.is_active == True).all()

    items = []
    for admin_user in admin_users:
        user = db.query(User).filter(User.id == admin_user.user_id).first()
        if user:
            items.append(AdminUserResponse(
                id=admin_user.id,
                email=user.email,
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                role=admin_user.role.value,
                is_active=admin_user.is_active,
                created_at=admin_user.created_at,
                last_login_at=admin_user.last_login_at
            ))

    return AdminUserListResponse(items=items, total=len(items))


@admin_router.post("/admins/invite", response_model=InviteAdminResponse)
async def invite_admin(
    request: InviteAdminRequest,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Invite a new admin user."""
    # Check if email already exists
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        existing_admin = db.query(AdminUser).filter(AdminUser.user_id == existing_user.id).first()
        if existing_admin:
            raise HTTPException(status_code=400, detail="User is already an admin")

    # Check for pending invitation
    existing_invite = db.query(AdminInvitation).filter(
        AdminInvitation.email == request.email,
        AdminInvitation.status == InvitationStatus.PENDING
    ).first()

    if existing_invite and not existing_invite.is_expired:
        raise HTTPException(status_code=400, detail="Invitation already sent")

    # Create invitation
    invitation = AdminInvitation(
        email=request.email,
        invitation_code=secrets.token_urlsafe(32),
        invited_by_id=admin.id,
        role=AdminRole.ADMIN
    )
    db.add(invitation)
    db.commit()

    # Get inviter name
    inviter_user = db.query(User).filter(User.id == admin.user_id).first()
    inviter_name = f"{inviter_user.name or 'Admin'}" if inviter_user else "Shopivell Admin"

    # Send invitation email
    send_admin_invitation_email(request.email, invitation.invitation_code, inviter_name)

    log_action(db, admin, AuditAction.INVITE, "admin", invitation.id, {"email": request.email})

    return InviteAdminResponse(
        message=f"Invitation sent to {request.email}",
        invitation_id=invitation.id
    )


@admin_router.get("/invite/verify/{code}", response_model=InvitationVerifyResponse)
async def verify_invitation(code: str, db: Session = Depends(get_db)):
    """Verify an invitation code."""
    invitation = db.query(AdminInvitation).filter(
        AdminInvitation.invitation_code == code
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invitation {invitation.status.value}")

    if invitation.is_expired:
        invitation.status = InvitationStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation expired")

    invited_by_user = None
    if invitation.invited_by_id:
        invited_by_admin = db.query(AdminUser).filter(AdminUser.id == invitation.invited_by_id).first()
        if invited_by_admin:
            invited_by_user = db.query(User).filter(User.id == invited_by_admin.user_id).first()

    return InvitationVerifyResponse(
        email=invitation.email,
        invited_by=f"{invited_by_user.first_name} {invited_by_user.last_name}" if invited_by_user else "System",
        expires_at=invitation.expires_at,
        status=invitation.status.value
    )


@admin_router.post("/invite/accept/{code}")
async def accept_invitation(
    code: str,
    request: AcceptInvitationRequest,
    db: Session = Depends(get_db)
):
    """Accept an invitation and create admin account."""
    invitation = db.query(AdminInvitation).filter(
        AdminInvitation.invitation_code == code,
        AdminInvitation.status == InvitationStatus.PENDING
    ).first()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    if invitation.is_expired:
        invitation.status = InvitationStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation expired")

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == invitation.email).first()

    if existing_user:
        # User exists, just create admin profile
        user = existing_user
        user.first_name = request.first_name
        user.last_name = request.last_name
    else:
        # Create new user
        from modules.users.models import UserRole
        user = User(
            email=invitation.email,
            first_name=request.first_name,
            last_name=request.last_name,
            name=f"{request.first_name} {request.last_name}",
            password_hash=get_password_hash(request.password),
            is_verified=True,
            is_active=True,
            role=UserRole.ADMIN
        )
        db.add(user)
        db.flush()

    # Create admin user
    admin_user = AdminUser(
        user_id=user.id,
        role=invitation.role,
        invited_by_id=invitation.invited_by_id
    )
    db.add(admin_user)

    # Update invitation
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = datetime.utcnow()

    db.commit()

    return {"message": "Account created successfully"}


@admin_router.delete("/admins/{admin_id}")
async def remove_admin(
    admin_id: uuid.UUID,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Remove an admin user."""
    # Only superadmins can remove admins
    if current_admin.role != AdminRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Only superadmins can remove admins")

    admin_to_remove = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin_to_remove:
        raise HTTPException(status_code=404, detail="Admin not found")

    if admin_to_remove.role == AdminRole.SUPERADMIN:
        raise HTTPException(status_code=400, detail="Cannot remove superadmin")

    admin_to_remove.is_active = False
    db.commit()

    log_action(db, current_admin, AuditAction.DELETE, "admin", admin_id)

    return {"message": "Admin removed"}


# ============ Payment Endpoints ============

@admin_router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all payments with pagination."""
    query = db.query(PaymentTransaction)

    if status:
        query = query.filter(PaymentTransaction.status == status)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    payments = query.order_by(PaymentTransaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for payment in payments:
        store = db.query(Store).filter(Store.id == payment.store_id).first()

        items.append(PaymentListItem(
            id=payment.id,
            store_name=store.store_name if store else "Unknown",
            amount=float(payment.amount),
            currency=payment.currency,
            payment_method=payment.payment_method,
            package_name=payment.package_name or "N/A",
            status=payment.status,
            created_at=payment.created_at
        ))

    return PaymentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@admin_router.get("/payments/income", response_model=IncomeStats)
async def get_income_stats(
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get income statistics."""
    # Total revenue (case-insensitive status check)
    total_revenue = db.query(func.sum(PaymentTransaction.amount)).filter(
        func.upper(func.cast(PaymentTransaction.status, String)) == "COMPLETED"
    ).scalar() or 0

    # Monthly revenue
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_revenue = db.query(func.sum(PaymentTransaction.amount)).filter(
        func.upper(func.cast(PaymentTransaction.status, String)) == "COMPLETED",
        PaymentTransaction.created_at >= month_start
    ).scalar() or 0

    # By package
    by_package = db.query(
        PaymentTransaction.package_name,
        func.sum(PaymentTransaction.amount).label("total")
    ).filter(
        func.upper(func.cast(PaymentTransaction.status, String)) == "COMPLETED",
        PaymentTransaction.package_name.isnot(None)
    ).group_by(PaymentTransaction.package_name).all()

    # By method
    by_method = db.query(
        PaymentTransaction.payment_method,
        func.sum(PaymentTransaction.amount).label("total")
    ).filter(
        func.upper(func.cast(PaymentTransaction.status, String)) == "COMPLETED"
    ).group_by(PaymentTransaction.payment_method).all()

    return IncomeStats(
        total_revenue=float(total_revenue),
        monthly_revenue=float(monthly_revenue),
        by_package=[{"package_name": p[0] or "N/A", "total": float(p[1])} for p in by_package],
        by_method=[{"method": m[0], "total": float(m[1])} for m in by_method]
    )


# ============ Feedback Endpoints ============

@admin_router.get("/feedback", response_model=FeedbackListResponse)
async def list_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all feedback with pagination."""
    query = db.query(Feedback)
    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    feedback_list = query.order_by(Feedback.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for feedback in feedback_list:
        user = db.query(User).filter(User.id == feedback.user_id).first()

        items.append(FeedbackListItem(
            id=feedback.id,
            user_email=user.email if user else "Unknown",
            type=feedback.type,
            title=feedback.title,
            description=feedback.description,
            status=feedback.status,
            priority=feedback.priority,
            admin_response=feedback.admin_response,
            created_at=feedback.created_at
        ))

    return FeedbackListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@admin_router.put("/feedback/{feedback_id}/respond")
async def respond_to_feedback(
    feedback_id: uuid.UUID,
    request: RespondToFeedbackRequest,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Respond to feedback."""
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    feedback.admin_response = request.admin_response
    feedback.responded_at = datetime.utcnow()
    feedback.status = "completed"
    db.commit()

    log_action(db, admin, AuditAction.UPDATE, "feedback", feedback_id)

    return {"message": "Response sent"}


# ============ Store CRUD Endpoints ============

@admin_router.post("/stores")
async def create_store(
    request: "CreateStoreRequest",
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Create a new store."""
    from .schemas import CreateStoreRequest

    # Find or create owner
    owner = db.query(User).filter(User.email == request.owner_email).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner email not found. User must register first.")

    # Check if store name exists
    existing = db.query(Store).filter(Store.store_name == request.store_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Store name already exists")

    # Create store
    store = Store(
        store_name=request.store_name,
        owner_id=owner.id,
        agency_id=request.agency_id
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    log_action(db, admin, AuditAction.CREATE, "store", store.id, {"store_name": request.store_name})

    return {"message": "Store created successfully", "id": str(store.id)}


@admin_router.put("/stores/{store_id}/status")
async def update_store_status(
    store_id: uuid.UUID,
    request: "UpdateStoreStatusRequest",
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update store status (activate/suspend)."""
    from .schemas import UpdateStoreStatusRequest

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Store doesn't have status column, we need to add it or use is_active
    # For now, we'll just log the action
    log_action(db, admin, AuditAction.UPDATE, "store", store_id, {"status": request.status})

    return {"message": f"Store status updated to {request.status}"}


@admin_router.delete("/stores/{store_id}")
async def delete_store(
    store_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Delete a store."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store_name = store.store_name
    db.delete(store)
    db.commit()

    log_action(db, admin, AuditAction.DELETE, "store", store_id, {"store_name": store_name})

    return {"message": "Store deleted successfully"}


# ============ Agency CRUD Endpoints ============

@admin_router.post("/agencies")
async def create_agency(
    request: "CreateAgencyRequest",
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Create a new agency."""
    from .schemas import CreateAgencyRequest

    # Find owner
    owner = db.query(User).filter(User.email == request.owner_email).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner email not found. User must register first.")

    # Check if agency name exists
    existing = db.query(Agency).filter(Agency.name == request.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Agency name already exists")

    # Create agency
    agency = Agency(
        name=request.name,
        owner_id=owner.id,
        status="active"
    )
    db.add(agency)
    db.commit()
    db.refresh(agency)

    log_action(db, admin, AuditAction.CREATE, "agency", agency.id, {"name": request.name})

    return {"message": "Agency created successfully", "id": str(agency.id)}


@admin_router.delete("/agencies/{agency_id}")
async def delete_agency(
    agency_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Delete an agency."""
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agency not found")

    agency_name = agency.name
    db.delete(agency)
    db.commit()

    log_action(db, admin, AuditAction.DELETE, "agency", agency_id, {"name": agency_name})

    return {"message": "Agency deleted successfully"}


# ============ User CRUD Endpoints ============

@admin_router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: uuid.UUID,
    request: "UpdateUserStatusRequest",
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update user active status."""
    from .schemas import UpdateUserStatusRequest

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = request.is_active
    db.commit()

    log_action(db, admin, AuditAction.UPDATE, "user", user_id, {"is_active": request.is_active})

    return {"message": f"User {'activated' if request.is_active else 'deactivated'} successfully"}


@admin_router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Delete a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent deleting self
    if user.id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    user_email = user.email
    db.delete(user)
    db.commit()

    log_action(db, admin, AuditAction.DELETE, "user", user_id, {"email": user_email})

    return {"message": "User deleted successfully"}

import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Configure structured, correlation-aware logging before anything else logs.
from utils.observability import setup_logging, RequestContextMiddleware
setup_logging()

logger = logging.getLogger(__name__)
from database import engine, init_db
from utils.cache import cache, check_redis_health
from middleware.cache_middleware import CacheMiddleware, CacheControlMiddleware

# Import all models FIRST to ensure SQLAlchemy relationships are properly resolved
# Order matters: base models first, then models that depend on them
from modules.users.models import *  # User model
from modules.stores.models import *  # Store model (depends on User)
from modules.assets.models import *  # Asset model (depends on Store)
from modules.campaigns.models import *  # UrlCampaign model (depends on Store, Asset)
from modules.customers.models import *
from modules.admin.models import *  # Admin models (depends on User)
from modules.procurement.models import *  # Procurement models (depends on Store, Product)
from modules.delivery.models import *  # Delivery models (depends on Store, CustomerOrder)
# from modules.fashion.models import *  # Fashion try-on models (depends on User, Store)
from modules.reviews.models import *  # Review models (depends on User, Store)
# from modules.coupons.models import *  # Coupon models (depends on User, Store)
# from modules.returns.models import *  # Return models (depends on User, Store)
from modules.business.models import *  # Business models (Facebook, Instagram)
from modules.openrouter.models import *  # AI usage tracking models
# from modules.micro_strategy.models import *  # REMOVED - Replaced by OpenClaw
from modules.jobs.models import *  # BackgroundJob (durable job queue)

from modules.customers.router import customer_router
from modules.orders.router import order_router  # Assuming 'o' is your orders router
from modules.products.router import products_router
from modules.analytics.router import analytics_router
# from modules.markets.router import markets_router
from modules.users.user_router import user_router
from modules.users.auth_router import auth_router
from modules.users.unsubscribe_router import unsubscribe_router
from modules.stores.router import store_router
#from modules.automation.router import automation_router
from modules.content.template.router import image_generation_router
from modules.content.content.router import content_router
from modules.social.router import social_router
from modules.business.router import business_router   
from modules.payment.router import payment_router 
# from modules.marketing.router import marketing_router  # REMOVED - Replaced by OpenClaw
from modules.whatsapp.router import whatsapp_router
from modules.whatsapp.faq_router import faq_router
from modules.whatsapp.embedded_signup_router import embedded_signup_router
from modules.whatsapp.flow_endpoint import flow_router
# from modules.agents.router import agents_router  # REMOVED - Replaced by OpenClaw
from modules.agency.router import agency_router
from modules.campaigns.router import campaign_router
from modules.market_research.router import research_router
from modules.assets.router import asset_router
# from modules.ad_generator.router import ad_generator_router  # REMOVED - Replaced by OpenClaw
from modules.notifications.router import notification_router
from modules.referral.router import referral_router
from modules.feedback.router import feedback_router
from modules.admin.router import admin_router
from modules.procurement.router import procurement_router
from modules.delivery.router import delivery_router
from modules.pos.router import pos_router
from modules.accounting.router import accounting_router
from modules.website_builder.router import website_builder_router
# from modules.fashion.router import fashion_router
from modules.reviews.router import review_router
# from modules.coupons.router import coupon_router
# from modules.returns.router import return_router
from modules.openrouter.router import ai_usage_router
# from modules.micro_strategy.router import micro_strategy_router  # REMOVED - Replaced by OpenClaw
from modules.openclaw.router import openclaw_router
from fastapi.middleware.cors import CORSMiddleware

# Initialize the database
init_db()

# Create FastAPI app
app = FastAPI(
    title="Shopivell Platform API",
    description="A comprehensive ecommerce platform with product management, orders, inventory, and customer management capabilities",
    version="1.0.0",
    contact={
        "name": "API Support",
        "email": "support@company.com",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://localhost:5179",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5176",
        "http://127.0.0.1:5177",
        "http://127.0.0.1:5178",
        "http://127.0.0.1:5179",
        "https://shopivell.com",
        "https://www.shopivell.com",
        "https://admin.shopivell.com",
        "https://shopivell-frontend.onrender.com",
        "https://shopivell-admin.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Correlation-id + access logging (outermost, so request_id is set for everything).
app.add_middleware(RequestContextMiddleware)

# Add caching middleware (optional - enable when Redis is configured)
# Uncomment the following lines to enable Redis caching:
# app.add_middleware(CacheMiddleware, default_ttl=60)
# app.add_middleware(CacheControlMiddleware)

# Include routers with a version prefix
app.include_router(customer_router, prefix="/v1")
app.include_router(order_router, prefix="/v1")
app.include_router(products_router, prefix="/v1")
app.include_router(analytics_router, prefix="/v1")
# app.include_router(markets_router, prefix="/v1")
app.include_router(user_router, prefix="/v1")
app.include_router(auth_router, prefix="/v1")
app.include_router(unsubscribe_router, prefix="/v1")
app.include_router(store_router, prefix="/v1")
app.include_router(image_generation_router, prefix="/v1")
# app.include_router(automation_router, prefix="/v1")
app.include_router(content_router, prefix="/v1")
app.include_router(social_router, prefix="/v1")
app.include_router(business_router, prefix="/v1")
app.include_router(payment_router, prefix="/v1")
# app.include_router(marketing_router, prefix="/v1")  # REMOVED - Replaced by OpenClaw
app.include_router(whatsapp_router, prefix="/v1")
app.include_router(faq_router, prefix="/v1")
app.include_router(embedded_signup_router, prefix="/v1/api")
app.include_router(flow_router, prefix="/v1")
# app.include_router(agents_router, prefix="/v1")  # REMOVED - Replaced by OpenClaw
app.include_router(agency_router, prefix="/v1")
app.include_router(campaign_router, prefix="/v1")
app.include_router(research_router, prefix="/v1")  # /v1/api/research/* (OpenClaw calls these)
app.include_router(asset_router, prefix="/v1")
# app.include_router(ad_generator_router, prefix="/v1")  # REMOVED - Replaced by OpenClaw
app.include_router(notification_router, prefix="/v1")
app.include_router(referral_router, prefix="/v1")
app.include_router(feedback_router, prefix="/v1/api")
app.include_router(admin_router, prefix="/v1")
app.include_router(procurement_router, prefix="/v1")
app.include_router(delivery_router, prefix="/v1")
app.include_router(pos_router, prefix="/v1")
app.include_router(accounting_router, prefix="/v1")
app.include_router(website_builder_router, prefix="/v1")
# app.include_router(fashion_router, prefix="/v1")
app.include_router(review_router, prefix="/v1")
# app.include_router(coupon_router, prefix="/v1")
# app.include_router(return_router, prefix="/v1")
app.include_router(ai_usage_router, prefix="/v1")
# app.include_router(micro_strategy_router, prefix="/v1")  # REMOVED - Replaced by OpenClaw
app.include_router(openclaw_router, prefix="/v1")  # OpenClaw - AI ad management via Zernio

# Mount static files for local asset uploads
uploads_dir = Path("uploads/assets")
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/assets", StaticFiles(directory=str(uploads_dir)), name="uploads")

# Serve the backend static assets (Shopivell logo, etc.)
static_dir = Path("static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
async def startup_event():
    """Start background services on app boot."""
    import os

    # Start the durable background-job worker (embedding sync, etc. off the
    # request path). On by default; disable with ENABLE_JOB_WORKER=false.
    if os.getenv("ENABLE_JOB_WORKER", "true").strip().lower() in ("1", "true", "yes"):
        try:
            from modules.jobs.queue import start_worker
            start_worker()
            logger.info("[Startup] Background job worker started")
        except Exception as e:
            logger.error(f"[Startup] Failed to start job worker: {e}")

    # 24/7 ad optimizer (rules over Zernio ad data; replaces the never-deployed
    # OpenClaw optimizer plugin). Dry run unless OPTIMIZER_DRY_RUN=false; disable
    # entirely with ENABLE_AD_OPTIMIZER=false.
    if os.getenv("ENABLE_AD_OPTIMIZER", "true").strip().lower() in ("1", "true", "yes"):
        try:
            from modules.optimizer.service import start_optimizer
            start_optimizer()
            logger.info("[Startup] Ad optimizer started")
        except Exception as e:
            logger.error(f"[Startup] Failed to start ad optimizer: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully stop background services."""
    try:
        from modules.optimizer.service import stop_optimizer
        stop_optimizer()
    except Exception as e:
        logger.error(f"[Shutdown] Failed to stop ad optimizer: {e}")
    try:
        from modules.jobs.queue import stop_worker
        stop_worker()
        logger.info("[Shutdown] Job worker stopped")
    except Exception as e:
        logger.error(f"[Shutdown] Failed to stop job worker: {e}")


@app.get("/health")
async def health_check():
    """Health check endpoint with Redis status"""
    redis_health = check_redis_health()
    return {
        "status": "healthy",
        "database": "connected",
        "cache": redis_health
    }


@app.post("/test-email")
async def test_email(to_email: str = "farairhato@gmail.com"):
    """
    Test email sending functionality.

    Sends a test email to verify SMTP configuration is working.
    """
    from utils.Verification_Codes_Services import VerificationCodeService

    subject = "Shopivell - Test Email"
    body = """Hello!

This is a test email from Shopivell to verify that email sending is working correctly.

If you received this email, the email configuration is set up properly.

Best regards,
Shopivell Team
support@shopivell.com
"""

    try:
        success = VerificationCodeService.send_email(to_email, subject, body.strip())
        return {
            "success": success,
            "message": f"Test email sent to {to_email}" if success else "Failed to send email",
            "to": to_email
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "to": to_email
        }


@app.post("/seed-test-users")
async def seed_test_users():
    """
    Seed test users for development/testing.

    Reads credentials from environment variables:
    - SEED_USER_EMAIL / SEED_USER_PASSWORD for regular user
    - SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD for admin user
    """
    import os
    import bcrypt
    from datetime import datetime
    from database import SessionLocal
    from modules.users.models import User, UserRole
    from modules.admin.models import AdminUser, AdminRole

    seed_user_email = os.environ.get("SEED_USER_EMAIL", "testuser@shopivell.com")
    seed_user_password = os.environ.get("SEED_USER_PASSWORD")
    seed_admin_email = os.environ.get("SEED_ADMIN_EMAIL", "admin@shopivell.com")
    seed_admin_password = os.environ.get("SEED_ADMIN_PASSWORD")

    if not seed_user_password or not seed_admin_password:
        return {
            "success": False,
            "message": "SEED_USER_PASSWORD and SEED_ADMIN_PASSWORD environment variables are required"
        }

    def hash_password(password: str) -> str:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    db = SessionLocal()
    results = {"users_created": [], "errors": []}

    try:
        # Test user credentials
        test_users = [
            {
                "email": seed_user_email,
                "password": seed_user_password,
                "name": "Test User",
                "role": UserRole.OWNER,
                "is_admin": False
            },
            {
                "email": seed_admin_email,
                "password": seed_admin_password,
                "name": "Admin User",
                "role": UserRole.ADMIN,
                "is_admin": True
            }
        ]

        for user_data in test_users:
            existing_user = db.query(User).filter(User.email == user_data["email"]).first()

            if existing_user:
                # Update password
                existing_user.password_hash = hash_password(user_data["password"])
                db.commit()
                results["users_created"].append({
                    "email": user_data["email"],
                    "status": "password_updated"
                })
                user = existing_user
            else:
                # Create new user
                user = User(
                    email=user_data["email"],
                    password_hash=hash_password(user_data["password"]),
                    name=user_data["name"],
                    role=user_data["role"],
                    is_verified=True,
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                results["users_created"].append({
                    "email": user_data["email"],
                    "status": "created"
                })

            # Create admin profile if needed
            if user_data["is_admin"]:
                existing_admin = db.query(AdminUser).filter(AdminUser.user_id == user.id).first()
                if not existing_admin:
                    admin_user = AdminUser(
                        user_id=user.id,
                        role=AdminRole.SUPERADMIN,
                        permissions={"all": True},
                        is_active=True,
                        created_at=datetime.utcnow()
                    )
                    db.add(admin_user)
                    db.commit()

        return {
            "success": True,
            "message": "Test users seeded successfully",
            "results": results,
            "credentials": {
                "regular_user": {
                    "email": seed_user_email
                },
                "admin_user": {
                    "email": seed_admin_email
                }
            }
        }

    except Exception as e:
        db.rollback()
        results["errors"].append(str(e))
        return {
            "success": False,
            "message": f"Error seeding users: {str(e)}",
            "results": results
        }
    finally:
        db.close()


# Run server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
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

from modules.customers.router import customer_router
from modules.orders.router import order_router  # Assuming 'o' is your orders router
from modules.products.router import products_router
from modules.analytics.router import analytics_router
# from modules.markets.router import markets_router
from modules.users.user_router import user_router
from modules.users.auth_router import auth_router
from modules.stores.router import store_router
#from modules.automation.router import automation_router
from modules.content.template.router import image_generation_router
from modules.content.content.router import content_router
from modules.social.router import social_router
from modules.business.router import business_router   
from modules.payment.router import payment_router 
from modules.marketing.router import marketing_router
from modules.whatsapp.router import whatsapp_router
from modules.whatsapp.faq_router import faq_router
from modules.whatsapp.embedded_signup_router import embedded_signup_router
from modules.agents.router import agents_router
from modules.agency.router import agency_router
from modules.campaigns.router import campaign_router
from modules.assets.router import asset_router
from modules.ad_generator.router import ad_generator_router
from modules.notifications.router import notification_router
from modules.referral.router import referral_router
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
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

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
app.include_router(store_router, prefix="/v1")
app.include_router(image_generation_router, prefix="/v1")
# app.include_router(automation_router, prefix="/v1")
app.include_router(content_router, prefix="/v1")
app.include_router(social_router, prefix="/v1")
app.include_router(business_router, prefix="/v1")
app.include_router(payment_router, prefix="/v1")
app.include_router(marketing_router, prefix="/v1")
app.include_router(whatsapp_router, prefix="/v1")
app.include_router(faq_router, prefix="/v1")
app.include_router(embedded_signup_router, prefix="/v1/api")
app.include_router(agents_router, prefix="/v1")
app.include_router(agency_router, prefix="/v1")
app.include_router(campaign_router, prefix="/v1")
app.include_router(asset_router, prefix="/v1")
app.include_router(ad_generator_router, prefix="/v1")
app.include_router(notification_router, prefix="/v1")
app.include_router(referral_router, prefix="/v1")

# Mount static files for local asset uploads
uploads_dir = Path("uploads/assets")
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/assets", StaticFiles(directory=str(uploads_dir)), name="uploads")


@app.get("/health")
async def health_check():
    """Health check endpoint with Redis status"""
    redis_health = check_redis_health()
    return {
        "status": "healthy",
        "database": "connected",
        "cache": redis_health
    }


# Run server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

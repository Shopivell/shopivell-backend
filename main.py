from fastapi import FastAPI
from database import engine, init_db
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

# ✅ Include routers with a version prefix
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

# Run server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

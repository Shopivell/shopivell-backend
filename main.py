from fastapi import FastAPI
from database import engine, init_db
from modules.customers.models import *
from modules.customers.router import customer_router
from modules.orders.router import order_router  # Assuming 'o' is your orders router
from modules.products.router import products_router
from modules.analytics.router import analytics_router
# from modules.markets.router import markets_router
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

# Run server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

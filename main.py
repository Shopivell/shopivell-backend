from fastapi import FastAPI
from database import engine
import models
from routers import analytics, user, supplier,products,request,offer,auth,orders

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# add cors middleware 
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# add routers
app.include_router(user.user_router)
app.include_router(supplier.supplier_router)
app.include_router(products.product_router)
app.include_router(request.request_router)
app.include_router(offer.offer_router)
app.include_router(auth.auth_router)
app.include_router(orders.orders_router)
app.include_router(analytics.analytics_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
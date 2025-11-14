# apis.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from typing import Optional
import uuid

from database import get_db
from models import Market, MarketInclude, MarketCustomization, Catalog, CatalogProduct, CatalogMarket, Product
from schemas import (
    # Market schemas
    MarketCreate, MarketResponse, MarketUpdate, MarketListResponse,
    MarketIncludeCreate, MarketCustomizationCreate,
    # Catalog schemas
    CatalogCreate, CatalogResponse, CatalogUpdate, CatalogListResponse,
    CatalogProductCreate, CatalogMarketCreate,
    # Product schemas
    ProductCreate, ProductResponse, ProductUpdate, ProductListResponse
)

markets_router = APIRouter()

# Market APIs
@markets_router.get("/markets", response_model=MarketListResponse, tags=["markets"])
async def get_markets(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(Market).options(
            joinedload(Market.market_includes),
            joinedload(Market.market_customizations)
        )
        
        if status:
            query = query.filter(Market.status == status)
        if search:
            query = query.filter(Market.name.ilike(f"%{search}%"))
        
        total = query.count()
        markets = query.offset(skip).limit(limit).all()
        
        return MarketListResponse(
            markets=markets,
            total=total,
            page=skip // limit + 1,
            size=len(markets)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching markets: {str(e)}")

@markets_router.get("/markets/{market_id}", response_model=MarketResponse, tags=["markets"])
async def get_market(market_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        market = db.query(Market).options(
            joinedload(Market.market_includes),
            joinedload(Market.market_customizations)
        ).filter(Market.id == market_id).first()
        
        if not market:
            raise HTTPException(status_code=404, detail="Market not found")
        return market
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching market: {str(e)}")

@markets_router.post("/markets", response_model=MarketResponse, status_code=201, tags=["markets"])
async def create_market(market_data: MarketCreate, db: Session = Depends(get_db)):
    try:
        existing_market = db.query(Market).filter(Market.name == market_data.name).first()
        if existing_market:
            raise HTTPException(status_code=400, detail="Market name already exists")
        
        market_dict = market_data.model_dump(exclude={'includes', 'customizations'})
        db_market = Market(**market_dict)
        db.add(db_market)
        db.flush()
        
        customizations_count = 0
        
        if market_data.includes:
            for include_data in market_data.includes:
                include = MarketInclude(market_id=db_market.id, **include_data.model_dump())
                db.add(include)
        
        if market_data.customizations:
            for customization_data in market_data.customizations:
                customization = MarketCustomization(market_id=db_market.id, **customization_data.model_dump())
                db.add(customization)
                customizations_count += 1
        
        db_market.customizations = customizations_count
        db.commit()
        db.refresh(db_market)
        return db_market
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating market: {str(e)}")

@markets_router.put("/markets/{market_id}", response_model=MarketResponse, tags=["markets"])
async def update_market(market_id: uuid.UUID, market_data: MarketUpdate, db: Session = Depends(get_db)):
    try:
        db_market = db.query(Market).filter(Market.id == market_id).first()
        if not db_market:
            raise HTTPException(status_code=404, detail="Market not found")
        
        update_data = market_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_market, field, value)
        
        db.commit()
        db.refresh(db_market)
        return db_market
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating market: {str(e)}")

@markets_router.delete("/markets/{market_id}", status_code=204, tags=["markets"])
async def delete_market(market_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        db_market = db.query(Market).filter(Market.id == market_id).first()
        if not db_market:
            raise HTTPException(status_code=404, detail="Market not found")
        
        db.delete(db_market)
        db.commit()
        return None
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting market: {str(e)}")

# Catalog APIs
@markets_router.get("/catalogs", response_model=CatalogListResponse, tags=["catalogs"])
async def get_catalogs(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(Catalog).options(
            joinedload(Catalog.catalog_products),
            joinedload(Catalog.catalog_markets).joinedload(CatalogMarket.market)
        )
        
        if status and status != "All":
            query = query.filter(Catalog.status == status)
        if search:
            query = query.filter(Catalog.title.ilike(f"%{search}%"))
        
        total = query.count()
        catalogs = query.offset(skip).limit(limit).all()
        
        return CatalogListResponse(
            catalogs=catalogs,
            total=total,
            page=skip // limit + 1,
            size=len(catalogs)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching catalogs: {str(e)}")

@markets_router.get("/catalogs/{catalog_id}", response_model=CatalogResponse, tags=["catalogs"])
async def get_catalog(catalog_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        catalog = db.query(Catalog).options(
            joinedload(Catalog.catalog_products),
            joinedload(Catalog.catalog_markets).joinedload(CatalogMarket.market)
        ).filter(Catalog.id == catalog_id).first()
        
        if not catalog:
            raise HTTPException(status_code=404, detail="Catalog not found")
        return catalog
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching catalog: {str(e)}")

@markets_router.post("/catalogs", response_model=CatalogResponse, status_code=201, tags=["catalogs"])
async def create_catalog(catalog_data: CatalogCreate, db: Session = Depends(get_db)):
    try:
        existing_catalog = db.query(Catalog).filter(Catalog.title == catalog_data.title).first()
        if existing_catalog:
            raise HTTPException(status_code=400, detail="Catalog title already exists")
        
        catalog_dict = catalog_data.model_dump(exclude={'products', 'markets'})
        db_catalog = Catalog(**catalog_dict)
        db.add(db_catalog)
        db.flush()
        
        products_count = 0
        price_overrides = 0
        
        if catalog_data.products:
            for product_data in catalog_data.products:
                product = CatalogProduct(catalog_id=db_catalog.id, **product_data.model_dump())
                db.add(product)
                products_count += 1
                if product_data.price_in_usd != 0:
                    price_overrides += 1
        
        if catalog_data.markets:
            for market_data in catalog_data.markets:
                market_assoc = CatalogMarket(catalog_id=db_catalog.id, **market_data.model_dump())
                db.add(market_assoc)
        
        db_catalog.products_count = products_count
        db_catalog.price_overrides = price_overrides
        
        db.commit()
        db.refresh(db_catalog)
        return db_catalog
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating catalog: {str(e)}")

@markets_router.put("/catalogs/{catalog_id}", response_model=CatalogResponse, tags=["catalogs"])
async def update_catalog(catalog_id: uuid.UUID, catalog_data: CatalogUpdate, db: Session = Depends(get_db)):
    try:
        db_catalog = db.query(Catalog).filter(Catalog.id == catalog_id).first()
        if not db_catalog:
            raise HTTPException(status_code=404, detail="Catalog not found")
        
        update_data = catalog_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_catalog, field, value)
        
        db.commit()
        db.refresh(db_catalog)
        return db_catalog
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating catalog: {str(e)}")

@markets_router.delete("/catalogs/{catalog_id}", status_code=204, tags=["catalogs"])
async def delete_catalog(catalog_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        db_catalog = db.query(Catalog).filter(Catalog.id == catalog_id).first()
        if not db_catalog:
            raise HTTPException(status_code=404, detail="Catalog not found")
        
        db.delete(db_catalog)
        db.commit()
        return None
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting catalog: {str(e)}")

# Product APIs
@markets_router.get("/products", response_model=ProductListResponse, tags=["products"])
async def get_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(Product)
        
        if search:
            query = query.filter(Product.name.ilike(f"%{search}%"))
        
        total = query.count()
        products = query.offset(skip).limit(limit).all()
        
        return ProductListResponse(
            products=products,
            total=total,
            page=skip // limit + 1,
            size=len(products)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching products: {str(e)}")

@markets_router.post("/products", response_model=ProductResponse, status_code=201, tags=["products"])
async def create_product(product_data: ProductCreate, db: Session = Depends(get_db)):
    try:
        db_product = Product(**product_data.model_dump())
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
        return db_product
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating product: {str(e)}")
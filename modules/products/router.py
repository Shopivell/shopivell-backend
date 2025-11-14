from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
import shutil
from pathlib import Path

from database import get_db
from modules.products.models import Product, Collection, CollectionProduct
from modules.products.schemas import (
    ProductCreate, ProductResponse, ProductUpdate, ProductListResponse,
    CollectionCreate, CollectionResponse, CollectionUpdate, CollectionListResponse,
    InventoryListResponse, InventoryItemResponse, InventoryUpdate
)

products_router = APIRouter(prefix="/api/products", tags=["products"])

# Image upload configuration
UPLOAD_DIR = Path("uploads")
PRODUCT_IMAGE_DIR = UPLOAD_DIR / "products"
COLLECTION_IMAGE_DIR = UPLOAD_DIR / "collections"

# Create upload directories if they don't exist
PRODUCT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
COLLECTION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# INVENTORY ENDPOINTS
# =============================================================================

# GET all inventory items (all products with inventory data)
@products_router.get("/inventory/items", response_model=InventoryListResponse)
async def get_inventory_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    product_id: Optional[uuid.UUID] = None,
    sku: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Build query with filters
        query = db.query(Product)
        
        if product_id:
            query = query.filter(Product.id == product_id)
        if sku:
            query = query.filter(Product.sku.ilike(f"%{sku}%"))
        if status:
            query = query.filter(Product.status == status)
        if search:
            query = query.filter(
                Product.title.ilike(f"%{search}%") | 
                Product.sku.ilike(f"%{search}%")
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        products = query.offset(skip).limit(limit).all()
        
        # Convert to inventory items format
        inventory_items = []
        for product in products:
            inventory_items.append(InventoryItemResponse(
                id=product.id,
                name=product.title,
                sku=product.sku,
                quantity=product.quantity,  # Add quantity
                unavailable=product.unavailable,
                committed=product.committed,
                available=product.available,
                on_hand=product.on_hand,
                status=product.status,
                inventory_tracked=product.inventory_tracked
            ))
        
        return InventoryListResponse(
            inventory_items=inventory_items,
            total=total,
            page=skip // limit + 1,
            size=len(inventory_items)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching inventory items: {str(e)}"
        )

# GET single product inventory
@products_router.get("/inventory/items/{product_id}", response_model=InventoryItemResponse)
async def get_inventory_item(product_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
            
        return InventoryItemResponse(
            id=product.id,
            name=product.title,
            sku=product.sku,
            unavailable=product.unavailable,
            committed=product.committed,
            available=product.available,
            on_hand=product.on_hand,
            status=product.status,
            inventory_tracked=product.inventory_tracked
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching inventory item: {str(e)}"
        )

# UPDATE product inventory quantities
@products_router.put("/inventory/items/{product_id}", response_model=InventoryItemResponse)
async def update_inventory_item(
    product_id: uuid.UUID, 
    inventory_data: InventoryUpdate, 
    db: Session = Depends(get_db)
):
    try:
        # Get existing product
        product = db.query(Product).filter(Product.id == product_id).first()
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Update inventory fields
        update_data = inventory_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(product, field, value)
        
        db.commit()
        db.refresh(product)
        
        return InventoryItemResponse(
            id=product.id,
            name=product.title,
            sku=product.sku,
            quantity=product.quantity,  # Add quantity
            unavailable=product.unavailable,
            committed=product.committed,
            available=product.available,
            on_hand=product.on_hand,
            status=product.status,
            inventory_tracked=product.inventory_tracked
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating inventory item: {str(e)}"
        )

# BULK UPDATE inventory quantities
@products_router.put("/inventory/bulk-update", response_model=List[InventoryItemResponse])
async def bulk_update_inventory(
    updates: List[dict],
    db: Session = Depends(get_db)
):
    try:
        results = []
        for update in updates:
            product_id = update.get('product_id')
            if not product_id:
                continue
                
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                continue
                
            # Update inventory fields
            if 'unavailable' in update:
                product.unavailable = update['unavailable']
            if 'committed' in update:
                product.committed = update['committed']
            if 'available' in update:
                product.available = update['available']
            if 'on_hand' in update:
                product.on_hand = update['on_hand']
            
            results.append(InventoryItemResponse(
                id=product.id,
                name=product.title,
                sku=product.sku,
                unavailable=product.unavailable,
                committed=product.committed,
                available=product.available,
                on_hand=product.on_hand,
                status=product.status,
                inventory_tracked=product.inventory_tracked
            ))
        
        db.commit()
        return results
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error bulk updating inventory: {str(e)}"
        )

# UPDATE inventory quantities (quick update)
@products_router.patch("/inventory/items/{product_id}/quantities", response_model=InventoryItemResponse)
async def update_inventory_quantities(
    product_id: uuid.UUID,
    unavailable: Optional[int] = None,
    committed: Optional[int] = None,
    available: Optional[int] = None,
    on_hand: Optional[int] = None,
    db: Session = Depends(get_db)
):
    try:
        # Get existing product
        product = db.query(Product).filter(Product.id == product_id).first()
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Update quantities if provided
        if unavailable is not None:
            product.unavailable = unavailable
        if committed is not None:
            product.committed = committed
        if available is not None:
            product.available = available
        if on_hand is not None:
            product.on_hand = on_hand
        
        db.commit()
        db.refresh(product)
        
        return InventoryItemResponse(
            id=product.id,
            name=product.title,
            sku=product.sku,
            unavailable=product.unavailable,
            committed=product.committed,
            available=product.available,
            on_hand=product.on_hand,
            status=product.status,
            inventory_tracked=product.inventory_tracked
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating inventory quantities: {str(e)}"
        )

# =============================================================================
# IMAGE UPLOAD ENDPOINTS
# =============================================================================

@products_router.post("/upload/product-image/{product_id}")
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Verify product exists
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Validate file type
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type. Allowed types: jpg, jpeg, png, gif, webp"
            )
        
        # Generate unique filename
        unique_filename = f"{product_id}_{uuid.uuid4()}{file_extension}"
        file_path = PRODUCT_IMAGE_DIR / unique_filename
        
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Update product with image paths
        product.image_path = str(file_path)
        product.image_url = f"/api/products/images/products/{unique_filename}"
        
        db.commit()
        db.refresh(product)
        
        return {
            "message": "Image uploaded successfully",
            "image_url": product.image_url,
            "image_path": product.image_path
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading image: {str(e)}"
        )

@products_router.post("/upload/collection-image/{collection_id}")
async def upload_collection_image(
    collection_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Verify collection exists
        collection = db.query(Collection).filter(Collection.id == collection_id).first()
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
        
        # Validate file type
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type. Allowed types: jpg, jpeg, png, gif, webp"
            )
        
        # Generate unique filename
        unique_filename = f"{collection_id}_{uuid.uuid4()}{file_extension}"
        file_path = COLLECTION_IMAGE_DIR / unique_filename
        
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Update collection with image paths
        collection.image_path = str(file_path)
        collection.image_url = f"/api/products/images/collections/{unique_filename}"
        
        db.commit()
        db.refresh(collection)
        
        return {
            "message": "Image uploaded successfully",
            "image_url": collection.image_url,
            "image_path": collection.image_path
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading image: {str(e)}"
        )

# Serve uploaded images
@products_router.get("/images/products/{filename}")
async def get_product_image(filename: str):
    file_path = PRODUCT_IMAGE_DIR / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    return FileResponse(file_path)

@products_router.get("/images/collections/{filename}")
async def get_collection_image(filename: str):
    file_path = COLLECTION_IMAGE_DIR / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    return FileResponse(file_path)

# =============================================================================
# PRODUCT ENDPOINTS
# =============================================================================

# GET all products with pagination and filtering
@products_router.get("/", response_model=ProductListResponse)
async def get_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    category: Optional[str] = None,
    status: Optional[str] = None,
    vendor: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Build query with filters
        query = db.query(Product)
        
        if category:
            query = query.filter(Product.category == category)
        if status:
            query = query.filter(Product.status == status)
        if vendor:
            query = query.filter(Product.vendor == vendor)
        if search:
            query = query.filter(
                Product.title.ilike(f"%{search}%") | 
                Product.description.ilike(f"%{search}%") |
                Product.sku.ilike(f"%{search}%")
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        products = query.offset(skip).limit(limit).all()
        
        return ProductListResponse(
            products=products,
            total=total,
            page=skip // limit + 1,
            size=len(products)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching products: {str(e)}"
        )

# GET single product by ID
@products_router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
            
        return product
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching product: {str(e)}"
        )

# GET product by SKU
@products_router.get("/sku/{sku}", response_model=ProductResponse)
async def get_product_by_sku(sku: str, db: Session = Depends(get_db)):
    try:
        product = db.query(Product).filter(Product.sku == sku).first()
        
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
            
        return product
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching product: {str(e)}"
        )

# CREATE product
# CREATE product
@products_router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(product_data: ProductCreate, db: Session = Depends(get_db)):
    try:
        # Prepare product data - handle empty strings by converting to None
        product_dict = product_data.model_dump(exclude={'collections'})
        
        # Convert all empty strings to None for database compatibility
        for key, value in product_dict.items():
            if isinstance(value, str) and value.strip() == '':
                product_dict[key] = None
        
        # Special handling for SKU
        if not product_dict.get('sku'):
            product_dict['sku'] = 'No SKU'
        
        # Check if SKU already exists (only if not using default)
        if product_dict['sku'] != 'No SKU':
            existing_product = db.query(Product).filter(
                Product.sku == product_dict['sku']
            ).first()
            
            if existing_product:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SKU already exists"
                )
        
        # Create new product
        db_product = Product(**product_dict)
        db.add(db_product)
        db.flush()
        
        # Handle collections if provided
        if product_data.collections:
            for collection_id in product_data.collections:
                collection_product = CollectionProduct(
                    product_id=db_product.id,
                    collection_id=collection_id
                )
                db.add(collection_product)
        
        db.commit()
        db.refresh(db_product)
        
        return db_product
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Detailed error: {str(e)}")  # Add this for debugging
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating product: {str(e)}"
        )
    
# UPDATE product
# UPDATE product
@products_router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID, 
    product_data: ProductUpdate, 
    db: Session = Depends(get_db)
):
    try:
        # Get existing product
        db_product = db.query(Product).filter(Product.id == product_id).first()
        
        if not db_product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Prepare update data - handle empty strings
        update_data = product_data.model_dump(exclude_unset=True)
        
        # Convert empty strings to None for nullable fields
        nullable_fields = ['description', 'category', 'type', 'vendor', 'tags', 'barcode', 'image_url', 'image_path']
        for field in nullable_fields:
            if field in update_data and update_data[field] == '':
                update_data[field] = None
        
        # Handle SKU specifically
        if 'sku' in update_data and (not update_data['sku'] or update_data['sku'].strip() == ''):
            update_data['sku'] = 'No SKU'
        
        # Check if SKU already exists (if being updated and not using default)
        if 'sku' in update_data and update_data['sku'] != 'No SKU' and update_data['sku'] != db_product.sku:
            existing_product = db.query(Product).filter(
                Product.sku == update_data['sku']
            ).first()
            
            if existing_product:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SKU already exists"
                )
        
        # Update fields
        for field, value in update_data.items():
            setattr(db_product, field, value)
        
        db.commit()
        db.refresh(db_product)
        
        return db_product
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating product: {str(e)}"
        )

# DELETE product
@products_router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        # Get existing product
        db_product = db.query(Product).filter(Product.id == product_id).first()
        
        if not db_product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Delete associated collection relationships first
        db.query(CollectionProduct).filter(
            CollectionProduct.product_id == product_id
        ).delete()
        
        db.delete(db_product)
        db.commit()
        
        return None
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting product: {str(e)}"
        )

# =============================================================================
# COLLECTION ENDPOINTS
# =============================================================================

# GET all collections with pagination and filtering
@products_router.get("/collections/", response_model=CollectionListResponse)
async def get_collections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    collection_type: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Build query with filters
        query = db.query(Collection)
        
        if collection_type:
            query = query.filter(Collection.collection_type == collection_type)
        if search:
            query = query.filter(Collection.title.ilike(f"%{search}%"))
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        collections = query.offset(skip).limit(limit).all()
        
        return CollectionListResponse(
            collections=collections,
            total=total,
            page=skip // limit + 1,
            size=len(collections)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching collections: {str(e)}"
        )

# GET single collection by ID
@products_router.get("/collections/{collection_id}", response_model=CollectionResponse)
async def get_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        collection = db.query(Collection).filter(Collection.id == collection_id).first()
        
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
            
        return collection
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching collection: {str(e)}"
        )

# CREATE collection
@products_router.post("/collections/", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(collection_data: CollectionCreate, db: Session = Depends(get_db)):
    try:
        # Check if collection title already exists
        existing_collection = db.query(Collection).filter(
            Collection.title == collection_data.title
        ).first()
        
        if existing_collection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Collection title already exists"
            )
        
        # Create new collection
        collection_dict = collection_data.model_dump(exclude={'product_ids'})
        db_collection = Collection(**collection_dict)
        db.add(db_collection)
        db.flush()  # Flush to get the collection ID
        
        # Handle products if provided
        if collection_data.product_ids:
            for product_id in collection_data.product_ids:
                # Verify product exists
                product = db.query(Product).filter(Product.id == product_id).first()
                if not product:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Product with ID {product_id} not found"
                    )
                
                collection_product = CollectionProduct(
                    collection_id=db_collection.id,
                    product_id=product_id
                )
                db.add(collection_product)
        
        db.commit()
        db.refresh(db_collection)
        
        return db_collection
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating collection: {str(e)}"
        )

# UPDATE collection
@products_router.put("/collections/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: uuid.UUID, 
    collection_data: CollectionUpdate, 
    db: Session = Depends(get_db)
):
    try:
        # Get existing collection
        db_collection = db.query(Collection).filter(Collection.id == collection_id).first()
        
        if not db_collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
        
        # Check if title already exists (if being updated)
        if collection_data.title and collection_data.title != db_collection.title:
            existing_collection = db.query(Collection).filter(
                Collection.title == collection_data.title
            ).first()
            
            if existing_collection:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Collection title already exists"
                )
        
        # Update fields
        update_data = collection_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_collection, field, value)
        
        db.commit()
        db.refresh(db_collection)
        
        return db_collection
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating collection: {str(e)}"
        )

# DELETE collection
@products_router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        # Get existing collection
        db_collection = db.query(Collection).filter(Collection.id == collection_id).first()
        
        if not db_collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
        
        # Delete associated collection relationships first
        db.query(CollectionProduct).filter(
            CollectionProduct.collection_id == collection_id
        ).delete()
        
        db.delete(db_collection)
        db.commit()
        
        return None
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting collection: {str(e)}"
        )

# ADD product to collection
@products_router.post("/collections/{collection_id}/products/{product_id}", response_model=CollectionResponse)
async def add_product_to_collection(
    collection_id: uuid.UUID,
    product_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    try:
        # Verify collection exists
        collection = db.query(Collection).filter(Collection.id == collection_id).first()
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
        
        # Verify product exists
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Check if product already in collection
        existing_relation = db.query(CollectionProduct).filter(
            CollectionProduct.collection_id == collection_id,
            CollectionProduct.product_id == product_id
        ).first()
        
        if existing_relation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product already in collection"
            )
        
        # Add product to collection
        collection_product = CollectionProduct(
            collection_id=collection_id,
            product_id=product_id
        )
        db.add(collection_product)
        db.commit()
        db.refresh(collection)
        
        return collection
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding product to collection: {str(e)}"
        )

# REMOVE product from collection
@products_router.delete("/collections/{collection_id}/products/{product_id}", response_model=CollectionResponse)
async def remove_product_from_collection(
    collection_id: uuid.UUID,
    product_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    try:
        # Verify collection exists
        collection = db.query(Collection).filter(Collection.id == collection_id).first()
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
        
        # Remove product from collection
        db.query(CollectionProduct).filter(
            CollectionProduct.collection_id == collection_id,
            CollectionProduct.product_id == product_id
        ).delete()
        
        db.commit()
        db.refresh(collection)
        
        return collection
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error removing product from collection: {str(e)}"
        )

# GET collection products
@products_router.get("/collections/{collection_id}/products", response_model=ProductListResponse)
async def get_collection_products(
    collection_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    try:
        # Verify collection exists
        collection = db.query(Collection).filter(Collection.id == collection_id).first()
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )
        
        # Get products in collection
        query = db.query(Product).join(
            CollectionProduct, 
            Product.id == CollectionProduct.product_id
        ).filter(CollectionProduct.collection_id == collection_id)
        
        total = query.count()
        products = query.offset(skip).limit(limit).all()
        
        return ProductListResponse(
            products=products,
            total=total,
            page=skip // limit + 1,
            size=len(products)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching collection products: {str(e)}"
        )
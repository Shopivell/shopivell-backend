from io import BytesIO
from typing import Optional, List
import uuid
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form, status, Request
from models import Product, User # Ensure your Product and User models are correctly imported
from schemas.products_schema import ProductResponse, ProductCreate, ProductUpdate # Use the updated schemas
from schemas.user_schema import SuccessMessage # Assuming SuccessMessage is in user_schema
from uuid import UUID

from dotenv import load_dotenv
import boto3
from botocore.exceptions import NoCredentialsError
import os


# Create a new router for products
product_router = APIRouter(prefix="/products", tags=["Products"]) # Changed tag to plural
# Load environment variables (ensure this is at the very top of your file or in main.py)

load_dotenv()

# Configuration from environment variables
SPACES_REGION = os.getenv("SPACES_REGION")
SPACES_ENDPOINT = os.getenv("SPACES_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# --- Validate Configuration (Optional but Recommended) ---
required_vars = ["SPACES_REGION", "SPACES_ENDPOINT", "ACCESS_KEY", "SECRET_KEY", "BUCKET_NAME"]
for var in required_vars:
    if os.getenv(var) is None:
        raise ValueError(f"Environment variable {var} not set. Please check your .env file.")

# Initialize S3 client globally. This should ideally be handled with FastAPI's dependency injection
# or application startup events for more robust error handling and resource management.
try:
    session = boto3.session.Session()
    s3_client = session.client(
        's3',
        region_name=SPACES_REGION,
        endpoint_url=SPACES_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY
    )
except Exception as e:
    print(f"Error initializing S3 client: {e}")
    s3_client = None # Set to None if initialization fails, and handle this in functions


def upload_file_to_spaces(file_data: bytes, filename: str, content_type: str):
    """
    Uploads a file to DigitalOcean Spaces.

    Args:
        file_data (bytes): The content of the file to upload.
        filename (str): The desired filename in Spaces.
        content_type (str): The MIME type of the file (e.g., "image/jpeg").

    Returns:
        str: The public URL of the uploaded file, or None if an error occurs.
    """
    if s3_client is None:
        print("S3 client not initialized. Cannot upload file.")
        return None
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=filename,
            Body=file_data,
            ACL='public-read',  # Makes the file publicly accessible
            ContentType=content_type
        )
        # Construct the public URL for the uploaded file
        return f"{SPACES_ENDPOINT}/{BUCKET_NAME}/{filename}"
    
    except NoCredentialsError:
        print("Credentials not available. Check ACCESS_KEY and SECRET_KEY in .env.")
        return None
    except Exception as e:
        print(f"Error uploading file to Spaces: {e}")
        return None

def delete_file_from_spaces(filename: str):
    """
    Deletes a file from DigitalOcean Spaces.

    Args:
        filename (str): The filename (Key) of the file to delete in Spaces.

    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    if s3_client is None:
        print("S3 client not initialized. Cannot delete file.")
        return False
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=filename)
        return True
    except Exception as e:
        print(f"Error deleting file from Spaces: {e}")
        return False
    
# --- Removed _get_image_url and any /image/{image_id} routes ---
# These are no longer needed because image_path directly stores the DO Spaces URL
# The client will fetch images directly from DO Spaces.


@product_router.post("/product", response_model=SuccessMessage, status_code=status.HTTP_201_CREATED) # Changed response_model
async def create_product(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price: float = Form(...),
    category: str = Form(...),
    supplier_id: UUID = Form(...),
    image: UploadFile = File(None),  # Single file
    db: Session = Depends(get_db)
):
    """
    Creates a new product with an associated image uploaded to DigitalOcean Spaces.
    """
    image_url = None
    supplier = db.query(User).filter(User.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    
    # Optional: Check if supplier has the 'supplier' role
    if supplier.role != "both":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not authorized to create products (not a supplier).")

    # Validate image file type
    # if not image.content_type or not image.content_type.startswith("image/"):
    #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File '{image.filename}' is not a valid image. Content type: {image.content_type}")
    if image is not None:
        contents = await image.read()
        file_extension = image.filename.split(".")[-1] if "." in image.filename else "jpg" # Default to jpg
        spaces_filename = f"products/{supplier_id}/{uuid.uuid4()}.{file_extension}" # Organized by supplier ID

        image_url = upload_file_to_spaces(contents, spaces_filename, image.content_type)
        # The upload_file_to_spaces function now raises HTTPException on error, so no explicit check here needed.

    db_product = Product(
        name=name,
        description=description,
        price=price,
        category=category,
        supplier_id=supplier_id,
        image_path=image_url # Store the DO Spaces URL directly
    )

    try:
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
    except Exception as e:
        db.rollback()
        # Attempt to delete the uploaded file if database commit fails
        delete_file_from_spaces(spaces_filename)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create product in database: {e}")

    # Return the created product including its ID and image_path
    return {"message": "Product created successfully"}


@product_router.get("/{product_id}", response_model=ProductResponse) # Changed response_model
def get_product(
    product_id: UUID, 
    db: Session = Depends(get_db)
):
    """
    Retrieves a single product by its ID.
    """
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    
    # Pydantic will automatically map the SQLAlchemy model to ProductResponse
    # which includes the image_path
    return db_product

@product_router.get("/", response_model=List[ProductResponse]) # Changed response_model
def get_all_products(
    db: Session = Depends(get_db)
):
    """
    Retrieves all products.
    """
    products = db.query(Product).all()
    # Pydantic will automatically convert the list of SQLAlchemy Product objects
    # into a List of ProductResponse objects, including image_path.
    return products

@product_router.put("/{product_id}", response_model=ProductResponse) # Changed response_model
def update_product(
    product_id: UUID, 
    product_update: ProductUpdate, # Use ProductUpdate schema for partial updates
    db: Session = Depends(get_db)
):
    """
    Updates an existing product's details (excluding image).
    """
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    
    # Apply updates from the Pydantic model to the SQLAlchemy model
    # Use model_dump(exclude_unset=True) to only update fields that are provided
    for key, value in product_update.model_dump(exclude_unset=True).items():
        setattr(db_product, key, value)
    
    try:
        db.commit()
        db.refresh(db_product)
        return db_product
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update product in database: {e}")

@product_router.post("/{product_id}/image", response_model=SuccessMessage)
async def update_product_image(
    product_id: UUID,
    image: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Updates the image for an existing product. Deletes the old image from DigitalOcean Spaces.
    """
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File '{image.filename}' is not a valid image.")

    # Delete old image from Spaces if it exists
    if db_product.image_path:
        # Extract filename from the URL for deletion (assuming URL format is SPACES_ENDPOINT/BUCKET_NAME/path/to/filename)
        old_filename_in_spaces = db_product.image_path.replace(f"{SPACES_ENDPOINT}/{BUCKET_NAME}/", "")
        if old_filename_in_spaces:
            if not delete_file_from_spaces(old_filename_in_spaces):
                print(f"Warning: Failed to delete old image {old_filename_in_spaces} from Spaces.")

    # Upload new image
    contents = await image.read()
    file_extension = image.filename.split(".")[-1] if "." in image.filename else "jpg"
    new_spaces_filename = f"products/{db_product.supplier_id}/{uuid.uuid4()}.{file_extension}" # Organize by supplier ID

    new_image_url = upload_file_to_spaces(contents, new_spaces_filename, image.content_type)
    
    db_product.image_path = new_image_url

    try:
        db.commit()
        db.refresh(db_product)
    except Exception as e:
        db.rollback()
        # If DB update fails, attempt to delete the newly uploaded image
        delete_file_from_spaces(new_spaces_filename)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update product image path in database: {e}")

    return SuccessMessage(message="Product image updated successfully", image_url=new_image_url)


@product_router.delete("/{product_id}", response_model=SuccessMessage, status_code=status.HTTP_200_OK) # Changed response_model
def delete_product(product_id: UUID, db: Session = Depends(get_db)):
    """
    Deletes a product and its associated image from DigitalOcean Spaces.
    """
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Delete associated image from DigitalOcean Spaces
    if db_product.image_path:
        filename_in_spaces = db_product.image_path.replace(f"{SPACES_ENDPOINT}/{BUCKET_NAME}/", "")
        if filename_in_spaces:
            if not delete_file_from_spaces(filename_in_spaces):
                print(f"Warning: Failed to delete image {filename_in_spaces} from Spaces.")
                # You might choose to raise an HTTPException here if image deletion is critical

    try:
        db.delete(db_product)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete product from database: {e}")

    return SuccessMessage(message="Product and associated image deleted successfully")


@product_router.get("/by-supplier/{supplier_id}", response_model=List[ProductResponse]) # Changed path for clarity
def get_products_by_supplier(
    supplier_id: UUID, 
    db: Session = Depends(get_db)
):
    """
    Retrieves all products for a given supplier.
    """
    db_supplier = db.query(User).filter(User.id == supplier_id).first()
    if not db_supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    
    # Optional: Check if the user is actually a supplier
    if db_supplier.role != "both":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a supplier.")

    products = db.query(Product).filter(Product.supplier_id == supplier_id).all()
    # Pydantic will handle the mapping to ProductResponse
    return products

@product_router.get("/by-category/{category}", response_model=List[ProductResponse]) # Changed path for clarity
def get_products_by_category(
    category: str, 
    db: Session = Depends(get_db)
):
    """
    Retrieves all products belonging to a specific category.
    """
    products = db.query(Product).filter(Product.category.ilike(category)).all() # Use ilike for case-insensitive
    if not products:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No products found in category: {category}")
    
    return products

@product_router.get("/search-products/{query}", response_model=List[ProductResponse]) # Changed path for clarity
def search_products(
    query: str, 
    db: Session = Depends(get_db)
):
    """
    Searches for products by name (case-insensitive partial match).
    """
    # Use .ilike for case-insensitive search
    products = db.query(Product).filter(Product.name.ilike(f"%{query}%")).all()
    if not products:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No products found matching query: '{query}'")
    
    return products

@product_router.get("/supplier-count/{supplier_id}", response_model=dict) # Changed path for clarity
def count_products_by_supplier(supplier_id: UUID, db: Session = Depends(get_db)):
    """
    Counts the number of products for a given supplier.
    """
    supplier = db.query(User).filter(User.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    
    if supplier.role != "supplier":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a supplier.")

    count = db.query(Product).filter(Product.supplier_id == supplier_id).count()
    return {"count": count}

@product_router.get("/total-count", response_model=dict) # Changed path for clarity
def count_all_products(db: Session = Depends(get_db)):
    """
    Counts the total number of products in the database.
    """
    count = db.query(Product).count()
    return {"count": count}
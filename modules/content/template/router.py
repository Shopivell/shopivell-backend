
from fastapi import APIRouter, Depends, HTTPException, Path, status, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
from datetime import datetime
import json
from uuid import UUID

# Cloudinary Imports 
import cloudinary
import cloudinary.uploader
# Configuration (Your actual secret is used here)
cloudinary.config( 
    cloud_name = "dw1lnczyk", 
    api_key = "449784537457564", 
    api_secret = "F1ThkpIpFNkcpGpfa1PSPHEe_f8", 
    secure=True
)

from database import get_db 
from .models import ImageGenerationRequest 
from .schemas import (
    TextToImageCreate, 
    ImageGenerationRequestResponse, 
    ImageGenerationRequestListResponse
) 

image_generation_router = APIRouter(prefix="/api/image-requests", tags=["image_generation"])

# --- Internal Templates Data ---
INTERNAL_TEMPLATES = [
    {
        "id": "b5280fa6-7a5e-4bd4-81e9-73ba8a7d23fe",
        "request_type": "template",
        "template_name": "Travel Collage",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763799888/image_generation_inputs/input_0fd13b97-4a73-4bcb-ac60-6bb74089b740.jpg"
        ],
        "prompt_text": "Turn the images I uploaded into an irregular collage, Japanese journal style, Japanese notebook vibes, Instagram travel moodboard.",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/b5280fa6-7a5e-4bd4-81e9-73ba8a7d23fe_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 3081,
        "created_at": "2025-11-22T08:24:49.063353",
        "updated_at": "2025-11-22T08:24:49.234124",
        "completed_at": "2025-11-22T08:24:49.232593"
    },
    {
        "id": "367f5027-5079-467e-a278-b8c8b4368168",
        "request_type": "template",
        "template_name": "Brand VI Design",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800041/image_generation_inputs/input_a46405b8-7710-41e3-b9bb-e1ae13cd393b.jpg"
        ],
        "prompt_text": "Reference this LOGO build a full [outdoor sport brand] visual system brand name [GREEN] deliverables [shopping bag cap paper box card wristband lanyard] keep yellow as core color fun minimal modern vibe",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/367f5027-5079-467e-a278-b8c8b4368168_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 603,
        "created_at": "2025-11-22T08:27:22.210723",
        "updated_at": "2025-11-22T08:27:22.361052",
        "completed_at": "2025-11-22T08:27:22.361052"
    },
    {
        "id": "ef633dbd-914b-4310-aa1f-400eb7ff6546",
        "request_type": "template",
        "template_name": "Recipe",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800131/image_generation_inputs/input_db8fb4cf-9a63-4b01-89e8-f1432dea9603.jpg"
        ],
        "prompt_text": "- [Food Name] cooking tutorial illustration, featuring a plaid border decoration. The cooking process is displayed step by step from top to bottom, with text instructions appearing on the right side of each step. Japanese hand-painted watercolor style, with bright and fresh soft colors, delicate details; the overall style is cute, healing, and full of life.",
        "output_image_url": None,
        "status": "failed",
        "model_name": None,
        "generation_time_ms": 4418,
        "created_at": "2025-11-22T08:28:51.578439",
        "updated_at": "2025-11-22T08:28:51.808840",
        "completed_at": "2025-11-22T08:28:51.807786"
    },
    {
        "id": "0f49f41f-e660-48bc-9a88-59fc47de4d8d",
        "request_type": "template",
        "template_name": "Review Display Card",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800307/image_generation_inputs/input_b0a2a477-ac22-4ee1-b883-38f6f20c7034.png"
        ],
        "prompt_text": "Design a customer review showcase featuring [rating] stars, customer testimonial about [product], social proof layout with modern design",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/0f49f41f-e660-48bc-9a88-59fc47de4d8d_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 3485,
        "created_at": "2025-11-22T08:31:47.948948",
        "updated_at": "2025-11-22T08:31:48.188108",
        "completed_at": "2025-11-22T08:31:48.188108"
    },
    {
        "id": "332e2213-e898-4049-bdf1-1db00eabd338",
        "request_type": "template",
        "template_name": "Instagram Story Template",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800371/image_generation_inputs/input_1811ad38-2595-49c9-a30d-e216ed0771c1.png"
        ],
        "prompt_text": "Create an Instagram story featuring [product/brand], [trendy style] design with [bright/pastel] colors and modern typography",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/332e2213-e898-4049-bdf1-1db00eabd338_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 3001,
        "created_at": "2025-11-22T08:32:52.045722",
        "updated_at": "2025-11-22T08:32:52.299495",
        "completed_at": "2025-11-22T08:32:52.298482"
    },
    {
        "id": "1079f06d-2886-4926-88f7-d5adb6b208cd",
        "request_type": "template",
        "template_name": "Multi-Language Version",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800495/image_generation_inputs/input_c3bd3a40-19c9-40a7-94d8-b3b791c43720.png"
        ],
        "prompt_text": "Adapt this product presentation for [target country/region] market, incorporating cultural elements and local preferences, maintaining brand consistency",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/1079f06d-2886-4926-88f7-d5adb6b208cd_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 4378,
        "created_at": "2025-11-22T08:34:56.583334",
        "updated_at": "2025-11-22T08:34:57.087230",
        "completed_at": "2025-11-22T08:34:57.086723"
    },
    {
        "id": "6f911d9c-dd29-4f77-843c-c892ea6811c8",
        "request_type": "template",
        "template_name": "Product Comparison",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800631/image_generation_inputs/input_39162567-d37b-4fd5-9ff2-29ba6d45a6ce.png"
        ],
        "prompt_text": "Extract the product from the background of the image and place it in a professional product comparison chart. Compare [Product 1] with [Product 2]. The segmented layout design highlights the key differences [Text description], with concise and clear fonts and modern visual design with comparison points, feature highlights, and clear visual distinctions",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/6f911d9c-dd29-4f77-843c-c892ea6811c8_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 4460,
        "created_at": "2025-11-22T08:37:12.159673",
        "updated_at": "2025-11-22T08:37:12.657341",
        "completed_at": "2025-11-22T08:37:12.656815"
    },
    {
        "id": "7c3054d2-b5ac-4d73-8b04-fb6cf7aa863a",
        "request_type": "template",
        "template_name": "360-Degree Product View",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800765/image_generation_inputs/input_72fa921d-c77c-4318-8aff-7906c8ea4c2a.png"
        ],
        "prompt_text": "Create a 360-degree product showcase of this [product] showing front, side, back and top views, professional studio lighting, white background",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/7c3054d2-b5ac-4d73-8b04-fb6cf7aa863a_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 4413,
        "created_at": "2025-11-22T08:39:26.252157",
        "updated_at": "2025-11-22T08:39:26.604183",
        "completed_at": "2025-11-22T08:39:26.603676"
    },
    {
        "id": "d652ca30-d028-492a-804c-4869b9257d00",
        "request_type": "template",
        "template_name": "Package Design",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800835/image_generation_inputs/input_154e454e-720f-4f3d-9865-4684a350b9d8.png"
        ],
        "prompt_text": "Design a [product type] packaging box with [brand name] logo, featuring [product highlights], [color scheme] theme, modern retail packaging style",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/d652ca30-d028-492a-804c-4869b9257d00_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 610,
        "created_at": "2025-11-22T08:40:36.338996",
        "updated_at": "2025-11-22T08:40:36.675827",
        "completed_at": "2025-11-22T08:40:36.675322"
    },
    {
        "id": "b9b851d0-01a8-48cd-8291-9cf94aea6866",
        "request_type": "template",
        "template_name": "Sales Banner",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763800908/image_generation_inputs/input_9efdc0a6-7381-47ec-87c8-df0dbf73ffbb.png"
        ],
        "prompt_text": "Create a promotional banner with [SALE 50% OFF] text featuring [product name], vibrant colors and eye-catching promotional elements",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/b9b851d0-01a8-48cd-8291-9cf94aea6866_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 2533,
        "created_at": "2025-11-22T08:41:48.770565",
        "updated_at": "2025-11-22T08:41:49.224438",
        "completed_at": "2025-11-22T08:41:49.223927"
    },
    {
        "id": "ab48414a-ef96-484a-8d4d-92dbec5d73c2",
        "request_type": "template",
        "template_name": "Product Shot",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763801023/image_generation_inputs/input_41396bc7-8030-4f27-ae87-9cc39550fc7d.png"
        ],
        "prompt_text": "Place this [product] on a [luxury marble countertop with soft warm lighting], professional product photography style",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/ab48414a-ef96-484a-8d4d-92dbec5d73c2_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 1831,
        "created_at": "2025-11-22T08:43:43.909254",
        "updated_at": "2025-11-22T08:43:44.201605",
        "completed_at": "2025-11-22T08:43:44.201086"
    },
    {
        "id": "a3224bd1-4874-45be-9366-4b17b2b615eb",
        "request_type": "template",
        "template_name": "Model Try-On",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763801104/image_generation_inputs/input_2d74f5ed-1512-4df5-a8e6-2bb1c8c908c5.png"
        ],
        "prompt_text": "Show [all item] worn by a [diverse/professional] model, [casual/formal] pose, [studio/lifestyle] setting",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/a3224bd1-4874-45be-9366-4b17b2b615eb_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 3160,
        "created_at": "2025-11-22T08:45:05.494791",
        "updated_at": "2025-11-22T08:45:05.857817",
        "completed_at": "2025-11-22T08:45:05.857817"
    },
    {
        "id": "19b1f7c7-c52e-4187-ba8f-0f0d7874774a",
        "request_type": "template",
        "template_name": "Product Mockup",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763801160/image_generation_inputs/input_ad195662-bf8b-4045-b9d4-d570ef1dab54.jpg"
        ],
        "prompt_text": "Apply custom [design/pattern/artwork] to this product with realistic presentation",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/19b1f7c7-c52e-4187-ba8f-0f0d7874774a_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 3294,
        "created_at": "2025-11-22T08:46:01.353861",
        "updated_at": "2025-11-22T08:46:01.676570",
        "completed_at": "2025-11-22T08:46:01.676570"
    },
    {
        "id": "a643bc7a-0489-430d-bb7f-c029306bec9e",
        "request_type": "template",
        "template_name": "Skincare Product",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763801782/image_generation_inputs/input_da6a17a1-bd5e-4a51-a918-fdacc3579df4.jpg"
        ],
        "prompt_text": "Revitalize Anti-Aging Serum before and after. Left side: a close-up of a woman's face with visible fine lines, wrinkles, and dull, uneven skin tone. Right side: the same woman's face now with smoother skin, significantly reduced wrinkles, and a radiant, glowing complexion.",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/a643bc7a-0489-430d-bb7f-c029306bec9e_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 1257,
        "created_at": "2025-11-22T08:56:23.408291",
        "updated_at": "2025-11-22T08:56:23.518284",
        "completed_at": "2025-11-22T08:56:23.518284"
    },
    {
        "id": "c9b962df-ea94-407d-aac2-0a72aad41ad1",
        "request_type": "template",
        "template_name": "Lawn Care Service",
        "input_image_urls": [
            "https://res.cloudinary.com/dw1lnczyk/image/upload/v1763801928/image_generation_inputs/input_75fa426d-9dfa-4702-a70f-f6d66cec3b17.jpg"
        ],
        "prompt_text": "GreenThumb Lawn Treatment before and after. Left side: a patchy, dry, and brown lawn with weeds and bare spots. Right side: the same lawn now thick, lush, uniformly green, and perfectly manicured",
        "output_image_url": "https://res.cloudinary.com/dw1lnczyk/image/upload/v1/c9b962df-ea94-407d-aac2-0a72aad41ad1_output.png",
        "status": "completed",
        "model_name": None,
        "generation_time_ms": 4662,
        "created_at": "2025-11-22T08:58:49.246929",
        "updated_at": "2025-11-22T08:58:49.638343",
        "completed_at": "2025-11-22T08:58:49.637656"
    }
]

# --- Helper Functions ---

def create_internal_templates(db: Session):
    """Create internal templates in the database if they don't exist"""
    for template_data in INTERNAL_TEMPLATES:
        # Check if template already exists
        existing_template = db.query(ImageGenerationRequest).filter(
            ImageGenerationRequest.template_name == template_data["template_name"]
        ).first()
        
        if not existing_template:
            # Convert string dates to datetime objects
            template_data["created_at"] = datetime.fromisoformat(template_data["created_at"].replace('Z', '+00:00'))
            template_data["updated_at"] = datetime.fromisoformat(template_data["updated_at"].replace('Z', '+00:00'))
            if template_data["completed_at"]:
                template_data["completed_at"] = datetime.fromisoformat(template_data["completed_at"].replace('Z', '+00:00'))
            
            # Create the template record
            template = ImageGenerationRequest(**template_data)
            db.add(template)
    
    db.commit()
    print(f"✅ Created {len(INTERNAL_TEMPLATES)} internal templates")

def process_generation(request: ImageGenerationRequest, db: Session):
    """Simulates the actual AI generation process."""
    import random
    import time
    
    # If output image was already provided via upload, mark as completed immediately
    if request.output_image_url:
        request.status = "completed"
        request.completed_at = datetime.utcnow()
        request.generation_time_ms = 0
        db.commit()
        db.refresh(request)
        return request
    
    # Otherwise, simulate AI generation
    time.sleep(random.uniform(0.1, 0.5)) 
    processing_time = random.randint(500, 5000)
    
    if random.random() < 0.9: 
        request.status = "completed"
        request.output_image_url = f"https://res.cloudinary.com/dw1lnczyk/image/upload/v1/{request.id}_output.png" 
        request.completed_at = datetime.utcnow()
        request.generation_time_ms = processing_time
    else:
        request.status = "failed"
        request.completed_at = datetime.utcnow()
        request.generation_time_ms = processing_time
        
    db.commit()
    db.refresh(request)
    return request

async def upload_files_to_cloudinary(input_images: List[UploadFile]):
    """Uploads files to Cloudinary and returns a list of secure URLs."""
    uploaded_urls = []
    for image_file in input_images:
        if image_file.size == 0 and not image_file.filename: continue 

        file_content = await image_file.read()
        try:
            upload_result = cloudinary.uploader.upload(
                file_content, 
                folder="image_generation_inputs", 
                public_id=f"input_{uuid.uuid4()}",
                resource_type="auto"
            )
            uploaded_urls.append(upload_result["secure_url"])
        except Exception as e:
            print(f"Cloudinary upload failed: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to upload image(s) to storage.")

    return uploaded_urls

# --- Template Management Endpoints ---

@image_generation_router.get("/templates/", response_model=List[ImageGenerationRequestResponse])
def get_all_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get all templates from the database"""
    # Ensure internal templates are created
    create_internal_templates(db)
    
    templates = db.query(ImageGenerationRequest).filter(
        ImageGenerationRequest.request_type == "template"
    ).offset(skip).limit(limit).all()
    
    return templates

@image_generation_router.get("/templates/{template_name}", response_model=ImageGenerationRequestResponse)
def get_template(template_name: str, db: Session = Depends(get_db)):
    """Get a specific template by name"""
    # Ensure internal templates are created
    create_internal_templates(db)
    
    template = db.query(ImageGenerationRequest).filter(
        ImageGenerationRequest.request_type == "template",
        ImageGenerationRequest.template_name == template_name
    ).first()
    
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    return template

@image_generation_router.put("/templates/{template_name}", response_model=ImageGenerationRequestResponse)
async def update_template(
    template_name: str,
    user_prompt: Optional[str] = Form(None),
    input_images: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Update an existing template"""
    # Ensure internal templates are created
    create_internal_templates(db)
    
    template = db.query(ImageGenerationRequest).filter(
        ImageGenerationRequest.request_type == "template",
        ImageGenerationRequest.template_name == template_name
    ).first()
    
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    # Update prompt text if provided
    if user_prompt is not None:
        template.prompt_text = user_prompt
    
    # Update images if provided
    if input_images is not None:
        uploaded_urls = await upload_files_to_cloudinary(input_images)
        template.input_image_urls = uploaded_urls
    
    template.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(template)
    
    return template

@image_generation_router.delete("/templates/{template_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_name: str, db: Session = Depends(get_db)):
    """Delete a template"""
    # Ensure internal templates are created
    create_internal_templates(db)
    
    template = db.query(ImageGenerationRequest).filter(
        ImageGenerationRequest.request_type == "template",
        ImageGenerationRequest.template_name == template_name
    ).first()
    
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    db.delete(template)
    db.commit()
    
    return {"message": "Template deleted successfully"}

# --- Image Generation Endpoints ---

## 🖼️ Template Based Endpoint (FIXED)
@image_generation_router.post("/template", response_model=ImageGenerationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_template_request(
    template_name: str = Form(..., description="The name of the template to use"),
    user_prompt: str = Form(..., description="The user's custom prompt to combine with the template"), 
    input_images: List[UploadFile] = File(None, description="Optional input images"),
    output_image: UploadFile = File(None, description="Optional output image for I2I requests"),  
    db: Session = Depends(get_db)
):
    """
    Handles generation based on a template from the database.
    """
    # Ensure internal templates are created
    create_internal_templates(db)
    
    # Handle input images upload
    uploaded_urls = await upload_files_to_cloudinary(input_images or [])
    
    # Handle output image upload if provided
    output_image_url = None
    if output_image and output_image.filename:
        try:
            file_content = await output_image.read()
            upload_result = cloudinary.uploader.upload(
                file_content, 
                folder="image_generation_outputs", 
                public_id=f"output_{uuid.uuid4()}",
                resource_type="auto"
            )
            output_image_url = upload_result["secure_url"]
        except Exception as e:
            print(f"Cloudinary output image upload failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="Failed to upload output image to storage."
            )
    
    # Create request using template
    request_data = {
        'prompt_text': user_prompt,
        'input_image_urls': uploaded_urls, 
        'output_image_url': output_image_url,  # ✅ Now storing URL string, not UploadFile object
        'request_type': "template",
        'template_name': template_name,
        'status': "pending"
    }
    
    request = ImageGenerationRequest(**request_data)
    db.add(request)
    db.commit()
    db.refresh(request)

    return process_generation(request, db)

## 📸 Image + Text to Image (I2I) Endpoint (Direct Prompt)
@image_generation_router.post("/i2i", response_model=ImageGenerationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_i2i_request(
    prompt_text: str = Form(..., description="The user's descriptive prompt"), 
    input_images: List[UploadFile] = File(..., description="One or more input images for I2I generation"),
    db: Session = Depends(get_db)
):
    """Handles Direct Image + Text to Image (I2I) generation"""
    uploaded_urls = await upload_files_to_cloudinary(input_images)
    
    if not uploaded_urls:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid images were provided for I2I request.")

    request_data = {
        'prompt_text': prompt_text,
        'input_image_urls': uploaded_urls, 
        'request_type': "prompt_i2i",
        'template_name': None,
        'status': "pending"
    }
    
    request = ImageGenerationRequest(**request_data)
    db.add(request)
    db.commit()
    db.refresh(request)
    
    return process_generation(request, db)

## ✍️ Text to Image (T2I) Endpoint (Direct Prompt)
@image_generation_router.post("/t2i", response_model=ImageGenerationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_t2i_request(
    request_data: TextToImageCreate,
    db: Session = Depends(get_db)
):
    """Handles Direct Text to Image (T2I) generation"""
    
    data_to_store = request_data.model_dump()
    data_to_store.update({
        'input_image_urls': [], 
        'request_type': "prompt_t2i",
        'template_name': None,
        'status': "pending"
    })
    
    request = ImageGenerationRequest(**data_to_store)
    db.add(request)
    db.commit()
    db.refresh(request)
    
    return process_generation(request, db)

# --- GET Endpoints (Unchanged) ---
@image_generation_router.get("/{request_id}", response_model=ImageGenerationRequestResponse)
def get_image_request(request_id: uuid.UUID, db: Session = Depends(get_db)):
    """Retrieves a specific image generation request by ID"""
    request = db.query(ImageGenerationRequest).filter(ImageGenerationRequest.id == request_id).first()
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image Generation Request not found"
        )
    return request

@image_generation_router.get("/", response_model=ImageGenerationRequestListResponse)
def get_all_image_requests(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get a paginated list of image generation requests"""
    query = db.query(ImageGenerationRequest)
    total_count = query.count()
    requests = query.offset(skip).limit(limit).all()
    
    return ImageGenerationRequestListResponse(
        requests=requests,
        total_count=total_count,
        page=skip // limit + 1,
        page_size=limit,
        total_pages=(total_count + limit - 1) // limit
    )

## 📸 Image + Text to Image (I2I) Endpoint (Using Image URLs)
@image_generation_router.post("/i2i/urls", response_model=ImageGenerationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_i2i_request_with_urls(
   prompt_text: str = Form(..., description="The text prompt for generation"),
    output_image_url: str = Form(None, description="Optional pre-generated output image URL"),  
    db: Session = Depends(get_db)
):
    """Handles Direct Text to Image (T2I) generation with optional output image URL"""
    
    # Validate output image URL if provided
    if output_image_url and not output_image_url.startswith(('http://', 'https://')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid output_image_url format: must be a valid HTTP/HTTPS URL"
        )
    
    request_data = {
        'prompt_text': prompt_text,
        'input_image_urls': [], 
        'output_image_url': output_image_url,
        'request_type': "prompt_i2i",
        'template_name': None,
        'status': "completed" if output_image_url else "pending"
    }
    
    request = ImageGenerationRequest(**request_data)
    db.add(request)
    db.commit()
    db.refresh(request)
    
    # If output image URL was provided, mark as completed immediately
    if output_image_url:
        request.status = "completed"
        request.completed_at = datetime.utcnow()
        request.generation_time_ms = 0
        db.commit()
        db.refresh(request)
        return request
    
    # Otherwise, process normally
    return process_generation(request, db)

## ✍️ Text to Image (T2I) Endpoint (Using URLs - for output image)
@image_generation_router.post("/t2i/urls", response_model=ImageGenerationRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_t2i_request_with_urls(
    prompt_text: str = Form(..., description="The text prompt for generation"),
    output_image_url: str = Form(None, description="Optional pre-generated output image URL"),  
    db: Session = Depends(get_db)
):
    """Handles Direct Text to Image (T2I) generation with optional output image URL"""
    
    # Validate output image URL if provided
    if output_image_url and not output_image_url.startswith(('http://', 'https://')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid output_image_url format: must be a valid HTTP/HTTPS URL"
        )
    
    request_data = {
        'prompt_text': prompt_text,
        'input_image_urls': [], 
        'output_image_url': output_image_url,
        'request_type': "prompt_t2i",
        'template_name': None,
        'status': "completed" if output_image_url else "pending"
    }
    
    request = ImageGenerationRequest(**request_data)
    db.add(request)
    db.commit()
    db.refresh(request)
    
    # If output image URL was provided, mark as completed immediately
    if output_image_url:
        request.status = "completed"
        request.completed_at = datetime.utcnow()
        request.generation_time_ms = 0
        db.commit()
        db.refresh(request)
        return request
    
    # Otherwise, process normally
    return process_generation(request, db)

## 📋 Get All Prompts and Image URLs
@image_generation_router.get("/prompts/all", response_model=List[dict])
def get_all_prompts_and_images(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get all prompts with their input and output image URLs"""
    requests = db.query(ImageGenerationRequest).offset(skip).limit(limit).all()
    
    result = []
    for request in requests:
        result.append({
            "id": str(request.id),
            "request_type": request.request_type,
            "template_name": request.template_name,
            "prompt_text": request.prompt_text,
            "input_image_urls": request.input_image_urls,  # This uses the property that deserializes JSON
            "output_image_url": request.output_image_url,
            "status": request.status,
            "created_at": request.created_at.isoformat() if request.created_at else None,
            "completed_at": request.completed_at.isoformat() if request.completed_at else None
        })
    
    return result
## 📋 Get All Non-Template Prompts and Images (Reverse Chronological Order)
@image_generation_router.get("/prompts/non-templates", response_model=List[dict])
def get_non_template_prompts_and_images(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Get all prompts excluding templates (only prompt_i2i and prompt_t2i) in reverse chronological order"""
    requests = db.query(ImageGenerationRequest).filter(
        ImageGenerationRequest.request_type.in_(["prompt_i2i", "prompt_t2i"])
    ).order_by(ImageGenerationRequest.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for request in requests:
        result.append({
            "id": str(request.id),
            "request_type": request.request_type,
            "prompt_text": request.prompt_text,
            "input_image_urls": request.input_image_urls,
            "output_image_url": request.output_image_url,
            "status": request.status,
            "created_at": request.created_at.isoformat() if request.created_at else None,
            "completed_at": request.created_at.isoformat() if request.completed_at else None
        })
    
    return result

## 🗑️ Delete Specific Generation by ID
@image_generation_router.delete("/{request_id}", status_code=status.HTTP_200_OK)
def delete_generation(
    request_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete a specific image generation request by ID"""
    request = db.query(ImageGenerationRequest).filter(ImageGenerationRequest.id == request_id).first()
    
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image Generation Request not found"
        )
    
    # Optional: Delete associated images from Cloudinary
    try:
        # Delete input images from Cloudinary
        for image_url in request.input_image_urls:
            # Extract public_id from Cloudinary URL
            if "cloudinary.com" in image_url:
                public_id = image_url.split("/")[-1].split(".")[0]
                cloudinary.uploader.destroy(public_id)
        
        # Delete output image from Cloudinary
        if request.output_image_url and "cloudinary.com" in request.output_image_url:
            public_id = request.output_image_url.split("/")[-1].split(".")[0]
            cloudinary.uploader.destroy(public_id)
    except Exception as e:
        print(f"Cloudinary deletion failed: {e}")
        # Continue with database deletion even if Cloudinary deletion fails
    
    # Delete from database
    db.delete(request)
    db.commit()
    
    return {
        "message": "Image generation request deleted successfully",
        "deleted_id": str(request_id)
    }

## 🗑️ Delete Specific Generation by ID
@image_generation_router.delete("/{request_id}", status_code=status.HTTP_200_OK)
def delete_generation_by_id(
    request_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete a specific image generation request by ID"""
    request = db.query(ImageGenerationRequest).filter(ImageGenerationRequest.id == request_id).first()
    
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image Generation Request not found"
        )
    
    # Store info for response
    request_info = {
        "id": str(request.id),
        "request_type": request.request_type,
        "template_name": request.template_name
    }
    
    # Optional: Delete associated images from Cloudinary
    try:
        # Delete input images from Cloudinary
        for image_url in request.input_image_urls:
            # Extract public_id from Cloudinary URL
            if "cloudinary.com" in image_url and "image_generation_inputs" in image_url:
                public_id = image_url.split("/")[-1].split(".")[0]
                # Include folder path in public_id for proper deletion
                full_public_id = f"image_generation_inputs/{public_id}"
                cloudinary.uploader.destroy(full_public_id)
        
        # Delete output image from Cloudinary
        if request.output_image_url and "cloudinary.com" in request.output_image_url:
            public_id = request.output_image_url.split("/")[-1].split(".")[0]
            cloudinary.uploader.destroy(public_id)
    except Exception as e:
        print(f"Cloudinary deletion failed: {e}")
        # Continue with database deletion even if Cloudinary deletion fails
    
    # Delete from database
    db.delete(request)
    db.commit()
    
    return {
        "message": "Image generation request deleted successfully",
        "deleted_request": request_info
    }

## 🔍 Get Image by Request ID
@image_generation_router.get("/{request_id}/image")
def get_image_by_id(
    request_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get output image URL for a specific request ID"""
    request = db.query(ImageGenerationRequest).filter(ImageGenerationRequest.id == request_id).first()
    
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )
    
    if not request.output_image_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not available for this request"
        )
    
    return {
        "image_url": request.output_image_url
    }
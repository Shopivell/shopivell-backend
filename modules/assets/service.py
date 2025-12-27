# modules/assets/service.py
"""
Asset service for Cloudinary uploads and AI image generation.
"""
import os
import uuid
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv
from openai import OpenAI

from .models import Asset, AssetType

load_dotenv()

# Check if Cloudinary is configured
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

CLOUDINARY_CONFIGURED = (
    CLOUDINARY_CLOUD_NAME and
    CLOUDINARY_API_KEY and
    CLOUDINARY_API_SECRET and
    CLOUDINARY_CLOUD_NAME != "your_cloud_name" and
    CLOUDINARY_API_KEY != "your_api_key"
)

print(f"[AssetService] Cloudinary configured: {CLOUDINARY_CONFIGURED}")
if not CLOUDINARY_CONFIGURED:
    print(f"[AssetService] Cloudinary env vars - Cloud: {bool(CLOUDINARY_CLOUD_NAME)}, Key: {bool(CLOUDINARY_API_KEY)}, Secret: {bool(CLOUDINARY_API_SECRET)}")

if CLOUDINARY_CONFIGURED:
    # Initialize Cloudinary
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True
    )

# Local upload directory for fallback
LOCAL_UPLOAD_DIR = Path("uploads/assets")
LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Initialize OpenAI for image generation
openai_api_key = os.getenv("OPENAI_API_KEY")


class AssetService:
    def __init__(self, db: Session):
        self.db = db
        self.openai = OpenAI(api_key=openai_api_key) if openai_api_key else None

    def upload_to_cloudinary(
        self,
        file_data: bytes,
        filename: str,
        store_id: uuid.UUID,
        resource_type: str = "auto"
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Upload a file to Cloudinary.
        Returns (upload_result, error_message)
        """
        try:
            # Create folder structure
            folder = f"shopivell/stores/{store_id}/assets"

            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                file_data,
                folder=folder,
                resource_type=resource_type,
                public_id=f"{uuid.uuid4()}_{filename.split('.')[0]}",
                overwrite=True,
                eager=[
                    {"width": 300, "height": 300, "crop": "fill", "format": "jpg"}  # Thumbnail
                ],
                eager_async=False
            )

            # Extract thumbnail URL
            thumbnail_url = None
            if result.get("eager") and len(result["eager"]) > 0:
                thumbnail_url = result["eager"][0].get("secure_url")

            return {
                "public_id": result.get("public_id"),
                "url": result.get("url"),
                "secure_url": result.get("secure_url"),
                "thumbnail_url": thumbnail_url,
                "width": result.get("width"),
                "height": result.get("height"),
                "format": result.get("format"),
                "resource_type": result.get("resource_type"),
                "bytes": result.get("bytes")
            }, None

        except Exception as e:
            print(f"[Cloudinary] Upload error: {e}")
            return None, str(e)

    def save_locally(
        self,
        file_data: bytes,
        filename: str,
        store_id: uuid.UUID
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Save file locally when Cloudinary is not configured.
        Returns (result, error_message)
        """
        try:
            # Create store-specific folder
            store_folder = LOCAL_UPLOAD_DIR / str(store_id)
            store_folder.mkdir(parents=True, exist_ok=True)

            # Generate unique filename
            file_ext = filename.split('.')[-1] if '.' in filename else 'bin'
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = store_folder / unique_filename

            # Save file
            with open(file_path, 'wb') as f:
                f.write(file_data)

            # Generate URL (relative path for local development)
            local_url = f"/uploads/assets/{store_id}/{unique_filename}"

            return {
                "public_id": unique_filename,
                "url": local_url,
                "secure_url": local_url,
                "thumbnail_url": local_url,
                "width": None,
                "height": None,
                "format": file_ext,
                "resource_type": "image",
                "bytes": len(file_data)
            }, None

        except Exception as e:
            print(f"[Local] Save error: {e}")
            return None, str(e)

    def create_asset_from_upload(
        self,
        store_id: uuid.UUID,
        filename: str,
        file_data: bytes,
        mime_type: str,
        file_type: AssetType = AssetType.IMAGE,
        name: Optional[str] = None,
        source_campaign_id: Optional[uuid.UUID] = None
    ) -> Tuple[Optional[Asset], Optional[str]]:
        """
        Upload file to Cloudinary (or locally if not configured) and create asset record.
        Returns (asset, error_message)
        """
        try:
            # Determine resource type for Cloudinary
            resource_type = "video" if file_type == AssetType.VIDEO else "image"

            # Try Cloudinary first, fall back to local storage
            if CLOUDINARY_CONFIGURED:
                upload_result, error = self.upload_to_cloudinary(
                    file_data=file_data,
                    filename=filename,
                    store_id=store_id,
                    resource_type=resource_type
                )
            else:
                print("[Asset] Cloudinary not configured, saving locally")
                upload_result, error = self.save_locally(
                    file_data=file_data,
                    filename=filename,
                    store_id=store_id
                )

            if error:
                return None, error

            # Create asset record
            asset = Asset(
                store_id=store_id,
                name=name or filename,
                original_filename=filename,
                file_type=file_type,
                mime_type=mime_type,
                file_size=upload_result.get("bytes"),
                cloudinary_public_id=upload_result.get("public_id"),
                cloudinary_url=upload_result.get("url"),
                cloudinary_secure_url=upload_result.get("secure_url"),
                thumbnail_url=upload_result.get("thumbnail_url"),
                width=upload_result.get("width"),
                height=upload_result.get("height"),
                source="upload",
                source_campaign_id=source_campaign_id
            )

            self.db.add(asset)
            self.db.commit()
            self.db.refresh(asset)

            return asset, None

        except Exception as e:
            self.db.rollback()
            print(f"[Asset] Creation error: {e}")
            return None, str(e)

    def generate_ad_image(
        self,
        store_id: uuid.UUID,
        headline: str,
        description: Optional[str] = None,
        features: List[str] = [],
        call_to_action: str = "Learn More",
        style: str = "modern",
        color_scheme: Optional[str] = None,
        campaign_id: Optional[uuid.UUID] = None
    ) -> Tuple[Optional[Asset], Optional[str]]:
        """
        Generate an ad image using DALL-E and save to Cloudinary.
        Returns (asset, error_message)
        """
        if not self.openai:
            return None, "OpenAI API key not configured"

        try:
            # Build image generation prompt
            features_text = ", ".join(features[:3]) if features else ""
            prompt = f"""Create a professional {style} advertisement image:
- Headline: "{headline}"
- Style: {style}, clean, professional
- Features to highlight: {features_text}
- Call to action: {call_to_action}
{f'- Color scheme: {color_scheme}' if color_scheme else ''}
- Do NOT include any text in the image
- Focus on imagery that conveys: {description or headline}
- Make it suitable for Facebook/Instagram ads
- 1024x1024, high quality, visually striking"""

            # Generate image with DALL-E
            response = self.openai.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1
            )

            image_url = response.data[0].url

            # Download the image
            import requests
            img_response = requests.get(image_url)
            if img_response.status_code != 200:
                return None, "Failed to download generated image"

            # Upload to Cloudinary
            upload_result, error = self.upload_to_cloudinary(
                file_data=img_response.content,
                filename=f"generated_{uuid.uuid4().hex[:8]}.png",
                store_id=store_id,
                resource_type="image"
            )

            if error:
                return None, error

            # Create asset record
            asset = Asset(
                store_id=store_id,
                name=f"Generated: {headline[:50]}",
                original_filename="dall-e-generated.png",
                file_type=AssetType.IMAGE,
                mime_type="image/png",
                file_size=upload_result.get("bytes"),
                cloudinary_public_id=upload_result.get("public_id"),
                cloudinary_url=upload_result.get("url"),
                cloudinary_secure_url=upload_result.get("secure_url"),
                thumbnail_url=upload_result.get("thumbnail_url"),
                width=upload_result.get("width"),
                height=upload_result.get("height"),
                headline=headline,
                description=description,
                features=features,
                call_to_action=call_to_action,
                source="generated",
                source_campaign_id=campaign_id,
                is_generated=True
            )

            self.db.add(asset)
            self.db.commit()
            self.db.refresh(asset)

            return asset, None

        except Exception as e:
            self.db.rollback()
            print(f"[Asset] Generation error: {e}")
            return None, str(e)

    def delete_asset(self, asset_id: uuid.UUID) -> Tuple[bool, Optional[str]]:
        """
        Delete asset from Cloudinary and database.
        Returns (success, error_message)
        """
        try:
            asset = self.db.query(Asset).filter(Asset.id == asset_id).first()
            if not asset:
                return False, "Asset not found"

            # Delete from Cloudinary
            if asset.cloudinary_public_id:
                try:
                    cloudinary.uploader.destroy(
                        asset.cloudinary_public_id,
                        resource_type="video" if asset.file_type == AssetType.VIDEO else "image"
                    )
                except Exception as e:
                    print(f"[Cloudinary] Delete warning: {e}")

            # Delete from database
            self.db.delete(asset)
            self.db.commit()

            return True, None

        except Exception as e:
            self.db.rollback()
            return False, str(e)

    def get_store_assets(
        self,
        store_id: uuid.UUID,
        file_type: Optional[AssetType] = None,
        source: Optional[str] = None,
        page: int = 1,
        size: int = 20
    ) -> Tuple[List[Asset], int]:
        """Get assets for a store with pagination."""
        query = self.db.query(Asset).filter(
            Asset.store_id == store_id,
            Asset.is_active == True
        )

        if file_type:
            query = query.filter(Asset.file_type == file_type)

        if source:
            query = query.filter(Asset.source == source)

        total = query.count()
        assets = query.order_by(Asset.created_at.desc()).offset((page - 1) * size).limit(size).all()

        return assets, total

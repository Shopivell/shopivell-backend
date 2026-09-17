# modules/assets/service.py
"""
Asset service for MinIO uploads (primary) with Cloudinary fallback and AI image generation.
"""
import os
import io
import uuid
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from openai import OpenAI

from .models import Asset, AssetType

load_dotenv()

# ============================================
# MinIO Configuration (Primary)
# ============================================
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "shopivell-assets")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "")

MINIO_CONFIGURED = bool(MINIO_ACCESS_KEY and MINIO_SECRET_KEY)

minio_client = None
if MINIO_CONFIGURED:
    try:
        from minio import Minio
        minio_client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_USE_SSL
        )
        # Ensure bucket exists
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            # Set bucket policy for public read access
            import json
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{MINIO_BUCKET}/*"]
                    }
                ]
            }
            minio_client.set_bucket_policy(MINIO_BUCKET, json.dumps(policy))
        print(f"[AssetService] MinIO configured: endpoint={MINIO_ENDPOINT}, bucket={MINIO_BUCKET}")
    except Exception as e:
        print(f"[AssetService] MinIO init error: {e}")
        minio_client = None

# ============================================
# Cloudinary Configuration (Fallback)
# ============================================
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

if CLOUDINARY_CONFIGURED:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True
    )

print(f"[AssetService] Storage: MinIO={'yes' if minio_client else 'no'}, Cloudinary={'yes' if CLOUDINARY_CONFIGURED else 'no'}")

# Local upload directory for fallback
LOCAL_UPLOAD_DIR = Path("uploads/assets")
LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Initialize OpenAI for image generation
openai_api_key = os.getenv("OPENAI_API_KEY")


STOREFRONT_URL = os.getenv("STOREFRONT_URL", "")
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "https://api.shopivell.com/v1")


def _get_minio_url(object_name: str) -> str:
    """Build the public URL for a MinIO object.
    Uses backend proxy endpoint for reliable access."""
    # Use backend proxy for serving files (most reliable)
    return f"{API_PUBLIC_URL}/api/assets/file/{object_name}"


def generate_image_bytes(prompt: str) -> Tuple[Optional[bytes], Optional[str]]:
    """PNG bytes from the OpenRouter image model (AD_IMAGE_MODEL).

    OpenRouter has no /images/generations: image models return the image as a data URI
    in message.images on the chat endpoint. No DB access, so safe in worker threads."""
    import base64
    import requests
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return None, "OPENROUTER_API_KEY not configured"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "HTTP-Referer": "https://shopivell.com",
                     "X-Title": "Shopivell Ad Images", "Content-Type": "application/json"},
            json={"model": os.getenv("AD_IMAGE_MODEL", "openai/gpt-5-image-mini"),
                  "modalities": ["image", "text"],
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=180,
        )
        if r.status_code >= 400:
            return None, f"Image generation failed ({r.status_code}): {r.text[:150]}"
        images = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("images") or []
        data_url = ((images[0].get("image_url") or {}).get("url") or "") if images else ""
        if not data_url:
            return None, "Image model returned no image"
        return base64.b64decode(data_url.split(",", 1)[-1]), None
    except Exception as e:
        return None, f"Image generation error: {e}"


class AssetService:
    def __init__(self, db: Session):
        self.db = db
        self.openai = OpenAI(api_key=openai_api_key) if openai_api_key else None

    def upload_to_minio(
        self,
        file_data: bytes,
        filename: str,
        store_id: uuid.UUID,
        content_type: str = "application/octet-stream"
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Upload a file to MinIO. Returns (result, error_message)."""
        try:
            # Build object path
            file_ext = filename.rsplit('.', 1)[-1] if '.' in filename else 'bin'
            object_name = f"stores/{store_id}/assets/{uuid.uuid4().hex}_{filename}"

            # Upload
            minio_client.put_object(
                MINIO_BUCKET,
                object_name,
                io.BytesIO(file_data),
                length=len(file_data),
                content_type=content_type
            )

            url = _get_minio_url(object_name)

            return {
                "public_id": object_name,
                "url": url,
                "secure_url": url,
                "thumbnail_url": url,
                "width": None,
                "height": None,
                "format": file_ext,
                "resource_type": "video" if content_type.startswith("video/") else "image",
                "bytes": len(file_data)
            }, None

        except Exception as e:
            print(f"[MinIO] Upload error: {e}")
            return None, str(e)

    def upload_to_cloudinary(
        self,
        file_data: bytes,
        filename: str,
        store_id: uuid.UUID,
        resource_type: str = "auto"
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Upload a file to Cloudinary. Returns (upload_result, error_message)."""
        try:
            import cloudinary.uploader
            folder = f"shopivell/stores/{store_id}/assets"
            result = cloudinary.uploader.upload(
                file_data,
                folder=folder,
                resource_type=resource_type,
                public_id=f"{uuid.uuid4()}_{filename.split('.')[0]}",
                overwrite=True,
                eager=[
                    {"width": 300, "height": 300, "crop": "fill", "format": "jpg"}
                ],
                eager_async=False
            )

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
        """Save file locally when no cloud storage is configured."""
        try:
            store_folder = LOCAL_UPLOAD_DIR / str(store_id)
            store_folder.mkdir(parents=True, exist_ok=True)

            file_ext = filename.split('.')[-1] if '.' in filename else 'bin'
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = store_folder / unique_filename

            with open(file_path, 'wb') as f:
                f.write(file_data)

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

    def _upload_file(
        self,
        file_data: bytes,
        filename: str,
        store_id: uuid.UUID,
        content_type: str = "application/octet-stream",
        resource_type: str = "auto"
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Upload using MinIO (primary), Cloudinary (fallback), or local storage."""
        if minio_client:
            return self.upload_to_minio(file_data, filename, store_id, content_type)
        elif CLOUDINARY_CONFIGURED:
            return self.upload_to_cloudinary(file_data, filename, store_id, resource_type)
        else:
            print("[Asset] No cloud storage configured, saving locally")
            return self.save_locally(file_data, filename, store_id)

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
        """Upload file and create asset record."""
        try:
            resource_type = "video" if file_type == AssetType.VIDEO else "image"

            upload_result, error = self._upload_file(
                file_data=file_data,
                filename=filename,
                store_id=store_id,
                content_type=mime_type,
                resource_type=resource_type
            )

            if error:
                return None, error

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
        """Generate an ad image (OpenRouter image model, or DALL-E without an OpenRouter key)."""
        import os as _os
        if not self.openai and not _os.getenv("OPENROUTER_API_KEY", ""):
            return None, "No OPENROUTER_API_KEY / OPENAI_API_KEY configured"

        try:
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

            if _os.getenv("OPENROUTER_API_KEY", ""):
                image_data, error = generate_image_bytes(prompt)
                if error:
                    return None, error
            else:
                import requests as _requests
                response = self.openai.images.generate(
                    model="dall-e-3",
                    prompt=prompt,
                    size="1024x1024",
                    quality="standard",
                    n=1
                )
                img_response = _requests.get(response.data[0].url)
                if img_response.status_code != 200:
                    return None, "Failed to download generated image"
                image_data = img_response.content

            return self.save_generated_image(store_id, image_data, headline, description=description,
                                             features=features, call_to_action=call_to_action,
                                             campaign_id=campaign_id)

        except Exception as e:
            self.db.rollback()
            print(f"[Asset] Generation error: {e}")
            return None, str(e)

    def save_generated_image(
        self,
        store_id: uuid.UUID,
        image_data: bytes,
        headline: str,
        description: Optional[str] = None,
        features: Optional[List[str]] = None,
        call_to_action: Optional[str] = None,
        campaign_id: Optional[uuid.UUID] = None
    ) -> Tuple[Optional[Asset], Optional[str]]:
        """Upload generated image bytes to storage and record them as a generated asset."""
        try:
            upload_result, error = self._upload_file(
                file_data=image_data,
                filename=f"generated_{uuid.uuid4().hex[:8]}.png",
                store_id=store_id,
                content_type="image/png",
                resource_type="image"
            )
            if error:
                return None, error

            asset = Asset(
                store_id=store_id,
                name=f"Generated: {(headline or '')[:50]}",
                original_filename="ai-generated.png",
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
                features=features or [],
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
            print(f"[Asset] Save generated image error: {e}")
            return None, str(e)

    def delete_asset(self, asset_id: uuid.UUID) -> Tuple[bool, Optional[str]]:
        """Delete asset from storage and database."""
        try:
            asset = self.db.query(Asset).filter(Asset.id == asset_id).first()
            if not asset:
                return False, "Asset not found"

            # Delete from storage
            if asset.cloudinary_public_id:
                if minio_client and asset.cloudinary_public_id.startswith("stores/"):
                    try:
                        minio_client.remove_object(MINIO_BUCKET, asset.cloudinary_public_id)
                    except Exception as e:
                        print(f"[MinIO] Delete warning: {e}")
                elif CLOUDINARY_CONFIGURED:
                    try:
                        import cloudinary.uploader
                        cloudinary.uploader.destroy(
                            asset.cloudinary_public_id,
                            resource_type="video" if asset.file_type == AssetType.VIDEO else "image"
                        )
                    except Exception as e:
                        print(f"[Cloudinary] Delete warning: {e}")

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

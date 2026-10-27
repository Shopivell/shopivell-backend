# modules/assets/router.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid

from database import get_db
from .models import Asset, AssetType
from .schemas import (
    AssetCreate, AssetUpdate, AssetResponse, AssetListResponse,
    GenerateAssetRequest
)
from .service import AssetService

asset_router = APIRouter(prefix="/api/assets", tags=["assets"])


@asset_router.post("/upload", response_model=AssetResponse)
async def upload_asset(
    file: UploadFile = File(...),
    store_id: uuid.UUID = Form(...),
    name: Optional[str] = Form(None),
    campaign_id: Optional[uuid.UUID] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload an image or video asset to Cloudinary."""
    print(f"[Asset Upload] Received file: {file.filename}, store_id: {store_id}, name: {name}")

    # Validate file type
    content_type = file.content_type or ""
    print(f"[Asset Upload] Content type: {content_type}")

    if content_type.startswith("image/"):
        file_type = AssetType.IMAGE
    elif content_type.startswith("video/"):
        file_type = AssetType.VIDEO
    else:
        print(f"[Asset Upload] Unsupported file type: {content_type}")
        raise HTTPException(status_code=400, detail="Unsupported file type. Only images and videos are allowed.")

    # Read file data
    file_data = await file.read()
    print(f"[Asset Upload] File size: {len(file_data)} bytes")

    if len(file_data) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 50MB.")

    service = AssetService(db)
    asset, error = service.create_asset_from_upload(
        store_id=store_id,
        filename=file.filename or "unnamed",
        file_data=file_data,
        mime_type=content_type,
        file_type=file_type,
        name=name,
        source_campaign_id=campaign_id
    )

    if error:
        print(f"[Asset Upload] Error: {error}")
        raise HTTPException(status_code=500, detail=error)

    print(f"[Asset Upload] Success! Asset ID: {asset.id}, URL: {asset.cloudinary_secure_url}")
    return AssetResponse.model_validate(asset)


@asset_router.post("/generate", response_model=AssetResponse)
def generate_asset(
    request: GenerateAssetRequest,
    db: Session = Depends(get_db)
):
    """Generate an ad image using AI (DALL-E)."""
    # System-wide AI metering: image generation draws on the same token wallet
    # as the agent. Free for zero-balance users; charged per use otherwise.
    try:
        from modules.stores.models import Store as _Store
        _store = db.query(_Store).filter(_Store.id == request.store_id).first()
        if _store is not None:
            from modules.agent.credits import charge_system
            from modules.agent.credit_costs import cost_of
            charge_system(db, _store.owner_id, cost_of("ad_image"), "system:ad_image",
                          detail=f"Asset image for store {request.store_id}", store_id=request.store_id)
    except Exception as _meter_err:
        print(f"[Assets] AI metering skipped (non-fatal): {_meter_err}")
    service = AssetService(db)
    asset, error = service.generate_ad_image(
        store_id=request.store_id,
        headline=request.headline,
        description=request.description,
        features=request.features,
        call_to_action=request.call_to_action,
        style=request.style,
        color_scheme=request.color_scheme,
        campaign_id=request.campaign_id
    )

    if error:
        raise HTTPException(status_code=500, detail=error)

    return AssetResponse.model_validate(asset)


@asset_router.get("/store/{store_id}", response_model=AssetListResponse)
def get_store_assets(
    store_id: uuid.UUID,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    file_type: Optional[AssetType] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all assets for a store."""
    service = AssetService(db)
    assets, total = service.get_store_assets(
        store_id=store_id,
        file_type=file_type,
        source=source,
        page=page,
        size=size
    )

    return AssetListResponse(
        assets=[AssetResponse.model_validate(a) for a in assets],
        total=total,
        page=page,
        size=size
    )


@asset_router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific asset."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse.model_validate(asset)


@asset_router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: uuid.UUID,
    update_data: AssetUpdate,
    db: Session = Depends(get_db)
):
    """Update asset metadata."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(asset, field, value)

    db.commit()
    db.refresh(asset)
    return AssetResponse.model_validate(asset)


@asset_router.delete("/{asset_id}")
def delete_asset(asset_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete an asset from Cloudinary and database."""
    service = AssetService(db)
    success, error = service.delete_asset(asset_id)

    if not success:
        raise HTTPException(status_code=404 if error == "Asset not found" else 500, detail=error)

    return {"message": "Asset deleted successfully"}


@asset_router.get("/campaign/{campaign_id}", response_model=List[AssetResponse])
def get_campaign_assets(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all assets associated with a campaign."""
    assets = db.query(Asset).filter(
        Asset.source_campaign_id == campaign_id,
        Asset.is_active == True
    ).all()
    return [AssetResponse.model_validate(a) for a in assets]


# ============================================
# SIMPLE IMAGE UPLOAD (No Asset record)
# ============================================

@asset_router.post("/upload-image")
async def upload_image_simple(
    file: UploadFile = File(...),
    folder: str = Form("shopivell/uploads")
):
    """
    Simple image upload - returns URL only.
    Uses MinIO (primary) or Cloudinary (fallback).
    No asset record is created.
    """
    from .service import minio_client, MINIO_BUCKET, MINIO_CONFIGURED, CLOUDINARY_CONFIGURED, _get_minio_url
    import io

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    file_data = await file.read()

    if len(file_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    try:
        if minio_client:
            import uuid as _uuid
            file_ext = file.filename.rsplit('.', 1)[-1] if file.filename and '.' in file.filename else 'jpg'
            object_name = f"{folder}/{_uuid.uuid4().hex}.{file_ext}"
            minio_client.put_object(
                MINIO_BUCKET, object_name, io.BytesIO(file_data),
                length=len(file_data), content_type=content_type
            )
            url = _get_minio_url(object_name)
            return {
                "success": True, "url": url, "public_id": object_name,
                "thumbnail_url": url, "width": None, "height": None,
                "format": file_ext, "bytes": len(file_data)
            }
        elif CLOUDINARY_CONFIGURED:
            import cloudinary.uploader
            result = cloudinary.uploader.upload(
                file_data, folder=folder, resource_type="image", overwrite=True,
                eager=[{"width": 300, "height": 300, "crop": "fill", "format": "jpg"}],
                eager_async=False
            )
            thumbnail_url = None
            if result.get("eager") and len(result["eager"]) > 0:
                thumbnail_url = result["eager"][0].get("secure_url")
            return {
                "success": True, "url": result.get("secure_url"),
                "public_id": result.get("public_id"), "thumbnail_url": thumbnail_url,
                "width": result.get("width"), "height": result.get("height"),
                "format": result.get("format"), "bytes": result.get("bytes")
            }
        else:
            raise HTTPException(status_code=503, detail="No storage backend configured")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Upload] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@asset_router.get("/debug/whatsapp-webhook-token")
async def get_webhook_token(db: Session = Depends(get_db)):
    """Debug: get WhatsApp webhook verify tokens. Auto-sets if null."""
    from sqlalchemy import text
    try:
        # Auto-set token if null
        db.execute(text("""
            UPDATE whatsapp_accounts
            SET webhook_verify_token = 'shopivell_webhook_verify_2026'
            WHERE webhook_verify_token IS NULL
        """))
        db.commit()
        result = db.execute(text("SELECT id, phone_number, webhook_verify_token, waba_id, phone_number_id FROM whatsapp_accounts"))
        rows = result.fetchall()
        return [{"id": str(r[0]), "phone": r[1], "token": r[2], "waba_id": r[3], "phone_number_id": r[4]} for r in rows]
    except Exception as e:
        return {"error": str(e)}


@asset_router.get("/debug/insights-status")
async def insights_status(db: Session = Depends(get_db)):
    """Debug: check if Meta ad insights are being collected."""
    from sqlalchemy import text
    try:
        # Count insights
        result = db.execute(text("SELECT COUNT(*) FROM meta_ad_insights"))
        total = result.scalar()

        # Get date range
        result2 = db.execute(text("SELECT MIN(date), MAX(date) FROM meta_ad_insights"))
        row = result2.fetchone()

        # Get sample
        result3 = db.execute(text("SELECT ad_id, date, impressions, clicks, spend, conversions FROM meta_ad_insights ORDER BY date DESC LIMIT 3"))
        samples = [{"ad_id": r[0], "date": str(r[1]), "impressions": r[2], "clicks": r[3], "spend": float(r[4]) if r[4] else 0, "conversions": r[5]} for r in result3.fetchall()]

        return {
            "total_insights": total,
            "date_range": {"min": str(row[0]) if row[0] else None, "max": str(row[1]) if row[1] else None},
            "recent_samples": samples,
        }
    except Exception as e:
        return {"error": str(e)}


@asset_router.get("/debug/storage-status")
async def storage_status():
    """Debug: check storage configuration status."""
    from .service import minio_client, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_CONFIGURED
    from .service import CLOUDINARY_CONFIGURED

    minio_test = None
    if minio_client:
        try:
            exists = minio_client.bucket_exists(MINIO_BUCKET)
            minio_test = f"bucket '{MINIO_BUCKET}' exists={exists}"
        except Exception as e:
            minio_test = f"error: {e}"

    # Test media_generator's upload path
    media_gen_minio = None
    try:
        from modules.agents.media_generator_agent import MediaGeneratorAgent
        mg = MediaGeneratorAgent()
        # Import what the method imports
        from modules.assets.service import minio_client as mc2
        media_gen_minio = f"minio_client is {'set' if mc2 else 'None'}"
    except Exception as e:
        media_gen_minio = f"import error: {e}"

    return {
        "minio_configured": MINIO_CONFIGURED,
        "minio_client": "connected" if minio_client else "None",
        "minio_endpoint": MINIO_ENDPOINT,
        "minio_bucket": MINIO_BUCKET,
        "minio_test": minio_test,
        "cloudinary_configured": CLOUDINARY_CONFIGURED,
        "media_generator_minio": media_gen_minio,
    }


@asset_router.get("/file/{object_path:path}")
async def serve_minio_file(object_path: str):
    """Proxy to serve MinIO files through the backend API."""
    from .service import minio_client, MINIO_BUCKET
    from fastapi.responses import StreamingResponse

    if not minio_client:
        raise HTTPException(status_code=503, detail="Storage not configured")

    try:
        response = minio_client.get_object(MINIO_BUCKET, object_path)
        # Determine content type from extension
        ext = object_path.rsplit('.', 1)[-1].lower() if '.' in object_path else ''
        content_types = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
            'mp4': 'video/mp4', 'webm': 'video/webm', 'pdf': 'application/pdf',
        }
        content_type = content_types.get(ext, 'application/octet-stream')

        return StreamingResponse(
            response,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000"}
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")

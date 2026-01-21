# modules/website_builder/router.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import asyncio

from database import get_db
from dependencies import get_current_user, CurrentUser

from .models import Website, WebsiteGeneration, WebsiteStatus, GenerationStatus
from .schemas import (
    WebsiteCreate, WebsiteUpdate, WebsiteResponse, WebsiteListResponse,
    GenerationRequest, GenerationStatusResponse,
    ChatMessage, ChatResponse,
    PreviewResponse, CodeExportResponse, CodeFileResponse,
    DeployRequest, DeployResponse
)
from .generation_service import website_generation_service

router = APIRouter(prefix="/api/website-builder", tags=["Website Builder"])


# Helper to run async in background
def run_async_generation(db_session_factory, website_id: UUID, generation_id: UUID, prompt: str, screens: List[str]):
    """Run website generation in background"""
    async def _generate():
        from database import SessionLocal
        db = SessionLocal()
        try:
            website = db.query(Website).filter(Website.id == website_id).first()
            generation = db.query(WebsiteGeneration).filter(WebsiteGeneration.id == generation_id).first()
            if website and generation:
                await website_generation_service.generate_website(db, website, generation, prompt, screens)
        finally:
            db.close()

    asyncio.run(_generate())


@router.get("/websites", response_model=WebsiteListResponse)
async def list_websites(
    store_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all websites for a store"""
    websites = db.query(Website).filter(Website.store_id == store_id).order_by(Website.created_at.desc()).all()
    return WebsiteListResponse(
        websites=[WebsiteResponse.model_validate(w) for w in websites],
        total=len(websites)
    )


@router.post("/websites", response_model=WebsiteResponse)
async def create_website(
    data: WebsiteCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new website"""
    website = Website(
        store_id=data.store_id,
        name=data.name,
        description=data.description,
        status=WebsiteStatus.DRAFT,
        pages={},
        theme={},
        integrations={}
    )
    db.add(website)
    db.commit()
    db.refresh(website)

    return WebsiteResponse.model_validate(website)


@router.get("/websites/store/{store_id}", response_model=Optional[WebsiteResponse])
async def get_website_by_store(
    store_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the most recent website for a store"""
    website = db.query(Website).filter(
        Website.store_id == store_id
    ).order_by(Website.created_at.desc()).first()

    if not website:
        return None

    return WebsiteResponse.model_validate(website)


@router.get("/websites/{website_id}", response_model=WebsiteResponse)
async def get_website(
    website_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific website"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    return WebsiteResponse.model_validate(website)


@router.put("/websites/{website_id}", response_model=WebsiteResponse)
async def update_website(
    website_id: UUID,
    data: WebsiteUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update website details"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    if data.name is not None:
        website.name = data.name
    if data.description is not None:
        website.description = data.description
    if data.theme is not None:
        website.theme = data.theme
    if data.integrations is not None:
        website.integrations = data.integrations

    db.commit()
    db.refresh(website)

    return WebsiteResponse.model_validate(website)


@router.delete("/websites/{website_id}")
async def delete_website(
    website_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a website"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    db.delete(website)
    db.commit()

    return {"message": "Website deleted successfully"}


@router.post("/websites/{website_id}/generate", response_model=GenerationStatusResponse)
async def start_generation(
    website_id: UUID,
    data: GenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start AI website generation"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    # Check if already generating
    if website.status == WebsiteStatus.GENERATING:
        existing = db.query(WebsiteGeneration).filter(
            WebsiteGeneration.website_id == website_id,
            WebsiteGeneration.status == GenerationStatus.PROCESSING
        ).first()
        if existing:
            return GenerationStatusResponse.model_validate(existing)

    # Create generation record
    generation = WebsiteGeneration(
        website_id=website_id,
        store_id=website.store_id,
        prompt=data.prompt,
        selected_screens=data.selected_screens,
        status=GenerationStatus.PENDING
    )
    db.add(generation)

    # Update website status
    website.status = WebsiteStatus.GENERATING
    db.commit()
    db.refresh(generation)

    # Start background generation
    from database import SessionLocal
    background_tasks.add_task(
        run_async_generation,
        SessionLocal,
        website_id,
        generation.id,
        data.prompt,
        data.selected_screens
    )

    return GenerationStatusResponse.model_validate(generation)


@router.get("/websites/{website_id}/generation-status", response_model=GenerationStatusResponse)
async def get_generation_status(
    website_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the latest generation status for a website"""
    generation = db.query(WebsiteGeneration).filter(
        WebsiteGeneration.website_id == website_id
    ).order_by(WebsiteGeneration.created_at.desc()).first()

    if not generation:
        raise HTTPException(status_code=404, detail="No generation found")

    return GenerationStatusResponse.model_validate(generation)


@router.get("/websites/{website_id}/preview", response_model=PreviewResponse)
async def get_preview(
    website_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the preview HTML for a website"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    return PreviewResponse(
        html=website.preview_html or "",
        pages=website.pages or {}
    )


@router.get("/websites/{website_id}/code", response_model=CodeExportResponse)
async def get_code(
    website_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the generated code files for export"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    files = []

    # Add each page as a file
    for page_name, html in (website.pages or {}).items():
        files.append(CodeFileResponse(
            filename=f"{page_name}.html",
            content=html,
            language="html"
        ))

    # Add package.json for a simple static site
    package_json = """{
  "name": "%s",
  "version": "1.0.0",
  "scripts": {
    "dev": "npx serve .",
    "build": "echo 'Static site - no build required'"
  }
}""" % website.name.lower().replace(" ", "-")

    files.append(CodeFileResponse(
        filename="package.json",
        content=package_json,
        language="json"
    ))

    # README
    readme = f"""# {website.name}

Generated with Shopivell AI Website Builder.

## Quick Start

1. Install dependencies: `npm install`
2. Run locally: `npm run dev`
3. Open http://localhost:3000

## Files

{chr(10).join(f'- {f.filename}' for f in files if f.filename != 'README.md')}

## Deployment

This is a static website. You can deploy it to:
- Vercel: `npx vercel`
- Netlify: Drag and drop the folder
- GitHub Pages: Push to gh-pages branch
"""

    files.append(CodeFileResponse(
        filename="README.md",
        content=readme,
        language="markdown"
    ))

    return CodeExportResponse(files=files, readme=readme)


@router.put("/websites/{website_id}/integrations", response_model=WebsiteResponse)
async def update_integrations(
    website_id: UUID,
    integrations: dict,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update website integrations"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    # Merge integrations
    current_integrations = website.integrations or {}
    current_integrations.update(integrations)
    website.integrations = current_integrations

    # Re-apply integrations to preview HTML if exists
    if website.preview_html:
        from .generation_service import website_generation_service
        website.preview_html = website_generation_service._inject_integrations(
            website.preview_html,
            website.integrations
        )

    db.commit()
    db.refresh(website)

    return WebsiteResponse.model_validate(website)


@router.post("/websites/{website_id}/chat", response_model=ChatResponse)
async def chat_refinement(
    website_id: UUID,
    data: ChatMessage,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send a chat message to refine the website"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    if not website.preview_html:
        return ChatResponse(
            message="Please generate your website first before making refinements.",
            updated_html=None
        )

    result = await website_generation_service.refine_website(db, website, data.message)

    return ChatResponse(
        message=result["message"],
        updated_html=result.get("updated_html")
    )


@router.post("/websites/{website_id}/deploy", response_model=DeployResponse)
async def deploy_website(
    website_id: UUID,
    data: Optional[DeployRequest] = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deploy the website (placeholder for actual deployment)"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")

    if website.status != WebsiteStatus.READY:
        raise HTTPException(status_code=400, detail="Website must be ready before deployment")

    # For now, just update status - actual deployment would integrate with hosting provider
    website.status = WebsiteStatus.DEPLOYED
    website.deployed_url = f"https://{website.name.lower().replace(' ', '-')}.shopivell.site"

    if data and data.custom_domain:
        website.custom_domain = data.custom_domain

    db.commit()
    db.refresh(website)

    return DeployResponse(
        deployed_url=website.deployed_url,
        status="deployed",
        message="Website deployed successfully! Note: Actual hosting integration coming soon."
    )


# Export router
website_builder_router = router

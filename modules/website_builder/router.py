# modules/website_builder/router.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import asyncio
import os
import logging
import uuid as uuid_module
from pathlib import Path
from copy import deepcopy

from database import get_db
from dependencies import get_current_user, CurrentUser

from .models import (
    Website, WebsiteGeneration, WebsiteStatus, GenerationStatus,
    WebsiteTemplate, WebsiteProjectPage, WebsiteProjectVersion, WebsiteInboxMessage, WebsiteMediaAsset,
)
from .schemas import (
    WebsiteCreate, WebsiteUpdate, WebsiteResponse, WebsiteListResponse,
    GenerationRequest, GenerationStatusResponse,
    ChatMessage, ChatResponse,
    PreviewResponse, CodeExportResponse, CodeFileResponse,
    DeployRequest, DeployResponse
)
from .schemas import WebsiteTemplateResponse, WebsiteTemplatePageResponse, WebsiteProjectPageResponse, WebsiteProjectPageUpdate, WebsiteVersionCreate, WebsiteTemplateInput, WebsiteTemplatePageInput, WebsitePageOrder
from .schemas import WebsiteChatMessageCreate
from .generation_service import website_generation_service
from .template_catalog import ensure_starter_templates

router = APIRouter(prefix="/api/website-builder", tags=["Website Builder"])
logger = logging.getLogger(__name__)


def _require_store(user: CurrentUser, store_id: UUID) -> None:
    if user.role.upper() in {"ADMIN", "SUPER_ADMIN"}:
        return
    if not user.store_id or str(store_id) != str(user.store_id):
        raise HTTPException(status_code=403, detail="You can only manage websites for your selected store")


def _owned_website(db: Session, website_id: UUID, user: CurrentUser) -> Website:
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    _require_store(user, website.store_id)
    return website


def _version_snapshot(db: Session, website: Website, user: CurrentUser, notes: str | None) -> WebsiteProjectVersion:
    pages = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.website_id == website.id).order_by(WebsiteProjectPage.sort_order).all()
    latest = db.query(WebsiteProjectVersion.version_number).filter(
        WebsiteProjectVersion.website_id == website.id
    ).order_by(WebsiteProjectVersion.version_number.desc()).first()
    version = WebsiteProjectVersion(
        website_id=website.id,
        version_number=(latest[0] if latest else 0) + 1,
        project_json={
            "website": {"name": website.name, "description": website.description, "theme": website.theme or {}},
            "pages": [{
                "id": str(page.id), "page_name": page.page_name, "route_path": page.route_path,
                "sort_order": page.sort_order, "grapesjs_project_json": deepcopy(page.grapesjs_project_json),
            } for page in pages],
        },
        created_by=user.id,
        notes=notes,
    )
    db.add(version)
    db.flush()
    return version


@router.get("/templates", response_model=List[WebsiteTemplateResponse])
async def list_templates(db: Session = Depends(get_db)):
    """List published SiteForge starter templates."""
    ensure_starter_templates(db)
    return db.query(WebsiteTemplate).filter(WebsiteTemplate.is_published.is_(True)).order_by(WebsiteTemplate.category, WebsiteTemplate.name).all()


@router.get("/templates/{template_id}", response_model=WebsiteTemplateResponse)
async def get_template(template_id: UUID, db: Session = Depends(get_db)):
    ensure_starter_templates(db)
    template = db.query(WebsiteTemplate).filter(WebsiteTemplate.id == template_id, WebsiteTemplate.is_published.is_(True)).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def _require_admin(user: CurrentUser) -> None:
    if user.role.upper() not in {"ADMIN", "SUPER_ADMIN"}:
        raise HTTPException(status_code=403, detail="Administrator access required")


@router.post("/templates", response_model=WebsiteTemplateResponse, status_code=201)
async def create_template(body: WebsiteTemplateInput, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(current_user)
    if db.query(WebsiteTemplate.id).filter(WebsiteTemplate.slug == body.slug).first():
        raise HTTPException(status_code=409, detail="A template with this slug already exists")
    data = body.model_dump(exclude={"pages"})
    template = WebsiteTemplate(**data, created_by=str(current_user.id))
    db.add(template)
    db.flush()
    for item in body.pages or []:
        db.add(WebsiteTemplatePage(template_id=template.id, **item.model_dump()))
    db.commit()
    db.refresh(template)
    return template


@router.put("/templates/{template_id}", response_model=WebsiteTemplateResponse)
async def update_template(template_id: UUID, body: WebsiteTemplateInput, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(current_user)
    template = db.query(WebsiteTemplate).filter(WebsiteTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    duplicate = db.query(WebsiteTemplate.id).filter(WebsiteTemplate.slug == body.slug, WebsiteTemplate.id != template_id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A template with this slug already exists")
    for key, value in body.model_dump(exclude={"pages"}).items():
        setattr(template, key, value)
    if body.pages is not None:
        template.pages.clear()
        db.flush()
        for item in body.pages:
            db.add(WebsiteTemplatePage(template_id=template.id, **item.model_dump()))
    db.commit()
    db.refresh(template)
    return template


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(current_user)
    template = db.query(WebsiteTemplate).filter(WebsiteTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return None


@router.post("/templates/{template_id}/pages", response_model=WebsiteTemplatePageResponse, status_code=201)
async def add_template_page(template_id: UUID, body: WebsiteTemplatePageInput, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(current_user)
    template = db.query(WebsiteTemplate).filter(WebsiteTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    page = WebsiteTemplatePage(template_id=template.id, **body.model_dump())
    db.add(page); db.commit(); db.refresh(page)
    return page


@router.put("/templates/{template_id}/pages/{page_id}", response_model=WebsiteTemplatePageResponse)
async def update_template_page(template_id: UUID, page_id: UUID, body: WebsiteTemplatePageInput, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(current_user)
    page = db.query(WebsiteTemplatePage).filter(WebsiteTemplatePage.id == page_id, WebsiteTemplatePage.template_id == template_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Template page not found")
    for key, value in body.model_dump().items(): setattr(page, key, value)
    db.commit(); db.refresh(page)
    return page


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
    _require_store(current_user, store_id)
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
    _require_store(current_user, data.store_id)
    template = None
    if data.template_id:
        ensure_starter_templates(db)
        template = db.query(WebsiteTemplate).filter(
            WebsiteTemplate.id == data.template_id,
            WebsiteTemplate.is_published.is_(True),
        ).first()
        if not template:
            raise HTTPException(status_code=404, detail="Published template not found")
    website = Website(
        store_id=data.store_id,
        name=data.name,
        description=data.description,
        status=WebsiteStatus.DRAFT,
        pages={},
        theme={**(data.theme or {}), **({
            "template_id": str(template.id),
            "template_name": template.name,
            "template_slug": template.slug,
        } if template else {})},
        integrations={}
    )
    db.add(website)
    db.commit()
    db.refresh(website)

    if template:
        # Copy each template page into rows owned by this project. The source
        # template remains immutable when users edit their copies.
        for template_page in template.pages:
            db.add(WebsiteProjectPage(
                website_id=website.id,
                template_page_id=template_page.id,
                page_name=template_page.page_name,
                route_path=template_page.route_path,
                sort_order=template_page.sort_order,
                grapesjs_project_json=deepcopy(template_page.grapesjs_project_json),
            ))
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
    _require_store(current_user, store_id)
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
    website = _owned_website(db, website_id, current_user)

    return WebsiteResponse.model_validate(website)


@router.put("/websites/{website_id}", response_model=WebsiteResponse)
async def update_website(
    website_id: UUID,
    data: WebsiteUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update website details"""
    website = _owned_website(db, website_id, current_user)

    if data.name is not None:
        website.name = data.name
    if data.description is not None:
        website.description = data.description
    if data.theme is not None:
        website.theme = data.theme
    if data.integrations is not None:
        website.integrations = data.integrations
    if data.preview_html is not None:
        website.preview_html = data.preview_html

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
    website = _owned_website(db, website_id, current_user)

    db.delete(website)
    db.commit()

    return {"message": "Website deleted successfully"}


@router.post("/websites/{website_id}/duplicate", response_model=WebsiteResponse, status_code=201)
async def duplicate_website(website_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    source = _owned_website(db, website_id, current_user)
    copied = Website(
        store_id=source.store_id, name=f"{source.name} copy", description=source.description,
        status=WebsiteStatus.READY if source.preview_html else WebsiteStatus.DRAFT,
        pages=deepcopy(source.pages or {}), theme=deepcopy(source.theme or {}),
        integrations=deepcopy(source.integrations or {}), preview_html=source.preview_html,
        generated_code=source.generated_code,
    )
    db.add(copied); db.flush()
    source_pages = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.website_id == source.id).all()
    for page in source_pages:
        db.add(WebsiteProjectPage(website_id=copied.id, template_page_id=page.template_page_id, page_name=page.page_name, route_path=page.route_path, sort_order=page.sort_order, grapesjs_project_json=deepcopy(page.grapesjs_project_json)))
    db.commit(); db.refresh(copied)
    return WebsiteResponse.model_validate(copied)


@router.post("/websites/{website_id}/generate", response_model=GenerationStatusResponse)
async def start_generation(
    website_id: UUID,
    data: GenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start AI website generation"""
    website = _owned_website(db, website_id, current_user)

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
    _owned_website(db, website_id, current_user)
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
    website = _owned_website(db, website_id, current_user)

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
    website = _owned_website(db, website_id, current_user)

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


@router.get("/websites/{website_id}/pages", response_model=List[WebsiteProjectPageResponse])
async def list_project_pages(website_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    website = _owned_website(db, website_id, current_user)
    pages = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.website_id == website_id).order_by(WebsiteProjectPage.sort_order).all()
    if not pages:
        # Upgrade legacy AI-builder sites into an editable home page on first visit.
        page = WebsiteProjectPage(
            website_id=website.id, page_name="Home", route_path="/", sort_order=0,
            grapesjs_project_json={"assets": [], "styles": [], "pages": [{"name": "Home", "component": website.preview_html or "<main><h1>Welcome</h1><p>Edit your website content here.</p></main>"}]},
        )
        db.add(page)
        db.commit()
        db.refresh(page)
        pages = [page]
    return pages


@router.post("/websites/{website_id}/pages", response_model=WebsiteProjectPageResponse, status_code=201)
async def add_project_page(website_id: UUID, body: WebsiteProjectPageUpdate, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    website = _owned_website(db, website_id, current_user)
    if not body.page_name or not body.route_path:
        raise HTTPException(status_code=422, detail="page_name and route_path are required")
    page = WebsiteProjectPage(
        website_id=website.id, page_name=body.page_name, route_path=body.route_path,
        sort_order=body.sort_order if body.sort_order is not None else 999,
        grapesjs_project_json=body.grapesjs_project_json or {"assets": [], "styles": [], "pages": [{"name": body.page_name, "component": {"type": "wrapper", "components": []}}]},
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


@router.put("/websites/{website_id}/pages/reorder")
async def reorder_project_pages(website_id: UUID, body: WebsitePageOrder, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_website(db, website_id, current_user)
    pages = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.website_id == website_id).all()
    by_id = {page.id: page for page in pages}
    if len(body.page_ids) != len(pages) or set(body.page_ids) != set(by_id):
        raise HTTPException(status_code=422, detail="page_ids must contain each project page exactly once")
    for position, page_id in enumerate(body.page_ids): by_id[page_id].sort_order = position
    db.commit()
    return {"message": "Pages reordered"}


@router.put("/websites/{website_id}/pages/{page_id}", response_model=WebsiteProjectPageResponse)
async def update_project_page(website_id: UUID, page_id: UUID, body: WebsiteProjectPageUpdate, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_website(db, website_id, current_user)
    page = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.id == page_id, WebsiteProjectPage.website_id == website_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Project page not found")
    for field in ("page_name", "route_path", "sort_order", "grapesjs_project_json"):
        value = getattr(body, field)
        if value is not None:
            setattr(page, field, value)
    db.commit()
    db.refresh(page)
    return page


@router.delete("/websites/{website_id}/pages/{page_id}")
async def delete_project_page(website_id: UUID, page_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_website(db, website_id, current_user)
    page = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.id == page_id, WebsiteProjectPage.website_id == website_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Project page not found")
    db.delete(page)
    db.commit()
    return {"message": "Page deleted"}


@router.get("/websites/{website_id}/versions")
async def list_project_versions(website_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_website(db, website_id, current_user)
    versions = db.query(WebsiteProjectVersion).filter(WebsiteProjectVersion.website_id == website_id).order_by(WebsiteProjectVersion.version_number.desc()).all()
    return [{"id": str(v.id), "version_number": v.version_number, "created_at": v.created_at, "created_by": v.created_by, "notes": v.notes} for v in versions]


@router.post("/websites/{website_id}/versions")
async def create_project_version(website_id: UUID, body: WebsiteVersionCreate, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    website = _owned_website(db, website_id, current_user)
    version = _version_snapshot(db, website, current_user, body.notes)
    db.commit()
    db.refresh(version)
    return {"id": str(version.id), "version_number": version.version_number, "created_at": version.created_at, "notes": version.notes}


@router.post("/websites/{website_id}/restore/{version_id}")
async def restore_project_version(website_id: UUID, version_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    website = _owned_website(db, website_id, current_user)
    version = db.query(WebsiteProjectVersion).filter(WebsiteProjectVersion.id == version_id, WebsiteProjectVersion.website_id == website_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    saved_ids = {str(row[0]) for row in db.query(WebsiteProjectPage.id).filter(WebsiteProjectPage.website_id == website_id).all()}
    version_pages = version.project_json.get("pages", [])
    for page_data in version_pages:
        page_id = page_data.get("id")
        page = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.id == page_id, WebsiteProjectPage.website_id == website_id).first() if page_id in saved_ids else None
        if page is None:
            page = WebsiteProjectPage(website_id=website_id, page_name=page_data["page_name"], route_path=page_data["route_path"], sort_order=page_data["sort_order"], grapesjs_project_json=page_data["grapesjs_project_json"])
            db.add(page)
        else:
            page.page_name = page_data["page_name"]
            page.route_path = page_data["route_path"]
            page.sort_order = page_data["sort_order"]
            page.grapesjs_project_json = deepcopy(page_data["grapesjs_project_json"])
    db.commit()
    return {"message": "Version restored", "website_id": str(website.id)}


@router.put("/websites/{website_id}/integrations", response_model=WebsiteResponse)
async def update_integrations(
    website_id: UUID,
    integrations: dict,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update website integrations"""
    website = _owned_website(db, website_id, current_user)

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
    website = _owned_website(db, website_id, current_user)

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
    """Publish a versioned site to its Shopivell hosted URL."""
    website = _owned_website(db, website_id, current_user)

    if website.status != WebsiteStatus.READY:
        raise HTTPException(status_code=400, detail="Website must be ready before deployment")

    _version_snapshot(db, website, current_user, "Automatic snapshot before publish")
    website.status = WebsiteStatus.DEPLOYED
    public_api = os.getenv("PUBLIC_API_URL", "https://api.shopivell.com").rstrip("/")
    website.deployed_url = f"{public_api}/v1/api/website-builder/public/sites/{website.id}"

    if data and data.custom_domain:
        website.custom_domain = data.custom_domain

    db.commit()
    db.refresh(website)

    return DeployResponse(
        deployed_url=website.deployed_url,
        status="deployed",
        message="Website published. Connect a custom domain in Domains when the registrar integration is configured."
    )


@router.get("/public/sites/{website_id}", response_class=HTMLResponse)
async def render_published_site(website_id: UUID, page: str = Query("/"), db: Session = Depends(get_db)):
    website = db.query(Website).filter(Website.id == website_id, Website.status == WebsiteStatus.DEPLOYED).first()
    if not website:
        raise HTTPException(status_code=404, detail="Published site not found")
    page_row = db.query(WebsiteProjectPage).filter(WebsiteProjectPage.website_id == website.id, WebsiteProjectPage.route_path == page).first()
    html = ((page_row.grapesjs_project_json or {}).get("rendered_html") if page_row else None) or website.preview_html or "<main><h1>Site content is being prepared</h1></main>"
    widget = f'''<style>#sf-chat-button{{position:fixed;right:24px;bottom:24px;z-index:2147483000;border:0;border-radius:999px;background:#111827;color:#fff;padding:14px 20px;font:600 15px system-ui;box-shadow:0 8px 24px #0003;cursor:pointer}}#sf-chat-box{{display:none;position:fixed;right:24px;bottom:84px;z-index:2147483000;width:min(350px,calc(100vw - 32px));height:420px;background:white;border:1px solid #ddd;border-radius:16px;box-shadow:0 12px 36px #0003;font:14px system-ui;overflow:hidden}}#sf-chat-head{{background:#111827;color:#fff;padding:14px;font-weight:700}}#sf-chat-log{{height:280px;overflow:auto;padding:12px;color:#222;white-space:pre-wrap}}#sf-chat-form{{padding:10px;display:grid;gap:8px}}#sf-chat-form input,#sf-chat-form textarea{{box-sizing:border-box;width:100%;padding:9px;border:1px solid #ddd;border-radius:8px;font:14px system-ui}}#sf-chat-form textarea{{resize:vertical}}#sf-chat-form button{{background:#111827;color:white;border:0;border-radius:8px;padding:10px;cursor:pointer}}</style><button id="sf-chat-button" type="button">Chat with us</button><section id="sf-chat-box" aria-label="Chat with the store"><header id="sf-chat-head">Message {website.name}</header><div id="sf-chat-log">Send a message to the store. The owner will receive it in Shopivell and by email.</div><form id="sf-chat-form"><input name="name" placeholder="Your name" maxlength="160"><input name="email" type="email" placeholder="Your email (optional)" maxlength="255"><textarea name="message" placeholder="Write your message" required maxlength="5000"></textarea><button>Send message</button></form></section><script>(()=>{{const b=document.getElementById('sf-chat-button'),box=document.getElementById('sf-chat-box'),form=document.getElementById('sf-chat-form'),log=document.getElementById('sf-chat-log');let cid=localStorage.getItem('sf-chat-{website.id}')||crypto.randomUUID();localStorage.setItem('sf-chat-{website.id}',cid);b.onclick=()=>box.style.display=box.style.display==='block'?'none':'block';form.onsubmit=async e=>{{e.preventDefault();const d=new FormData(form),message=String(d.get('message')||'');if(!message.trim())return;log.textContent='Sending…';try{{const r=await fetch('/v1/api/website-builder/public/sites/{website.id}/messages',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{conversation_id:cid,sender_name:d.get('name')||null,sender_email:d.get('email')||null,message}})}});if(!r.ok)throw new Error();const result=await r.json();log.textContent='You: '+message+'\\n\\nShopivell assistant: '+(result.reply||'Thanks. The store will follow up soon.');form.elements.message.value=''}}catch{{log.textContent='Could not send your message. Please try again.'}}}}}})()</script>'''
    if "</body>" in html.lower():
        index = html.lower().rfind("</body>")
        html = html[:index] + widget + html[index:]
    else:
        html += widget
    return HTMLResponse(html)


@router.post("/public/sites/{website_id}/messages", status_code=201)
async def receive_visitor_message(website_id: UUID, body: WebsiteChatMessageCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Store a visitor chat message for the owner and notify the store by email."""
    website = db.query(Website).filter(Website.id == website_id, Website.status == WebsiteStatus.DEPLOYED).first()
    if not website:
        raise HTTPException(status_code=404, detail="Published site not found")
    message = WebsiteInboxMessage(
        website_id=website.id, conversation_id=body.conversation_id,
        sender_name=body.sender_name, sender_email=body.sender_email,
        sender_type="visitor", message=body.message.strip(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    # Use the store's existing, knowledge-grounded Shopivell bot. If no answer
    # is available, the owner still gets the message and the visitor gets a safe handoff.
    reply_text = None
    try:
        from modules.whatsapp.chatbot_engine import MultiTenantSalesBot
        bot = MultiTenantSalesBot(store_id=website.store_id, db=db)
        reply_text = await bot.generate_response(body.message.strip(), f"website:{body.conversation_id}")
    except Exception:
        logger.exception("Website assistant failed to answer visitor message for website %s", website.id)
    if not reply_text:
        reply_text = "Thanks for your message. I’ve shared it with the store team, and they’ll follow up with you."
    db.add(WebsiteInboxMessage(
        website_id=website.id, conversation_id=body.conversation_id,
        sender_type="assistant", message=reply_text,
    ))
    db.commit()
    from modules.stores.models import Store
    store = db.query(Store).filter(Store.id == website.store_id).first()
    recipient = (store.store_email or (store.owner.email if store.owner else None)) if store else None
    if recipient:
        background_tasks.add_task(_email_visitor_message, recipient, website.name, body.sender_name, body.sender_email, body.message.strip())
    return {"id": str(message.id), "received": True, "email_notified": bool(recipient), "reply": reply_text}


def _email_visitor_message(recipient: str, site_name: str, sender_name: str | None, sender_email: str | None, content: str) -> None:
    from utils.Verification_Codes_Services import VerificationCodeService
    subject = f"New website enquiry: {site_name}"
    text = f"Website: {site_name}\nFrom: {sender_name or 'Visitor'}\nEmail: {sender_email or 'Not provided'}\n\n{content}"
    VerificationCodeService.send_email(recipient, subject, text)


@router.get("/websites/{website_id}/media")
async def list_website_media(website_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    website = _owned_website(db, website_id, current_user)
    rows = db.query(WebsiteMediaAsset).filter(WebsiteMediaAsset.website_id == website.id).order_by(WebsiteMediaAsset.created_at.desc()).all()
    return [{"id": str(row.id), "file_name": row.file_name, "file_url": row.file_url, "mime_type": row.mime_type, "file_size": row.file_size, "created_at": row.created_at} for row in rows]


@router.post("/websites/{website_id}/media", status_code=201)
async def upload_website_media(website_id: UUID, file: UploadFile = File(...), current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    website = _owned_website(db, website_id, current_user)
    allowed = {"image/png": (".png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")), "image/jpeg": (".jpg", lambda b: b.startswith(b"\xff\xd8\xff")), "image/webp": (".webp", lambda b: b.startswith(b"RIFF") and b[8:12] == b"WEBP"), "image/gif": (".gif", lambda b: b.startswith((b"GIF87a", b"GIF89a")))}
    if file.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPEG, WebP, or GIF image")
    data = await file.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be smaller than 10 MB")
    extension, verify = allowed[file.content_type]
    if not verify(data):
        raise HTTPException(status_code=415, detail="File content does not match the selected image type")
    storage_name = f"{uuid_module.uuid4().hex}{extension}"
    root = Path(os.getenv("WEBSITE_UPLOAD_DIR", "uploads/website-builder")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / storage_name).write_bytes(data)
    base = os.getenv("PUBLIC_API_URL", "https://api.shopivell.com").rstrip("/")
    asset = WebsiteMediaAsset(store_id=website.store_id, website_id=website.id, file_name=(file.filename or "image")[:255], storage_name=storage_name, file_url=f"{base}/v1/api/website-builder/public/media/{storage_name}", mime_type=file.content_type, file_size=len(data))
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"id": str(asset.id), "file_name": asset.file_name, "file_url": asset.file_url, "mime_type": asset.mime_type, "file_size": asset.file_size}


@router.get("/public/media/{storage_name}")
async def get_website_media(storage_name: str, db: Session = Depends(get_db)):
    if Path(storage_name).name != storage_name:
        raise HTTPException(status_code=404, detail="Media not found")
    asset = db.query(WebsiteMediaAsset).filter(WebsiteMediaAsset.storage_name == storage_name).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found")
    path = Path(os.getenv("WEBSITE_UPLOAD_DIR", "uploads/website-builder")).resolve() / asset.storage_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.file_name, content_disposition_type="inline")


@router.delete("/websites/{website_id}/media/{asset_id}")
async def delete_website_media(website_id: UUID, asset_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_website(db, website_id, current_user)
    asset = db.query(WebsiteMediaAsset).filter(WebsiteMediaAsset.id == asset_id, WebsiteMediaAsset.website_id == website_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    path = Path(os.getenv("WEBSITE_UPLOAD_DIR", "uploads/website-builder")).resolve() / asset.storage_name
    path.unlink(missing_ok=True)
    db.delete(asset)
    db.commit()
    return {"message": "Media asset deleted"}


@router.get("/websites/{website_id}/inbox")
async def list_website_inbox(website_id: UUID, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    _owned_website(db, website_id, current_user)
    rows = db.query(WebsiteInboxMessage).filter(WebsiteInboxMessage.website_id == website_id).order_by(WebsiteInboxMessage.created_at.desc()).limit(250).all()
    return [{"id": str(row.id), "conversation_id": row.conversation_id, "sender_name": row.sender_name, "sender_email": row.sender_email, "sender_type": row.sender_type, "message": row.message, "created_at": row.created_at} for row in rows]


# Export router
website_builder_router = router

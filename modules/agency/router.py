from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
import re
from datetime import datetime

from database import get_db
from .models import Agency, AgencyStatus
from .schemas import (
    AgencyCreate,
    AgencyUpdate,
    AgencyResponse,
    AgencyListResponse,
    AgencyWithStoresResponse,
    StoreBasicInfo
)
from modules.stores.models import Store

agency_router = APIRouter(prefix="/api/agencies", tags=["agencies"])


def generate_slug(name: str) -> str:
    """Generate URL-safe slug from name"""
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', name.lower())
    slug = re.sub(r'[\s_-]+', '-', slug)
    return slug.strip('-')


# Create Agency
@agency_router.post("/", response_model=AgencyResponse, status_code=status.HTTP_201_CREATED)
async def create_agency(
    agency_data: AgencyCreate,
    db: Session = Depends(get_db)
):
    """Create a new agency"""
    try:
        # Generate unique slug
        base_slug = generate_slug(agency_data.name)
        slug = base_slug
        counter = 1
        while db.query(Agency).filter(Agency.slug == slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        # Create agency
        agency = Agency(
            owner_id=agency_data.owner_id,
            name=agency_data.name,
            slug=slug,
            description=agency_data.description,
            logo_url=agency_data.logo_url,
            email=agency_data.email,
            phone=agency_data.phone,
            website=agency_data.website,
            address=agency_data.address,
            city=agency_data.city,
            country=agency_data.country,
            status=AgencyStatus.ACTIVE
        )
        db.add(agency)
        db.commit()
        db.refresh(agency)
        return agency

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating agency: {str(e)}"
        )


# Get Agency by ID
@agency_router.get("/{agency_id}", response_model=AgencyResponse)
async def get_agency(
    agency_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get agency by ID"""
    try:
        agency = db.query(Agency).filter(Agency.id == agency_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agency not found"
            )
        return agency

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching agency: {str(e)}"
        )


# Get Agency with Stores
@agency_router.get("/{agency_id}/with-stores", response_model=AgencyWithStoresResponse)
async def get_agency_with_stores(
    agency_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get agency with all its stores"""
    try:
        agency = db.query(Agency).filter(Agency.id == agency_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agency not found"
            )

        # Get stores for this agency
        stores = db.query(Store).filter(Store.agency_id == agency_id).all()
        store_infos = [
            StoreBasicInfo(
                id=store.id,
                store_name=store.store_name,
                store_phone=store.store_phone,
                business_type=store.business_type,
                is_setup_completed=store.is_setup_completed,
                created_at=store.created_at
            )
            for store in stores
        ]

        return AgencyWithStoresResponse(
            id=agency.id,
            owner_id=agency.owner_id,
            name=agency.name,
            slug=agency.slug,
            description=agency.description,
            logo_url=agency.logo_url,
            email=agency.email,
            phone=agency.phone,
            website=agency.website,
            address=agency.address,
            city=agency.city,
            country=agency.country,
            status=agency.status,
            settings=agency.settings,
            created_at=agency.created_at,
            updated_at=agency.updated_at,
            stores=store_infos
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching agency with stores: {str(e)}"
        )


# Update Agency
@agency_router.patch("/{agency_id}", response_model=AgencyResponse)
async def update_agency(
    agency_id: uuid.UUID,
    agency_data: AgencyUpdate,
    db: Session = Depends(get_db)
):
    """Update agency details"""
    try:
        agency = db.query(Agency).filter(Agency.id == agency_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agency not found"
            )

        # Update fields
        update_data = agency_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(agency, field, value)

        db.commit()
        db.refresh(agency)
        return agency

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating agency: {str(e)}"
        )


# Delete Agency
@agency_router.delete("/{agency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agency(
    agency_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete agency (and all its stores via cascade)"""
    try:
        agency = db.query(Agency).filter(Agency.id == agency_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agency not found"
            )

        db.delete(agency)
        db.commit()
        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting agency: {str(e)}"
        )


# Get Agency Stores
@agency_router.get("/{agency_id}/stores", response_model=List[StoreBasicInfo])
async def get_agency_stores(
    agency_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get all stores belonging to an agency"""
    try:
        # Verify agency exists
        agency = db.query(Agency).filter(Agency.id == agency_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agency not found"
            )

        stores = db.query(Store).filter(Store.agency_id == agency_id).offset(skip).limit(limit).all()

        return [
            StoreBasicInfo(
                id=store.id,
                store_name=store.store_name,
                store_phone=store.store_phone,
                business_type=store.business_type,
                is_setup_completed=store.is_setup_completed,
                created_at=store.created_at
            )
            for store in stores
        ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching agency stores: {str(e)}"
        )


# Get User's Agency
@agency_router.get("/user/{user_id}", response_model=AgencyResponse)
async def get_user_agency(
    user_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get the agency owned by a specific user"""
    try:
        agency = db.query(Agency).filter(Agency.owner_id == user_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No agency found for this user"
            )
        return agency

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching user's agency: {str(e)}"
        )


# List All Agencies (admin endpoint)
@agency_router.get("/", response_model=AgencyListResponse)
async def list_agencies(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status_filter: Optional[AgencyStatus] = None,
    db: Session = Depends(get_db)
):
    """List all agencies with pagination"""
    try:
        query = db.query(Agency)

        if status_filter:
            query = query.filter(Agency.status == status_filter)

        total = query.count()
        agencies = query.offset(skip).limit(limit).all()

        return AgencyListResponse(
            agencies=agencies,
            total=total,
            page=skip // limit + 1 if limit > 0 else 1,
            size=len(agencies)
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing agencies: {str(e)}"
        )

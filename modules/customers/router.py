from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import csv
import io
from datetime import datetime, timedelta
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from database import get_db
from .models import Customer, CustomerSegment, CustomerSegmentMembership, CustomerRequest
from .schemas import (
    CustomerResponse, CustomerCreate, CustomerUpdate, BulkCustomerCreate, BulkCustomerResponse,
    CustomerListResponse, SuccessMessage, CustomerSegmentResponse, CustomerSegmentCreate,
    CustomerSegmentUpdate, CustomerSegmentListResponse, SegmentMembership, BulkSegmentMembership,
    CustomerOrderResponse, CustomerOrderCreate, CustomerRequestResponse, CustomerRequestCreate
)

customer_router = APIRouter(prefix="/api/customers", tags=["customers"])

# Sample segments data matching your frontend
SAMPLE_SEGMENTS = [
    {
        "name": "Customers who have purchased at least once",
        "description": "All customers who have made at least one purchase",
        "percentage": "0%",
        "type": "purchase_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Email subscribers",
        "description": "Customers who have subscribed to email marketing",
        "percentage": "0%",
        "type": "engagement",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Abandoned checkouts in the last 30 days",
        "description": "Customers who added items to cart but did not complete purchase",
        "percentage": "0%",
        "type": "cart_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Customers who have purchased more than once",
        "description": "Repeat customers with 2 or more purchases",
        "percentage": "0%",
        "type": "loyalty",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Customers who haven't purchased",
        "description": "Registered customers with zero purchases",
        "percentage": "0%",
        "type": "engagement",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "High-value customers (Top 10%)",
        "description": "Customers in the top 10% by total spending",
        "percentage": "0%",
        "type": "value",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "VIP Customers",
        "description": "Customers with VIP status and premium benefits",
        "percentage": "0%",
        "type": "loyalty",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "New customers (Last 30 days)",
        "description": "Customers who made their first purchase in the last 30 days",
        "percentage": "0%",
        "type": "acquisition",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "At-risk customers",
        "description": "Previously active customers with no purchases in 90+ days",
        "percentage": "0%",
        "type": "retention",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Mobile shoppers",
        "description": "Customers who primarily shop via mobile devices",
        "percentage": "0%",
        "type": "device_preference",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Discount seekers",
        "description": "Customers who frequently use discount codes",
        "percentage": "0%",
        "type": "purchase_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Product reviewers",
        "description": "Customers who have written product reviews",
        "percentage": "0%",
        "type": "engagement",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Seasonal shoppers",
        "description": "Customers who only shop during holiday seasons",
        "percentage": "0%",
        "type": "seasonal",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "International customers",
        "description": "Customers located outside the primary market",
        "percentage": "0%",
        "type": "geographic",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Premium product buyers",
        "description": "Customers who purchase premium/high-end products",
        "percentage": "0%",
        "type": "product_preference",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Social media followers",
        "description": "Customers who follow on social media platforms",
        "percentage": "0%",
        "type": "engagement",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Bulk purchasers",
        "description": "Customers who frequently purchase in large quantities",
        "percentage": "0%",
        "type": "purchase_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Newsletter engaged",
        "description": "Customers who regularly open and click newsletter emails",
        "percentage": "0%",
        "type": "engagement",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Recently browsed",
        "description": "Customers who browsed products in the last 7 days",
        "percentage": "0%",
        "type": "browsing_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Wishlist users",
        "description": "Customers who maintain active wishlists",
        "percentage": "0%",
        "type": "engagement",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Multi-category shoppers",
        "description": "Customers who purchase across multiple product categories",
        "percentage": "0%",
        "type": "purchase_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Early adopters",
        "description": "Customers who purchase new products within first week of launch",
        "percentage": "0%",
        "type": "innovation",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Customer referral sources",
        "description": "Customers acquired through referral programs",
        "percentage": "0%",
        "type": "acquisition",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Weekend shoppers",
        "description": "Customers who primarily shop on weekends",
        "percentage": "0%",
        "type": "time_behavior",
        "is_active": True,
        "created_by": "shopivell"
    },
    {
        "name": "Subscription members",
        "description": "Customers enrolled in subscription services",
        "percentage": "0%",
        "type": "loyalty",
        "is_active": True,
        "created_by": "shopivell"
    }
]

# Initialize sample segments
@customer_router.on_event("startup")
async def startup_event():
    db = next(get_db())
    try:
        # Check if segments already exist
        existing_segments = db.query(CustomerSegment).count()
        if existing_segments == 0:
            # Create sample segments
            for segment_data in SAMPLE_SEGMENTS:
                segment = CustomerSegment(
                    **segment_data,
                    customer_count=0,
                    last_activity=datetime.utcnow()
                )
                db.add(segment)
            db.commit()
            print("Sample segments initialized successfully")
    except Exception as e:
        print(f"Error initializing segments: {e}")
    finally:
        db.close()

# Customer CRUD Operations
@customer_router.get("/", response_model=CustomerListResponse)
def get_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    customer_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get paginated list of customers with optional filtering"""
    query = db.query(Customer)
    
    # Apply filters
    if customer_type:
        query = query.filter(Customer.customer_type == customer_type)
    if status:
        query = query.filter(Customer.status == status)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Customer.first_name.ilike(search_filter)) |
            (Customer.last_name.ilike(search_filter)) |
            (Customer.email.ilike(search_filter)) |
            (Customer.phone.ilike(search_filter))
        )
    
    total_count = query.count()
    customers = query.offset(skip).limit(limit).all()
    
    return CustomerListResponse(
        customers=customers,
        total_count=total_count,
        page=skip // limit + 1,
        page_size=limit,
        total_pages=(total_count + limit - 1) // limit
    )

@customer_router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific customer by ID"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    return customer

@customer_router.post("/", response_model=CustomerResponse)
def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    """Create a new customer"""
    # Check if email already exists
    existing_customer = db.query(Customer).filter(Customer.email == customer_data.email).first()
    if existing_customer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create customer
    customer = Customer(**customer_data.model_dump())
    
    db.add(customer)
    db.commit()
    db.refresh(customer)
    
    return customer

@customer_router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: uuid.UUID, customer_data: CustomerUpdate, db: Session = Depends(get_db)):
    """Update a customer"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    
    # Check if email already exists (if being updated)
    if customer_data.email and customer_data.email != customer.email:
        existing_customer = db.query(Customer).filter(Customer.email == customer_data.email).first()
        if existing_customer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Update customer fields
    update_data = customer_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)
    
    customer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(customer)
    
    return customer

@customer_router.delete("/{customer_id}", response_model=SuccessMessage)
def delete_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a customer"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    
    db.delete(customer)
    db.commit()
    
    return SuccessMessage(message="Customer deleted successfully")

# Bulk Customer Operations
@customer_router.post("/bulk", response_model=BulkCustomerResponse)
def bulk_create_customers(customer_data: BulkCustomerCreate, db: Session = Depends(get_db)):
    """Create multiple customers at once"""
    created_customers = []
    failed_customers = []
    
    for customer_create in customer_data.customers:
        try:
            # Check if email already exists
            existing_customer = db.query(Customer).filter(Customer.email == customer_create.email).first()
            if existing_customer:
                failed_customers.append({
                    "email": customer_create.email,
                    "error": "Email already registered"
                })
                continue
            
            # Create customer
            customer = Customer(**customer_create.model_dump())
            
            db.add(customer)
            created_customers.append(customer)
            
        except Exception as e:
            failed_customers.append({
                "email": customer_create.email,
                "error": str(e)
            })
    
    db.commit()
    
    # Refresh created customers to get their IDs
    for customer in created_customers:
        db.refresh(customer)
    
    return BulkCustomerResponse(
        created_count=len(created_customers),
        failed_count=len(failed_customers),
        failed_customers=failed_customers,
        created_customers=created_customers
    )

@customer_router.get("/template/download")
async def download_customer_template():
    """Download Excel template for customer import"""
    # Create a new workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"

    # Define headers
    headers = [
        "first_name", "last_name", "email", "phone", "date_of_birth",
        "gender", "address", "city", "state", "country", "postal_code",
        "customer_type", "status", "notes"
    ]

    # Define header styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="374151", end_color="374151", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Write headers with styling
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        # Auto-adjust column width
        ws.column_dimensions[cell.column_letter].width = max(15, len(header) + 5)

    # Add sample data row
    sample_data = [
        "John", "Doe", "john.doe@example.com", "+263771234567", "1990-01-15",
        "Male", "123 Main Street", "Harare", "Harare", "Zimbabwe", "00263",
        "regular", "active", "Sample customer note"
    ]

    for col, value in enumerate(sample_data, 1):
        cell = ws.cell(row=2, column=col, value=value)
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="left", vertical="center")

    # Add instructions sheet
    instructions_ws = wb.create_sheet(title="Instructions")
    instructions = [
        ("Column", "Description", "Required", "Example"),
        ("first_name", "Customer's first name", "Yes", "John"),
        ("last_name", "Customer's last name", "Yes", "Doe"),
        ("email", "Customer's email address (must be unique)", "Yes", "john@example.com"),
        ("phone", "Phone number with country code", "No", "+263771234567"),
        ("date_of_birth", "Date of birth (YYYY-MM-DD format)", "No", "1990-01-15"),
        ("gender", "Gender (Male/Female/Other)", "No", "Male"),
        ("address", "Street address", "No", "123 Main Street"),
        ("city", "City name", "No", "Harare"),
        ("state", "State/Province", "No", "Harare"),
        ("country", "Country name", "No", "Zimbabwe"),
        ("postal_code", "Postal/ZIP code", "No", "00263"),
        ("customer_type", "Customer type (regular/premium/vip)", "No", "regular"),
        ("status", "Customer status (active/inactive)", "No", "active"),
        ("notes", "Additional notes about the customer", "No", "VIP customer")
    ]

    # Style instructions header
    for col, value in enumerate(instructions[0], 1):
        cell = instructions_ws.cell(row=1, column=col, value=value)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Write instructions data
    for row_idx, row_data in enumerate(instructions[1:], 2):
        for col_idx, value in enumerate(row_data, 1):
            cell = instructions_ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            # Highlight required fields
            if col_idx == 3 and value == "Yes":
                cell.fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

    # Adjust column widths for instructions sheet
    instructions_ws.column_dimensions['A'].width = 15
    instructions_ws.column_dimensions['B'].width = 45
    instructions_ws.column_dimensions['C'].width = 10
    instructions_ws.column_dimensions['D'].width = 20

    # Save to BytesIO
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    # Return as streaming response
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=customer_import_template.xlsx"
        }
    )


@customer_router.post("/bulk-upload", response_model=BulkCustomerResponse)
async def bulk_upload_customers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Bulk upload customers from CSV or Excel file"""
    filename = file.filename.lower()

    if not (filename.endswith('.csv') or filename.endswith('.xlsx') or filename.endswith('.xls')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV and Excel (.xlsx, .xls) files are supported"
        )

    content = await file.read()
    created_customers = []
    failed_customers = []
    rows_to_process = []

    # Parse file based on type
    if filename.endswith('.csv'):
        csv_content = io.StringIO(content.decode('utf-8'))
        csv_reader = csv.DictReader(csv_content)
        for row_num, row in enumerate(csv_reader, start=2):
            rows_to_process.append((row_num, row))
    else:
        # Excel file
        try:
            excel_content = io.BytesIO(content)
            workbook = load_workbook(excel_content, read_only=True)
            ws = workbook.active

            # Get headers from first row
            headers = []
            for cell in ws[1]:
                headers.append(cell.value.lower().strip() if cell.value else '')

            # Process data rows (skip header and sample row if it matches template)
            for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                # Skip empty rows
                if not any(row):
                    continue

                # Convert row to dictionary
                row_dict = {}
                for col_idx, value in enumerate(row):
                    if col_idx < len(headers) and headers[col_idx]:
                        # Convert value to string if not None
                        row_dict[headers[col_idx]] = str(value) if value is not None else None

                # Skip sample row from template
                if row_dict.get('email') == 'john.doe@example.com':
                    continue

                rows_to_process.append((row_num, row_dict))

            workbook.close()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error parsing Excel file: {str(e)}"
            )

    # Process all rows
    for row_num, row in rows_to_process:
        try:
            # Validate required fields
            if not row.get('email') or not row.get('first_name') or not row.get('last_name'):
                failed_customers.append({
                    "row": row_num,
                    "email": row.get('email', 'N/A'),
                    "error": "Missing required fields (email, first_name, last_name)"
                })
                continue

            # Check if email already exists
            existing_customer = db.query(Customer).filter(Customer.email == row['email']).first()
            if existing_customer:
                failed_customers.append({
                    "row": row_num,
                    "email": row['email'],
                    "error": "Email already registered"
                })
                continue

            # Create customer data
            customer_data = {
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'email': row['email'],
                'phone': row.get('phone'),
                'date_of_birth': row.get('date_of_birth'),
                'gender': row.get('gender'),
                'address': row.get('address'),
                'city': row.get('city'),
                'state': row.get('state'),
                'country': row.get('country'),
                'postal_code': row.get('postal_code'),
                'customer_type': row.get('customer_type', 'regular'),
                'status': row.get('status', 'active'),
                'profile_image': row.get('profile_image'),
                'notes': row.get('notes')
            }

            # Create customer
            customer = Customer(**customer_data)

            db.add(customer)
            created_customers.append(customer)

        except Exception as e:
            failed_customers.append({
                "row": row_num,
                "email": row.get('email', 'N/A'),
                "error": str(e)
            })
    
    db.commit()
    
    # Refresh created customers to get their IDs
    for customer in created_customers:
        db.refresh(customer)
    
    return BulkCustomerResponse(
        created_count=len(created_customers),
        failed_count=len(failed_customers),
        failed_customers=failed_customers,
        created_customers=created_customers
    )

# Customer Segments Operations
@customer_router.get("/segments/", response_model=CustomerSegmentListResponse)
def get_segments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get paginated list of customer segments"""
    query = db.query(CustomerSegment)
    
    # Apply filters
    if is_active is not None:
        query = query.filter(CustomerSegment.is_active == is_active)
    if type:
        query = query.filter(CustomerSegment.type == type)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(CustomerSegment.name.ilike(search_filter))
    
    total_count = query.count()
    segments = query.offset(skip).limit(limit).all()
    
    return CustomerSegmentListResponse(
        segments=segments,
        total_count=total_count,
        page=skip // limit + 1,
        page_size=limit,
        total_pages=(total_count + limit - 1) // limit
    )

@customer_router.get("/segments/{segment_id}", response_model=CustomerSegmentResponse)
def get_segment(segment_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a specific segment by ID"""
    segment = db.query(CustomerSegment).filter(CustomerSegment.id == segment_id).first()
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    return segment

@customer_router.post("/segments/", response_model=CustomerSegmentResponse)
def create_segment(segment_data: CustomerSegmentCreate, db: Session = Depends(get_db)):
    """Create a new customer segment"""
    # Check if segment name already exists
    existing_segment = db.query(CustomerSegment).filter(CustomerSegment.name == segment_data.name).first()
    if existing_segment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Segment name already exists"
        )
    
    segment = CustomerSegment(
        **segment_data.model_dump(),
        customer_count=0,
        last_activity=datetime.utcnow()
    )
    
    db.add(segment)
    db.commit()
    db.refresh(segment)
    
    return segment

@customer_router.put("/segments/{segment_id}", response_model=CustomerSegmentResponse)
def update_segment(segment_id: uuid.UUID, segment_data: CustomerSegmentUpdate, db: Session = Depends(get_db)):
    """Update a customer segment"""
    segment = db.query(CustomerSegment).filter(CustomerSegment.id == segment_id).first()
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    # Check if segment name already exists (if being updated)
    if segment_data.name and segment_data.name != segment.name:
        existing_segment = db.query(CustomerSegment).filter(CustomerSegment.name == segment_data.name).first()
        if existing_segment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Segment name already exists"
            )
    
    # Update segment fields
    update_data = segment_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(segment, field, value)
    
    segment.updated_at = datetime.utcnow()
    segment.last_activity = datetime.utcnow()
    db.commit()
    db.refresh(segment)
    
    return segment

@customer_router.delete("/segments/{segment_id}", response_model=SuccessMessage)
def delete_segment(segment_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a customer segment"""
    segment = db.query(CustomerSegment).filter(CustomerSegment.id == segment_id).first()
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    db.delete(segment)
    db.commit()
    
    return SuccessMessage(message="Segment deleted successfully")

@customer_router.post("/segments/{segment_id}/add-customers", response_model=SuccessMessage)
def add_customers_to_segment(segment_id: uuid.UUID, membership_data: BulkSegmentMembership, db: Session = Depends(get_db)):
    """Add multiple customers to a segment"""
    segment = db.query(CustomerSegment).filter(CustomerSegment.id == segment_id).first()
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found"
        )
    
    added_count = 0
    for membership in membership_data.memberships:
        # Check if customer exists
        customer = db.query(Customer).filter(Customer.id == membership.customer_id).first()
        if not customer:
            continue
        
        # Check if already in segment
        existing_membership = db.query(CustomerSegmentMembership).filter(
            CustomerSegmentMembership.customer_id == membership.customer_id,
            CustomerSegmentMembership.segment_id == segment_id
        ).first()
        
        if not existing_membership:
            membership_record = CustomerSegmentMembership(
                customer_id=membership.customer_id,
                segment_id=segment_id
            )
            db.add(membership_record)
            added_count += 1
    
    # Update segment customer count
    segment.customer_count = db.query(CustomerSegmentMembership).filter(
        CustomerSegmentMembership.segment_id == segment_id
    ).count()
    
    segment.updated_at = datetime.utcnow()
    segment.last_activity = datetime.utcnow()
    
    db.commit()
    
    return SuccessMessage(message=f"Added {added_count} customers to segment")


@customer_router.get("/{customer_id}/requests", response_model=List[CustomerRequestResponse])
def get_customer_requests(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get all requests for a customer"""
    requests = db.query(CustomerRequest).filter(CustomerRequest.customer_id == customer_id).all()
    return requests

@customer_router.post("/{customer_id}/requests", response_model=CustomerRequestResponse)
def create_customer_request(customer_id: uuid.UUID, request_data: CustomerRequestCreate, db: Session = Depends(get_db)):
    """Create a new request for a customer"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    
    request = CustomerRequest(
        customer_id=customer_id,
        **request_data.model_dump(exclude={'customer_id'})
    )
    
    db.add(request)
    db.commit()
    db.refresh(request)
    
    return request
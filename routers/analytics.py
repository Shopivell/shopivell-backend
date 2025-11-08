

from fastapi import APIRouter, Depends, HTTPException
from scipy import stats
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased, Session
from database import get_db
from models import Offer, Order, Product, RequestPost, User
from schemas.analytics_schema import ComprehensiveOfferStatsResponseSchema, ComprehensiveOrderStatsResponseSchema, ComprehensiveProductStatsResponseSchema, ComprehensiveRequestStatsResponseSchema, ComprehensiveUserStatsResponseSchema, OfferDetailSchema, OrderDetailSchema, ProductDetailSchema, RequestDetailSchema


analytics_router = APIRouter(prefix="/analytics", tags=["analytics"]) # Changed tag to plural
@analytics_router.get(
    "/users-stats",
    response_model=ComprehensiveUserStatsResponseSchema,
    summary="Get comprehensive user statistics and a list of users",
    description="""
    Returns a full dashboard of user statistics, including:
    - Total, active, pending, and disabled user counts.
    - Business account count.
    - User counts by role (with percentages).
    - Monthly registration trends.
    - A list of the most recently registered users.
    """
)
async def get_comprehensive_user_stats(db: Session = Depends(get_db)):
    """
    Asynchronously retrieves and returns comprehensive user statistics.

    Args:
        db (Session): The SQLAlchemy database session, provided via dependency injection.

    Returns:
        ComprehensiveUserStatsResponseSchema: An object containing all requested user data.
    """
    try:
        # 1. Get total user count
        total_users = db.query(User).count()

        # 2. Get status-based counts
        status_counts = dict(
            db.query(User.status, func.count())
            .group_by(User.status)
            .all()
        )
        active_users = status_counts.get("active", 0)
        pending_users = status_counts.get("pending", 0)
        disabled_users = status_counts.get("disabled", 0)

        # 3. Get business account count
        business_accounts_count = db.query(User).filter(User.role.in_(['supplier', 'both'])).count()

        # 4. Get users by role count and percentage
        role_counts = db.query(User.role, func.count()).group_by(User.role).all()
        users_by_role = []
        if total_users > 0:
            for role, count in role_counts:
                percentage = (count / total_users) * 100
                users_by_role.append({"role": role, "count": count, "percentage": round(percentage, 2)})

        # 5. Get monthly registration count (using func.to_char for PostgreSQL)
        monthly_data = (
            db.query(
                func.to_char(User.created_at, 'YYYY-MM').label('month'),
                func.count().label('count')
            )
            .group_by('month')
            .order_by('month')
            .all()
        )
        monthly_registrations = [{"month": row.month, "count": row.count} for row in monthly_data]

        # 6. Get a list of recent users
        recent_users_query = db.query(User).order_by(User.created_at.desc()).all()

        # 7. Assemble and return the final comprehensive response
        response_data = {
            "total_users": total_users,
            "active_users": active_users,
            "pending_users": pending_users,
            "disabled_users": disabled_users,
            "business_accounts": business_accounts_count,
            "users_by_role": users_by_role,
            "monthly_registrations": monthly_registrations,
            "recent_users": recent_users_query
        }

        return ComprehensiveUserStatsResponseSchema(**response_data)

    except Exception as e:
        # Re-introducing the try-except block, as the root cause is now identified
        print(f"An error occurred while fetching user stats: {e}")
        raise HTTPException(
            status_code=stats.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred."
        )
    
# THIS ENDPOINT MUST BE DEFINED FIRST
@analytics_router.get(
    "/requests-stats",
    response_model=ComprehensiveRequestStatsResponseSchema,
    summary="Get comprehensive request statistics and a list of requests",
    description="""
    Returns a full dashboard of request statistics, including:
    - Total, active request counts.
    - Request counts by status (with percentages).
    - Monthly creation trends.
    - A list of the most recently created requests with customer details.
    """
)
async def get_comprehensive_request_stats(db: Session = Depends(get_db)):
    """
    Asynchronously retrieves and returns comprehensive request statistics.
    
    This function no longer takes 'user_id' as a parameter.
    
    Args:
        db (Session): The SQLAlchemy database session, provided via dependency injection.

    Returns:
        ComprehensiveRequestStatsResponseSchema: An object containing all requested request data.
    """
    try:
        # 1. Get total requests
        total_requests = db.query(RequestPost).count()

        # 2. Get active requests (status is 'open', 'supplier_accepted', or 'counter_offered')
        active_requests = db.query(RequestPost).filter(
            or_(
                RequestPost.status == 'open',
                RequestPost.status == 'supplier_accepted',
                RequestPost.status == 'counter_offered'
            )
        ).count()

        # 3. Get requests by status count and percentage
        status_counts = db.query(
            RequestPost.status,
            func.count()
        ).group_by(RequestPost.status).all()

        requests_by_status = []
        if total_requests > 0:
            for status_name, count in status_counts:
                percentage = (count / total_requests) * 100
                requests_by_status.append(
                    {"status": status_name, "count": count, "percentage": round(percentage, 2)}
                )

        # 4. Get monthly request count (using func.to_char for PostgreSQL)
        monthly_data = (
            db.query(
                func.to_char(RequestPost.created_at, 'YYYY-MM').label('month'),
                func.count().label('count')
            )
            .group_by('month')
            .order_by('month')
            .all()
        )
        monthly_requests = [{"month": row.month, "count": row.count} for row in monthly_data]

        # 5. Get a list of recent requests with customer details
        recent_requests_query = (
            db.query(
                RequestPost.id,
                RequestPost.title,
                RequestPost.description,
                RequestPost.category,
                RequestPost.quantity,
                RequestPost.status,
                RequestPost.created_at,
                RequestPost.updated_at,
                RequestPost.image_path,
                User.name.label("customer_name"),
                User.id.label("customer_id")
            )
            .join(User, RequestPost.customer_id == User.id)
            .order_by(RequestPost.created_at.desc())
            .all()
        )

        # 6. Assemble and return the final comprehensive response
        response_data = {
            "total_requests": total_requests,
            "active_requests": active_requests,
            "requests_by_status": requests_by_status,
            "monthly_requests": monthly_requests,
            "recent_requests": [
                RequestDetailSchema(
                    id=row.id,
                    title=row.title,
                    description=row.description,
                    category=row.category,
                    quantity=row.quantity,
                    status=row.status,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    image_path=row.image_path,
                    customer_name=row.customer_name,
                    customer_id=row.customer_id
                ) for row in recent_requests_query
            ]
        }
        
        return ComprehensiveRequestStatsResponseSchema(**response_data)

    except Exception as e:
        print(f"An error occurred while fetching request stats: {e}")
        raise HTTPException(
            status_code=stats.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred."
        )
    

@analytics_router.get(
    "/offers-stats",
    response_model=ComprehensiveOfferStatsResponseSchema,
    summary="Get comprehensive offer statistics and a list of offers",
    description="""
    Returns a full dashboard of offer statistics, including:
    - Total offer count.
    - Offer counts by status (with percentages).
    - Monthly creation trends.
    - A list of the most recently created offers with related request and supplier details.
    """
)
async def get_comprehensive_offer_stats(db: Session = Depends(get_db)):
    """
    Asynchronously retrieves and returns comprehensive offer statistics.

    Args:
        db (Session): The SQLAlchemy database session, provided via dependency injection.

    Returns:
        ComprehensiveOfferStatsResponseSchema: An object containing all requested offer data.
    """
    try:
        # 1. Get total offer count
        total_offers = db.query(Offer).count()

        # 2. Get offers by status count and percentage
        status_counts = db.query(
            Offer.status,
            func.count()
        ).group_by(Offer.status).all()

        offers_by_status = []
        if total_offers > 0:
            for status_name, count in status_counts:
                percentage = (count / total_offers) * 100
                offers_by_status.append(
                    {"status": status_name, "count": count, "percentage": round(percentage, 2)}
                )

        # 3. Get monthly offer count (using func.to_char for PostgreSQL)
        monthly_data = (
            db.query(
                func.to_char(Offer.created_at, 'YYYY-MM').label('month'),
                func.count().label('count')
            )
            .group_by('month')
            .order_by('month')
            .all()
        )
        monthly_offers = [{"month": row.month, "count": row.count} for row in monthly_data]

        # 4. Get a list of recent offers with related request and supplier details
        recent_offers_query = (
            db.query(
                Offer.id,
                Offer.request_id,
                Offer.supplier_id,
                Offer.proposed_price,
                Offer.message,
                Offer.delivery_date,
                Offer.status,
                Offer.created_at,
                Offer.updated_at,
                RequestPost.title.label("request_title"),
                User.business_name.label("supplier_name")
            )
            .join(RequestPost, Offer.request_id == RequestPost.id)
            .join(User, Offer.supplier_id == User.id)
            .order_by(Offer.created_at.desc())
            .all()
        )

        # 5. Assemble and return the final comprehensive response
        response_data = {
            "total_offers": total_offers,
            "offers_by_status": offers_by_status,
            "monthly_offers": monthly_offers,
            "recent_offers": [
                OfferDetailSchema(
                    id=row.id,
                    request_id=row.request_id,
                    supplier_id=row.supplier_id,
                    proposed_price=float(row.proposed_price),
                    message=row.message,
                    delivery_date=row.delivery_date,
                    status=row.status,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    request_title=row.request_title,
                    supplier_name=row.supplier_name
                ) for row in recent_offers_query
            ]
        }
        
        return ComprehensiveOfferStatsResponseSchema(**response_data)

    except Exception as e:
        print(f"An error occurred while fetching offer stats: {e}")
        raise HTTPException(
            status_code=stats.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred."
        )
    


@analytics_router.get(
    "/orders-stats",
    response_model=ComprehensiveOrderStatsResponseSchema,
    summary="Get comprehensive order statistics and a list of orders",
    description="""
    Returns a full dashboard of order statistics, including:
    - Total order count.
    - Order counts by status (with percentages).
    - Monthly creation trends.
    - A list of the most recently created orders with related request, customer, and supplier details.
    """
)
async def get_comprehensive_order_stats(db: Session = Depends(get_db)):
    """
    Asynchronously retrieves and returns comprehensive order statistics.

    Args:
        db (Session): The SQLAlchemy database session, provided via dependency injection.

    Returns:
        ComprehensiveOrderStatsResponseSchema: An object containing all requested order data.
    """
    try:
        # Define aliases for the User table to perform multiple joins
        Customer = aliased(User)
        Supplier = aliased(User)

        # 1. Get total order count
        total_orders = db.query(Order).count()

        # 2. Get orders by status count and percentage
        status_counts = db.query(
            Order.status,
            func.count()
        ).group_by(Order.status).all()

        orders_by_status = []
        if total_orders > 0:
            for status_name, count in status_counts:
                percentage = (count / total_orders) * 100
                orders_by_status.append(
                    {"status": status_name, "count": count, "percentage": round(percentage, 2)}
                )

        # 3. Get monthly order count (using func.to_char for PostgreSQL)
        monthly_data = (
            db.query(
                func.to_char(Order.created_at, 'YYYY-MM').label('month'),
                func.count().label('count')
            )
            .group_by('month')
            .order_by('month')
            .all()
        )
        monthly_orders = [{"month": row.month, "count": row.count} for row in monthly_data]

        # 4. Get a list of recent orders with related request, customer, and supplier details
        recent_orders_query = (
            db.query(
                Order.id,
                Order.request_id,
                Order.offer_id,
                Order.customer_id,
                Order.supplier_id,
                Order.total_price,
                Order.status,
                Order.created_at,
                Order.updated_at,
                Order.delivered_at,
                RequestPost.title.label("request_title"),
                Customer.name.label("customer_name"),
                Supplier.business_name.label("supplier_name")
            )
            .join(RequestPost, Order.request_id == RequestPost.id)
            .join(Customer, Order.customer_id == Customer.id)
            .join(Supplier, Order.supplier_id == Supplier.id)
            .order_by(Order.created_at.desc())
            .all()
        )

        # 5. Assemble and return the final comprehensive response
        response_data = {
            "total_orders": total_orders,
            "orders_by_status": orders_by_status,
            "monthly_orders": monthly_orders,
            "recent_orders": [
                OrderDetailSchema(
                    id=row.id,
                    request_id=row.request_id,
                    offer_id=row.offer_id,
                    customer_id=row.customer_id,
                    supplier_id=row.supplier_id,
                    total_price=float(row.total_price),
                    status=row.status,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    delivered_at=row.delivered_at,
                    request_title=row.request_title,
                    customer_name=row.customer_name,
                    supplier_name=row.supplier_name
                ) for row in recent_orders_query
            ]
        }
        
        return ComprehensiveOrderStatsResponseSchema(**response_data)

    except Exception as e:
        print(f"An error occurred while fetching order stats: {e}")
        raise HTTPException(
            status_code=stats.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred."
        )


@analytics_router.get(
    "/products-stats",
    response_model=ComprehensiveProductStatsResponseSchema,
    summary="Get comprehensive product statistics and a list of products",
    description="""
    Returns a full dashboard of product statistics, including:
    - Total product count.
    - Average product price.
    - Unique product categories.
    - Product category distribution by percentage.
    - Product price distribution by range.
    - A list of the most recently created products with related supplier details.
    """
)
async def get_comprehensive_product_stats(db: Session = Depends(get_db)):
    """
    Asynchronously retrieves and returns comprehensive product statistics.

    Args:
        db (Session): The SQLAlchemy database session, provided via dependency injection.

    Returns:
        ComprehensiveProductStatsResponseSchema: An object containing all requested product data.
    """
    try:
        # 1. Get total product count
        total_products = db.query(Product).count()

        # 2. Get average product price
        avg_price_result = db.query(func.avg(Product.price)).scalar()
        average_price = round(float(avg_price_result), 2) if avg_price_result else 0.0

        # 3. Get unique categories and their distribution
        category_counts = db.query(
            Product.category,
            func.count()
        ).group_by(Product.category).all()

        unique_categories = [cat for cat, count in category_counts]
        category_distribution = []
        if total_products > 0:
            for category_name, count in category_counts:
                percentage = (count / total_products) * 100
                category_distribution.append(
                    {"category": category_name, "count": count, "percentage": round(percentage, 2)}
                )

        # 4. Get product price distribution
        all_prices = db.query(Product.price).all()
        price_bins = {
            "$0 - $100": 0,
            "$101 - $500": 0,
            "$501 - $1000": 0,
            "$1001+": 0
        }
        
        for price_tuple in all_prices:
            price = float(price_tuple[0])
            if price <= 100:
                price_bins["$0 - $100"] += 1
            elif price <= 500:
                price_bins["$101 - $500"] += 1
            elif price <= 1000:
                price_bins["$501 - $1000"] += 1
            else:
                price_bins["$1001+"] += 1
        
        price_distribution = []
        if total_products > 0:
            for price_range, count in price_bins.items():
                percentage = (count / total_products) * 100
                price_distribution.append(
                    {"price_range": price_range, "count": count, "percentage": round(percentage, 2)}
                )

        # 5. Get a list of recent products with related supplier details
        recent_products_query = (
            db.query(
                Product.id,
                Product.name,
                Product.price,
                Product.category,
                Product.created_at,
                User.business_name.label("supplier_name")
            )
            .join(User, Product.supplier_id == User.id)
            .order_by(Product.created_at.desc())
            .all()
        )

        # 6. Assemble and return the final comprehensive response
        response_data = {
            "total_products": total_products,
            "average_price": average_price,
            "unique_categories": unique_categories,
            "category_distribution": category_distribution,
            "price_distribution": price_distribution,
            "recent_products": [
                ProductDetailSchema(
                    id=row.id,
                    name=row.name,
                    price=float(row.price),
                    category=row.category,
                    created_at=row.created_at,
                    supplier_name=row.supplier_name
                ) for row in recent_products_query
            ]
        }
        
        return ComprehensiveProductStatsResponseSchema(**response_data)

    except Exception as e:
        print(f"An error occurred while fetching product stats: {e}")
        raise HTTPException(
            status_code=stats.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred."
        )

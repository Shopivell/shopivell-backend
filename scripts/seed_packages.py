"""
Seed script for package pricing data.
Run: python scripts/seed_packages.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, engine, init_db

# Import ALL models to register relationships (same as init_db)
from modules.customers import models as customer_models
from modules.orders import models as order_models
from modules.products import models as products_models
from modules.analytics import models as analytics_models
from modules.stores import models as store_models
from modules.users import models as user_models
from modules.content.template import models as template_models
from modules.content.content import models as content_models
from modules.social import models as social_models
from modules.business import models as business_models
from modules.payment import models as payment_models
from modules.marketing import models as marketing_models
from modules.whatsapp import models as whatsapp_models
from modules.agents import models as agents_models
from modules.agency import models as agency_models

from modules.payment.models import PackagePricing, SubscriptionPlan, PackageFeature

def seed_packages():
    """Seed the package pricing table with default packages."""
    db = SessionLocal()

    try:
        # Check if packages already exist
        existing = db.query(PackagePricing).count()
        if existing > 0:
            print(f"Packages already exist ({existing} found). Updating...")
            # Delete existing to reseed
            db.query(PackagePricing).delete()
            db.commit()

        packages = [
            {
                "package_name": SubscriptionPlan.FREE,
                "description": "Perfect for getting started. Create your online store and start selling with essential features.",
                "monthly_price": 0.00,
                "annual_price": 0.00,
                "currency": "USD",
                "features": [
                    "Up to 10 products",
                    "Up to 50 orders/month",
                    "Basic store customization",
                    "Social media posting",
                    "Email support",
                    "Mobile-friendly store",
                    "Secure checkout",
                    "Basic analytics"
                ],
                "is_active": True
            },
            {
                "package_name": SubscriptionPlan.PREMIUM,
                "description": "For growing businesses. Unlock advanced features to scale your store and reach more customers.",
                "monthly_price": 9.99,
                "annual_price": 99.90,  # 2 months free
                "currency": "USD",
                "features": [
                    "Up to 100 products",
                    "Up to 500 orders/month",
                    "Advanced store customization",
                    "Social media posting",
                    "Priority email support",
                    "Custom domain",
                    "Advanced analytics",
                    "Inventory management",
                    "Discount codes",
                    "Abandoned cart recovery",
                    "SEO tools"
                ],
                "is_active": True
            },
            {
                # Custom plan: priced PER PAGE/STORE. monthly_price is the per-unit price;
                # the charged amount is monthly_price × quantity (pages/stores).
                "package_name": SubscriptionPlan.BUSINESS,
                "description": "Custom plan — run multiple pages or stores. Billed per page/store; a page is a store.",
                "monthly_price": 14.99,   # price per page/store
                "annual_price": None,     # Custom is billed monthly per page
                "currency": "USD",
                "features": [
                    "Everything in the Monthly plan",
                    "One Facebook page/account per store",
                    "Add as many pages/stores as you need",
                    "Manage every page from one dashboard",
                    "Team collaboration",
                    "Priority support"
                ],
                "is_active": True
            }
        ]

        for pkg_data in packages:
            package = PackagePricing(**pkg_data)
            db.add(package)
            print(f"  Added {pkg_data['package_name'].value}: ${pkg_data['monthly_price']}/mo, ${pkg_data['annual_price']}/yr")

        db.commit()
        print(f"\nSuccessfully seeded {len(packages)} packages!")

        # Also seed package features for reference
        features = [
            {"name": "products", "description": "Number of products you can list"},
            {"name": "orders", "description": "Monthly order limit"},
            {"name": "analytics", "description": "Sales and traffic analytics"},
            {"name": "custom_domain", "description": "Use your own domain name"},
            {"name": "priority_support", "description": "Priority customer support"},
            {"name": "social_posting", "description": "Post to social media"},
            {"name": "inventory_management", "description": "Track stock levels"},
            {"name": "multi_user_access", "description": "Multiple team members"},
            {"name": "api_access", "description": "Access to REST API"},
            {"name": "custom_branding", "description": "Remove Shopivell branding"},
        ]

        # Clear existing features
        db.query(PackageFeature).delete()
        db.commit()

        for feat_data in features:
            feature = PackageFeature(**feat_data)
            db.add(feature)

        db.commit()
        print(f"Seeded {len(features)} package features.")

    except Exception as e:
        db.rollback()
        print(f"Error seeding packages: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("Seeding package pricing data...")
    seed_packages()

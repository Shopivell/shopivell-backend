"""
Setup script for Platinum Pharmacy Store in Shopivell

This script:
1. Creates a store for Platinum Pharmacy
2. Configures the WhatsApp bot with product knowledge
3. Fetches products and categories from the Platinum Pharmacy API

Usage:
    python scripts/setup_platinum_pharmacy.py
"""

import os
import sys
import json
import asyncio
import requests
from pathlib import Path
from datetime import datetime

# Add parent directory to path so we can import from modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Use SQLite for local testing only if USE_SQLITE not already set
if "USE_SQLITE" not in os.environ:
    os.environ["USE_SQLITE"] = "true"

from database import SessionLocal, init_db, Base, engine
from modules.users.models import User
from modules.stores.models import Store, StoreSetupStep
from modules.whatsapp.models import (
    WhatsAppAccount, StoreBotConfig, CompanyKnowledge, FAQ
)
from modules.business.models import FacebookBusinessAccount
from modules.agency.models import Agency

# Configuration
STORE_CONFIG = {
    "store_name": "Platinum Pharmacy",
    "store_email": os.environ.get("PHARMACY_STORE_EMAIL", "store@example.com"),
    "store_phone": "+263780587502",
    "store_link": "https://platinumpharmacy.co.zw",
    "business_type": "pharmacy",
    "store_description": """Platinum Pharmacy is a leading pharmacy chain in Zimbabwe with 4 branches:
- Angwa Street Branch (Harare): +263 78 005 0999
- Rezende Street Branch (Harare): +263 77 499 9956
- Bulawayo Branch: +263 78 144 4222
- Gweru Branch: +263 77 499 9950

We offer prescription services, vitamins, cold & flu medication, first aid supplies, personal care products, and pharmacist consultation via WhatsApp.""",
    "store_voice": "professional, caring, knowledgeable",
    "store_tone": "friendly and helpful",
    "currency": "USD",
    "country_code": "ZW",
    "store_city": "Harare",
    "store_country": "Zimbabwe",
}

# Platinum Pharmacy API endpoints
PRODUCTS_API = "https://platinumpharmacy.co.zw/api/products/"
CATEGORIES_API = "https://platinumpharmacy.co.zw/api/categories/"

# Categories from the API (pre-fetched)
PHARMACY_CATEGORIES = [
    {"id": 44, "name": "Skin Care", "subcategories": ["Face Wash", "Moisturizers", "Serums"]},
    {"id": 45, "name": "Hair Care", "subcategories": ["Hair Oil", "Shampoo", "Conditioner"]},
    {"id": 46, "name": "Makeup", "subcategories": ["Face Powder", "Lipstick", "Mascara"]},
    {"id": 47, "name": "Bath & Body", "subcategories": ["Body Lotion", "Shower Gel", "Soap"]},
    {"id": 48, "name": "Fragrances", "subcategories": ["Body Spray", "Perfume", "Cologne"]},
    {"id": 49, "name": "Men's Grooming", "subcategories": ["Shaving", "Aftershave", "Skincare"]},
    {"id": 50, "name": "Prescriptions", "subcategories": []},
    {"id": 51, "name": "Vitamins & Supplements", "subcategories": []},
    {"id": 52, "name": "Cold & Flu", "subcategories": []},
    {"id": 53, "name": "First Aid", "subcategories": []},
    {"id": 54, "name": "Personal Care", "subcategories": []},
]


def fetch_categories():
    """Fetch categories from Platinum Pharmacy API"""
    try:
        response = requests.get(CATEGORIES_API, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[WARN] Could not fetch categories: {e}")
    return PHARMACY_CATEGORIES


def fetch_products():
    """Try to fetch products from Platinum Pharmacy API"""
    products = []
    # Try different search terms to get products
    search_terms = ["", "vitamin", "medicine", "cream", "lotion", "tablet", "capsule"]

    for term in search_terms:
        try:
            url = f"{PRODUCTS_API}?search={term}" if term else PRODUCTS_API
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    products.extend(data)
                elif isinstance(data, dict) and "results" in data:
                    products.extend(data["results"])
        except Exception as e:
            print(f"[WARN] Could not fetch products for '{term}': {e}")

    # Remove duplicates by ID
    seen_ids = set()
    unique_products = []
    for p in products:
        if isinstance(p, dict):
            pid = p.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                unique_products.append(p)

    return unique_products


def create_or_get_user(db):
    """Create or get the test user"""
    user = db.query(User).filter(User.email == STORE_CONFIG["store_email"]).first()

    if not user:
        import uuid
        user = User(
            id=uuid.uuid4(),
            email=STORE_CONFIG["store_email"],
            name="Platinum Pharmacy Admin",
            first_name="Platinum",
            last_name="Pharmacy",
            password_hash="test_password_hash",  # In production, use proper hashing
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[OK] Created user: {user.email}")
    else:
        print(f"[OK] Found existing user: {user.email}")

    return user


def create_or_get_agency(db, user):
    """Create or get the agency"""
    agency = db.query(Agency).filter(Agency.owner_id == user.id).first()

    if not agency:
        import uuid
        agency = Agency(
            id=uuid.uuid4(),
            owner_id=user.id,
            name="Platinum Pharmacy",
            slug="platinum-pharmacy",
            email=STORE_CONFIG["store_email"],
            phone=STORE_CONFIG["store_phone"],
            description="Platinum Pharmacy - Leading pharmacy chain in Zimbabwe",
        )
        db.add(agency)
        db.commit()
        db.refresh(agency)
        print(f"[OK] Created agency: {agency.name}")
    else:
        print(f"[OK] Found existing agency: {agency.name}")

    return agency


def create_or_get_store(db, user, agency):
    """Create or get the Platinum Pharmacy store"""
    store = db.query(Store).filter(Store.store_name == STORE_CONFIG["store_name"]).first()

    if not store:
        import uuid
        store = Store(
            id=uuid.uuid4(),
            owner_id=user.id,
            agency_id=agency.id,
            store_name=STORE_CONFIG["store_name"],
            store_email=STORE_CONFIG["store_email"],
            store_phone=STORE_CONFIG["store_phone"],
            store_link=STORE_CONFIG["store_link"],
            business_type=STORE_CONFIG["business_type"],
            store_description=STORE_CONFIG["store_description"],
            store_voice=STORE_CONFIG["store_voice"],
            store_tone=STORE_CONFIG["store_tone"],
            currency=STORE_CONFIG.get("currency", "USD"),
            country_code=STORE_CONFIG.get("country_code", "ZW"),
            store_city=STORE_CONFIG.get("store_city"),
            store_country=STORE_CONFIG.get("store_country"),
            current_step=StoreSetupStep.COMPLETED,
            is_setup_completed=True,
        )
        db.add(store)
        db.commit()
        db.refresh(store)
        print(f"[OK] Created store: {store.store_name}")
    else:
        print(f"[OK] Found existing store: {store.store_name}")

    return store


def create_bot_config(db, store):
    """Create or update bot configuration"""
    config = db.query(StoreBotConfig).filter(StoreBotConfig.store_id == store.id).first()

    if not config:
        import uuid
        config = StoreBotConfig(
            id=uuid.uuid4(),
            store_id=store.id,
            bot_name="Platinum Pharmacy Assistant",
            bot_personality="""You are a helpful pharmacy assistant for Platinum Pharmacy Zimbabwe.
You help customers with product inquiries, prescription questions, store locations, and general health advice.
Always be professional, caring, and knowledgeable. If you don't know something, honestly say so and offer to connect them with a pharmacist.""",
            greeting_message="Hello! Welcome to Platinum Pharmacy. How can I help you today? I can assist with product inquiries, prescriptions, or store locations.",
            fallback_message="I'm not sure about that. Let me connect you with one of our pharmacists who can help you better.",
            handoff_message="A pharmacist will be with you shortly. Thank you for your patience!",
            temperature=0.7,
            max_response_tokens=500,
            similarity_threshold=0.4,
            is_enabled=True,
            auto_respond=True,
        )
        db.add(config)
        db.commit()
        print(f"[OK] Created bot config for store: {store.store_name}")
    else:
        print(f"[OK] Found existing bot config for store: {store.store_name}")

    return config


def add_knowledge_entry(db, store, title, content, category="general", content_type="manual"):
    """Add a knowledge entry for the bot"""
    import uuid

    # Check if similar entry exists
    existing = db.query(CompanyKnowledge).filter(
        CompanyKnowledge.store_id == store.id,
        CompanyKnowledge.title == title
    ).first()

    if existing:
        print(f"  [SKIP] Knowledge entry exists: {title[:50]}...")
        return existing

    knowledge = CompanyKnowledge(
        id=uuid.uuid4(),
        store_id=store.id,
        title=title,
        content=content,
        category=category,
        content_type=content_type,
        is_active=True,
        priority=1.0,
    )
    db.add(knowledge)
    return knowledge


def add_faq(db, store, question, answer, category="general"):
    """Add a FAQ for the store"""
    import uuid

    existing = db.query(FAQ).filter(
        FAQ.store_id == store.id,
        FAQ.question == question
    ).first()

    if existing:
        return existing

    faq = FAQ(
        id=uuid.uuid4(),
        store_id=store.id,
        question=question,
        answer=answer,
        category=category,
        is_active=True,
        is_featured=True,
    )
    db.add(faq)
    return faq


def setup_knowledge_base(db, store):
    """Set up the knowledge base with Platinum Pharmacy information"""
    print("\n[INFO] Setting up knowledge base...")

    # Store information
    add_knowledge_entry(
        db, store,
        title="Platinum Pharmacy Store Information",
        content=STORE_CONFIG["store_description"],
        category="store_info",
        content_type="manual"
    )

    # Branch locations
    branches_content = """
Platinum Pharmacy Branch Locations in Zimbabwe:

1. ANGWA STREET BRANCH (HARARE)
   - Phone: +263 78 005 0999
   - WhatsApp: +263 78 005 0999
   - Hours: 7:30 AM - Midnight

2. REZENDE STREET BRANCH (HARARE)
   - Phone: +263 77 499 9956
   - WhatsApp: +263 77 499 9956

3. BULAWAYO BRANCH
   - Phone: +263 78 144 4222
   - WhatsApp: +263 78 144 4222

4. GWERU BRANCH
   - Phone: +263 77 499 9950
   - WhatsApp: +263 77 499 9950

All branches offer prescription services, over-the-counter medications, vitamins, personal care products, and pharmacist consultation.
"""
    add_knowledge_entry(
        db, store,
        title="Platinum Pharmacy Branch Locations",
        content=branches_content,
        category="locations",
        content_type="manual"
    )

    # Services
    services_content = """
Platinum Pharmacy Services:

1. PRESCRIPTION SERVICES
   - Upload prescriptions via WhatsApp
   - Auto-refill available
   - Medication reminders

2. PHARMACIST CONSULTATION
   - Chat with a pharmacist via WhatsApp
   - Medication advice
   - Drug interactions information

3. PRODUCT CATEGORIES
   - Prescriptions & Medications
   - Vitamins & Supplements
   - Cold & Flu remedies
   - First Aid supplies
   - Personal Care products
   - Skin Care
   - Hair Care
   - Makeup & Cosmetics
   - Fragrances
   - Men's Grooming
   - Bath & Body products

4. DELIVERY SERVICES
   - Home delivery available
   - Same-day delivery in Harare
"""
    add_knowledge_entry(
        db, store,
        title="Platinum Pharmacy Services",
        content=services_content,
        category="services",
        content_type="manual"
    )

    # Add categories as knowledge
    print("\n[INFO] Adding product categories...")
    categories = fetch_categories()
    for cat in categories:
        if isinstance(cat, dict):
            cat_name = cat.get("name", "Unknown")
            subcats = cat.get("subcategories", [])
            content = f"Product Category: {cat_name}\n"
            if subcats:
                content += f"Subcategories: {', '.join(subcats)}\n"
            content += f"\nFind {cat_name} products at Platinum Pharmacy. Visit our website or WhatsApp us for specific product inquiries."

            add_knowledge_entry(
                db, store,
                title=f"Category: {cat_name}",
                content=content,
                category="product_category",
                content_type="manual"
            )

    # Try to fetch and add products
    print("\n[INFO] Fetching products from API...")
    products = fetch_products()
    print(f"[INFO] Found {len(products)} products")

    for product in products[:50]:  # Limit to first 50 products
        if isinstance(product, dict):
            name = product.get("name", "Unknown Product")
            price = product.get("price") or product.get("discounted_price")
            description = product.get("description", "")

            content = f"Product: {name}\n"
            if price:
                content += f"Price: ${price}\n"
            if description:
                content += f"Description: {description}\n"
            content += "\nAvailable at Platinum Pharmacy. Contact us for availability and ordering."

            add_knowledge_entry(
                db, store,
                title=f"Product: {name}",
                content=content,
                category="product",
                content_type="product"
            )

    # Add FAQs
    print("\n[INFO] Adding FAQs...")
    faqs = [
        ("What are your operating hours?", "Our Angwa Street branch is open from 7:30 AM to Midnight. Other branches have varying hours. Contact your nearest branch for specific times."),
        ("Do you deliver?", "Yes! We offer home delivery services. Same-day delivery is available in Harare. Contact us via WhatsApp to arrange delivery."),
        ("Can I upload my prescription via WhatsApp?", "Yes! You can send a photo of your prescription via WhatsApp and we'll prepare your medication for pickup or delivery."),
        ("Where are you located?", "We have 4 branches: Angwa Street (Harare), Rezende Street (Harare), Bulawayo, and Gweru. Contact us for exact addresses."),
        ("Do you have vitamins and supplements?", "Yes, we stock a wide range of vitamins and supplements. WhatsApp us with your requirements and we'll check availability."),
        ("Can I speak to a pharmacist?", "Yes! Our qualified pharmacists are available for consultation. Send us a message and we'll connect you with a pharmacist."),
        ("What payment methods do you accept?", "We accept cash, EcoCash, bank transfers, and card payments at our branches."),
        ("Do you stock skincare products?", "Yes, we have a full range of skincare products including moisturizers, serums, face wash, and more."),
    ]

    for question, answer in faqs:
        add_faq(db, store, question, answer, category="general")

    db.commit()
    print(f"\n[OK] Knowledge base setup complete!")


def main():
    """Main setup function"""
    print("=" * 60)
    print("PLATINUM PHARMACY STORE SETUP")
    print("=" * 60)

    # Initialize database
    print("\n[INFO] Initializing database...")
    init_db()

    # Create session
    db = SessionLocal()

    try:
        # Create user
        print("\n[INFO] Setting up user...")
        user = create_or_get_user(db)

        # Create agency
        print("\n[INFO] Setting up agency...")
        agency = create_or_get_agency(db, user)

        # Create store
        print("\n[INFO] Setting up store...")
        store = create_or_get_store(db, user, agency)

        # Create bot config
        print("\n[INFO] Setting up bot configuration...")
        bot_config = create_bot_config(db, store)

        # Setup knowledge base
        setup_knowledge_base(db, store)

        print("\n" + "=" * 60)
        print("SETUP COMPLETE!")
        print("=" * 60)
        print(f"""
Store Details:
  - Name: {store.store_name}
  - ID: {store.id}
  - Email: {store.store_email}
  - Phone: {store.store_phone}
  - Website: {store.store_link}

Bot Configuration:
  - Bot Name: {bot_config.bot_name}
  - Enabled: {bot_config.is_enabled}
  - Auto Respond: {bot_config.auto_respond}

To test the bot:
  1. Start the backend server: uvicorn main:app --reload
  2. Send a WhatsApp message to the configured number
  3. Or use the API endpoint: POST /api/whatsapp/chat
""")

    except Exception as e:
        print(f"\n[ERROR] Setup failed: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Seed script for Zim Secure Sights security products and FAQs
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from sqlalchemy import text
from uuid import UUID
import json

def seed_products_and_faqs():
    db = SessionLocal()

    try:
        # Find Zim Secure Sights store
        result = db.execute(text("""
            SELECT id, store_name FROM stores WHERE store_name ILIKE '%Zim Secure%' LIMIT 1
        """))
        store = result.fetchone()

        if not store:
            print("[X] Zim Secure Sights store not found!")
            return

        store_id = store[0]
        store_name = store[1]
        print(f"[OK] Found store: {store_name} (ID: {store_id})")

        # Security Products with pricing
        products = [
            # CCTV Packages
            {
                "title": "4 Channel DVR Package",
                "description": "Complete 4 channel DVR CCTV system with 4 cameras. Includes DVR recorder, 4x HD cameras, cables, and power supplies. Installation fee is 20% of material cost.",
                "category": "CCTV Systems",
                "price": 150.00,
                "sku": "CCTV-4CH-PKG",
                "type": "package"
            },
            {
                "title": "8 Channel DVR Package",
                "description": "Complete 8 channel DVR CCTV system with 8 cameras. Includes DVR recorder, 8x HD cameras, cables, and power supplies. Installation fee is 20% of material cost.",
                "category": "CCTV Systems",
                "price": 280.00,
                "sku": "CCTV-8CH-PKG",
                "type": "package"
            },
            {
                "title": "16 Channel DVR Package",
                "description": "Professional 16 channel DVR CCTV system with 16 cameras. Includes DVR recorder, 16x HD cameras, cables, and power supplies. Installation fee is 20% of material cost.",
                "category": "CCTV Systems",
                "price": 450.00,
                "sku": "CCTV-16CH-PKG",
                "type": "package"
            },
            {
                "title": "HD Camera (Individual)",
                "description": "High definition security camera with night vision. Compatible with all our DVR systems.",
                "category": "CCTV Components",
                "price": 25.00,
                "sku": "CAM-HD-001",
                "type": "product"
            },

            # Gate Motor Packages
            {
                "title": "Sliding Gate Motor - Light Duty",
                "description": "Automatic sliding gate motor for residential gates up to 400kg. Includes motor, remote controls, and basic installation. Installation fee is 20% of material cost.",
                "category": "Gate Motors",
                "price": 180.00,
                "sku": "GATE-SLIDE-LD",
                "type": "package"
            },
            {
                "title": "Sliding Gate Motor - Heavy Duty",
                "description": "Heavy duty automatic sliding gate motor for commercial gates up to 1000kg. Includes motor, remote controls, and basic installation. Installation fee is 20% of material cost.",
                "category": "Gate Motors",
                "price": 350.00,
                "sku": "GATE-SLIDE-HD",
                "type": "package"
            },
            {
                "title": "Swing Gate Motor - Double",
                "description": "Automatic swing gate motor for double gates. Includes dual motors, remote controls, and installation. Installation fee is 20% of material cost.",
                "category": "Gate Motors",
                "price": 320.00,
                "sku": "GATE-SWING-DBL",
                "type": "package"
            },
            {
                "title": "Extra Remote Control",
                "description": "Additional remote control for gate motor systems.",
                "category": "Gate Motor Accessories",
                "price": 15.00,
                "sku": "GATE-REMOTE",
                "type": "product"
            },

            # Electric Fence Packages
            {
                "title": "Electric Fence - Residential (50m)",
                "description": "Complete electric fence system for residential properties. Covers up to 50 meters. Includes energizer, wires, insulators, and warning signs. Installation fee is 20% of material cost.",
                "category": "Electric Fence",
                "price": 220.00,
                "sku": "FENCE-RES-50",
                "type": "package"
            },
            {
                "title": "Electric Fence - Residential (100m)",
                "description": "Complete electric fence system for larger residential properties. Covers up to 100 meters. Includes energizer, wires, insulators, and warning signs. Installation fee is 20% of material cost.",
                "category": "Electric Fence",
                "price": 380.00,
                "sku": "FENCE-RES-100",
                "type": "package"
            },
            {
                "title": "Electric Fence - Commercial (200m)",
                "description": "Heavy duty electric fence system for commercial properties. Covers up to 200 meters. Includes industrial energizer, wires, insulators, and warning signs. Installation fee is 20% of material cost.",
                "category": "Electric Fence",
                "price": 650.00,
                "sku": "FENCE-COM-200",
                "type": "package"
            },
            {
                "title": "Electric Fence Energizer",
                "description": "Replacement or upgrade energizer for electric fence systems.",
                "category": "Electric Fence Components",
                "price": 85.00,
                "sku": "FENCE-ENRG",
                "type": "product"
            },

            # Biometric Access Control
            {
                "title": "Biometric Fingerprint Reader - Basic",
                "description": "Standalone biometric fingerprint reader for door access. Supports up to 500 fingerprints. Includes installation and basic setup. Installation fee is 20% of material cost.",
                "category": "Access Control",
                "price": 120.00,
                "sku": "BIO-FP-BASIC",
                "type": "package"
            },
            {
                "title": "Biometric Fingerprint Reader - Advanced",
                "description": "Advanced biometric system with fingerprint and card access. Supports up to 3000 users with time attendance features. Installation fee is 20% of material cost.",
                "category": "Access Control",
                "price": 250.00,
                "sku": "BIO-FP-ADV",
                "type": "package"
            },
            {
                "title": "Face Recognition Access System",
                "description": "Modern face recognition access control system. Touchless entry with temperature screening option. Installation fee is 20% of material cost.",
                "category": "Access Control",
                "price": 380.00,
                "sku": "BIO-FACE",
                "type": "package"
            },
            {
                "title": "Magnetic Door Lock",
                "description": "Electromagnetic door lock for access control systems. 600 lbs holding force.",
                "category": "Access Control Components",
                "price": 45.00,
                "sku": "ACC-MAGLOCK",
                "type": "product"
            },

            # Alarm Systems
            {
                "title": "Home Alarm System - Basic",
                "description": "Basic home alarm system with 4 zones, control panel, 2 PIR sensors, 2 door contacts, and siren. Installation fee is 20% of material cost.",
                "category": "Alarm Systems",
                "price": 150.00,
                "sku": "ALARM-HOME-B",
                "type": "package"
            },
            {
                "title": "Home Alarm System - Advanced",
                "description": "Advanced home alarm with 8 zones, LCD control panel, 4 PIR sensors, 4 door contacts, outdoor siren, and smartphone app. Installation fee is 20% of material cost.",
                "category": "Alarm Systems",
                "price": 280.00,
                "sku": "ALARM-HOME-A",
                "type": "package"
            },

            # Services
            {
                "title": "Site Survey & Consultation",
                "description": "Professional security assessment of your property. Our experts will evaluate your security needs and provide recommendations.",
                "category": "Services",
                "price": 0.00,
                "sku": "SRV-SURVEY",
                "type": "service"
            },
            {
                "title": "Maintenance Contract - Annual",
                "description": "Annual maintenance contract for all security systems. Includes 4 scheduled visits and priority emergency response.",
                "category": "Services",
                "price": 120.00,
                "sku": "SRV-MAINT-YR",
                "type": "service"
            },
        ]

        # Insert products
        for product in products:
            # Check if product exists
            exists = db.execute(text("""
                SELECT id FROM products WHERE store_id = :store_id AND sku = :sku
            """), {"store_id": store_id, "sku": product["sku"]}).fetchone()

            if exists:
                # Update existing
                db.execute(text("""
                    UPDATE products SET
                        title = :title,
                        description = :description,
                        category = :category,
                        price = :price,
                        type = :type,
                        status = 'active',
                        updated_at = NOW()
                    WHERE store_id = :store_id AND sku = :sku
                """), {**product, "store_id": store_id})
                print(f"  [OK] Updated: {product['title']} - ${product['price']}")
            else:
                # Insert new
                db.execute(text("""
                    INSERT INTO products (id, store_id, title, description, category, price, sku, type, status, quantity, available, on_hand)
                    VALUES (gen_random_uuid(), :store_id, :title, :description, :category, :price, :sku, :type, 'active', 100, 100, 100)
                """), {**product, "store_id": store_id})
                print(f"  [OK] Created: {product['title']} - ${product['price']}")

        db.commit()
        print(f"\n[OK] {len(products)} products added/updated")

        # FAQs for security business
        faqs = [
            {
                "question": "What is included in the installation fee?",
                "answer": "Our installation fee is 20% of the material cost. This covers professional installation by our certified technicians, cable routing, system configuration, and a demonstration of how to use your new security system.",
                "category": "pricing"
            },
            {
                "question": "Do you offer free site surveys?",
                "answer": "Yes! We offer free site surveys and security consultations for all potential customers. Our security experts will visit your property, assess your security needs, and provide a detailed quotation.",
                "category": "services"
            },
            {
                "question": "How long does CCTV installation take?",
                "answer": "A standard 4-camera CCTV system typically takes 4-6 hours to install. Larger systems (8-16 cameras) may require 1-2 days depending on the complexity of the installation and cable routing requirements.",
                "category": "services"
            },
            {
                "question": "What warranty do you offer on your products?",
                "answer": "All our products come with a 12-month warranty covering manufacturing defects. Extended warranties are available. Our installation work is guaranteed for 6 months.",
                "category": "general"
            },
            {
                "question": "Can I view my CCTV cameras on my phone?",
                "answer": "Yes! All our DVR systems support remote viewing via smartphone apps (iOS and Android). We'll help you set up the app during installation so you can monitor your property from anywhere in the world.",
                "category": "products"
            },
            {
                "question": "Do you offer payment plans?",
                "answer": "Yes, we offer flexible payment plans for larger installations. You can pay 50% deposit and the balance on completion, or arrange monthly installments for qualifying customers.",
                "category": "pricing"
            },
            {
                "question": "What happens if there's a power outage?",
                "answer": "Our DVR systems have built-in battery backup that can last 2-4 hours. For extended protection, we can install a UPS (Uninterruptible Power Supply) to keep your security system running during longer outages.",
                "category": "products"
            },
            {
                "question": "How do I get a quote for my property?",
                "answer": "You can get a quote by: 1) Sending us a WhatsApp message with details of what you need, 2) Requesting a free site survey, or 3) Visiting our office with photos of your property. We'll provide a detailed quotation within 24 hours.",
                "category": "general"
            },
            {
                "question": "Do you service and repair existing systems?",
                "answer": "Yes! We service and repair all major brands of security systems, not just the ones we install. Our technicians are trained to diagnose and fix issues quickly.",
                "category": "services"
            },
            {
                "question": "What areas do you service?",
                "answer": "We service Harare and surrounding areas including Norton, Chitungwiza, and Ruwa. For locations outside Harare, additional transport costs may apply.",
                "category": "general"
            },
            {
                "question": "How much is a basic electric fence installation?",
                "answer": "A basic residential electric fence for a standard property (up to 50m) costs $220 for materials. Installation is an additional 20% ($44), making the total approximately $264. Larger properties will require a site survey for accurate pricing.",
                "category": "pricing"
            },
            {
                "question": "Can gate motors work during power cuts?",
                "answer": "Yes, all our gate motors come with battery backup that provides approximately 20-30 operations during power outages. We can also integrate solar charging for complete independence from the grid.",
                "category": "products"
            },
        ]

        # Insert FAQs
        for faq in faqs:
            # Check if FAQ exists
            exists = db.execute(text("""
                SELECT id FROM faqs WHERE store_id = :store_id AND question = :question
            """), {"store_id": store_id, "question": faq["question"]}).fetchone()

            if not exists:
                db.execute(text("""
                    INSERT INTO faqs (id, store_id, question, answer, category, is_active, is_featured, display_order)
                    VALUES (gen_random_uuid(), :store_id, :question, :answer, :category, true, false, 0)
                """), {**faq, "store_id": store_id})
                print(f"  [OK] Created FAQ: {faq['question'][:50]}...")
            else:
                print(f"  [SKIP] FAQ exists: {faq['question'][:50]}...")

        db.commit()
        print(f"\n[OK] {len(faqs)} FAQs added")

        # Show summary
        product_count = db.execute(text("""
            SELECT COUNT(*) FROM products WHERE store_id = :store_id
        """), {"store_id": store_id}).scalar()

        faq_count = db.execute(text("""
            SELECT COUNT(*) FROM faqs WHERE store_id = :store_id
        """), {"store_id": store_id}).scalar()

        print("\n" + "=" * 60)
        print("SEEDING COMPLETE")
        print("=" * 60)
        print(f"Store: {store_name}")
        print(f"Total Products: {product_count}")
        print(f"Total FAQs: {faq_count}")
        print("\nNext steps:")
        print("  1. Sync products to knowledge base: POST /v1/api/whatsapp/stores/{store_id}/knowledge/sync-products")
        print("  2. Sync FAQs to knowledge base: POST /v1/api/whatsapp/stores/{store_id}/faqs/sync-all")

    except Exception as e:
        print(f"[X] Error: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    seed_products_and_faqs()

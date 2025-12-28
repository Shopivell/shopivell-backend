"""
Population script for Zim Secure Sights - Security Products & FAQs

Adds:
- CCTV/DVR packages
- Gate motor packages
- Electric fence packages
- Biometric access control packages
- FAQs for security services

Pricing based on:
- User specified: 4 Channel DVR with 4 cameras = $150
- Installation fee: 20% of material cost
- Zimbabwe market rates for security products
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from modules.stores.models import Store
from modules.products.models import Product
from modules.whatsapp.models import FAQ
from modules.whatsapp.knowledge_service import KnowledgeService
from uuid import UUID
import uuid

def get_zim_secure_store(db):
    """Find Zim Secure Sights store"""
    store = db.query(Store).filter(
        Store.store_name.ilike("%zim%secure%")
    ).first()

    if not store:
        # Try alternative names
        store = db.query(Store).filter(
            Store.store_name.ilike("%security%")
        ).first()

    return store

def create_products(db, store_id: UUID):
    """Create security products for Zim Secure Sights"""

    products = [
        # ===================== CCTV PACKAGES =====================
        {
            "title": "4 Channel DVR CCTV Package",
            "description": """Complete 4 Channel DVR Security System Package includes:
- 1x 4 Channel DVR (Digital Video Recorder)
- 4x HD Cameras (720p/1080p)
- 500GB Hard Drive for storage
- All cables and connectors
- Power supply unit
- Remote viewing app setup
- Free installation manual

Perfect for small homes, shops, and small offices.
Supports remote viewing via smartphone app.
Installation available at 20% of material cost ($30).""",
            "category": "CCTV",
            "price": 150.00,
            "sku": "CCTV-4CH-PKG",
            "type": "Package",
            "tags": "cctv,dvr,cameras,security,surveillance,4 channel"
        },
        {
            "title": "8 Channel DVR CCTV Package",
            "description": """Complete 8 Channel DVR Security System Package includes:
- 1x 8 Channel DVR (Digital Video Recorder)
- 8x HD Cameras (1080p Full HD)
- 1TB Hard Drive for extended storage
- All cables and connectors (up to 20m per camera)
- Power supply unit with surge protection
- Remote viewing app setup (iOS & Android)
- Free installation manual

Ideal for medium-sized homes, retail stores, and offices.
Supports remote viewing and playback via smartphone.
Installation available at 20% of material cost ($56).""",
            "category": "CCTV",
            "price": 280.00,
            "sku": "CCTV-8CH-PKG",
            "type": "Package",
            "tags": "cctv,dvr,cameras,security,surveillance,8 channel"
        },
        {
            "title": "16 Channel DVR CCTV Package",
            "description": """Premium 16 Channel DVR Security System Package includes:
- 1x 16 Channel DVR (Digital Video Recorder)
- 16x Full HD Cameras (1080p)
- 2TB Hard Drive for maximum storage
- All cables and connectors (up to 30m per camera)
- Industrial power supply unit
- Remote viewing app setup with cloud backup
- On-site installation included

Perfect for large properties, warehouses, factories, and commercial buildings.
30-day recording capacity. 24/7 technical support.
Installation available at 20% of material cost ($90).""",
            "category": "CCTV",
            "price": 450.00,
            "sku": "CCTV-16CH-PKG",
            "type": "Package",
            "tags": "cctv,dvr,cameras,security,surveillance,16 channel,commercial"
        },
        {
            "title": "Single CCTV Camera (Add-on)",
            "description": """Single HD Security Camera for expanding your existing system:
- 1080p Full HD resolution
- Night vision up to 30m
- Weather-resistant (IP66)
- Compatible with most DVR systems
- Includes 20m cable

Add extra coverage to your existing CCTV system.
Installation: $8 per camera.""",
            "category": "CCTV",
            "price": 35.00,
            "sku": "CAM-SINGLE-HD",
            "type": "Component",
            "tags": "camera,cctv,add-on,single"
        },

        # ===================== GATE MOTORS =====================
        {
            "title": "Sliding Gate Motor - Standard (D5 Type)",
            "description": """Centurion D5 Type Sliding Gate Motor Package:
- Suitable for gates up to 500kg
- 20 operations per day
- Includes 2 remote controls
- Anti-theft bracket included
- Battery backup compatible
- 2-year warranty

Ideal for residential homes with standard sliding gates.
Professional installation at 20% of material cost ($70).""",
            "category": "Gate Motors",
            "price": 350.00,
            "sku": "GATE-D5-STD",
            "type": "Package",
            "tags": "gate motor,sliding,centurion,d5,residential"
        },
        {
            "title": "Sliding Gate Motor - Heavy Duty (D10 Type)",
            "description": """Centurion D10 Type Heavy Duty Sliding Gate Motor Package:
- Suitable for gates up to 1000kg
- 50+ operations per day
- High-speed operation (45m/min)
- Includes 4 remote controls
- Anti-theft bracket included
- Battery backup included
- 3-year warranty

Perfect for commercial properties, estates, and heavy industrial gates.
Professional installation at 20% of material cost ($130).""",
            "category": "Gate Motors",
            "price": 650.00,
            "sku": "GATE-D10-HD",
            "type": "Package",
            "tags": "gate motor,sliding,centurion,d10,commercial,heavy duty"
        },
        {
            "title": "Swing Gate Motor - Single",
            "description": """Single Swing Gate Motor Package:
- For gates up to 4m wide
- Includes 1 motor arm
- 2 remote controls
- Safety sensors included
- Battery backup compatible

For single swing gates at residential properties.
Installation at 20% of material cost ($50).""",
            "category": "Gate Motors",
            "price": 250.00,
            "sku": "GATE-SWING-SGL",
            "type": "Package",
            "tags": "gate motor,swing,single,residential"
        },
        {
            "title": "Swing Gate Motor - Double",
            "description": """Double Swing Gate Motor Package:
- For gates up to 4m per leaf (8m total)
- Includes 2 motor arms
- 4 remote controls
- Safety sensors included
- Battery backup included
- Solar compatible

For double swing gates at estates and commercial properties.
Installation at 20% of material cost ($80).""",
            "category": "Gate Motors",
            "price": 400.00,
            "sku": "GATE-SWING-DBL",
            "type": "Package",
            "tags": "gate motor,swing,double,estate"
        },
        {
            "title": "Gate Motor Battery Backup",
            "description": """Battery Backup System for Gate Motors:
- 7Ah battery included
- Automatic switchover on power failure
- 20+ operations during power cuts
- Compatible with all our gate motors

Never be locked out during load shedding!
Installation: $10.""",
            "category": "Gate Motors",
            "price": 45.00,
            "sku": "GATE-BATTERY",
            "type": "Accessory",
            "tags": "battery,backup,gate motor,load shedding"
        },
        {
            "title": "Extra Gate Remote Control",
            "description": """Additional remote control for gate motor systems:
- Works with all Centurion-type motors
- 4-button remote
- Long range (50m+)
- Easy programming

Installation/Programming: Free with purchase.""",
            "category": "Gate Motors",
            "price": 25.00,
            "sku": "GATE-REMOTE",
            "type": "Accessory",
            "tags": "remote,gate motor,extra"
        },

        # ===================== ELECTRIC FENCE =====================
        {
            "title": "Electric Fence - Residential Basic (50m)",
            "description": """Basic Electric Fence Package for residential properties:
- 50 meters of 4-strand electric fence
- 1x Energizer (2 Joule output)
- Warning signs (3 pcs)
- All brackets, insulators, wire
- Siren for alarm

Provides perimeter security for small residential properties.
Height: 1.2m above wall.
Installation at 20% of material cost ($30).""",
            "category": "Electric Fence",
            "price": 150.00,
            "sku": "EFENCE-RES-50M",
            "type": "Package",
            "tags": "electric fence,residential,50m,basic"
        },
        {
            "title": "Electric Fence - Residential Standard (100m)",
            "description": """Standard Electric Fence Package for medium homes:
- 100 meters of 6-strand electric fence
- 1x Energizer (4 Joule output)
- Warning signs (5 pcs)
- All brackets, insulators, wire
- Siren with battery backup
- Gate isolator for access gate

Complete perimeter security for standard homes.
Height: 1.5m above wall.
Installation at 20% of material cost ($60).""",
            "category": "Electric Fence",
            "price": 300.00,
            "sku": "EFENCE-RES-100M",
            "type": "Package",
            "tags": "electric fence,residential,100m,standard"
        },
        {
            "title": "Electric Fence - Commercial (200m)",
            "description": """Commercial Electric Fence Package:
- 200 meters of 8-strand electric fence
- 1x Industrial Energizer (8 Joule output)
- Warning signs (10 pcs)
- All heavy-duty brackets, insulators, wire
- Alarm panel with GSM dialer
- Multiple zone monitoring
- Battery backup system

Professional-grade perimeter security for commercial properties.
Height: 1.8m above wall/ground.
Installation at 20% of material cost ($140).""",
            "category": "Electric Fence",
            "price": 700.00,
            "sku": "EFENCE-COM-200M",
            "type": "Package",
            "tags": "electric fence,commercial,200m,industrial"
        },
        {
            "title": "Electric Fence - Per Meter Installation",
            "description": """Electric Fence supply and installation per meter:
- Price per linear meter
- Includes wire, brackets, insulators
- 6-strand configuration
- Professional installation

Minimum order: 30 meters.
Energizer sold separately.
Installation included in price.""",
            "category": "Electric Fence",
            "price": 5.00,
            "sku": "EFENCE-PER-M",
            "type": "Service",
            "tags": "electric fence,per meter,installation"
        },
        {
            "title": "Electric Fence Energizer - 4 Joule",
            "description": """4 Joule Electric Fence Energizer:
- Suitable for up to 150m fence
- LED indicator lights
- Built-in lightning protection
- Low power consumption
- Wall-mount design

Replacement or upgrade energizer for existing systems.
Installation: $15.""",
            "category": "Electric Fence",
            "price": 85.00,
            "sku": "EFENCE-ENRG-4J",
            "type": "Component",
            "tags": "energizer,electric fence,4 joule"
        },
        {
            "title": "Electric Fence Energizer - 8 Joule",
            "description": """8 Joule Industrial Electric Fence Energizer:
- Suitable for up to 500m fence
- Digital display
- Zone monitoring capability
- Built-in lightning protection
- GSM module compatible
- Battery backup compatible

Heavy-duty energizer for large properties.
Installation: $20.""",
            "category": "Electric Fence",
            "price": 180.00,
            "sku": "EFENCE-ENRG-8J",
            "type": "Component",
            "tags": "energizer,electric fence,8 joule,industrial"
        },

        # ===================== BIOMETRIC ACCESS CONTROL =====================
        {
            "title": "Biometric Fingerprint Access Control - Basic",
            "description": """ZKTeco Basic Fingerprint Access Control:
- Fingerprint recognition
- PIN code backup
- Stores up to 1,000 fingerprints
- Standalone operation
- Electric lock output
- Attendance log

Perfect for small offices and shops.
Includes electric strike lock.
Installation at 20% of material cost ($24).""",
            "category": "Biometric Access",
            "price": 120.00,
            "sku": "BIO-FP-BASIC",
            "type": "Package",
            "tags": "biometric,fingerprint,access control,zkteco,basic"
        },
        {
            "title": "Biometric Fingerprint Access Control - Pro",
            "description": """ZKTeco Pro Fingerprint & Card Access Control:
- Fingerprint + RFID card recognition
- PIN code backup
- Stores up to 3,000 fingerprints
- Network capable (TCP/IP)
- Electric lock output
- Time attendance software included
- Door sensor input

Ideal for offices and commercial buildings.
Includes magnetic lock (280kg holding force).
Installation at 20% of material cost ($50).""",
            "category": "Biometric Access",
            "price": 250.00,
            "sku": "BIO-FP-PRO",
            "type": "Package",
            "tags": "biometric,fingerprint,rfid,access control,zkteco,pro"
        },
        {
            "title": "Biometric Face Recognition System",
            "description": """ZKTeco Face Recognition Access Control:
- Facial recognition (mask detection capable)
- Fingerprint backup
- RFID card backup
- Stores 3,000 faces
- Network capable with cloud management
- Temperature screening optional
- Time attendance software included

Premium access control for offices, factories, and secure facilities.
Includes magnetic lock and door sensor.
Installation at 20% of material cost ($100).""",
            "category": "Biometric Access",
            "price": 500.00,
            "sku": "BIO-FACE-PRO",
            "type": "Package",
            "tags": "biometric,face recognition,facial,access control,zkteco"
        },
        {
            "title": "Magnetic Door Lock (Electromagnetic)",
            "description": """Electromagnetic Door Lock:
- 280kg (600lbs) holding force
- Fail-safe design
- LED status indicator
- Door position sensor included
- 12V DC operation

For use with access control systems.
Installation: $20.""",
            "category": "Biometric Access",
            "price": 65.00,
            "sku": "LOCK-MAG-280",
            "type": "Component",
            "tags": "magnetic lock,electromagnetic,door lock,access control"
        },
        {
            "title": "Electric Strike Lock",
            "description": """Electric Strike Door Lock:
- Fail-secure design
- Works with most door frames
- 12V DC operation
- Adjustable tongue

Alternative to magnetic locks.
Installation: $15.""",
            "category": "Biometric Access",
            "price": 45.00,
            "sku": "LOCK-STRIKE",
            "type": "Component",
            "tags": "electric strike,door lock,access control"
        },

        # ===================== ALARM SYSTEMS =====================
        {
            "title": "Wireless Alarm System - Home",
            "description": """Complete Wireless Home Alarm System:
- Main control panel with keypad
- 2x PIR motion sensors
- 2x Door/window sensors
- 1x Siren (indoor/outdoor)
- 2x Remote controls
- GSM module for SMS alerts

Easy DIY installation or professional install available.
Sends SMS alerts to your phone when triggered.
Installation at 20% of material cost ($30).""",
            "category": "Alarm Systems",
            "price": 150.00,
            "sku": "ALARM-HOME",
            "type": "Package",
            "tags": "alarm,wireless,home,gsm,motion sensor"
        },
        {
            "title": "Wired Alarm System - Commercial",
            "description": """Commercial Wired Alarm System:
- Main control panel (8 zones, expandable to 16)
- 4x PIR motion sensors
- 4x Door contacts
- 1x Indoor siren
- 1x Outdoor siren with strobe
- Control keypad
- GSM communicator for alerts
- 24-hour battery backup

Professional security for businesses.
Installation at 20% of material cost ($70).""",
            "category": "Alarm Systems",
            "price": 350.00,
            "sku": "ALARM-COM",
            "type": "Package",
            "tags": "alarm,wired,commercial,zones"
        },

        # ===================== INTERCOM SYSTEMS =====================
        {
            "title": "Video Intercom System - 7 inch",
            "description": """7-inch Video Intercom System:
- 7" color LCD indoor monitor
- Outdoor camera with night vision
- Electric lock output
- 2-way audio
- Photo capture capability
- Supports 2 outdoor stations

See who's at your gate before opening.
Installation at 20% of material cost ($30).""",
            "category": "Intercom",
            "price": 150.00,
            "sku": "INTERCOM-7",
            "type": "Package",
            "tags": "intercom,video,7 inch,gate"
        },
        {
            "title": "Audio Intercom System",
            "description": """Audio-only Intercom System:
- Indoor handset station
- Outdoor weather-resistant station
- Electric lock output
- 2-way crystal-clear audio

Budget-friendly gate communication.
Installation at 20% of material cost ($14).""",
            "category": "Intercom",
            "price": 70.00,
            "sku": "INTERCOM-AUDIO",
            "type": "Package",
            "tags": "intercom,audio,gate,budget"
        }
    ]

    created_count = 0
    for product_data in products:
        # Check if product already exists
        existing = db.query(Product).filter(
            Product.store_id == store_id,
            Product.sku == product_data["sku"]
        ).first()

        if existing:
            print(f"  [SKIP] Product already exists: {product_data['title']}")
            continue

        product = Product(
            store_id=store_id,
            title=product_data["title"],
            description=product_data["description"],
            category=product_data["category"],
            price=product_data["price"],
            sku=product_data["sku"],
            type=product_data.get("type"),
            tags=product_data.get("tags"),
            status="active",
            quantity=100,
            available=100,
            on_hand=100,
            inventory_tracked=False,  # Services don't need inventory tracking
            physical_product=True
        )
        db.add(product)
        created_count += 1
        print(f"  [OK] Created: {product_data['title']} - ${product_data['price']}")

    db.commit()
    return created_count

def create_faqs(db, store_id: UUID):
    """Create FAQs for Zim Secure Sights"""

    faqs = [
        # General
        {
            "question": "What areas do you service in Zimbabwe?",
            "answer": "We provide installation and maintenance services in Harare, Bulawayo, Mutare, Gweru, and surrounding areas. For locations outside these cities, please contact us for a quote including travel costs.",
            "category": "general"
        },
        {
            "question": "How do I get a quote for security installation?",
            "answer": "You can get a quote by:\n1. WhatsApp us with your requirements\n2. We'll ask about property size and security needs\n3. A free site survey can be arranged for larger projects\n4. You'll receive a detailed quote within 24 hours\n\nAll our quotes include materials, installation (20% of material cost), and 1-year warranty.",
            "category": "general"
        },
        {
            "question": "Do you offer payment plans?",
            "answer": "Yes! We offer flexible payment options:\n- Cash/EcoCash: 5% discount\n- 50% deposit, 50% on completion\n- 3-month payment plan (for orders over $300)\n\nContact us to discuss the best payment option for you.",
            "category": "general"
        },
        {
            "question": "What warranty do you provide?",
            "answer": "All our installations come with:\n- 1 year warranty on installation workmanship\n- Manufacturer warranty on equipment (1-3 years depending on product)\n- Free support via WhatsApp\n- Discounted maintenance after warranty period",
            "category": "general"
        },
        {
            "question": "How long does installation take?",
            "answer": "Typical installation times:\n- CCTV (4-8 cameras): 1 day\n- Gate motor: 4-6 hours\n- Electric fence (100m): 1-2 days\n- Biometric access: 2-4 hours\n\nLarger or complex installations may take longer. We'll confirm timing when you book.",
            "category": "general"
        },

        # CCTV FAQs
        {
            "question": "Can I view my CCTV cameras on my phone?",
            "answer": "Yes! All our CCTV packages include free setup of the mobile viewing app. You can:\n- View live feeds from anywhere\n- Playback recorded footage\n- Receive motion alerts\n- Share access with family/staff\n\nWorks on both iPhone and Android phones.",
            "category": "cctv"
        },
        {
            "question": "How many days of recording can the CCTV store?",
            "answer": "Recording capacity depends on your package:\n- 4 Channel (500GB): ~14 days continuous\n- 8 Channel (1TB): ~21 days continuous\n- 16 Channel (2TB): ~30 days continuous\n\nRecording can be extended with motion-detection recording mode. Hard drives can also be upgraded for more storage.",
            "category": "cctv"
        },
        {
            "question": "Do CCTV cameras work at night?",
            "answer": "Yes! All our cameras have infrared night vision:\n- Indoor cameras: 10-15m night vision\n- Outdoor cameras: 20-30m night vision\n\nThey automatically switch to night mode when it gets dark. No additional lighting needed.",
            "category": "cctv"
        },
        {
            "question": "What's the difference between 4, 8, and 16 channel DVR?",
            "answer": "The channel number refers to how many cameras can be connected:\n\n4 Channel ($150): Perfect for small homes/shops - covers entrance, back door, driveway, one room\n\n8 Channel ($280): Medium properties - all of above plus garden, parking, additional rooms\n\n16 Channel ($450): Large properties - full commercial coverage\n\nYou can start with fewer cameras and add more later.",
            "category": "cctv"
        },

        # Gate Motor FAQs
        {
            "question": "Will the gate motor work during load shedding?",
            "answer": "Our gate motors are battery-backup compatible. Options:\n\n1. Add battery backup ($45) - 20+ operations during power cuts\n2. D10 package includes battery backup\n\nNever get locked out during load shedding!",
            "category": "gate_motors"
        },
        {
            "question": "What size gate can your motors handle?",
            "answer": "We have motors for all gate sizes:\n\n- D5 Standard: Gates up to 500kg (most residential gates)\n- D10 Heavy Duty: Gates up to 1000kg (commercial/industrial)\n- Swing Single: Up to 4m wide\n- Swing Double: Up to 8m total (4m per leaf)\n\nNot sure? Send us a photo and we'll recommend the right motor.",
            "category": "gate_motors"
        },
        {
            "question": "How many remotes come with the gate motor?",
            "answer": "Remotes included per package:\n- D5 Standard: 2 remotes\n- D10 Heavy Duty: 4 remotes\n- Swing motors: 2-4 remotes\n\nExtra remotes available for $25 each. We can program up to 60 remotes per system.",
            "category": "gate_motors"
        },
        {
            "question": "Can I open the gate with my phone?",
            "answer": "Yes! We can add GSM (phone call) or WiFi modules to your gate motor:\n- GSM Module ($65): Call the system to open\n- WiFi Module ($85): Use app to open from anywhere\n\nPerfect for letting in guests when you're not home!",
            "category": "gate_motors"
        },

        # Electric Fence FAQs
        {
            "question": "Is electric fence dangerous to people or pets?",
            "answer": "Electric fence is designed to deter, not harm:\n- Gives a short, sharp shock (similar to static electricity)\n- Not dangerous to humans or pets\n- Warning signs legally required and included\n- Energizers are safety-certified\n\nThe shock is memorable enough to deter intruders without causing injury.",
            "category": "electric_fence"
        },
        {
            "question": "What happens when the electric fence is triggered?",
            "answer": "When someone touches the fence:\n1. They receive a deterrent shock\n2. Siren sounds (optional based on settings)\n3. SMS alert sent to your phone (GSM module required)\n4. Log recorded for review\n\nYou'll know immediately if someone tries to breach your perimeter.",
            "category": "electric_fence"
        },
        {
            "question": "How high should electric fence be installed?",
            "answer": "Recommended heights:\n- On top of wall: 1.2m - 1.8m above wall\n- Free-standing: 2.4m total height\n\nWe assess your property and recommend the best height for maximum security. Higher fence = better deterrent.",
            "category": "electric_fence"
        },
        {
            "question": "Does electric fence work in rain?",
            "answer": "Yes! Our electric fence systems are designed for all weather:\n- All components are weather-resistant\n- Rain doesn't affect the shock delivery\n- Lightning protection is built into energizers\n- UV-resistant insulators and wire\n\nZimbabwe's rainy season is no problem!",
            "category": "electric_fence"
        },

        # Biometric FAQs
        {
            "question": "What if the fingerprint reader doesn't recognize my finger?",
            "answer": "All our biometric systems have backup access methods:\n- PIN code (set your own 4-6 digit code)\n- RFID card (included with Pro packages)\n- Master override code\n\nWe register multiple fingers per person during setup. Dry or wet fingers can sometimes cause issues - wipe and try again.",
            "category": "biometric"
        },
        {
            "question": "Can biometric systems track employee attendance?",
            "answer": "Yes! Our Pro and Face Recognition packages include:\n- Time attendance software\n- Clock-in/clock-out logging\n- Late arrival reports\n- Overtime calculation\n- Export to Excel for payroll\n\nPerfect for businesses tracking staff attendance.",
            "category": "biometric"
        },
        {
            "question": "How many users can register on biometric system?",
            "answer": "User capacity by model:\n- Basic: 1,000 fingerprints\n- Pro: 3,000 fingerprints + 3,000 cards\n- Face Recognition: 3,000 faces\n\nNeed more capacity? We have enterprise solutions for large organizations.",
            "category": "biometric"
        },

        # Installation FAQs
        {
            "question": "What does the installation fee include?",
            "answer": "Installation fee (20% of material cost) includes:\n- Professional technician visit\n- Complete system installation\n- Cable routing and concealment\n- System configuration and testing\n- User training\n- Phone app setup (where applicable)\n- 1-year warranty on workmanship",
            "category": "installation"
        },
        {
            "question": "Do I need to prepare anything before installation?",
            "answer": "Before we arrive:\n1. Ensure power points are accessible\n2. Clear access to installation areas\n3. Decide on camera/sensor positions\n4. For gate motors: gate should be in good working condition\n\nOur technician will call you 1 day before to confirm details.",
            "category": "installation"
        },

        # Pricing FAQs
        {
            "question": "How much does a complete home security system cost?",
            "answer": "Complete home security depends on your needs:\n\nBasic Package (~$350):\n- 4 Channel CCTV ($150)\n- Electric fence 50m ($150)\n- Installation (~$60)\n\nStandard Package (~$700):\n- 8 Channel CCTV ($280)\n- Gate motor D5 ($350)\n- Installation (~$125)\n\nPremium Package (~$1,200+):\n- 8 Channel CCTV\n- Gate motor\n- Electric fence\n- Biometric access\n\nContact us for a custom quote based on your property.",
            "category": "pricing"
        },
        {
            "question": "Do you charge for site surveys?",
            "answer": "Site surveys are FREE for:\n- Projects over $200 in Harare/Bulawayo\n- All commercial projects\n\nFor smaller projects or distant locations, we may charge a small transport fee that's credited if you proceed with installation.",
            "category": "pricing"
        }
    ]

    created_count = 0
    for faq_data in faqs:
        # Check if FAQ already exists
        existing = db.query(FAQ).filter(
            FAQ.store_id == store_id,
            FAQ.question == faq_data["question"]
        ).first()

        if existing:
            print(f"  [SKIP] FAQ already exists: {faq_data['question'][:50]}...")
            continue

        faq = FAQ(
            store_id=store_id,
            question=faq_data["question"],
            answer=faq_data["answer"],
            category=faq_data["category"],
            is_active=True
        )
        db.add(faq)
        created_count += 1
        print(f"  [OK] Created FAQ: {faq_data['question'][:50]}...")

    db.commit()
    return created_count

def sync_to_knowledge_base(db, store_id: UUID):
    """Sync products and FAQs to knowledge base with embeddings"""
    print("\n4. Syncing to knowledge base (generating embeddings)...")

    knowledge_service = KnowledgeService(store_id)

    # Sync products
    print("   Syncing products...")
    products_synced = knowledge_service.sync_products_to_knowledge(db)
    print(f"   [OK] {products_synced} products synced")

    # Sync FAQs
    print("   Syncing FAQs...")
    faqs_synced = knowledge_service.sync_all_faqs_to_knowledge(db)
    print(f"   [OK] {faqs_synced} FAQs synced")

    # Get stats
    stats = knowledge_service.get_knowledge_stats(db)
    print(f"\n   Knowledge Base Stats:")
    print(f"   - Total entries: {stats['total']}")
    print(f"   - Active entries: {stats['active']}")
    print(f"   - By type: {stats['by_type']}")

    return products_synced + faqs_synced

def main():
    print("=" * 60)
    print("ZIM SECURE SIGHTS - PRODUCT & FAQ POPULATION")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Find store
        print("\n1. Finding Zim Secure Sights store...")
        store = get_zim_secure_store(db)

        if not store:
            print("   [ERROR] Zim Secure Sights store not found!")
            print("   Please create the store first.")
            return

        print(f"   [OK] Found store: {store.store_name} (ID: {store.id})")

        # Create products
        print("\n2. Creating security products...")
        products_created = create_products(db, store.id)
        print(f"\n   Total products created: {products_created}")

        # Create FAQs
        print("\n3. Creating FAQs...")
        faqs_created = create_faqs(db, store.id)
        print(f"\n   Total FAQs created: {faqs_created}")

        # Sync to knowledge base
        total_synced = sync_to_knowledge_base(db, store.id)

        print("\n" + "=" * 60)
        print("POPULATION COMPLETE")
        print("=" * 60)
        print(f"\nSummary:")
        print(f"  - Products created: {products_created}")
        print(f"  - FAQs created: {faqs_created}")
        print(f"  - Knowledge entries synced: {total_synced}")
        print(f"\nThe AI Sales Bot can now answer questions about:")
        print(f"  - CCTV packages ($150 - $450)")
        print(f"  - Gate motors ($250 - $650)")
        print(f"  - Electric fence ($150 - $700)")
        print(f"  - Biometric access ($120 - $500)")
        print(f"  - Alarm systems and intercoms")
        print(f"  - Installation fees (20% of material cost)")
        print(f"\nTest by messaging your WhatsApp number!")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

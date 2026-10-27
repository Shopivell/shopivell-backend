"""
Seed script to populate SecureSights store with company knowledge and FAQs.
Run this script when OpenAI API credits are available.

Usage: python scripts/seed_securesights_knowledge.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import uuid
from datetime import datetime
from database import SessionLocal
from modules.whatsapp.models import CompanyKnowledge, FAQ

STORE_ID = uuid.UUID("d2c66a7a-a673-4ad4-beb7-491b2fb8d9a8")

# ============ KNOWLEDGE ENTRIES ============
KNOWLEDGE_ENTRIES = [
    {
        "title": "About SecureSights Security",
        "content": "About SecureSights Security: SecureSights Security was founded in Harare, Zimbabwe in 2020. It started as a small team of security experts with a vision to revolutionize property protection. What started with basic CCTV installations has grown into a comprehensive security solutions provider serving clients across Zimbabwe. Over the past 5+ years, SecureSights has adapted to technological advancements while maintaining a commitment to reliability and customer service. As one of the top providers of fire and security solutions in Zimbabwe, SecureSights supplies, installs, and maintains a wide range of security products and services to ensure maximum safety for businesses of all sizes. SecureSights takes pride in supporting thousands of commercial fire and security systems.",
        "category": "general",
        "content_type": "manual",
        "tags": ["about", "company", "history", "founded"],
        "priority": 3.0,
    },
    {
        "title": "Contact Information",
        "content": "SecureSights Contact Information: Address: 9 Bishoff Granite Side, Harare, Zimbabwe. Phone: +263 78 127 6999. Email: info@zimsecuresights.com. Support Email: support@zimsecuresights.com. Website: www.zimsecuresights.co.zw. Business Hours: Monday to Friday 8:00 AM to 5:00 PM, Saturday 8:00 AM to 1:00 PM. We are closed on Sundays and public holidays. For emergencies, our 24/7 monitoring centre is always available.",
        "category": "general",
        "content_type": "manual",
        "tags": ["contact", "address", "phone", "email", "hours"],
        "priority": 3.0,
    },
    {
        "title": "CCTV Services",
        "content": "SecureSights CCTV Services: We provide comprehensive CCTV surveillance solutions including: 1) 4K Ultra HD Surveillance - Crystal clear monitoring with advanced 4K resolution cameras (3840x2160 pixels, 4x the detail of 1080p). 2) AI-Powered Security Systems - Smart cameras with facial recognition and behavior analysis for proactive security. 3) Wireless CCTV Systems - Flexible installation with high-performance wireless security solutions, no wiring needed. 4) Thermal Imaging Cameras - 24/7 surveillance regardless of lighting conditions. 5) PTZ (Pan-Tilt-Zoom) Systems - Complete area coverage with remotely controllable cameras. 6) Video Analytics - Advanced software for intelligent monitoring and data insights. CCTV footage can be accessed and viewed remotely through a web-based interface or mobile app. We also provide ongoing maintenance and support for all CCTV systems.",
        "category": "services",
        "content_type": "manual",
        "tags": ["cctv", "surveillance", "cameras", "4k", "ai", "wireless", "thermal", "ptz"],
        "priority": 2.0,
    },
    {
        "title": "Access Control Systems",
        "content": "SecureSights Access Control Systems: We offer advanced access control solutions including: 1) Automated Boom Gates - Motorized barrier arms for controlling vehicle access in car parks, business entrances, and industrial sites. Features automatic gate access for authorized vehicles and real-time occupancy monitoring. 2) Biometric Access Systems - Advanced biometric systems using fingerprints, retina scans, or facial recognition with 99.9% accuracy. Can combine multiple biometric methods for maximum security. 3) Key Card Access Systems - Compatible with existing security systems and time attendance solutions. Flexible and scalable for different property sizes. All access control systems include comprehensive logging with timestamped records of all entries and exits, and can be integrated with existing CCTV and security systems.",
        "category": "services",
        "content_type": "manual",
        "tags": ["access-control", "boom-gates", "biometric", "key-card", "fingerprint", "facial-recognition"],
        "priority": 2.0,
    },
    {
        "title": "Intruder Alarm Systems",
        "content": "SecureSights Intruder Alarm Systems: We provide advanced security solutions to protect your property from unauthorized access. Our intruder alarm offerings include: 1) Wireless Alarm Systems - Modern wireless security systems with easy installation and no wiring needed. Flexible and expandable. 2) Wired Alarm Systems - Reliable wired security systems for maximum protection and stability. Require professional installation. 3) Smart Alarm Systems - Intelligent security systems that integrate with your smart home devices. Modern systems allow remote arming and disarming via smartphone apps, with notifications if the alarm is triggered. Intruder alarms deter burglars, alert you to break-ins, can lower insurance premiums, and provide peace of mind knowing your property is protected 24/7. Monitored alarm systems can be connected to police response through an Alarm Receiving Centre.",
        "category": "services",
        "content_type": "manual",
        "tags": ["intruder-alarms", "wireless", "wired", "smart", "burglar"],
        "priority": 2.0,
    },
    {
        "title": "ANPR Technology",
        "content": "SecureSights ANPR (Automatic Number Plate Recognition) Technology: Advanced AI-powered technology for real-time vehicle identification and management with 99.8% accuracy. Features include: Military-grade encryption and access controls for data security and regulatory compliance. Easy integration with existing security systems, gates, barriers, and third-party applications. Applications include: 1) Property Access Control - Automate gate operations, maintain digital records, fully automatic gate access for authorized vehicles. 2) Parking Access Control - Automated vehicle identification and processing. 3) Law Enforcement and Security - Quickly identify stolen vehicles, track persons of interest, maintain comprehensive records. 4) Toll Collection - Electronic toll collection without stopping. Benefits: Minimize staffing requirements, reduce infrastructure costs, strengthen security with real-time vehicle identification, watchlist alerts, and access control for sensitive areas.",
        "category": "services",
        "content_type": "manual",
        "tags": ["anpr", "number-plate", "vehicle", "recognition", "ai"],
        "priority": 2.0,
    },
    {
        "title": "Pricing and Quotes",
        "content": "SecureSights Pricing and Quotes: CCTV installation costs vary based on property size and system complexity. Basic CCTV systems start from $300 USD, while comprehensive commercial systems can cost several thousand dollars depending on requirements. We offer free, no-obligation quotes tailored to your specific needs and budget. Our security experts will design a custom solution for your property. For accurate pricing on any of our services (CCTV, access control, intruder alarms, ANPR), contact us directly at +263 78 127 6999 or email info@zimsecuresights.com. We serve both residential and commercial properties across Zimbabwe.",
        "category": "pricing",
        "content_type": "manual",
        "tags": ["pricing", "cost", "quote", "budget"],
        "priority": 2.5,
    },
    {
        "title": "Fire and Safety Solutions",
        "content": "SecureSights Fire and Safety Solutions: As one of the top providers of fire and security solutions in Zimbabwe, we supply, install, and maintain fire safety systems. Our fire safety offerings include: Early warning systems that spot heat signatures before flames appear, fire detection and alarm systems, emergency response planning. We ensure that fire safety systems continue to function properly and effectively protect your business through regular maintenance and testing.",
        "category": "services",
        "content_type": "manual",
        "tags": ["fire", "safety", "detection", "alarm"],
        "priority": 2.0,
    },
]

# ============ FAQ ENTRIES ============
FAQ_ENTRIES = [
    {
        "question": "When was SecureSights founded?",
        "answer": "SecureSights Security was founded in 2020 in Harare, Zimbabwe. It started as a small team of security experts with a vision to revolutionize property protection and has since grown into a comprehensive security solutions provider serving clients across Zimbabwe.",
        "category": "general",
    },
    {
        "question": "Where is SecureSights located?",
        "answer": "SecureSights is located at 9 Bishoff Granite Side, Harare, Zimbabwe. You can reach us at +263 78 127 6999 or email info@zimsecuresights.com.",
        "category": "general",
    },
    {
        "question": "What are your business hours?",
        "answer": "Our business hours are Monday to Friday 8:00 AM to 5:00 PM, and Saturday 8:00 AM to 1:00 PM. We are closed on Sundays and public holidays. For emergencies, our 24/7 monitoring centre is always available.",
        "category": "general",
    },
    {
        "question": "What services does SecureSights offer?",
        "answer": "SecureSights offers comprehensive security solutions including: CCTV Surveillance (4K Ultra HD, AI-powered, wireless, thermal imaging, PTZ systems, video analytics), Access Control Systems (automated boom gates, biometric access, key card systems), Intruder Alarm Systems (wireless, wired, smart), ANPR (Automatic Number Plate Recognition), and Fire & Safety Solutions. We also provide ongoing installation, maintenance, and support for all systems.",
        "category": "services",
    },
    {
        "question": "How much does CCTV installation cost?",
        "answer": "CCTV installation costs vary based on property size and system complexity. Basic CCTV systems start from $300 USD, while comprehensive commercial systems can cost several thousand dollars. We offer free, no-obligation quotes tailored to your specific needs and budget. Contact us at +263 78 127 6999 for an accurate estimate.",
        "category": "pricing",
    },
    {
        "question": "Do you offer free quotes?",
        "answer": "Yes, we offer free, no-obligation quotes tailored to your specific needs and budget. Our security experts will design a custom solution for your property. Contact us at +263 78 127 6999 or email info@zimsecuresights.com to request a quote.",
        "category": "pricing",
    },
    {
        "question": "Can I view CCTV footage remotely?",
        "answer": "Yes, CCTV footage can be accessed and viewed remotely through a web-based interface or mobile app, as long as the CCTV system is connected to the internet. This allows you to monitor your property from anywhere at any time.",
        "category": "services",
    },
    {
        "question": "What types of CCTV cameras do you offer?",
        "answer": "We offer a wide range of CCTV cameras including: 4K Ultra HD cameras (3840x2160 resolution), AI-powered cameras with facial recognition and behavior analysis, wireless CCTV systems, thermal imaging cameras for 24/7 surveillance in any lighting, PTZ (Pan-Tilt-Zoom) cameras for complete area coverage, and video analytics systems. Each type suits different environments and needs.",
        "category": "services",
    },
    {
        "question": "Do you provide maintenance for security systems?",
        "answer": "Yes, we provide comprehensive maintenance and support for all our security systems including CCTV, access control, intruder alarms, and fire safety systems. We offer troubleshooting, repairs, and regular servicing to ensure your systems continue to function properly and effectively protect your property.",
        "category": "services",
    },
    {
        "question": "What is the difference between wired and wireless alarm systems?",
        "answer": "Wired alarm systems are more reliable and stable but require professional installation with cabling. Wireless alarm systems are easier to install with no wiring needed, and can be expanded more flexibly. Both provide excellent security, and the best choice depends on your property and requirements.",
        "category": "services",
    },
    {
        "question": "Can intruder alarms be connected to police response?",
        "answer": "Yes, monitored alarm systems can be connected to police response through an Alarm Receiving Centre (ARC). Response times may vary based on location and circumstances.",
        "category": "services",
    },
    {
        "question": "What is ANPR and how does it work?",
        "answer": "ANPR (Automatic Number Plate Recognition) is our advanced AI-powered technology that identifies vehicles in real-time with 99.8% accuracy. It can automate gate operations, manage parking access, assist law enforcement in identifying stolen vehicles, and provide comprehensive vehicle movement records. It integrates with existing security systems, gates, and barriers.",
        "category": "services",
    },
    {
        "question": "Do your systems work during a power failure?",
        "answer": "Yes, our security systems can be configured with backup power solutions to ensure continued operation during power failures. We recommend UPS (Uninterruptible Power Supply) systems and battery backups for critical security infrastructure. Ask our team about power backup options for your installation.",
        "category": "services",
    },
    {
        "question": "Can I integrate access control with my current security system?",
        "answer": "Yes, all our access control systems (boom gates, biometric systems, key card systems) can be integrated with existing CCTV and security systems. They include comprehensive logging with timestamped records of all entries and exits. Our team will assess your current setup and design a compatible solution.",
        "category": "services",
    },
    {
        "question": "Do you serve residential properties?",
        "answer": "Yes, SecureSights serves both residential and commercial properties across Zimbabwe. We provide comprehensive protection tailored to your specific needs, whether it's a home, office, warehouse, industrial site, or commercial complex.",
        "category": "general",
    },
    {
        "question": "How can I contact SecureSights?",
        "answer": "You can contact SecureSights through: Phone: +263 78 127 6999, Email: info@zimsecuresights.com, Support: support@zimsecuresights.com, or visit us at 9 Bishoff Granite Side, Harare, Zimbabwe. Our business hours are Mon-Fri 8AM-5PM and Sat 8AM-1PM.",
        "category": "general",
    },
]


def seed_knowledge_with_embeddings(db):
    """Create knowledge entries with OpenAI embeddings"""
    try:
        from langchain_openai import OpenAIEmbeddings
        embeddings_model = OpenAIEmbeddings()
        print("✅ OpenAI embeddings initialized")
    except Exception as e:
        print(f"❌ Failed to initialize OpenAI embeddings: {e}")
        print("   Will create entries WITHOUT embeddings. Run sync later.")
        embeddings_model = None

    created = 0
    for entry in KNOWLEDGE_ENTRIES:
        # Check if already exists
        existing = db.query(CompanyKnowledge).filter(
            CompanyKnowledge.store_id == STORE_ID,
            CompanyKnowledge.title == entry["title"]
        ).first()

        if existing:
            print(f"  ⏭️  Skipping (exists): {entry['title']}")
            continue

        embedding = None
        if embeddings_model:
            try:
                embedding = embeddings_model.embed_query(entry["content"])
                print(f"  ✅ Generated embedding for: {entry['title']}")
            except Exception as e:
                print(f"  ⚠️  Embedding failed for {entry['title']}: {e}")

        knowledge = CompanyKnowledge(
            id=uuid.uuid4(),
            store_id=STORE_ID,
            title=entry["title"],
            content=entry["content"],
            category=entry["category"],
            content_type=entry["content_type"],
            tags=entry["tags"],
            priority=entry["priority"],
            embedding=embedding,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(knowledge)
        created += 1

    db.commit()
    print(f"\n📝 Knowledge entries created: {created}/{len(KNOWLEDGE_ENTRIES)}")
    return created


def seed_faqs(db):
    """Create FAQ entries"""
    created = 0
    for i, entry in enumerate(FAQ_ENTRIES):
        # Check if already exists
        existing = db.query(FAQ).filter(
            FAQ.store_id == STORE_ID,
            FAQ.question == entry["question"]
        ).first()

        if existing:
            print(f"  ⏭️  Skipping (exists): {entry['question'][:50]}...")
            continue

        faq = FAQ(
            id=uuid.uuid4(),
            store_id=STORE_ID,
            question=entry["question"],
            answer=entry["answer"],
            category=entry["category"],
            display_order=i + 1,
            is_active=True,
            is_featured=i < 5,  # First 5 are featured
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(faq)
        created += 1

    db.commit()
    print(f"\n❓ FAQ entries created: {created}/{len(FAQ_ENTRIES)}")
    return created


def update_bot_config(db):
    """Update the bot configuration for SecureSights"""
    from modules.whatsapp.models import StoreBotConfig

    config = db.query(StoreBotConfig).filter(
        StoreBotConfig.store_id == STORE_ID
    ).first()

    if not config:
        config = StoreBotConfig(
            id=uuid.uuid4(),
            store_id=STORE_ID,
        )
        db.add(config)

    config.bot_name = "SecureSights Assistant"
    config.bot_personality = "Professional, knowledgeable, and helpful security solutions expert. Friendly but focused on providing accurate information about SecureSights products and services."
    config.greeting_message = "Welcome to SecureSights Security! 👋 How can we help you protect your property today? We offer CCTV, access control, alarm systems, and more."
    config.fallback_message = "I appreciate your question! Let me connect you with our team for more detailed assistance. You can also reach us at +263 78 127 6999 or email info@zimsecuresights.com."
    config.handoff_message = "I'm connecting you with a member of our team who can assist you further. You can also call us at +263 78 127 6999."
    config.handoff_keywords = [
        "speak to human", "talk to someone", "speak to manager",
        "talk to a person", "real person", "human agent",
        "site survey", "book appointment", "schedule visit"
    ]
    config.is_enabled = True
    config.auto_respond = True
    config.similarity_threshold = 0.4
    config.hot_lead_threshold = 75
    config.max_fallbacks_before_handoff = 3
    config.temperature = 0.7
    config.max_response_tokens = 500
    config.updated_at = datetime.utcnow()

    db.commit()
    print("\n🤖 Bot config updated for SecureSights")


if __name__ == "__main__":
    print("=" * 60)
    print("🔒 SecureSights Knowledge Seed Script")
    print("=" * 60)
    print(f"Store ID: {STORE_ID}")
    print()

    db = SessionLocal()
    try:
        print("📚 Seeding knowledge entries...")
        seed_knowledge_with_embeddings(db)

        print("\n📋 Seeding FAQ entries...")
        seed_faqs(db)

        print("\n⚙️  Updating bot configuration...")
        update_bot_config(db)

        print("\n" + "=" * 60)
        print("✅ SecureSights seed complete!")
        print("=" * 60)
        print("\nNote: If embeddings failed due to OpenAI quota, run:")
        print("  POST /api/whatsapp/stores/{store_id}/faqs/sync-all")
        print("  to regenerate embeddings later.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

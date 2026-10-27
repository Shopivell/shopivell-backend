#!/usr/bin/env python3
"""
Upload all Platinum Pharmacy products to the knowledge base.
Run this on the production server.
"""

import os
import sys
import json
import uuid
import asyncio
import httpx
from datetime import datetime

# Database connection
import psycopg2
from psycopg2.extras import execute_values

# Config
DB_URL = os.getenv("DATABASE_URL", "postgresql://shopivell:shopivell@localhost:5432/shopivell")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"  # Platinum Pharmacy

# Products from the API
PRODUCTS = [
    {"id":1824,"name":"ZORA SKIN REPAIR DAY CREAM 50G","price":"6.00","category_name":"Moisturizers"},
    {"id":1823,"name":"ZORA SCALP TREATMENT CREAM 100ML","price":"9.75","category_name":"Moisturizers"},
    {"id":1815,"name":"ZARON WINK 4 IN 1 MASCARA","price":"16.01","category_name":"Mascara"},
    {"id":1814,"name":"ZARON VOLUMIZING MASCARA BLACK","price":"10.01","category_name":"Mascara"},
    {"id":1756,"name":"VASELINE LOTION COCOA GLOW","price":"8.00","category_name":"Body Lotion"},
    {"id":1755,"name":"VASELINE LOTION ARGAN OIL","price":"7.00","category_name":"Body Lotion"},
    {"id":1754,"name":"VASELINE LIP THERAPY ALOE 20G","price":"4.00","category_name":"Lipstick"},
    {"id":1753,"name":"VASELINE LIP THERAPY (ROSY LIPS) 20G","price":"4.00","category_name":"Lipstick"},
    {"id":1752,"name":"VASELINE LIP THERAPY (ORIGINAL) 20G","price":"4.00","category_name":"Lipstick"},
    {"id":1751,"name":"VASELINE COCOA RADIANT BODY OIL 200MLS","price":"31.00","category_name":"Hair Oil"},
    {"id":1750,"name":"VASELINE CERA-GLOW EVENTONE AND MOISTURE","price":"14.00","category_name":"Other"},
    {"id":1749,"name":"VASELINE CERA-GLOW BODY GELOIL 200MLS","price":"15.00","category_name":"Hair Oil"},
    {"id":1748,"name":"VASELINE CERA GLOW STRETCH MARKS BODY CREAM 400ML","price":"13.00","category_name":"Moisturizers"},
    {"id":1747,"name":"VASELINE CERA GLOW FIRMING&MOISTURE LOTION 625ML","price":"17.00","category_name":"Body Lotion"},
    {"id":1746,"name":"VASELINE BLUESEAL 450ML","price":"7.00","category_name":"Other"},
    {"id":1745,"name":"USN PHEDRA CUT LIPO LIQUID 500ML","price":"16.00","category_name":"Lipstick"},
    {"id":1733,"name":"SUNSCREEN SPF50+ CREAM SPF 75G (PHOTO GUARD)","price":"9.00","category_name":"Moisturizers"},
    {"id":1732,"name":"SUNBLOCK SUNSCREEN CREAM SPF90 (RR)","price":"6.52","category_name":"Moisturizers"},
    {"id":1724,"name":"SORBET HAIR REMOVER SENSITIVE SKIN","price":"10.00","category_name":"Other"},
    {"id":1723,"name":"SORBET EVEN AFFECT 3IN1 (CLEANSER, SCRUB & MASK) 150ML","price":"9.00","category_name":"Other"},
    {"id":1722,"name":"SORBET BODY WASH REJUVENATING 400ML","price":"7.00","category_name":"Face Wash"},
    {"id":1721,"name":"SORBET BODY WASH BALANCING 400ML","price":"7.00","category_name":"Face Wash"},
    {"id":1720,"name":"SORBET BODY TISSUE OIL 120ML","price":"11.00","category_name":"Hair Oil"},
    {"id":1719,"name":"SORBET BODY SCRUB HYDRATING 250ML","price":"8.00","category_name":"Other"},
    {"id":1718,"name":"SORBET BODY BUTTER SLEEP 230ML","price":"7.00","category_name":"Other"},
    {"id":1717,"name":"SORBET BODY BUTTER REJUVENATING 400ML","price":"8.00","category_name":"Other"},
    {"id":1716,"name":"SORBET BODY BUTTER REJUVENATING 230ML","price":"7.00","category_name":"Other"},
    {"id":1715,"name":"SORBET BODY BUTTER NOURISHING 230ML","price":"7.00","category_name":"Other"},
    {"id":1714,"name":"SORBET BODY BUTTER HYDRATING 230ML","price":"8.00","category_name":"Other"},
    {"id":1713,"name":"SORBET BODY BUTTER FIRMING 400ML","price":"8.00","category_name":"Other"},
    {"id":1712,"name":"SORBET BODY BUTTER FIRMING 230ML","price":"8.00","category_name":"Other"},
    {"id":1711,"name":"SORBET BODY BUTTER BALANCING 230ML","price":"7.00","category_name":"Other"},
    {"id":1710,"name":"SOOTHEGEL SUSPENSION 200ML","price":"6.00","category_name":"Other"},
    {"id":1709,"name":"SOOTHEGEL SUSPENSION 100ML","price":"4.00","category_name":"Other"},
    {"id":1707,"name":"SLK TWIST UP LIPLINER SPICED ORANGE","price":"4.00","category_name":"Lipstick"},
    {"id":1706,"name":"SLK TWIST UP LIPLINER MACARON","price":"4.00","category_name":"Lipstick"},
    {"id":1705,"name":"SLK TWIST UP LIPLINER CHESTNUT","price":"4.00","category_name":"Lipstick"},
    {"id":1704,"name":"SLK MAKEUP PIXIE PINK BLUSH","price":"8.00","category_name":"Other"},
    {"id":1703,"name":"SLK MAKEUP FLAMINGO BLUSH","price":"8.00","category_name":"Other"},
    {"id":1702,"name":"SLK MAKEUP CORAL BLUSH","price":"8.00","category_name":"Other"},
    {"id":1701,"name":"SLK PRESSED POWDER SC BROWN VELVET","price":"15.00","category_name":"Face Powder"},
    {"id":1700,"name":"SKIN REPUBLIC RETINOID SERUM","price":"24.00","category_name":"Serums"},
    {"id":1699,"name":"SKIN REPUBLIC NIACINAMIDE SERUM 30ML","price":"23.43","category_name":"Serums"},
    {"id":1698,"name":"SKIN REPUBLIC COLLAGEN SERUM SPF 15","price":"23.43","category_name":"Serums"},
    {"id":1697,"name":"SKIN REPUBLIC COLLAGEN SERUM","price":"24.00","category_name":"Serums"},
    {"id":1696,"name":"SIMPLE BOOSTER SERUM 25ML","price":"17.00","category_name":"Serums"},
    {"id":1695,"name":"SILKY FOOT SUPER PEEL EXFOLIATION SOCKS","price":"5.00","category_name":"Other"},
    {"id":1693,"name":"SHE ARGAN CONDITIONER 400ML","price":"7.00","category_name":"Conditioner"},
    {"id":1692,"name":"SHE ALOE VERA CONDITIONER 400ML","price":"7.00","category_name":"Conditioner"},
    {"id":1691,"name":"SELSUN BLUE SHAMPOO 200ML","price":"12.00","category_name":"Shampoo"},
    {"id":1690,"name":"SECRET CLINICAL STRENGTH ANTIPERSPIRANT/DEODORANT","price":"13.00","category_name":"Other"},
    {"id":1688,"name":"SCHWARZKOPF SHAMPOO KERATIN COLOUR 400ML","price":"8.00","category_name":"Shampoo"},
    {"id":1687,"name":"SCHWARZKOPF SHAMPOO HYALURONIC MOISTURE 400ML","price":"8.00","category_name":"Shampoo"},
    {"id":1686,"name":"SCHWARZKOPF SHAMPOO BIOTIN + STRENGTH 400ML","price":"8.00","category_name":"Shampoo"},
    {"id":1685,"name":"SCHWARZKOPF CONDITIONER KERATIN COLOUR 400ML","price":"8.00","category_name":"Conditioner"},
    {"id":1684,"name":"SCHWARZKOPF CONDITIONER HYALURONIC MOISTURE 400ML","price":"8.00","category_name":"Conditioner"},
    {"id":1683,"name":"SCHWARZKOPF CONDITIONER BIOTIN + STRENGTH 400ML","price":"8.00","category_name":"Conditioner"},
    {"id":1680,"name":"REXONA ROLL ON NATURAL WHITENING 50ML","price":"4.50","category_name":"Other"},
    {"id":1679,"name":"REXONA ROLL ON FRESH AQUA 50ML","price":"4.50","category_name":"Other"},
    {"id":1677,"name":"REVLON ULTRA HD LIPCOLOR ORCHID","price":"10.00","category_name":"Lipstick"},
    {"id":1675,"name":"REVLON SUPER LUSTROUS LIPSTICK PINK VELVET","price":"10.00","category_name":"Lipstick"},
    {"id":1674,"name":"REVLON SUPER LUSTROUS LIPSTICK BLUSHED PINK","price":"10.00","category_name":"Lipstick"},
    {"id":1673,"name":"REVLON SUPER LUSTROUS LIPSTICK BERRY HAUTE","price":"10.00","category_name":"Lipstick"},
    {"id":1671,"name":"REVLON COLORSTAY LIQUID LIPSTICK MANZANA","price":"10.00","category_name":"Lipstick"},
    {"id":1670,"name":"REVLON COLORSTAY LIQUID LIPSTICK FINAL ACT","price":"10.00","category_name":"Lipstick"},
    {"id":1668,"name":"REVLON COLORSTAY 16HR EYESHADOW SEDUCTIVE","price":"14.00","category_name":"Other"},
    {"id":1667,"name":"REVLON COLORSTAY 16HR EYESHADOW BRAZEN","price":"14.00","category_name":"Other"},
    {"id":1666,"name":"REVLON COLORSTAY 16HR EYESHADOW ADDICTIVE","price":"14.00","category_name":"Other"},
    {"id":1649,"name":"POOL LOTION 500ML","price":"8.00","category_name":"Body Lotion"},
    {"id":1648,"name":"POOL LOTION 250ML","price":"5.00","category_name":"Body Lotion"},
    {"id":1647,"name":"POOL BODY BUTTER 500ML","price":"9.00","category_name":"Other"},
    {"id":1635,"name":"PALMERS COCOA BUTTER (JAR) 200G","price":"7.00","category_name":"Other"},
    {"id":1634,"name":"PALMERS COCOA BUTTER (JAR) 100G","price":"5.00","category_name":"Other"},
    {"id":1633,"name":"PALMOLIVE NATURALS BODY WASH MILK&HONEY 500ML","price":"6.00","category_name":"Face Wash"},
    {"id":1631,"name":"PANTENE REPAIR & PROTECT SHAMPOO 400ML","price":"8.00","category_name":"Shampoo"},
    {"id":1630,"name":"PANTENE REPAIR & PROTECT CONDITIONER 400ML","price":"8.00","category_name":"Conditioner"},
    {"id":1629,"name":"PANTENE CLASSIC CLEAN SHAMPOO 400ML","price":"8.00","category_name":"Shampoo"},
    {"id":1628,"name":"PANTENE CLASSIC CLEAN CONDITIONER 400ML","price":"8.00","category_name":"Conditioner"},
    {"id":1622,"name":"OLAY REGENERIST RETINOL 24 MOISTURIZER","price":"28.00","category_name":"Moisturizers"},
    {"id":1621,"name":"OLAY REGENERIST MICRO SCULPTING CREAM","price":"30.00","category_name":"Moisturizers"},
    {"id":1620,"name":"OLAY FIRMING & HYDRATING BODY LOTION","price":"15.00","category_name":"Body Lotion"},
    {"id":1613,"name":"NIVEA SUN UV FACE SPF50 50ML","price":"14.00","category_name":"Moisturizers"},
    {"id":1612,"name":"NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 200ML","price":"7.00","category_name":"Moisturizers"},
    {"id":1611,"name":"NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 100ML","price":"5.00","category_name":"Moisturizers"},
    {"id":1610,"name":"NIVEA SHOWER GEL WATERLILY & OIL 500ML","price":"7.00","category_name":"Face Wash"},
    {"id":1609,"name":"NIVEA SHOWER GEL CARE & COCONUT 500ML","price":"7.00","category_name":"Face Wash"},
    {"id":1608,"name":"NIVEA ROLL ON PEARL & BEAUTY 50ML","price":"4.50","category_name":"Other"},
    {"id":1607,"name":"NIVEA ROLL ON EXTRA WHITENING 50ML","price":"4.50","category_name":"Other"},
    {"id":1606,"name":"NIVEA MEN ROLL ON FRESH OCEAN 50ML","price":"4.50","category_name":"Other"},
    {"id":1605,"name":"NIVEA MEN ROLL ON DEEP IMPACT 50ML","price":"4.50","category_name":"Other"},
    {"id":1604,"name":"NIVEA MEN CREME 150ML","price":"6.00","category_name":"Moisturizers"},
    {"id":1603,"name":"NIVEA LOTION COCOA BUTTER 400ML","price":"8.00","category_name":"Body Lotion"},
    {"id":1602,"name":"NIVEA BODY LOTION WHITENING EVEN TONE 400ML","price":"8.00","category_name":"Body Lotion"},
    {"id":1601,"name":"NIVEA BODY LOTION REPAIR & CARE 400ML","price":"8.00","category_name":"Body Lotion"},
    {"id":1600,"name":"NIVEA BODY LOTION NOURISHING 400ML","price":"8.00","category_name":"Body Lotion"},
    {"id":1599,"name":"NIVEA BODY LOTION COCOA BUTTER 625ML","price":"10.00","category_name":"Body Lotion"},
    {"id":1597,"name":"NEUTROGENA HYDRO BOOST WATER GEL","price":"25.00","category_name":"Moisturizers"},
    {"id":1596,"name":"NEUTROGENA BODY LOTION DEEP MOISTURE 400ML","price":"12.00","category_name":"Body Lotion"},
    {"id":1594,"name":"NATURALS ARGAN OIL SHAMPOO 400ML","price":"6.00","category_name":"Shampoo"},
    {"id":1593,"name":"NATURALS ARGAN OIL CONDITIONER 400ML","price":"6.00","category_name":"Conditioner"},
    {"id":1591,"name":"MAYBELLINE SUPERSTAY MATTE INK LIQUID LIPSTICK","price":"12.00","category_name":"Lipstick"},
    {"id":1590,"name":"MAYBELLINE LASH SENSATIONAL MASCARA BLACK","price":"12.00","category_name":"Mascara"},
    {"id":1588,"name":"MAYBELLINE FIT ME FOUNDATION","price":"10.00","category_name":"Face Powder"},
    {"id":1587,"name":"MAYBELLINE COLOSSAL MASCARA BLACK","price":"10.00","category_name":"Mascara"},
    {"id":1584,"name":"MAC LIPSTICK RUBY WOO","price":"25.00","category_name":"Lipstick"},
    {"id":1583,"name":"MAC LIPSTICK MOCHA","price":"25.00","category_name":"Lipstick"},
    {"id":1581,"name":"LOREAL PARIS REVITALIFT FILLER SERUM","price":"35.00","category_name":"Serums"},
    {"id":1580,"name":"LOREAL PARIS ELVIVE EXTRAORDINARY OIL SHAMPOO 400ML","price":"9.00","category_name":"Shampoo"},
    {"id":1579,"name":"LOREAL PARIS ELVIVE EXTRAORDINARY OIL CONDITIONER 400ML","price":"9.00","category_name":"Conditioner"},
]


async def get_embedding(text: str) -> list:
    """Get embedding using OpenAI API."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "text-embedding-3-small",
                "input": text
            },
            timeout=30.0
        )
        if response.status_code == 200:
            data = response.json()
            return data["data"][0]["embedding"]
        else:
            print(f"Error getting embedding: {response.status_code} - {response.text}")
            return None


def main():
    print("=" * 60)
    print("UPLOADING PLATINUM PHARMACY PRODUCTS")
    print("=" * 60)

    # Connect to database
    print("\n[INFO] Connecting to database...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Check existing products
    cur.execute("""
        SELECT COUNT(*) FROM company_knowledge
        WHERE store_id = %s AND category = 'product'
    """, (STORE_ID,))
    existing = cur.fetchone()[0]
    print(f"[INFO] Existing products in knowledge base: {existing}")

    # Insert products
    print(f"\n[INFO] Inserting {len(PRODUCTS)} products...")

    inserted = 0
    skipped = 0

    for product in PRODUCTS:
        name = product["name"]
        price = product["price"]
        category = product.get("category_name", "Other")

        # Check if product already exists
        cur.execute("""
            SELECT id FROM company_knowledge
            WHERE store_id = %s AND title = %s
        """, (STORE_ID, f"Product: {name}"))

        if cur.fetchone():
            skipped += 1
            continue

        # Create content
        content = f"""Product: {name}
Price: ${price} USD
Category: {category}

Available at Platinum Pharmacy Zimbabwe. Contact us via WhatsApp for availability and ordering.
- Angwa Street Branch (Harare): +263 78 005 0999
- Rezende Street Branch (Harare): +263 77 499 9956
- Bulawayo Branch: +263 78 144 4222
- Gweru Branch: +263 77 499 9950"""

        # Insert product
        product_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO company_knowledge
            (id, store_id, title, content, category, content_type, is_active, priority, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'product', 'product', true, 1.0, NOW(), NOW())
        """, (product_id, STORE_ID, f"Product: {name}", content))

        inserted += 1
        print(f"  [+] {name} - ${price}")

    conn.commit()
    print(f"\n[OK] Inserted {inserted} products, skipped {skipped} duplicates")

    # Generate embeddings
    if OPENAI_API_KEY:
        print("\n[INFO] Generating embeddings for new products...")

        # Get products without embeddings
        cur.execute("""
            SELECT id, title, content FROM company_knowledge
            WHERE store_id = %s AND category = 'product' AND embedding IS NULL
        """, (STORE_ID,))

        products_needing_embeddings = cur.fetchall()
        print(f"[INFO] {len(products_needing_embeddings)} products need embeddings")

        async def generate_embeddings():
            for pid, title, content in products_needing_embeddings:
                text = f"{title}\n{content}"
                embedding = await get_embedding(text)
                if embedding:
                    # Convert to PostgreSQL array format
                    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
                    cur.execute("""
                        UPDATE company_knowledge
                        SET embedding = %s::vector
                        WHERE id = %s
                    """, (embedding_str, pid))
                    print(f"  [E] {title[:50]}...")
            conn.commit()

        asyncio.run(generate_embeddings())
        print("[OK] Embeddings generated")
    else:
        print("\n[WARN] OPENAI_API_KEY not set, skipping embeddings")

    # Final count
    cur.execute("""
        SELECT COUNT(*) FROM company_knowledge
        WHERE store_id = %s AND category = 'product'
    """, (STORE_ID,))
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM company_knowledge
        WHERE store_id = %s AND category = 'product' AND embedding IS NOT NULL
    """, (STORE_ID,))
    with_embeddings = cur.fetchone()[0]

    print(f"\n[DONE] Total products: {total}, with embeddings: {with_embeddings}")

    cur.close()
    conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

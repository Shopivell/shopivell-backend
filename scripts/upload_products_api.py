#!/usr/bin/env python3
"""
Upload Platinum Pharmacy products via the Shopivell API
"""

import requests
import time
import json

API_URL = "https://api.shopivell.com/v1/api/whatsapp/knowledge"
STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"

# All products from Platinum Pharmacy API
PRODUCTS = [
    {"name": "ZORA SKIN REPAIR DAY CREAM 50G", "price": "6.00", "category": "Moisturizers"},
    {"name": "ZORA SCALP TREATMENT CREAM 100ML", "price": "9.75", "category": "Moisturizers"},
    {"name": "ZARON WINK 4 IN 1 MASCARA", "price": "16.01", "category": "Mascara"},
    {"name": "ZARON VOLUMIZING MASCARA BLACK", "price": "10.01", "category": "Mascara"},
    {"name": "VASELINE LOTION COCOA GLOW", "price": "8.00", "category": "Body Lotion"},
    {"name": "VASELINE LOTION ARGAN OIL", "price": "7.00", "category": "Body Lotion"},
    {"name": "VASELINE LIP THERAPY ALOE 20G", "price": "4.00", "category": "Lip Care"},
    {"name": "VASELINE LIP THERAPY (ROSY LIPS) 20G", "price": "4.00", "category": "Lip Care"},
    {"name": "VASELINE LIP THERAPY (ORIGINAL) 20G", "price": "4.00", "category": "Lip Care"},
    {"name": "VASELINE COCOA RADIANT BODY OIL 200MLS", "price": "31.00", "category": "Body Oil"},
    {"name": "VASELINE CERA-GLOW EVENTONE AND MOISTURE", "price": "14.00", "category": "Body Cream"},
    {"name": "VASELINE CERA-GLOW BODY GELOIL 200MLS", "price": "15.00", "category": "Body Oil"},
    {"name": "VASELINE CERA GLOW STRETCH MARKS BODY CREAM 400ML", "price": "13.00", "category": "Body Cream"},
    {"name": "VASELINE CERA GLOW FIRMING&MOISTURE LOTION 625ML", "price": "17.00", "category": "Body Lotion"},
    {"name": "VASELINE BLUESEAL 450ML", "price": "7.00", "category": "Petroleum Jelly"},
    {"name": "USN PHEDRA CUT LIPO LIQUID 500ML", "price": "16.00", "category": "Weight Loss"},
    {"name": "SUNSCREEN SPF50+ CREAM SPF 75G (PHOTO GUARD)", "price": "9.00", "category": "Sun Protection"},
    {"name": "SUNBLOCK SUNSCREEN CREAM SPF90 (RR)", "price": "6.52", "category": "Sun Protection"},
    {"name": "SORBET HAIR REMOVER SENSITIVE SKIN", "price": "10.00", "category": "Hair Removal"},
    {"name": "SORBET EVEN AFFECT 3IN1 (CLEANSER, SCRUB & MASK) 150ML", "price": "9.00", "category": "Face Care"},
    {"name": "SORBET BODY WASH REJUVENATING 400ML", "price": "7.00", "category": "Body Wash"},
    {"name": "SORBET BODY WASH BALANCING 400ML", "price": "7.00", "category": "Body Wash"},
    {"name": "SORBET BODY TISSUE OIL 120ML", "price": "11.00", "category": "Body Oil"},
    {"name": "SORBET BODY SCRUB HYDRATING 250ML", "price": "8.00", "category": "Body Scrub"},
    {"name": "SORBET BODY BUTTER SLEEP 230ML", "price": "7.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER REJUVENATING 400ML", "price": "8.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER REJUVENATING 230ML", "price": "7.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER NOURISHING 230ML", "price": "7.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER HYDRATING 230ML", "price": "8.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER FIRMING 400ML", "price": "8.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER FIRMING 230ML", "price": "8.00", "category": "Body Butter"},
    {"name": "SORBET BODY BUTTER BALANCING 230ML", "price": "7.00", "category": "Body Butter"},
    {"name": "SOOTHEGEL SUSPENSION 200ML", "price": "6.00", "category": "Antacid"},
    {"name": "SOOTHEGEL SUSPENSION 100ML", "price": "4.00", "category": "Antacid"},
    {"name": "SLK TWIST UP LIPLINER SPICED ORANGE", "price": "4.00", "category": "Lip Liner"},
    {"name": "SLK TWIST UP LIPLINER MACARON", "price": "4.00", "category": "Lip Liner"},
    {"name": "SLK TWIST UP LIPLINER CHESTNUT", "price": "4.00", "category": "Lip Liner"},
    {"name": "SLK MAKEUP PIXIE PINK BLUSH", "price": "8.00", "category": "Blush"},
    {"name": "SLK MAKEUP FLAMINGO BLUSH", "price": "8.00", "category": "Blush"},
    {"name": "SLK MAKEUP CORAL BLUSH", "price": "8.00", "category": "Blush"},
    {"name": "SLK PRESSED POWDER SC BROWN VELVET", "price": "15.00", "category": "Face Powder"},
    {"name": "SKIN REPUBLIC RETINOID SERUM", "price": "24.00", "category": "Serums"},
    {"name": "SKIN REPUBLIC NIACINAMIDE SERUM 30ML", "price": "23.43", "category": "Serums"},
    {"name": "SKIN REPUBLIC COLLAGEN SERUM SPF 15", "price": "23.43", "category": "Serums"},
    {"name": "SKIN REPUBLIC COLLAGEN SERUM", "price": "24.00", "category": "Serums"},
    {"name": "SIMPLE BOOSTER SERUM 25ML", "price": "17.00", "category": "Serums"},
    {"name": "SILKY FOOT SUPER PEEL EXFOLIATION SOCKS", "price": "5.00", "category": "Foot Care"},
    {"name": "SHE ARGAN CONDITIONER 400ML", "price": "7.00", "category": "Conditioner"},
    {"name": "SHE ALOE VERA CONDITIONER 400ML", "price": "7.00", "category": "Conditioner"},
    {"name": "SELSUN BLUE SHAMPOO 200ML", "price": "12.00", "category": "Shampoo"},
    {"name": "SECRET CLINICAL STRENGTH ANTIPERSPIRANT/DEODORANT", "price": "13.00", "category": "Deodorant"},
    {"name": "SCHWARZKOPF SHAMPOO KERATIN COLOUR 400ML", "price": "8.00", "category": "Shampoo"},
    {"name": "SCHWARZKOPF SHAMPOO HYALURONIC MOISTURE 400ML", "price": "8.00", "category": "Shampoo"},
    {"name": "SCHWARZKOPF SHAMPOO BIOTIN + STRENGTH 400ML", "price": "8.00", "category": "Shampoo"},
    {"name": "SCHWARZKOPF CONDITIONER KERATIN COLOUR 400ML", "price": "8.00", "category": "Conditioner"},
    {"name": "SCHWARZKOPF CONDITIONER HYALURONIC MOISTURE 400ML", "price": "8.00", "category": "Conditioner"},
    {"name": "SCHWARZKOPF CONDITIONER BIOTIN + STRENGTH 400ML", "price": "8.00", "category": "Conditioner"},
    {"name": "REXONA ROLL ON NATURAL WHITENING 50ML", "price": "4.50", "category": "Deodorant"},
    {"name": "REXONA ROLL ON FRESH AQUA 50ML", "price": "4.50", "category": "Deodorant"},
    {"name": "REVLON ULTRA HD LIPCOLOR ORCHID", "price": "10.00", "category": "Lipstick"},
    {"name": "REVLON SUPER LUSTROUS LIPSTICK PINK VELVET", "price": "10.00", "category": "Lipstick"},
    {"name": "REVLON SUPER LUSTROUS LIPSTICK BLUSHED PINK", "price": "10.00", "category": "Lipstick"},
    {"name": "REVLON SUPER LUSTROUS LIPSTICK BERRY HAUTE", "price": "10.00", "category": "Lipstick"},
    {"name": "REVLON COLORSTAY LIQUID LIPSTICK MANZANA", "price": "10.00", "category": "Lipstick"},
    {"name": "REVLON COLORSTAY LIQUID LIPSTICK FINAL ACT", "price": "10.00", "category": "Lipstick"},
    {"name": "REVLON COLORSTAY 16HR EYESHADOW SEDUCTIVE", "price": "14.00", "category": "Eyeshadow"},
    {"name": "REVLON COLORSTAY 16HR EYESHADOW BRAZEN", "price": "14.00", "category": "Eyeshadow"},
    {"name": "REVLON COLORSTAY 16HR EYESHADOW ADDICTIVE", "price": "14.00", "category": "Eyeshadow"},
    {"name": "POOL LOTION 500ML", "price": "8.00", "category": "Body Lotion"},
    {"name": "POOL LOTION 250ML", "price": "5.00", "category": "Body Lotion"},
    {"name": "POOL BODY BUTTER 500ML", "price": "9.00", "category": "Body Butter"},
    {"name": "PALMERS COCOA BUTTER (JAR) 200G", "price": "7.00", "category": "Body Butter"},
    {"name": "PALMERS COCOA BUTTER (JAR) 100G", "price": "5.00", "category": "Body Butter"},
    {"name": "PALMOLIVE NATURALS BODY WASH MILK&HONEY 500ML", "price": "6.00", "category": "Body Wash"},
    {"name": "PANTENE REPAIR & PROTECT SHAMPOO 400ML", "price": "8.00", "category": "Shampoo"},
    {"name": "PANTENE REPAIR & PROTECT CONDITIONER 400ML", "price": "8.00", "category": "Conditioner"},
    {"name": "PANTENE CLASSIC CLEAN SHAMPOO 400ML", "price": "8.00", "category": "Shampoo"},
    {"name": "PANTENE CLASSIC CLEAN CONDITIONER 400ML", "price": "8.00", "category": "Conditioner"},
    {"name": "OLAY REGENERIST RETINOL 24 MOISTURIZER", "price": "28.00", "category": "Moisturizers"},
    {"name": "OLAY REGENERIST MICRO SCULPTING CREAM", "price": "30.00", "category": "Moisturizers"},
    {"name": "OLAY FIRMING & HYDRATING BODY LOTION", "price": "15.00", "category": "Body Lotion"},
    {"name": "NIVEA SUN UV FACE SPF50 50ML", "price": "14.00", "category": "Sun Protection"},
    {"name": "NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 200ML", "price": "7.00", "category": "Moisturizers"},
    {"name": "NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 100ML", "price": "5.00", "category": "Moisturizers"},
    {"name": "NIVEA SHOWER GEL WATERLILY & OIL 500ML", "price": "7.00", "category": "Body Wash"},
    {"name": "NIVEA SHOWER GEL CARE & COCONUT 500ML", "price": "7.00", "category": "Body Wash"},
    {"name": "NIVEA ROLL ON PEARL & BEAUTY 50ML", "price": "4.50", "category": "Deodorant"},
    {"name": "NIVEA ROLL ON EXTRA WHITENING 50ML", "price": "4.50", "category": "Deodorant"},
    {"name": "NIVEA MEN ROLL ON FRESH OCEAN 50ML", "price": "4.50", "category": "Men Deodorant"},
    {"name": "NIVEA MEN ROLL ON DEEP IMPACT 50ML", "price": "4.50", "category": "Men Deodorant"},
    {"name": "NIVEA MEN CREME 150ML", "price": "6.00", "category": "Men Grooming"},
    {"name": "NIVEA LOTION COCOA BUTTER 400ML", "price": "8.00", "category": "Body Lotion"},
    {"name": "NIVEA BODY LOTION WHITENING EVEN TONE 400ML", "price": "8.00", "category": "Body Lotion"},
    {"name": "NIVEA BODY LOTION REPAIR & CARE 400ML", "price": "8.00", "category": "Body Lotion"},
    {"name": "NIVEA BODY LOTION NOURISHING 400ML", "price": "8.00", "category": "Body Lotion"},
    {"name": "NIVEA BODY LOTION COCOA BUTTER 625ML", "price": "10.00", "category": "Body Lotion"},
    {"name": "NEUTROGENA HYDRO BOOST WATER GEL", "price": "25.00", "category": "Moisturizers"},
    {"name": "NEUTROGENA BODY LOTION DEEP MOISTURE 400ML", "price": "12.00", "category": "Body Lotion"},
    {"name": "NATURALS ARGAN OIL SHAMPOO 400ML", "price": "6.00", "category": "Shampoo"},
    {"name": "NATURALS ARGAN OIL CONDITIONER 400ML", "price": "6.00", "category": "Conditioner"},
    {"name": "MAYBELLINE SUPERSTAY MATTE INK LIQUID LIPSTICK", "price": "12.00", "category": "Lipstick"},
    {"name": "MAYBELLINE LASH SENSATIONAL MASCARA BLACK", "price": "12.00", "category": "Mascara"},
    {"name": "MAYBELLINE FIT ME FOUNDATION", "price": "10.00", "category": "Foundation"},
    {"name": "MAYBELLINE COLOSSAL MASCARA BLACK", "price": "10.00", "category": "Mascara"},
    {"name": "MAC LIPSTICK RUBY WOO", "price": "25.00", "category": "Lipstick"},
    {"name": "MAC LIPSTICK MOCHA", "price": "25.00", "category": "Lipstick"},
    {"name": "LOREAL PARIS REVITALIFT FILLER SERUM", "price": "35.00", "category": "Serums"},
    {"name": "LOREAL PARIS ELVIVE EXTRAORDINARY OIL SHAMPOO 400ML", "price": "9.00", "category": "Shampoo"},
    {"name": "LOREAL PARIS ELVIVE EXTRAORDINARY OIL CONDITIONER 400ML", "price": "9.00", "category": "Conditioner"},
]


def format_product_content(product):
    """Format product for knowledge base"""
    return f"""Product: {product['name']}
Price: ${product['price']} USD
Category: {product['category']}

Available at Platinum Pharmacy Zimbabwe. Contact us via WhatsApp for availability and ordering.
Branches:
- Angwa Street (Harare): +263 78 005 0999
- Rezende Street (Harare): +263 77 499 9956
- Bulawayo: +263 78 144 4222
- Gweru: +263 77 499 9950"""


def main():
    print("=" * 60)
    print("UPLOADING PLATINUM PHARMACY PRODUCTS")
    print("=" * 60)
    print(f"API: {API_URL}")
    print(f"Store ID: {STORE_ID}")
    print(f"Products: {len(PRODUCTS)}")
    print()

    success = 0
    failed = 0

    for i, product in enumerate(PRODUCTS, 1):
        content = format_product_content(product)

        try:
            response = requests.post(
                API_URL,
                json={
                    "store_id": STORE_ID,
                    "content": content
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                print(f"[{i}/{len(PRODUCTS)}] OK: {product['name'][:40]}... (dims: {data.get('embedding_dimensions', 'N/A')})")
                success += 1
            else:
                print(f"[{i}/{len(PRODUCTS)}] FAIL: {product['name'][:40]}... ({response.status_code})")
                failed += 1

        except Exception as e:
            print(f"[{i}/{len(PRODUCTS)}] ERROR: {product['name'][:40]}... ({e})")
            failed += 1

        # Small delay to avoid rate limiting
        time.sleep(0.5)

    print()
    print("=" * 60)
    print(f"DONE: {success} success, {failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    main()

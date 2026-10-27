-- Insert Platinum Pharmacy products into knowledge base
-- Store ID: 94caaf72-2f38-4a62-9f4a-76f327ff44c0

-- First, delete existing product entries to avoid duplicates
DELETE FROM company_knowledge WHERE store_id = '94caaf72-2f38-4a62-9f4a-76f327ff44c0' AND category = 'product';

-- Insert all products
INSERT INTO company_knowledge (id, store_id, title, content, category, content_type, is_active, priority, created_at, updated_at) VALUES
(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: ZORA SKIN REPAIR DAY CREAM 50G', 'Product: ZORA SKIN REPAIR DAY CREAM 50G
Price: $6.00 USD
Category: Moisturizers

Available at Platinum Pharmacy Zimbabwe. Contact us via WhatsApp for availability and ordering.
- Angwa Street Branch (Harare): +263 78 005 0999
- Rezende Street Branch (Harare): +263 77 499 9956
- Bulawayo Branch: +263 78 144 4222
- Gweru Branch: +263 77 499 9950', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: ZORA SCALP TREATMENT CREAM 100ML', 'Product: ZORA SCALP TREATMENT CREAM 100ML
Price: $9.75 USD
Category: Moisturizers

Available at Platinum Pharmacy Zimbabwe. Contact us via WhatsApp.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE LOTION COCOA GLOW', 'Product: VASELINE LOTION COCOA GLOW
Price: $8.00 USD
Category: Body Lotion

A rich, moisturizing body lotion with cocoa butter for soft, glowing skin. Available at Platinum Pharmacy Zimbabwe.
- Angwa Street Branch (Harare): +263 78 005 0999
- Rezende Street Branch (Harare): +263 77 499 9956
- Bulawayo Branch: +263 78 144 4222
- Gweru Branch: +263 77 499 9950', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE LOTION ARGAN OIL', 'Product: VASELINE LOTION ARGAN OIL
Price: $7.00 USD
Category: Body Lotion

Moisturizing body lotion with argan oil. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE LIP THERAPY ALOE 20G', 'Product: VASELINE LIP THERAPY ALOE 20G
Price: $4.00 USD
Category: Lip Care

Lip therapy with aloe vera for soft, moisturized lips. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE LIP THERAPY (ROSY LIPS) 20G', 'Product: VASELINE LIP THERAPY (ROSY LIPS) 20G
Price: $4.00 USD
Category: Lip Care

Tinted lip therapy for rosy, moisturized lips. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE CERA GLOW FIRMING&MOISTURE LOTION 625ML', 'Product: VASELINE CERA GLOW FIRMING&MOISTURE LOTION 625ML
Price: $17.00 USD
Category: Body Lotion

Firming and moisturizing body lotion for smooth, toned skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA BODY LOTION COCOA BUTTER 625ML', 'Product: NIVEA BODY LOTION COCOA BUTTER 625ML
Price: $10.00 USD
Category: Body Lotion

Rich cocoa butter lotion for deep moisturization. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA LOTION COCOA BUTTER 400ML', 'Product: NIVEA LOTION COCOA BUTTER 400ML
Price: $8.00 USD
Category: Body Lotion

Cocoa butter body lotion for soft skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: POOL LOTION 500ML', 'Product: POOL LOTION 500ML
Price: $8.00 USD
Category: Body Lotion

Body lotion 500ml size. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: POOL LOTION 250ML', 'Product: POOL LOTION 250ML
Price: $5.00 USD
Category: Body Lotion

Body lotion 250ml size. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: OLAY FIRMING & HYDRATING BODY LOTION', 'Product: OLAY FIRMING & HYDRATING BODY LOTION
Price: $15.00 USD
Category: Body Lotion

Premium firming and hydrating body lotion. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NEUTROGENA BODY LOTION DEEP MOISTURE 400ML', 'Product: NEUTROGENA BODY LOTION DEEP MOISTURE 400ML
Price: $12.00 USD
Category: Body Lotion

Deep moisturizing body lotion. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA BODY LOTION WHITENING EVEN TONE 400ML', 'Product: NIVEA BODY LOTION WHITENING EVEN TONE 400ML
Price: $8.00 USD
Category: Body Lotion

Even tone body lotion for radiant skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA BODY LOTION REPAIR & CARE 400ML', 'Product: NIVEA BODY LOTION REPAIR & CARE 400ML
Price: $8.00 USD
Category: Body Lotion

Repair and care body lotion for dry skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA BODY LOTION NOURISHING 400ML', 'Product: NIVEA BODY LOTION NOURISHING 400ML
Price: $8.00 USD
Category: Body Lotion

Nourishing body lotion. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PANTENE REPAIR & PROTECT SHAMPOO 400ML', 'Product: PANTENE REPAIR & PROTECT SHAMPOO 400ML
Price: $8.00 USD
Category: Shampoo

Repair and protect shampoo for damaged hair. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PANTENE CLASSIC CLEAN SHAMPOO 400ML', 'Product: PANTENE CLASSIC CLEAN SHAMPOO 400ML
Price: $8.00 USD
Category: Shampoo

Classic clean shampoo for everyday use. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SCHWARZKOPF SHAMPOO KERATIN COLOUR 400ML', 'Product: SCHWARZKOPF SHAMPOO KERATIN COLOUR 400ML
Price: $8.00 USD
Category: Shampoo

Color-protecting shampoo with keratin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SCHWARZKOPF SHAMPOO HYALURONIC MOISTURE 400ML', 'Product: SCHWARZKOPF SHAMPOO HYALURONIC MOISTURE 400ML
Price: $8.00 USD
Category: Shampoo

Moisturizing shampoo with hyaluronic acid. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SCHWARZKOPF SHAMPOO BIOTIN + STRENGTH 400ML', 'Product: SCHWARZKOPF SHAMPOO BIOTIN + STRENGTH 400ML
Price: $8.00 USD
Category: Shampoo

Strengthening shampoo with biotin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SELSUN BLUE SHAMPOO 200ML', 'Product: SELSUN BLUE SHAMPOO 200ML
Price: $12.00 USD
Category: Shampoo

Anti-dandruff shampoo. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: LOREAL PARIS ELVIVE EXTRAORDINARY OIL SHAMPOO 400ML', 'Product: LOREAL PARIS ELVIVE EXTRAORDINARY OIL SHAMPOO 400ML
Price: $9.00 USD
Category: Shampoo

Nourishing oil-infused shampoo. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NATURALS ARGAN OIL SHAMPOO 400ML', 'Product: NATURALS ARGAN OIL SHAMPOO 400ML
Price: $6.00 USD
Category: Shampoo

Argan oil shampoo for soft, manageable hair. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PANTENE REPAIR & PROTECT CONDITIONER 400ML', 'Product: PANTENE REPAIR & PROTECT CONDITIONER 400ML
Price: $8.00 USD
Category: Conditioner

Repair and protect conditioner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PANTENE CLASSIC CLEAN CONDITIONER 400ML', 'Product: PANTENE CLASSIC CLEAN CONDITIONER 400ML
Price: $8.00 USD
Category: Conditioner

Classic clean conditioner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SCHWARZKOPF CONDITIONER KERATIN COLOUR 400ML', 'Product: SCHWARZKOPF CONDITIONER KERATIN COLOUR 400ML
Price: $8.00 USD
Category: Conditioner

Color-protecting conditioner with keratin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SCHWARZKOPF CONDITIONER HYALURONIC MOISTURE 400ML', 'Product: SCHWARZKOPF CONDITIONER HYALURONIC MOISTURE 400ML
Price: $8.00 USD
Category: Conditioner

Moisturizing conditioner with hyaluronic acid. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SCHWARZKOPF CONDITIONER BIOTIN + STRENGTH 400ML', 'Product: SCHWARZKOPF CONDITIONER BIOTIN + STRENGTH 400ML
Price: $8.00 USD
Category: Conditioner

Strengthening conditioner with biotin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SHE ARGAN CONDITIONER 400ML', 'Product: SHE ARGAN CONDITIONER 400ML
Price: $7.00 USD
Category: Conditioner

Argan oil conditioner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SHE ALOE VERA CONDITIONER 400ML', 'Product: SHE ALOE VERA CONDITIONER 400ML
Price: $7.00 USD
Category: Conditioner

Aloe vera conditioner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: LOREAL PARIS ELVIVE EXTRAORDINARY OIL CONDITIONER 400ML', 'Product: LOREAL PARIS ELVIVE EXTRAORDINARY OIL CONDITIONER 400ML
Price: $9.00 USD
Category: Conditioner

Nourishing oil-infused conditioner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NATURALS ARGAN OIL CONDITIONER 400ML', 'Product: NATURALS ARGAN OIL CONDITIONER 400ML
Price: $6.00 USD
Category: Conditioner

Argan oil conditioner for soft hair. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SKIN REPUBLIC RETINOID SERUM', 'Product: SKIN REPUBLIC RETINOID SERUM
Price: $24.00 USD
Category: Serums

Anti-aging retinoid serum for youthful skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SKIN REPUBLIC NIACINAMIDE SERUM 30ML', 'Product: SKIN REPUBLIC NIACINAMIDE SERUM 30ML
Price: $23.43 USD
Category: Serums

Niacinamide serum for clear, bright skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SKIN REPUBLIC COLLAGEN SERUM', 'Product: SKIN REPUBLIC COLLAGEN SERUM
Price: $24.00 USD
Category: Serums

Collagen serum for firm, youthful skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SIMPLE BOOSTER SERUM 25ML', 'Product: SIMPLE BOOSTER SERUM 25ML
Price: $17.00 USD
Category: Serums

Gentle booster serum for sensitive skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: LOREAL PARIS REVITALIFT FILLER SERUM', 'Product: LOREAL PARIS REVITALIFT FILLER SERUM
Price: $35.00 USD
Category: Serums

Premium anti-aging filler serum. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: OLAY REGENERIST RETINOL 24 MOISTURIZER', 'Product: OLAY REGENERIST RETINOL 24 MOISTURIZER
Price: $28.00 USD
Category: Moisturizers

Premium retinol moisturizer for anti-aging. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: OLAY REGENERIST MICRO SCULPTING CREAM', 'Product: OLAY REGENERIST MICRO SCULPTING CREAM
Price: $30.00 USD
Category: Moisturizers

Premium sculpting cream for firmer skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NEUTROGENA HYDRO BOOST WATER GEL', 'Product: NEUTROGENA HYDRO BOOST WATER GEL
Price: $25.00 USD
Category: Moisturizers

Hydrating water gel moisturizer. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 200ML', 'Product: NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 200ML
Price: $7.00 USD
Category: Moisturizers

Soft, refreshing moisturizing cream. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 100ML', 'Product: NIVEA SOFT REFRESHINGLY SOFT MOISTURIZING CREAM 100ML
Price: $5.00 USD
Category: Moisturizers

Soft, refreshing moisturizing cream. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA SUN UV FACE SPF50 50ML', 'Product: NIVEA SUN UV FACE SPF50 50ML
Price: $14.00 USD
Category: Sun Protection

SPF50 face sunscreen. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA MEN CREME 150ML', 'Product: NIVEA MEN CREME 150ML
Price: $6.00 USD
Category: Men Grooming

Men''s moisturizing creme. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SUNSCREEN SPF50+ CREAM SPF 75G (PHOTO GUARD)', 'Product: SUNSCREEN SPF50+ CREAM SPF 75G (PHOTO GUARD)
Price: $9.00 USD
Category: Sun Protection

High SPF sunscreen cream. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SUNBLOCK SUNSCREEN CREAM SPF90 (RR)', 'Product: SUNBLOCK SUNSCREEN CREAM SPF90 (RR)
Price: $6.52 USD
Category: Sun Protection

High SPF sunblock cream. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: MAC LIPSTICK RUBY WOO', 'Product: MAC LIPSTICK RUBY WOO
Price: $25.00 USD
Category: Lipstick

Iconic red matte lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: MAC LIPSTICK MOCHA', 'Product: MAC LIPSTICK MOCHA
Price: $25.00 USD
Category: Lipstick

Rich mocha shade lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON SUPER LUSTROUS LIPSTICK PINK VELVET', 'Product: REVLON SUPER LUSTROUS LIPSTICK PINK VELVET
Price: $10.00 USD
Category: Lipstick

Pink velvet shade lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON SUPER LUSTROUS LIPSTICK BLUSHED PINK', 'Product: REVLON SUPER LUSTROUS LIPSTICK BLUSHED PINK
Price: $10.00 USD
Category: Lipstick

Blushed pink shade lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON SUPER LUSTROUS LIPSTICK BERRY HAUTE', 'Product: REVLON SUPER LUSTROUS LIPSTICK BERRY HAUTE
Price: $10.00 USD
Category: Lipstick

Berry haute shade lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: MAYBELLINE SUPERSTAY MATTE INK LIQUID LIPSTICK', 'Product: MAYBELLINE SUPERSTAY MATTE INK LIQUID LIPSTICK
Price: $12.00 USD
Category: Lipstick

Long-lasting matte liquid lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: MAYBELLINE LASH SENSATIONAL MASCARA BLACK', 'Product: MAYBELLINE LASH SENSATIONAL MASCARA BLACK
Price: $12.00 USD
Category: Mascara

Volumizing black mascara. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: MAYBELLINE COLOSSAL MASCARA BLACK', 'Product: MAYBELLINE COLOSSAL MASCARA BLACK
Price: $10.00 USD
Category: Mascara

Colossal volume mascara. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: ZARON WINK 4 IN 1 MASCARA', 'Product: ZARON WINK 4 IN 1 MASCARA
Price: $16.01 USD
Category: Mascara

4-in-1 mascara for lashes. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: ZARON VOLUMIZING MASCARA BLACK', 'Product: ZARON VOLUMIZING MASCARA BLACK
Price: $10.01 USD
Category: Mascara

Volumizing black mascara. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: MAYBELLINE FIT ME FOUNDATION', 'Product: MAYBELLINE FIT ME FOUNDATION
Price: $10.00 USD
Category: Face Powder

Natural-looking foundation. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK PRESSED POWDER SC BROWN VELVET', 'Product: SLK PRESSED POWDER SC BROWN VELVET
Price: $15.00 USD
Category: Face Powder

Brown velvet pressed powder. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PALMERS COCOA BUTTER (JAR) 200G', 'Product: PALMERS COCOA BUTTER (JAR) 200G
Price: $7.00 USD
Category: Body Butter

Rich cocoa butter in jar. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PALMERS COCOA BUTTER (JAR) 100G', 'Product: PALMERS COCOA BUTTER (JAR) 100G
Price: $5.00 USD
Category: Body Butter

Cocoa butter in jar. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY BUTTER REJUVENATING 400ML', 'Product: SORBET BODY BUTTER REJUVENATING 400ML
Price: $8.00 USD
Category: Body Butter

Rejuvenating body butter. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY BUTTER FIRMING 400ML', 'Product: SORBET BODY BUTTER FIRMING 400ML
Price: $8.00 USD
Category: Body Butter

Firming body butter. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY BUTTER HYDRATING 230ML', 'Product: SORBET BODY BUTTER HYDRATING 230ML
Price: $8.00 USD
Category: Body Butter

Hydrating body butter. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: POOL BODY BUTTER 500ML', 'Product: POOL BODY BUTTER 500ML
Price: $9.00 USD
Category: Body Butter

Body butter 500ml. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA SHOWER GEL WATERLILY & OIL 500ML', 'Product: NIVEA SHOWER GEL WATERLILY & OIL 500ML
Price: $7.00 USD
Category: Body Wash

Waterlily & oil shower gel. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA SHOWER GEL CARE & COCONUT 500ML', 'Product: NIVEA SHOWER GEL CARE & COCONUT 500ML
Price: $7.00 USD
Category: Body Wash

Care & coconut shower gel. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY WASH REJUVENATING 400ML', 'Product: SORBET BODY WASH REJUVENATING 400ML
Price: $7.00 USD
Category: Body Wash

Rejuvenating body wash. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY WASH BALANCING 400ML', 'Product: SORBET BODY WASH BALANCING 400ML
Price: $7.00 USD
Category: Body Wash

Balancing body wash. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: PALMOLIVE NATURALS BODY WASH MILK&HONEY 500ML', 'Product: PALMOLIVE NATURALS BODY WASH MILK&HONEY 500ML
Price: $6.00 USD
Category: Body Wash

Milk & honey body wash. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REXONA ROLL ON NATURAL WHITENING 50ML', 'Product: REXONA ROLL ON NATURAL WHITENING 50ML
Price: $4.50 USD
Category: Deodorant

Whitening roll-on deodorant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REXONA ROLL ON FRESH AQUA 50ML', 'Product: REXONA ROLL ON FRESH AQUA 50ML
Price: $4.50 USD
Category: Deodorant

Fresh aqua roll-on deodorant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA ROLL ON PEARL & BEAUTY 50ML', 'Product: NIVEA ROLL ON PEARL & BEAUTY 50ML
Price: $4.50 USD
Category: Deodorant

Pearl & beauty roll-on deodorant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA ROLL ON EXTRA WHITENING 50ML', 'Product: NIVEA ROLL ON EXTRA WHITENING 50ML
Price: $4.50 USD
Category: Deodorant

Extra whitening roll-on deodorant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA MEN ROLL ON FRESH OCEAN 50ML', 'Product: NIVEA MEN ROLL ON FRESH OCEAN 50ML
Price: $4.50 USD
Category: Men Deodorant

Men''s fresh ocean roll-on deodorant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: NIVEA MEN ROLL ON DEEP IMPACT 50ML', 'Product: NIVEA MEN ROLL ON DEEP IMPACT 50ML
Price: $4.50 USD
Category: Men Deodorant

Men''s deep impact roll-on deodorant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SECRET CLINICAL STRENGTH ANTIPERSPIRANT/DEODORANT', 'Product: SECRET CLINICAL STRENGTH ANTIPERSPIRANT/DEODORANT
Price: $13.00 USD
Category: Deodorant

Clinical strength antiperspirant. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE COCOA RADIANT BODY OIL 200MLS', 'Product: VASELINE COCOA RADIANT BODY OIL 200MLS
Price: $31.00 USD
Category: Body Oil

Cocoa radiant body oil. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE CERA-GLOW BODY GELOIL 200MLS', 'Product: VASELINE CERA-GLOW BODY GELOIL 200MLS
Price: $15.00 USD
Category: Body Oil

Body gel oil for radiant skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY TISSUE OIL 120ML', 'Product: SORBET BODY TISSUE OIL 120ML
Price: $11.00 USD
Category: Body Oil

Tissue oil for skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET HAIR REMOVER SENSITIVE SKIN', 'Product: SORBET HAIR REMOVER SENSITIVE SKIN
Price: $10.00 USD
Category: Hair Removal

Hair remover for sensitive skin. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET EVEN AFFECT 3IN1 (CLEANSER, SCRUB & MASK) 150ML', 'Product: SORBET EVEN AFFECT 3IN1 (CLEANSER, SCRUB & MASK) 150ML
Price: $9.00 USD
Category: Face Care

3-in-1 cleanser, scrub and mask. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SORBET BODY SCRUB HYDRATING 250ML', 'Product: SORBET BODY SCRUB HYDRATING 250ML
Price: $8.00 USD
Category: Body Scrub

Hydrating body scrub. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SOOTHEGEL SUSPENSION 200ML', 'Product: SOOTHEGEL SUSPENSION 200ML
Price: $6.00 USD
Category: Antacid

Antacid suspension 200ml. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SOOTHEGEL SUSPENSION 100ML', 'Product: SOOTHEGEL SUSPENSION 100ML
Price: $4.00 USD
Category: Antacid

Antacid suspension 100ml. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SILKY FOOT SUPER PEEL EXFOLIATION SOCKS', 'Product: SILKY FOOT SUPER PEEL EXFOLIATION SOCKS
Price: $5.00 USD
Category: Foot Care

Exfoliating foot peel socks. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON COLORSTAY 16HR EYESHADOW SEDUCTIVE', 'Product: REVLON COLORSTAY 16HR EYESHADOW SEDUCTIVE
Price: $14.00 USD
Category: Eyeshadow

Long-lasting seductive eyeshadow. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON COLORSTAY 16HR EYESHADOW BRAZEN', 'Product: REVLON COLORSTAY 16HR EYESHADOW BRAZEN
Price: $14.00 USD
Category: Eyeshadow

Long-lasting brazen eyeshadow. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON COLORSTAY 16HR EYESHADOW ADDICTIVE', 'Product: REVLON COLORSTAY 16HR EYESHADOW ADDICTIVE
Price: $14.00 USD
Category: Eyeshadow

Long-lasting addictive eyeshadow. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK MAKEUP PIXIE PINK BLUSH', 'Product: SLK MAKEUP PIXIE PINK BLUSH
Price: $8.00 USD
Category: Blush

Pixie pink blush. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK MAKEUP FLAMINGO BLUSH', 'Product: SLK MAKEUP FLAMINGO BLUSH
Price: $8.00 USD
Category: Blush

Flamingo shade blush. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK MAKEUP CORAL BLUSH', 'Product: SLK MAKEUP CORAL BLUSH
Price: $8.00 USD
Category: Blush

Coral shade blush. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK TWIST UP LIPLINER SPICED ORANGE', 'Product: SLK TWIST UP LIPLINER SPICED ORANGE
Price: $4.00 USD
Category: Lip Liner

Spiced orange lip liner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK TWIST UP LIPLINER MACARON', 'Product: SLK TWIST UP LIPLINER MACARON
Price: $4.00 USD
Category: Lip Liner

Macaron shade lip liner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: SLK TWIST UP LIPLINER CHESTNUT', 'Product: SLK TWIST UP LIPLINER CHESTNUT
Price: $4.00 USD
Category: Lip Liner

Chestnut shade lip liner. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON ULTRA HD LIPCOLOR ORCHID', 'Product: REVLON ULTRA HD LIPCOLOR ORCHID
Price: $10.00 USD
Category: Lipstick

Ultra HD orchid lipcolor. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON COLORSTAY LIQUID LIPSTICK MANZANA', 'Product: REVLON COLORSTAY LIQUID LIPSTICK MANZANA
Price: $10.00 USD
Category: Lipstick

Manzana liquid lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: REVLON COLORSTAY LIQUID LIPSTICK FINAL ACT', 'Product: REVLON COLORSTAY LIQUID LIPSTICK FINAL ACT
Price: $10.00 USD
Category: Lipstick

Final act liquid lipstick. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: USN PHEDRA CUT LIPO LIQUID 500ML', 'Product: USN PHEDRA CUT LIPO LIQUID 500ML
Price: $16.00 USD
Category: Weight Loss

Fat burner liquid supplement. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE CERA GLOW STRETCH MARKS BODY CREAM 400ML', 'Product: VASELINE CERA GLOW STRETCH MARKS BODY CREAM 400ML
Price: $13.00 USD
Category: Body Cream

Stretch marks body cream. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE CERA-GLOW EVENTONE AND MOISTURE', 'Product: VASELINE CERA-GLOW EVENTONE AND MOISTURE
Price: $14.00 USD
Category: Body Cream

Even tone and moisture body cream. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW()),

(gen_random_uuid(), '94caaf72-2f38-4a62-9f4a-76f327ff44c0', 'Product: VASELINE BLUESEAL 450ML', 'Product: VASELINE BLUESEAL 450ML
Price: $7.00 USD
Category: Petroleum Jelly

Blue seal petroleum jelly. Available at Platinum Pharmacy Zimbabwe.', 'product', 'product', true, 1.0, NOW(), NOW());

-- Verify insertion
SELECT COUNT(*) as product_count FROM company_knowledge WHERE store_id = '94caaf72-2f38-4a62-9f4a-76f327ff44c0' AND category = 'product';

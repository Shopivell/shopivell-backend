-- Express Care Pharmacy (store 76624a45-d935-4479-9706-2efcca8d1589)
--
-- Everything here comes from expresscare.co.zw: /home (branches and phone
-- numbers), /about (founded 2005, 24/7 support), /services.html (prescriptions,
-- refills, reminders, pharmacist chat, blood-pressure and blood-glucose checks),
-- /prescription (photo or PDF upload), /terms (Paynow or cash, valid script
-- required) and the Terms/Privacy contact address. Anything the site does not
-- state (branch hours, delivery fee, minimum order, medical-aid cover, returns)
-- is answered as "ask us and we'll confirm" rather than invented.
--
-- Safe to re-run: the FAQs it owns are replaced, nothing else is touched.

BEGIN;

UPDATE stores
SET store_name        = 'Express Care Pharmacy',
    business_type     = 'pharmacy',
    store_category    = 'Pharmacy',
    store_city        = 'Harare',
    store_country     = 'Zimbabwe',
    country_code      = 'ZW',
    currency          = 'USD',
    store_address     = 'Shop 1 Mon Repos Building, Newlands Shopping Centre, Harare',
    store_email       = 'admin@expresscare.co.zw',
    store_phone       = '+263 78 836 8390',
    store_description = 'Community pharmacy group in Zimbabwe, serving customers since 2005. '
                        'Branches: Newlands and Avenues (Harare), Bonda Pharmacy (Nyanga) and '
                        'Murambinda. Prescriptions, repeat refills, medication reminders, '
                        'pharmacist advice, blood-pressure and blood-glucose checks, and '
                        'personal-care products.',
    store_voice       = 'Community pharmacy group in Zimbabwe since 2005: prescriptions, repeat '
                        'refills, medication reminders, pharmacist advice, health checks and '
                        'personal care across Newlands, Avenues, Bonda (Nyanga) and Murambinda.',
    products_or_services = '["Prescription dispensing", "Repeat prescription refills", '
                        '"Medication reminders", "Pharmacist advice", "Blood pressure checks", '
                        '"Blood glucose checks", "Personal care products", '
                        '"Online orders with delivery or collection"]'::json
WHERE id = '76624a45-d935-4479-9706-2efcca8d1589';

UPDATE store_bot_configs
SET bot_name         = 'Express Care Assistant',
    bot_personality  = 'Friendly, careful pharmacy assistant. Answers questions about branches, '
                       'delivery, payments, prescriptions and services, checks prices and stock, '
                       'and hands anything clinical (dosage, what to take, side effects, '
                       'pregnancy, prescriptions) to a pharmacist.',
    greeting_message = 'Hello and welcome to Express Care Pharmacy 👋 How can we help today? '
                       'You can send a prescription photo, ask about a product, or ask about '
                       'our branches, delivery and payments.',
    fallback_message = 'Let me pass that to our team so you get a correct answer. You can also '
                       'call Newlands on +263 78 836 8390 or Avenues on +263 78 868 6593.',
    handoff_message  = 'I am connecting you with a pharmacist who can help with this. You can '
                       'also call your branch - Newlands +263 78 836 8390, Avenues +263 78 868 6593.',
    updated_at       = now()
WHERE store_id = '76624a45-d935-4479-9706-2efcca8d1589';

DELETE FROM faqs WHERE store_id = '76624a45-d935-4479-9706-2efcca8d1589';

INSERT INTO faqs (id, store_id, question, answer, category, display_order,
                  is_active, is_featured, view_count, helpful_count,
                  not_helpful_count, created_at, updated_at)
VALUES
(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'What is Express Care Pharmacy?',
 'Express Care Pharmacy is a community pharmacy group in Zimbabwe that has served customers since 2005. We dispense prescriptions, support repeat refills and medication reminders, give pharmacist advice, and offer health checks such as blood-pressure and blood-glucose screening alongside everyday personal-care products.',
 'general', 1, true, true, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Where are your branches?',
 E'We have four branches:\n1. Express Care Pharmacy Newlands - Shop 1 Mon Repos Building, Newlands Shopping Centre, Harare\n2. Express Care Pharmacy Avenues - Shop No 6 Real Time Building, 3rd Avenue, Avenues, Harare\n3. Bonda Pharmacy - Stand 1 Bonda Farm, Sanyatwe, Juliasdale, Nyanga\n4. Express Care Pharmacy Murambinda - 1329 Murambinda Growth Point',
 'locations', 2, true, true, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'What are your phone numbers?',
 E'Newlands: +263 78 836 8390\nAvenues: +263 78 868 6593\nBonda Pharmacy: +263 78 868 6814\nMurambinda: +263 77 501 7139\nYou can also WhatsApp the branch nearest you.',
 'locations', 3, true, true, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'What are your opening hours?',
 'Our support line is available 24/7, but branch opening hours are not published online. Send us a message with the branch you plan to visit and we will confirm the hours for today.',
 'general', 4, true, true, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Do you deliver?',
 'Yes, we deliver. Any delivery fee is shown before you confirm your order. Send us your suburb and the items you need and we will confirm the fee and the timing.',
 'delivery', 5, true, true, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Is there a minimum order for delivery?',
 'A minimum order value is not published, so we confirm it per order. Send your list and your suburb and we will tell you whether it qualifies for delivery and what the fee is before you pay.',
 'delivery', 6, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'How can I pay?',
 'Online orders are paid through Paynow, or cash on delivery or collection. If you would like to use another method, ask us and we will confirm what is possible at your branch.',
 'payments', 7, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Do you accept medical aid?',
 'Medical aid is handled by our pharmacists. Send your scheme name and membership number and a pharmacist will confirm what your plan covers before you collect.',
 'payments', 8, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'How do I send my prescription?',
 'Send a clear photo or a PDF of the prescription here on WhatsApp, or upload it at expresscare.co.zw. A pharmacist will check it and tell you when it is ready.',
 'prescriptions', 9, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Do I need a prescription to buy medicine?',
 'Prescription medicines need a valid prescription from a licensed doctor. Our pharmacists may refuse an unclear, invalid or unsafe prescription - that is for your safety.',
 'prescriptions', 10, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Can you refill my repeat prescription?',
 'Yes. We support repeat refills and can remind you when your medication is due. Tell us the medicine and the branch you use and a pharmacist will confirm.',
 'prescriptions', 11, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Can I get a reminder for my medication?',
 'Yes, we offer medication reminders. Send us the medicine and the time you take it and we will set the reminder up for you.',
 'services', 12, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'What services do you offer?',
 'Prescription dispensing and repeat refills, medication reminders, pharmacist advice, blood-pressure and blood-glucose screening, and personal-care products.',
 'services', 13, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Can I check the price or stock of a product?',
 'Yes. Send the product name, or a photo of the pack, and we will check the price and availability at your branch.',
 'products', 14, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Do you sell cosmetics and personal care?',
 'Yes, we stock personal-care items alongside medicines. Send us what you are looking for and we will check what is available at your branch.',
 'products', 15, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Can I speak to a pharmacist?',
 'Yes. Send your question here and a pharmacist will reply, or call your branch - Newlands +263 78 836 8390, Avenues +263 78 868 6593.',
 'support', 16, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Do you offer health checks?',
 'Yes - blood-pressure and blood-glucose screening. Ask at your branch or message us to check availability and the price.',
 'services', 17, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Can I order online?',
 'Yes. Order at expresscare.co.zw, or send your list here and we will prepare it for delivery or collection.',
 'general', 18, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'What if my prescription is unclear or out of date?',
 'A pharmacist will tell you and may ask for a new prescription from your doctor before anything is dispensed.',
 'prescriptions', 19, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'Can I return medicine?',
 'For safety, medicines cannot simply be returned once they have left the pharmacy. Tell us what happened and our team will advise you.',
 'support', 20, true, false, 0, 0, 0, now(), now()),

(gen_random_uuid(), '76624a45-d935-4479-9706-2efcca8d1589',
 'How do I contact you by email?',
 'admin@expresscare.co.zw, or message us here on WhatsApp and we will help you from there.',
 'support', 21, true, false, 0, 0, 0, now(), now());

COMMIT;

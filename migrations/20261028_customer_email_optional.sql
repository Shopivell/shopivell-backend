-- WhatsApp orders do not necessarily include an email address. Preserve the
-- absence of an address instead of inventing one when creating a customer.
ALTER TABLE customers ALTER COLUMN email DROP NOT NULL;

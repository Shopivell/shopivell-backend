ALTER TABLE customer_segments ADD COLUMN IF NOT EXISTS store_id UUID NULL REFERENCES stores(id) ON DELETE CASCADE;

-- Replace the old global unique-name constraint so each store can own a segment
-- with the same display name. Legacy rows with a NULL store_id remain valid.
ALTER TABLE customer_segments DROP CONSTRAINT IF EXISTS customer_segments_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_segments_store_name
    ON customer_segments (store_id, name) WHERE store_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_customer_segments_store_id ON customer_segments (store_id);

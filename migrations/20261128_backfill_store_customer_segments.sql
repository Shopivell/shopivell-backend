-- Create a store-owned copy of each legacy global segment for every store.
-- Keep the original rows intact for compatibility with older clients.
INSERT INTO customer_segments (
    id, store_id, name, description, criteria, percentage, customer_count,
    type, is_active, created_by, created_at, updated_at, last_activity
)
SELECT
    gen_random_uuid(), stores.id, segments.name, segments.description,
    segments.criteria, '0%', 0, segments.type, segments.is_active,
    segments.created_by, segments.created_at, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM stores
CROSS JOIN customer_segments AS segments
WHERE segments.store_id IS NULL
ON CONFLICT (store_id, name) WHERE store_id IS NOT NULL DO NOTHING;

-- Copy each legacy membership only to the segment copy for that customer's store.
INSERT INTO customer_segment_membership (id, customer_id, segment_id, joined_at)
SELECT
    gen_random_uuid(), customers.id, store_segments.id, memberships.joined_at
FROM customer_segment_membership AS memberships
JOIN customer_segments AS legacy_segments
    ON legacy_segments.id = memberships.segment_id
   AND legacy_segments.store_id IS NULL
JOIN customers
    ON customers.id = memberships.customer_id
   AND customers.store_id IS NOT NULL
JOIN customer_segments AS store_segments
    ON store_segments.store_id = customers.store_id
   AND store_segments.name = legacy_segments.name
WHERE NOT EXISTS (
    SELECT 1
    FROM customer_segment_membership AS existing
    WHERE existing.customer_id = customers.id
      AND existing.segment_id = store_segments.id
);

UPDATE customer_segments AS segments
SET customer_count = (
    SELECT COUNT(*)
    FROM customer_segment_membership AS memberships
    WHERE memberships.segment_id = segments.id
)
WHERE segments.store_id IS NOT NULL;

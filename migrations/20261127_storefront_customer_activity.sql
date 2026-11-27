CREATE TABLE IF NOT EXISTS storefront_customer_activities (
    id UUID PRIMARY KEY,
    store_id UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    activity_type VARCHAR(40) NOT NULL,
    occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_storefront_customer_activities_store_id
    ON storefront_customer_activities (store_id);
CREATE INDEX IF NOT EXISTS ix_storefront_customer_activities_customer_id
    ON storefront_customer_activities (customer_id);
CREATE INDEX IF NOT EXISTS ix_storefront_customer_activities_activity_type
    ON storefront_customer_activities (activity_type);
CREATE INDEX IF NOT EXISTS ix_storefront_customer_activities_occurred_at
    ON storefront_customer_activities (occurred_at);

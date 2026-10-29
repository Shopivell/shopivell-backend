ALTER TABLE store_bot_configs
    ADD COLUMN IF NOT EXISTS pharmacy_instructions JSON NULL;

ALTER TABLE store_bot_configs
    ADD COLUMN IF NOT EXISTS pharmacy_instructions JSON NULL;

ALTER TABLE store_bot_configs
    ADD COLUMN IF NOT EXISTS reply_templates JSON NULL;

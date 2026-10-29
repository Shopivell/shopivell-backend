ALTER TABLE store_members ADD COLUMN IF NOT EXISTS branch_names JSON NULL;
ALTER TABLE whatsapp_conversations ADD COLUMN IF NOT EXISTS branch VARCHAR(100) NULL;
CREATE INDEX IF NOT EXISTS ix_whatsapp_conversations_branch ON whatsapp_conversations (branch);


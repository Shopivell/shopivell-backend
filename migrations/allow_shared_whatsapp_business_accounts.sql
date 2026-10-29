-- A WhatsApp Business Account may own several phone numbers.
-- Phone-number IDs remain unique; keep a non-unique WABA lookup index.
BEGIN;
DROP INDEX IF EXISTS ix_whatsapp_accounts_waba_id;
CREATE INDEX ix_whatsapp_accounts_waba_id ON whatsapp_accounts (waba_id);
COMMIT;

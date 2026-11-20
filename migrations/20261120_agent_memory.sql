ALTER TABLE agent_conversations
ADD COLUMN IF NOT EXISTS memory_cleared_at TIMESTAMP NULL;

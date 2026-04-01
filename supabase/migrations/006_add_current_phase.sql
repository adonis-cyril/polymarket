-- ============================================
-- Migration 6: Add current_phase to bot_state
-- ============================================

ALTER TABLE bot_state ADD COLUMN current_phase INTEGER DEFAULT 1;
UPDATE bot_state SET current_phase = 1 WHERE id = 1;

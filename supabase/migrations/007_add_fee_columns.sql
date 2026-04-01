-- ============================================
-- Migration 7: Add fee tracking + active management columns
-- ============================================

ALTER TABLE trades ADD COLUMN IF NOT EXISTS fee_rate DECIMAL(10,6);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS fees_paid DECIMAL(10,4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS net_profit_after_fees DECIMAL(10,4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS num_entries_this_window INTEGER DEFAULT 1;
ALTER TABLE trades ALTER COLUMN exit_reason TYPE VARCHAR(30);

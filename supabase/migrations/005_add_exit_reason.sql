-- ============================================
-- Migration 5: Add exit tracking columns
-- ============================================

ALTER TABLE trades ADD COLUMN exit_reason VARCHAR(25);
ALTER TABLE trades ADD COLUMN entry_price DECIMAL(10,4);
ALTER TABLE trades ADD COLUMN exit_price DECIMAL(10,4);
ALTER TABLE trades ADD COLUMN hold_duration_seconds INTEGER;
ALTER TABLE trades ADD COLUMN return_pct DECIMAL(10,4);

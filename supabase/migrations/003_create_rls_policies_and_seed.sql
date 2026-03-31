-- ============================================
-- Migration 3: RLS Policies + Seed Data
-- ============================================

-- Enable RLS on all tables
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE levels ENABLE ROW LEVEL SECURITY;
ALTER TABLE commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracked_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE whale_trades ENABLE ROW LEVEL SECURITY;

-- Dashboard read access (anon key)
CREATE POLICY "anon_read_trades" ON trades FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_bot_state" ON bot_state FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_levels" ON levels FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_tracked_wallets" ON tracked_wallets FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read_whale_trades" ON whale_trades FOR SELECT TO anon USING (true);

-- Admin panel: insert and read commands
CREATE POLICY "anon_insert_commands" ON commands FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_read_commands" ON commands FOR SELECT TO anon USING (true);

-- Seed bot_state singleton row
INSERT INTO bot_state (id, status, current_balance, current_level, level_target, peak_balance, today_starting_balance)
VALUES (1, 'STOPPED', 20.00, 1, 40.00, 20.00, 20.00);

-- Seed level milestones ($20 → $40 → $80 → ... → $10,240)
INSERT INTO levels (level, target) VALUES
    (1, 40.00),
    (2, 80.00),
    (3, 160.00),
    (4, 320.00),
    (5, 640.00),
    (6, 1280.00),
    (7, 2560.00),
    (8, 5120.00),
    (9, 10240.00);

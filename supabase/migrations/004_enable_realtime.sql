-- ============================================
-- Migration 4: Enable Realtime + Tighten RLS
-- ============================================

-- Enable Supabase Realtime on dashboard tables
ALTER PUBLICATION supabase_realtime ADD TABLE trades;
ALTER PUBLICATION supabase_realtime ADD TABLE bot_state;
ALTER PUBLICATION supabase_realtime ADD TABLE levels;
ALTER PUBLICATION supabase_realtime ADD TABLE commands;

-- Tighten commands INSERT policy to only allow known command types
DROP POLICY "anon_insert_commands" ON commands;
CREATE POLICY "anon_insert_commands" ON commands
  FOR INSERT TO anon
  WITH CHECK (
    command IN ('PAUSE', 'RESUME', 'SET_KELLY_ALPHA', 'FORCE_SKIP', 'FORCE_CLAIM', 'PING')
  );

export interface Trade {
  id: number;
  timestamp: string;
  window_ts: number;
  asset: string;
  direction: "UP" | "DOWN";
  trade_type: "SNIPE" | "REVERSAL";
  token_price: number;
  bet_size: number;
  kelly_fraction: number | null;
  signal_score: number | null;
  regime: string | null;
  result: "WIN" | "LOSS";
  balance_before: number;
  balance_after: number;
  pnl: number | null;
  payout_ratio: number | null;
  brier_rolling: number | null;
  win_rate_rolling: number | null;
  execution_type: string | null;
  whale_aligned: boolean;
  whale_count: number;
  reversal_counter_move_pct: number | null;
  created_at: string;
}

export interface BotState {
  id: number;
  status: "RUNNING" | "PAUSED" | "STOPPED" | "BLOWN_UP";
  current_balance: number | null;
  current_level: number;
  level_target: number | null;
  peak_balance: number | null;
  today_starting_balance: number | null;
  total_trades: number;
  total_wins: number;
  win_rate: number | null;
  brier_score: number | null;
  current_regime: string | null;
  kelly_alpha: number | null;
  consecutive_losses: number;
  last_trade_at: string | null;
  updated_at: string | null;
}

export interface Level {
  id: number;
  level: number;
  target: number;
  reached_at: string | null;
  trades_taken: number | null;
  time_elapsed_hours: number | null;
}

export interface TrackedWallet {
  id: number;
  address: string;
  alias: string | null;
  total_trades: number | null;
  win_rate: number | null;
  total_pnl: number | null;
  avg_entry_delta_pct: number | null;
  avg_entry_seconds_left: number | null;
  preferred_assets: string[] | null;
  is_active: boolean;
  last_profiled_at: string | null;
}

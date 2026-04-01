"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { BotState, Trade } from "@/lib/types";

interface Stats {
  winRate: string;
  totalTrades: number;
  targetHitRate: string;
  avgNetReturn: string;
  avgHoldDuration: string;
  bestTrade: string;
  exitBreakdown: Record<string, number>;
  reentriesPerWindow: string;
  currentFeeRate: string;
  feesNormal: boolean;
}

const EXIT_LABELS: Record<string, string> = {
  TAKE_PROFIT_10PCT: "10% TP",
  RESOLUTION_WIN: "Res Win",
  ACCEPTABLE_PROFIT: "7-9% TP",
  EDGE_VANISHED_PROFIT: "Edge Exit",
  BREAKEVEN_EXIT: "Breakeven",
  STOP_LOSS: "Stop Loss",
  RESOLUTION_LOSS: "Res Loss",
};

const EXIT_COLORS: Record<string, string> = {
  TAKE_PROFIT_10PCT: "bg-green-500",
  RESOLUTION_WIN: "bg-accent",
  ACCEPTABLE_PROFIT: "bg-emerald-400",
  EDGE_VANISHED_PROFIT: "bg-yellow-500",
  BREAKEVEN_EXIT: "bg-gray-400",
  STOP_LOSS: "bg-red-500",
  RESOLUTION_LOSS: "bg-red-700",
};

export default function StatsGrid() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    async function load() {
      const [{ data: state }, { data: trades }] = await Promise.all([
        supabase.from("bot_state").select("*").eq("id", 1).single(),
        supabase.from("trades").select("*").order("timestamp", { ascending: false }).limit(500),
      ]);

      if (!state || !trades) return;

      const s = state as BotState;
      const allTrades = trades as Trade[];

      // 10% target hit rate
      const targetHits = allTrades.filter(
        (t) =>
          t.exit_reason === "TAKE_PROFIT_10PCT" ||
          t.exit_reason === "RESOLUTION_WIN" ||
          (t.return_pct !== null && t.return_pct >= 10)
      );
      const targetHitRate = allTrades.length > 0
        ? `${((targetHits.length / allTrades.length) * 100).toFixed(1)}%`
        : "N/A";

      // Avg net return (after fees)
      const withNet = allTrades.filter((t) => t.net_profit_after_fees !== null);
      const avgNet = withNet.length > 0
        ? withNet.reduce((s, t) => s + (t.net_profit_after_fees ?? 0), 0) / withNet.length
        : 0;
      // Express as % of bet
      const withBet = allTrades.filter((t) => t.bet_size > 0 && t.net_profit_after_fees !== null);
      const avgNetPct = withBet.length > 0
        ? withBet.reduce((s, t) => s + ((t.net_profit_after_fees ?? 0) / t.bet_size) * 100, 0) / withBet.length
        : 0;

      // Avg hold duration
      const withHold = allTrades.filter((t) => t.hold_duration_seconds !== null && t.hold_duration_seconds > 0);
      const avgHoldSecs = withHold.length > 0
        ? withHold.reduce((s, t) => s + (t.hold_duration_seconds ?? 0), 0) / withHold.length
        : 0;

      // Exit breakdown
      const exitBreakdown: Record<string, number> = {};
      for (const t of allTrades) {
        const reason = t.exit_reason ?? "UNKNOWN";
        exitBreakdown[reason] = (exitBreakdown[reason] ?? 0) + 1;
      }

      // Re-entries per window
      const maxEntries = allTrades.reduce((m, t) => Math.max(m, t.num_entries_this_window ?? 1), 1);
      const multiEntryWindows = allTrades.filter((t) => (t.num_entries_this_window ?? 1) > 1).length;

      // Fee info
      const latestFee = allTrades.find((t) => t.fee_rate !== null);
      const feeRate = latestFee?.fee_rate ?? 0;
      const roundTripPct = feeRate * 2 * 100;

      // Best trade (by net profit)
      const sorted = [...allTrades].sort((a, b) => (b.net_profit_after_fees ?? b.pnl ?? 0) - (a.net_profit_after_fees ?? a.pnl ?? 0));
      const best = sorted[0];
      const bestStr = best
        ? `+$${(best.net_profit_after_fees ?? best.pnl ?? 0).toFixed(2)} (${best.asset.toUpperCase()})`
        : "N/A";

      setStats({
        winRate: `${((s.win_rate ?? 0) * 100).toFixed(1)}%`,
        totalTrades: s.total_trades,
        targetHitRate,
        avgNetReturn: avgNetPct !== 0 ? `${avgNetPct.toFixed(1)}%` : "N/A",
        avgHoldDuration: avgHoldSecs > 0 ? `${Math.round(avgHoldSecs)}s` : "N/A",
        bestTrade: bestStr,
        exitBreakdown,
        reentriesPerWindow: multiEntryWindows > 0 ? `${multiEntryWindows} multi-entry windows` : "None yet",
        currentFeeRate: `${roundTripPct.toFixed(2)}% RT`,
        feesNormal: roundTripPct <= 3,
      });
    }

    load();

    const channel = supabase
      .channel("stats_updates")
      .on("postgres_changes", { event: "*", schema: "public", table: "bot_state" }, () => load())
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "trades" }, () => load())
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  if (!stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-card-bg border border-card-border rounded-xl p-4 animate-pulse">
            <div className="h-4 bg-card-border rounded w-20 mb-2" />
            <div className="h-8 bg-card-border rounded w-16" />
          </div>
        ))}
      </div>
    );
  }

  const totalExits = Object.values(stats.exitBreakdown).reduce((s, n) => s + n, 0);

  return (
    <div className="space-y-4">
      {/* Main stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {[
          { label: "Win Rate", value: stats.winRate, sub: `${stats.totalTrades} total trades` },
          { label: "10% Target Hit Rate", value: stats.targetHitRate, sub: "trades reaching 10%+ net" },
          { label: "Avg Net Return", value: stats.avgNetReturn, sub: `avg hold: ${stats.avgHoldDuration}` },
          { label: "Best Trade", value: stats.bestTrade, sub: "net profit after fees" },
          { label: "Re-entries", value: stats.reentriesPerWindow, sub: "max 3 per window" },
          {
            label: "Fee Rate",
            value: stats.currentFeeRate,
            sub: stats.feesNormal ? "normal" : "ABNORMAL — check!",
          },
        ].map((card) => (
          <div key={card.label} className="bg-card-bg border border-card-border rounded-xl p-4">
            <div className="text-xs text-muted uppercase tracking-wide mb-1">{card.label}</div>
            <div className="text-xl font-mono font-bold">{card.value}</div>
            <div className={`text-xs mt-1 ${card.label === "Fee Rate" && !stats.feesNormal ? "text-loss" : "text-muted"}`}>
              {card.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Exit reason breakdown bar */}
      {totalExits > 0 && (
        <div className="bg-card-bg border border-card-border rounded-xl p-4">
          <div className="text-xs text-muted uppercase tracking-wide mb-3">Exit Breakdown</div>
          <div className="flex h-4 rounded-full overflow-hidden mb-3">
            {Object.entries(stats.exitBreakdown).map(([reason, count]) => (
              <div
                key={reason}
                className={`${EXIT_COLORS[reason] ?? "bg-gray-600"}`}
                style={{ width: `${(count / totalExits) * 100}%` }}
                title={`${EXIT_LABELS[reason] ?? reason}: ${count}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-3 text-xs">
            {Object.entries(stats.exitBreakdown)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, count]) => (
                <div key={reason} className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${EXIT_COLORS[reason] ?? "bg-gray-600"}`} />
                  <span className="text-muted">{EXIT_LABELS[reason] ?? reason}:</span>
                  <span className="font-mono">{count} ({((count / totalExits) * 100).toFixed(0)}%)</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

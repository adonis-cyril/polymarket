"use client";

import { useEffect, useState } from "react";
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

const POLL_MS = 4000;

export default function StatsGrid() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    async function load() {
      const [stateRes, tradesRes] = await Promise.all([
        fetch("/api/bot-state"),
        fetch("/api/trades?limit=500"),
      ]);
      if (!stateRes.ok || !tradesRes.ok) return;

      const state = (await stateRes.json()) as BotState;
      const allTrades = (await tradesRes.json()) as Trade[];
      if (!state) return;

      const targetHits = allTrades.filter(
        (t) =>
          t.exit_reason === "TAKE_PROFIT_10PCT" ||
          t.exit_reason === "RESOLUTION_WIN" ||
          (t.return_pct !== null && Number(t.return_pct) >= 10)
      );
      const targetHitRate = allTrades.length > 0
        ? `${((targetHits.length / allTrades.length) * 100).toFixed(1)}%`
        : "N/A";

      const withBet = allTrades.filter((t) => Number(t.bet_size) > 0 && t.net_profit_after_fees !== null);
      const avgNetPct = withBet.length > 0
        ? withBet.reduce((s, t) => s + ((Number(t.net_profit_after_fees) ?? 0) / Number(t.bet_size)) * 100, 0) / withBet.length
        : 0;

      const withHold = allTrades.filter((t) => t.hold_duration_seconds !== null && Number(t.hold_duration_seconds) > 0);
      const avgHoldSecs = withHold.length > 0
        ? withHold.reduce((s, t) => s + (Number(t.hold_duration_seconds) ?? 0), 0) / withHold.length
        : 0;

      const exitBreakdown: Record<string, number> = {};
      for (const t of allTrades) {
        const reason = t.exit_reason ?? "UNKNOWN";
        exitBreakdown[reason] = (exitBreakdown[reason] ?? 0) + 1;
      }

      const multiEntryWindows = allTrades.filter((t) => (t.num_entries_this_window ?? 1) > 1).length;

      const latestFee = allTrades.find((t) => t.fee_rate !== null);
      const feeRate = Number(latestFee?.fee_rate ?? 0);
      const roundTripPct = feeRate * 2 * 100;

      const sorted = [...allTrades].sort(
        (a, b) => (Number(b.net_profit_after_fees ?? b.pnl ?? 0)) - (Number(a.net_profit_after_fees ?? a.pnl ?? 0))
      );
      const best = sorted[0];
      const bestStr = best
        ? `+$${(Number(best.net_profit_after_fees ?? best.pnl ?? 0)).toFixed(2)} (${best.asset.toUpperCase()})`
        : "N/A";

      setStats({
        winRate: `${((state.win_rate ?? 0) * 100).toFixed(1)}%`,
        totalTrades: state.total_trades,
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
    const interval = setInterval(load, POLL_MS);
    return () => clearInterval(interval);
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

"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { BotState, Trade } from "@/lib/types";

interface Stats {
  winRate: string;
  totalTrades: number;
  reversalCount: number;
  targetHitRate: string;
  avgReturn: string;
  avgHoldDuration: string;
  bestTrade: string;
  reversalWinRate: string;
  whaleAlignment: string;
}

export default function StatsGrid() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    async function load() {
      const [{ data: state }, { data: trades }] = await Promise.all([
        supabase.from("bot_state").select("*").eq("id", 1).single(),
        supabase
          .from("trades")
          .select("*")
          .order("pnl", { ascending: false })
          .limit(500),
      ]);

      if (!state || !trades) return;

      const s = state as BotState;
      const allTrades = trades as Trade[];
      const reversals = allTrades.filter((t) => t.trade_type === "REVERSAL");
      const reversalWins = reversals.filter((t) => t.result === "WIN");
      const whaleAligned = allTrades.filter((t) => t.whale_aligned);

      const best = allTrades[0];
      const bestStr = best
        ? `+$${(best.pnl ?? 0).toFixed(2)} (${best.asset.toUpperCase()})`
        : "N/A";

      // 10% target hit rate: trades where return_pct >= 10 OR exit_reason is TAKE_PROFIT_10PCT or RESOLUTION_WIN
      const targetHits = allTrades.filter(
        (t) =>
          (t.return_pct !== null && t.return_pct >= 10) ||
          t.exit_reason === "TAKE_PROFIT_10PCT" ||
          t.exit_reason === "RESOLUTION_WIN"
      );
      const targetHitRate =
        allTrades.length > 0
          ? `${((targetHits.length / allTrades.length) * 100).toFixed(1)}%`
          : "N/A";

      // Average return per trade
      const returnsWithData = allTrades.filter((t) => t.return_pct !== null);
      const avgReturn =
        returnsWithData.length > 0
          ? `${(returnsWithData.reduce((s, t) => s + (t.return_pct ?? 0), 0) / returnsWithData.length).toFixed(1)}%`
          : "N/A";

      // Average hold duration
      const holdsWithData = allTrades.filter(
        (t) => t.hold_duration_seconds !== null && t.hold_duration_seconds > 0
      );
      const avgHoldSecs =
        holdsWithData.length > 0
          ? holdsWithData.reduce((s, t) => s + (t.hold_duration_seconds ?? 0), 0) /
            holdsWithData.length
          : 0;
      const avgHoldDuration =
        avgHoldSecs > 0 ? `${Math.round(avgHoldSecs)}s` : "N/A";

      setStats({
        winRate: `${((s.win_rate ?? 0) * 100).toFixed(1)}%`,
        totalTrades: s.total_trades,
        reversalCount: reversals.length,
        targetHitRate,
        avgReturn,
        avgHoldDuration,
        bestTrade: bestStr,
        reversalWinRate:
          reversals.length > 0
            ? `${((reversalWins.length / reversals.length) * 100).toFixed(1)}%`
            : "N/A",
        whaleAlignment:
          allTrades.length > 0
            ? `${((whaleAligned.length / allTrades.length) * 100).toFixed(0)}%`
            : "N/A",
      });
    }

    load();

    const channel = supabase
      .channel("stats_updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "bot_state" },
        () => load()
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "trades" },
        () => load()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  if (!stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="bg-card-bg border border-card-border rounded-xl p-4 animate-pulse"
          >
            <div className="h-4 bg-card-border rounded w-20 mb-2" />
            <div className="h-8 bg-card-border rounded w-16" />
          </div>
        ))}
      </div>
    );
  }

  const cards = [
    { label: "Win Rate", value: stats.winRate, sub: `${stats.totalTrades} trades (${stats.reversalCount} reversals)` },
    {
      label: "10% Target Hit Rate",
      value: stats.targetHitRate,
      sub: "trades reaching 10%+ return",
    },
    {
      label: "Avg Return / Trade",
      value: stats.avgReturn,
      sub: `avg hold: ${stats.avgHoldDuration}`,
    },
    { label: "Best Trade", value: stats.bestTrade, sub: "" },
    {
      label: "Reversals",
      value: `${stats.reversalWinRate} win rate`,
      sub: `${stats.reversalCount} reversal trades`,
    },
    {
      label: "Whale Alignment",
      value: stats.whaleAlignment,
      sub: "trades with whale confirmation",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-card-bg border border-card-border rounded-xl p-4"
        >
          <div className="text-xs text-muted uppercase tracking-wide mb-1">
            {card.label}
          </div>
          <div className="text-xl font-mono font-bold">{card.value}</div>
          {card.sub && (
            <div className="text-xs text-muted mt-1">{card.sub}</div>
          )}
        </div>
      ))}
    </div>
  );
}
